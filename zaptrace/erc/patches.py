from __future__ import annotations

import contextlib

from zaptrace.core.models import Design
from zaptrace.core.net_identity import voltage_from_net_name
from zaptrace.erc.models import ERCResult, ERCViolation
from zaptrace.synthesis.calculators import i2c_pullup, led_series_resistor

# Assumptions used when the design does not pin these down. They are echoed in
# the patch so a reviewer can see (and override) what the value was based on.
_DEFAULT_LED_VF = 2.0
_DEFAULT_LED_CURRENT_MA = 10.0
_DEFAULT_I2C_BUS_PF = 100.0
_DEFAULT_I2C_SPEED_HZ = 100_000
_DEFAULT_I2C_RAIL_V = 3.3


def _infer_rail_voltage(design: Design, net_id: str) -> float | None:
    """Best-effort rail voltage for a net: connected supplies first, then the name."""
    net = design.nets.get(net_id) or next((n for n in design.nets.values() if n.id == net_id), None)
    if net is None:
        return None
    voltages: list[float] = []
    for node in net.nodes:
        comp = design.get_component(node.component_ref)
        if comp and comp.voltage_supply:
            with contextlib.suppress(ValueError):
                voltages.append(float(comp.voltage_supply))
    if voltages:
        return max(voltages)
    return voltage_from_net_name(net.name)


def _format_ohms(ohms: float) -> str:
    if ohms >= 1e6:
        return f"{ohms / 1e6:g}M"
    if ohms >= 1e3:
        return f"{ohms / 1e3:g}k"
    return f"{ohms:g}"


def _led_supply_voltage(design: Design, led_ref: str) -> float | None:
    """Rail voltage feeding an LED, inferred from its anode net."""
    net = design.get_net_for_pin(led_ref, "ANODE")
    if net is None:
        return None
    return _infer_rail_voltage(design, net.id)


def _remove_net_patch(violation: ERCViolation) -> dict[str, str] | None:
    if len(violation.net_refs) != 1:
        return None
    return {"op": "remove_net", "net_id": violation.net_refs[0], "reason": violation.message}


def _power_pin_note_patch(violation: ERCViolation) -> dict[str, str] | None:
    if not violation.patch_suggestion:
        return None
    return {
        "op": "add_note",
        "ref": violation.component_refs[0] if violation.component_refs else "",
        "note": violation.patch_suggestion,
    }


def _led_resistor_patch(design: Design, violation: ERCViolation) -> dict[str, str] | None:
    if not violation.component_refs:
        return None
    led_ref = violation.component_refs[0]
    supply = _led_supply_voltage(design, led_ref)
    if supply is not None and supply > _DEFAULT_LED_VF:
        result = led_series_resistor(supply, _DEFAULT_LED_VF, _DEFAULT_LED_CURRENT_MA)
        return {
            "op": "add_series_resistor",
            "ref": led_ref,
            "value": _format_ohms(result.chosen_ohms),
            "reason": violation.message,
            "assumptions": f"Vsupply={supply:g}V, Vf={_DEFAULT_LED_VF:g}V, I={_DEFAULT_LED_CURRENT_MA:g}mA",
        }
    if violation.patch_suggestion:
        return {"op": "add_note", "ref": led_ref, "note": violation.patch_suggestion}
    return None


def _i2c_pullup_patch(design: Design, violation: ERCViolation) -> dict[str, str] | None:
    if not violation.net_refs:
        return None
    net_id = violation.net_refs[0]
    supply = _infer_rail_voltage(design, net_id) or _DEFAULT_I2C_RAIL_V
    try:
        result = i2c_pullup(supply, _DEFAULT_I2C_BUS_PF, bus_speed_hz=_DEFAULT_I2C_SPEED_HZ)
    except ValueError:
        if violation.patch_suggestion:
            return {"op": "add_note", "net_id": net_id, "note": violation.patch_suggestion}
        return None
    return {
        "op": "add_pullup",
        "net_id": net_id,
        "value": _format_ohms(result.recommended_ohms),
        "reason": violation.message,
        "assumptions": f"Vdd={supply:g}V, Cbus={_DEFAULT_I2C_BUS_PF:g}pF, speed={_DEFAULT_I2C_SPEED_HZ}Hz",
    }


def _patch_for_violation(design: Design, violation: ERCViolation) -> dict[str, str] | None:
    """Return the single patch supported for one ERC violation, when any."""
    if violation.rule_id == "ERC012":
        return _remove_net_patch(violation)
    if violation.rule_id == "ERC001":
        return _power_pin_note_patch(violation)
    if violation.rule_id == "ERC008":
        return _led_resistor_patch(design, violation)
    if violation.rule_id == "ERC005":
        return _i2c_pullup_patch(design, violation)
    return None


def suggest_patches(design: Design, erc_result: ERCResult) -> list[dict[str, str]]:
    """Generate auto-patch suggestions for fixable ERC violations.

    Where possible the patch carries a *computed* component value (LED series
    resistor, I2C pull-up) rather than generic prose, with the assumptions it
    was based on. When a value cannot be derived it falls back to the rule's
    textual ``patch_suggestion``.

    Returns a list of patches that can be applied programmatically.
    """
    patches: list[dict[str, str]] = []
    for violation in erc_result.violations:
        patch = _patch_for_violation(design, violation)
        if patch is not None:
            patches.append(patch)
    return patches
