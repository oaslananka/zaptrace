"""SPICE netlist export.

Generates a flat SPICE netlist from a :class:`~zaptrace.core.models.Design`.

This is an **export adapter, not a simulator**. It maps nets to SPICE nodes
(ground nets collapse to node ``0``) and emits standard element cards for
passives and diodes. Active devices (MCUs, regulators, connectors, ...) are
written as *commented placeholders* because the component library does not yet
carry SPICE models — emitting a guessed model would be worse than an honest gap.

The output targets ngspice / LTspice style syntax and is intended as a starting
point for simulation, which still requires device models and human review.
"""

from __future__ import annotations

import re
from pathlib import Path

from zaptrace.core.models import Component, Design, NetType

# ---------------------------------------------------------------------------
# Element classification
# ---------------------------------------------------------------------------

_GENERIC_DIODE_MODEL = "DGEN"


def _element_class(comp: Component) -> str:
    """Return the SPICE element letter for *comp*, or "" if it has no model.

    Classification is by component ``type`` keyword. Anything we cannot map to a
    primitive (R/C/L/D) is treated as a modelled device we do not have a model
    for, and is emitted as a comment rather than guessed.
    """
    t = comp.type.lower().strip()
    if t in {"r", "res", "resistor"} or t.startswith(("res-", "res_", "resistor")):
        return "R"
    if t in {"c", "cap", "capacitor"} or t.startswith(("cap-", "cap_", "capacitor")):
        return "C"
    if t in {"l", "ind", "inductor"} or t.startswith(("ind-", "ind_", "inductor")):
        return "L"
    if t in {"d", "diode", "led"} or "diode" in t or t.startswith(("led", "led-", "led_")):
        return "D"
    return ""


def _spice_value(raw: str | None) -> str:
    """Normalise a component value into a SPICE magnitude.

    Strips trailing unit symbols (F/H/ohm/Ω) while keeping the SI prefix, e.g.
    ``"100nF" -> "100n"``, ``"4.7uF" -> "4.7u"``, ``"10kΩ" -> "10k"``.
    Returns "" when there is nothing usable.
    """
    if not raw:
        return ""
    value = raw.strip()
    value = re.sub(r"(?i)(ohms?|Ω|f|h)$", "", value).strip()
    return value


def _sanitize_node(name: str) -> str:
    safe = re.sub(r"(?a)\W", "_", name).strip("_")
    return safe or "n"


# ---------------------------------------------------------------------------
# Node mapping
# ---------------------------------------------------------------------------


def _build_node_map(design: Design) -> dict[str, str]:
    """Map ``net_id -> SPICE node label``. Ground nets collapse to ``0``."""
    node_map: dict[str, str] = {}
    used: set[str] = {"0"}
    # Ground first so every ground id resolves to node 0.
    for net_id, net in design.nets.items():
        if net.type == NetType.GROUND:
            node_map[net_id] = "0"
    for net_id, net in design.nets.items():
        if net_id in node_map:
            continue
        base = _sanitize_node(net.name)
        label = base
        suffix = 1
        while label in used:
            label = f"{base}_{suffix}"
            suffix += 1
        used.add(label)
        node_map[net_id] = label
    return node_map


def _pin_node(design: Design, node_map: dict[str, str], comp: Component, pin_name: str) -> str:
    """Resolve the SPICE node for one component pin (dangling pins get a unique node)."""
    net = design.get_net_for_pin(comp.ref, pin_name)
    if net is not None:
        return node_map.get(net.id, _sanitize_node(net.name))
    return _sanitize_node(f"NC_{comp.ref}_{pin_name}")


def _element_name(ref: str, cls: str) -> str:
    """Ensure the SPICE card name starts with the device letter without doubling it."""
    return ref if ref[:1].upper() == cls else f"{cls}{ref}"


def _diode_terminals(comp: Component) -> tuple[str, str] | None:
    """Return (anode_pin, cathode_pin) for a 2-pin diode/LED, or None."""
    pins = list(comp.pins.keys())
    if len(pins) < 2:
        return None
    anode = next((p for p in pins if p.upper() in {"ANODE", "A", "A+", "+"}), None)
    cathode = next((p for p in pins if p.upper() in {"CATHODE", "K", "C", "-"}), None)
    if anode and cathode:
        return anode, cathode
    return pins[0], pins[1]


def _passive_card(
    design: Design,
    node_map: dict[str, str],
    component: Component,
    element_class: str,
    pins: list[str],
) -> tuple[str, bool]:
    value = _spice_value(component.value)
    if len(pins) >= 2 and value:
        first = _pin_node(design, node_map, component, pins[0])
        second = _pin_node(design, node_map, component, pins[1])
        return f"{_element_name(component.ref, element_class)} {first} {second} {value}", False
    reason = "no value" if not value else "needs 2 pins"
    return f"* Unsupported: {component.ref} ({component.type}) [{reason}]", True


def _diode_card(
    design: Design,
    node_map: dict[str, str],
    component: Component,
) -> tuple[str, bool]:
    terminals = _diode_terminals(component)
    if terminals is None:
        return f"* Unsupported: {component.ref} ({component.type}) [needs 2 pins]", True
    anode = _pin_node(design, node_map, component, terminals[0])
    cathode = _pin_node(design, node_map, component, terminals[1])
    return f"{_element_name(component.ref, 'D')} {anode} {cathode} {_GENERIC_DIODE_MODEL}", False


def _unsupported_component_card(
    design: Design,
    node_map: dict[str, str],
    component: Component,
    pins: list[str],
) -> str:
    nodes = " ".join(_pin_node(design, node_map, component, pin) for pin in pins) if pins else "(no pins)"
    return f"* Unsupported: {component.ref} ({component.type}) [no SPICE model] nodes: {nodes}"


def _component_card(
    design: Design,
    node_map: dict[str, str],
    component: Component,
) -> tuple[str, bool, bool]:
    element_class = _element_class(component)
    pins = list(component.pins)
    if element_class in {"R", "C", "L"}:
        card, skipped = _passive_card(design, node_map, component, element_class, pins)
        return card, skipped, False
    if element_class == "D":
        card, skipped = _diode_card(design, node_map, component)
        return card, skipped, not skipped
    return _unsupported_component_card(design, node_map, component, pins), True, False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export_spice_netlist(
    design: Design,
    *,
    title: str | None = None,
    extra_cards: list[str] | None = None,
) -> str:
    """Render *design* as a SPICE netlist string.

    Args:
        design: Design to export.
        title: Optional title line; defaults to the design name.
        extra_cards: Optional SPICE cards (for example, behavioral source
            models) injected before ``.end``.

    Returns:
        SPICE netlist text with title, element cards, models, and ``.end``.
    """
    node_map = _build_node_map(design)
    lines = [
        f"* {title or design.meta.name}",
        "* Generated by ZapTrace SPICE export — review required.",
        "* Active devices without a SPICE model are listed as comments below.",
    ]
    skipped_count = 0
    needs_diode_model = False
    for component in sorted(design.components.values(), key=lambda item: item.ref):
        card, skipped, uses_diode_model = _component_card(design, node_map, component)
        lines.append(card)
        skipped_count += int(skipped)
        needs_diode_model = needs_diode_model or uses_diode_model
    if needs_diode_model:
        lines.append(f".model {_GENERIC_DIODE_MODEL} D()")
    if skipped_count:
        lines.append(f"* {skipped_count} component(s) not simulated (no SPICE model or value).")
    if extra_cards:
        lines.append("* Behavioral DC bias models (ideal sources):")
        lines.extend(extra_cards)
    lines.append(".end")
    return "\n".join(lines) + "\n"


def write_spice_netlist(design: Design, output_path: str | Path, *, title: str | None = None) -> Path:
    """Write the SPICE netlist for *design* to *output_path* and return the path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(export_spice_netlist(design, title=title), encoding="utf-8")
    return path
