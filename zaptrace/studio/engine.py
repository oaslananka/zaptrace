"""Canonical YAML editor and source-linked previews for local ZapTrace Studio.

The source file remains the only persistent design state. Browser drafts and
exploratory placements never count as verified schematic/PCB/fabrication proof.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from zaptrace.algo.placer import place_components
from zaptrace.core.board import canonical_board_definition
from zaptrace.core.exceptions import ParseError
from zaptrace.core.parser import parse_str
from zaptrace.export.kicad import _build_schematic, _verified_schematic_wires
from zaptrace.studio.native_symbols import native_match
from zaptrace.viewer.interactive import _extract_viewer_data

MAX_SOURCE_SIZE = 200_000
_REF = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,64}$")


class StudioInputError(ValueError):
    """A draft or mutation cannot be represented in a supported design."""


class StudioConflictError(ValueError):
    """Another actor modified the source since this view was opened."""


def source_sha(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _parse(source: str) -> Any:
    if not isinstance(source, str) or len(source.encode("utf-8")) > MAX_SOURCE_SIZE:
        raise StudioInputError("Studio design source is missing or too large")
    try:
        return parse_str(source, source="studio-source-buffer")
    except (ParseError, ValueError, TypeError, KeyError) as error:
        raise StudioInputError(str(error)[:750]) from error


def preview_design(source: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        design = _parse(source)
        viewer = _extract_viewer_data(design)
        _verified_schematic_wires(design)
        if design.schematic_wires:
            # Reject physical KiCad segment overlap with a foreign source net
            # before allowing Save, not only when a user downloads the export.
            _build_schematic(design)
        board = canonical_board_definition(design)
        calculated = place_components(design)
        source_positions = design.placement or {}
        calculated.update(source_positions)
        parts: list[dict[str, Any]] = []
        for component in viewer.components:
            model = design.components[component.id]
            pos = calculated.get(component.id) or calculated.get(component.ref)
            footprint = model.footprint_def
            size = footprint.courtyard if footprint and footprint.courtyard else (3.0, 3.0)
            pad_numbers: dict[str, list[str]] = {}
            for physical_pad, logical_name in model.package_pin_map.items():
                pad_numbers.setdefault(logical_name, []).append(physical_pad)
            parts.append(
                {
                    "ref": component.ref,
                    "id": component.id,
                    "type": component.type,
                    "value": component.value,
                    "footprint": component.footprint,
                    "pins": [
                        {**pin, "source_package_pads": pad_numbers.get(pin["name"], [])} for pin in component.pins
                    ],
                    "position": [float(pos[0]), float(pos[1])] if pos else None,
                    "size": [float(size[0]), float(size[1])],
                    "source_placed": component.id in source_positions or component.ref in source_positions,
                }
            )
        return {
            "ok": True,
            "name": design.meta.name,
            "source_hash": source_sha(source),
            "board": {"width": float(board.width), "height": float(board.height)},
            "components": parts,
            "nets": [net.model_dump(mode="json") for net in viewer.nets],
            "schematic_wires": [wire.model_dump(mode="json") for wire in design.schematic_wires],
            "routed": bool(design.routing and design.routing.traces),
            "generated_placement": any(not item["source_placed"] for item in parts),
            "engineering": {
                "erc": "not_checked",
                "drc": viewer.review.drc_state,
                "fabrication": "human_review_required",
            },
            "parse_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except (StudioInputError, ValueError) as error:
        return {"ok": False, "error": str(error)}


def _verified_component(source: str, ref: str) -> Any:
    if not isinstance(ref, str) or not _REF.fullmatch(ref):
        raise StudioInputError("Select a supported component reference")
    design = _parse(source)
    for component in design.components.values():
        if component.ref == ref:
            return design, component
    raise StudioInputError(f"Component {ref} does not exist in this design")


def apply_placement(source: str, *, component_ref: str, x: float, y: float) -> str:
    """Rewrite only one simple YAML placement entry, preserving all other source."""
    design, component = _verified_component(source, component_ref)
    try:
        x, y = float(x), float(y)
    except (TypeError, ValueError) as error:
        raise StudioInputError("Position must be numeric") from error
    board = canonical_board_definition(design)
    if not all(map(math.isfinite, (x, y))) or not (0 <= x <= board.width and 0 <= y <= board.height):
        raise StudioInputError("Component position must be inside the board outline")
    if design.routing and design.routing.traces:
        raise StudioInputError("Cannot visually move a routed board without rerouting its copper")
    coordinates = f"[{round(x, 3)}, {round(y, 3)}]"
    source = source.rstrip("\n") + "\n"
    section = re.search(r"^placement:[ \t]*(?:#.*)?$", source, flags=re.MULTILINE | re.ASCII)
    if section is None:
        return source + f"\nplacement:\n  {component.id}: {coordinates}\n"
    following = re.search(r"^[A-Za-z][\w]*:", source[section.end() :], flags=re.MULTILINE | re.ASCII)
    end = section.end() + following.start() if following else len(source)
    placement_block = source[section.end() : end]
    target = re.search(r"(?m)^  " + re.escape(component.id) + r":.*$", placement_block)
    entry = f"  {component.id}: {coordinates}"
    if target:
        if not re.match(r"^  " + re.escape(component.id) + r":\s*\[[^\]\n]+\]\s*(?:#.*)?$", target.group()):
            raise StudioInputError("This placement syntax cannot be edited visually; edit the YAML directly")
        placement_block = placement_block[: target.start()] + entry + placement_block[target.end() :]
    else:
        placement_block = placement_block.rstrip("\n") + "\n" + entry + "\n"
    return source[: section.end()] + placement_block + source[end:]


def apply_component_value(source: str, *, component_ref: str, value: str) -> str:
    """Change only a named component's scalar value in the source components block."""
    _, component = _verified_component(source, component_ref)
    if not isinstance(value, str) or len(value) > 120 or "\x00" in value:
        raise StudioInputError("Value must be a short string")
    header = re.search(r"(?m)^components:[ \t]*(?:#.*)?$", source)
    if header is None:
        raise StudioInputError("A block-style components section is required")
    next_top = re.search(r"(?m)^[A-Za-z][\w]*:", source[header.end() :])
    section_end = header.end() + next_top.start() if next_top else len(source)
    block = source[header.end() : section_end]
    start = re.search(r"(?m)^  " + re.escape(component.id) + r":[ \t]*(?:#.*)?$", block)
    if start is None:
        raise StudioInputError("Only canonical block-style YAML components can be edited")
    following = re.search(r"(?m)^ {2}[A-Za-z][\w-]*:", block[start.end() :])
    end = start.end() + following.start() if following else len(block)
    entry = block[start.end() : end]
    replacement = f"value: {json.dumps(value, ensure_ascii=False)}"
    lines = entry.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("    value:"):
            lines[index] = "    " + replacement + ("\n" if line.endswith("\n") else "")
            break
    else:
        lines.insert(0, "\n    " + replacement)
    entry = "".join(lines)
    updated_block = block[: start.end()] + entry + block[end:]
    result = source[: header.end()] + updated_block + source[section_end:]
    if not preview_design(result)["ok"]:
        raise StudioInputError("The generated value edit would produce an invalid design")
    return result


def _section_bounds(lines: list[str], name: str) -> tuple[int, int]:
    headings = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == name + ":"]
    if len(headings) != 1:
        raise StudioInputError(f"Canonical {name} section is required")
    start = headings[0] + 1
    end = next(
        (
            i
            for i in range(start, len(lines))
            if lines[i].strip() and not lines[i][0].isspace() and not lines[i].startswith("#")
        ),
        len(lines),
    )
    return start, end


def _pin_line_index(lines: list[str], component_id: str, pin_name: str) -> int:
    start, end = _section_bounds(lines, "components")
    headings = [i for i in range(start, end) if lines[i].rstrip("\r\n") == "  " + component_id + ":"]
    if len(headings) != 1:
        raise StudioInputError("Canonical component block is required")
    start = headings[0] + 1
    end = next(
        (
            i
            for i in range(start, end)
            if lines[i].startswith("  ") and not lines[i].startswith("    ") and lines[i].strip()
        ),
        end,
    )
    headings = [i for i in range(start, end) if lines[i].rstrip("\r\n") == "    pins:"]
    if len(headings) != 1:
        raise StudioInputError("Canonical pin block is required")
    start = headings[0] + 1
    end = next(
        (
            i
            for i in range(start, end)
            if lines[i].startswith("    ") and not lines[i].startswith("      ") and lines[i].strip()
        ),
        end,
    )
    matches = [i for i in range(start, end) if lines[i].startswith("      " + pin_name + ":")]
    if len(matches) != 1:
        raise StudioInputError("Only canonical inline pin definitions can be visually edited")
    return matches[0]


def _patch_pin_net(lines: list[str], index: int, old_net: str, target_net: str) -> None:
    original = lines[index]
    if "{" not in original or "}" not in original:
        raise StudioInputError("Only canonical inline pin definitions can be visually edited")
    found = re.search(r'(?<![A-Za-z_])net:[ \t]*"([A-Za-z0-9_-]+)"', original)
    if not found or found.group(1) != old_net:
        raise StudioInputError("Unsupported pin net value syntax; edit the YAML directly")
    lines[index] = original[: found.start(1)] + target_net + original[found.end(1) :]


def _patch_net_nodes(lines: list[str], net_name: str, node_id: str, *, remove: bool) -> None:
    start, end = _section_bounds(lines, "nets")
    matches = [i for i in range(start, end) if lines[i].startswith("  " + net_name + ":")]
    if len(matches) != 1:
        raise StudioInputError("Canonical inline net nodes are required")
    index = matches[0]
    original = lines[index]
    marker = original.find("nodes:")
    left = original.find("[", marker)
    right = original.find("]", left)
    if marker < 0 or left < 0 or right < 0:
        raise StudioInputError("Only single-line JSON-compatible net nodes can be edited")
    try:
        nodes = json.loads(original[left : right + 1])
    except json.JSONDecodeError as error:
        raise StudioInputError("Only double-quoted inline net nodes can be edited") from error
    if not isinstance(nodes, list) or not all(isinstance(node, str) for node in nodes):
        raise StudioInputError("Expected plain source net node names")
    if remove:
        if nodes.count(node_id) != 1:
            raise StudioInputError("Pin source and old net node list disagree")
        nodes.remove(node_id)
    else:
        if node_id in nodes:
            raise StudioInputError("Pin already exists in the target net")
        nodes.append(node_id)
    lines[index] = original[:left] + json.dumps(nodes) + original[right + 1 :]


def _wire_endpoint_parts(value: object) -> tuple[str, str] | None:
    """Parse bounded ASCII pin references without data-dependent regex backtracking."""
    if not isinstance(value, str) or len(value) > 192:
        return None
    component, dot, pin = value.partition(".")
    if not dot or "." in pin:
        return None
    for part in (component, pin):
        if (
            not part
            or not part[0].isascii()
            or not part[0].isalpha()
            or any(not ((char.isascii() and char.isalnum()) or char in "_-") for char in part[1:])
        ):
            return None
    return component, pin


def apply_schematic_wire(source: str, *, start: str, end: str, bend: float = 0.5) -> str:
    """Persist a pin-anchored KiCad schematic elbow path in canonical YAML.

    A different-net target first adopts the starting pin's net; only Save
    writes to disk. This is schematic geometry, never routed PCB copper.
    """
    start_parts = _wire_endpoint_parts(start)
    end_parts = _wire_endpoint_parts(end)
    if start_parts is None or end_parts is None:
        raise StudioInputError("Choose two real source component pins")
    if isinstance(bend, bool) or not isinstance(bend, (float, int)) or not math.isfinite(bend):
        raise StudioInputError("Wire bend must be a finite number")
    bend = round(float(bend), 3)
    if not 0.1 <= abs(bend) <= 0.9:
        raise StudioInputError("Wire bend must be between 0.1 and 0.9 on either channel")
    start_ref, start_pin = start_parts
    end_ref, end_pin = end_parts
    if start_ref == end_ref:
        raise StudioInputError("Wires between pins of the same symbol are not supported")
    design, source_component = _verified_component(source, start_ref)
    _, target_component = _verified_component(source, end_ref)
    if start_pin not in source_component.pins or end_pin not in target_component.pins:
        raise StudioInputError("A selected pin does not exist in the source")
    target_net = source_component.pins[start_pin].net
    if not target_net or target_net not in design.nets:
        raise StudioInputError("The source pin must have an existing electrical net")
    if target_component.pins[end_pin].net != target_net:
        source = apply_pin_connection(source, component_ref=end_ref, pin_name=end_pin, target_net=target_net)

    validated = preview_design(source)
    if not validated["ok"]:
        raise StudioInputError(validated["error"])
    existing = validated["schematic_wires"]
    endpoints = frozenset((start, end))
    if len(existing) >= 64 and not any(frozenset((route["start"], route["end"])) == endpoints for route in existing):
        raise StudioInputError("The Studio wire limit of 64 has been reached")
    entry = f"  - {{start: {json.dumps(start)}, end: {json.dumps(end)}, bend: {bend}}}\n"
    lines = source.splitlines(keepends=True)
    if not any(line.rstrip("\r\n") == "schematic_wires:" for line in lines):
        edited = source.rstrip("\n") + "\nschematic_wires:\n" + entry
    else:
        first, last = _section_bounds(lines, "schematic_wires")
        match_line = None
        for i in range(first, last):
            stripped = lines[i]
            if not stripped.strip() or stripped.lstrip().startswith("#"):
                continue
            match = re.fullmatch(
                r'  - \{start: "([^"]+)", end: "([^"]+)", bend: (-?0\.[0-9]+)\}\r?\n?',
                stripped,
            )
            if not match:
                raise StudioInputError("Only Studio-authored wire rows can be moved on canvas")
            if frozenset((match.group(1), match.group(2))) == endpoints:
                match_line = i
        if match_line is not None:
            lines[match_line] = entry
        else:
            lines.insert(last, entry)
        edited = "".join(lines)
    final = preview_design(edited)
    if not final["ok"] and bend > 0 and "crosses another net" in final["error"]:
        # Choose the other side of the symbol row when the first corridor
        # would short a distinct net; still validate the native geometry.
        alternate = entry.replace(f"bend: {bend}", f"bend: {-bend}")
        proposed = edited.replace(entry, alternate, 1)
        alternate_preview = preview_design(proposed)
        if alternate_preview["ok"]:
            return proposed
    if not final["ok"]:
        raise StudioInputError(final["error"])
    return edited


def remove_schematic_wire(source: str, *, start: str, end: str) -> str:
    """Remove a stored schematic path without changing its electrical net."""
    valid = preview_design(source)
    if not valid["ok"]:
        raise StudioInputError(valid["error"])
    wanted = frozenset((start, end))
    if not any(frozenset((wire["start"], wire["end"])) == wanted for wire in valid["schematic_wires"]):
        raise StudioInputError("Selected source wire path does not exist")
    lines = source.splitlines(keepends=True)
    first, last = _section_bounds(lines, "schematic_wires")
    index = next(
        (
            i
            for i in range(first, last)
            if (
                match := re.fullmatch(
                    r'  - \{start: "([^"]+)", end: "([^"]+)", bend: (-?0\.[0-9]+)\}\r?\n?',
                    lines[i],
                )
            )
            is not None
            and frozenset((match.group(1), match.group(2))) == wanted
        ),
        None,
    )
    if index is None:
        raise StudioInputError("Only Studio-authored wire paths can be removed on canvas")
    del lines[index]
    if len(valid["schematic_wires"]) == 1:
        del lines[first - 1]  # Remove empty optional section; no YAML null.
    edited = "".join(lines)
    if not preview_design(edited)["ok"]:
        raise StudioInputError("Removing this wire did not preserve a valid design")
    return edited


def export_native_kicad_schematic(source: str) -> dict[str, str]:
    """Render a portable, embedded-symbol KiCad schematic from the live draft.

    This is the genuine native KiCad wire/global-label interchange produced by
    ZapTrace's existing exporter; it does not rewrite the user's source YAML.
    Generated symbols are generic connectivity shapes, not verified vendor art.
    """
    design = _parse(source)
    try:
        native = _build_schematic(design)
    except (ValueError, OSError, KeyError) as error:
        raise StudioInputError("Could not generate a KiCad schematic from this source") from error
    if len(native.encode("utf-8")) > 3_000_000:
        raise StudioInputError("Generated KiCad schematic exceeds the Studio download size limit")
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", design.meta.name).strip("-")[:56] or "design"
    return {
        "filename": label + ".kicad_sch",
        "schematic": native,
        "source_hash": source_sha(source),
    }


def inspect_native_symbol(source: str, *, component_ref: str) -> dict[str, Any]:
    """Resolve an optional local KiCad symbol against the current source draft."""
    _, component = _verified_component(source, component_ref)
    return {"native": native_match(component.type, component.package_pin_map)}


def apply_pin_connection(source: str, *, component_ref: str, pin_name: str, target_net: str) -> str:
    """Update a pin declaration and both source net node lists in one draft.

    Reject unsupported YAML instead of rewriting unrelated comments. This is
    logical connectivity editing, not ERC/DRC or routed-copper verification.
    """
    design, component = _verified_component(source, component_ref)
    if not isinstance(pin_name, str) or not _REF.fullmatch(pin_name) or pin_name not in component.pins:
        raise StudioInputError("Choose a declared pin on the selected component")
    if not isinstance(target_net, str) or not _REF.fullmatch(target_net) or target_net not in design.nets:
        raise StudioInputError("Choose an existing net in this design")
    old_net = component.pins[pin_name].net
    if old_net == target_net:
        return source
    if old_net not in design.nets:
        raise StudioInputError("The source pin does not have an existing net")
    if design.routing and design.routing.traces:
        raise StudioInputError("Cannot change a routed pin without regenerating its copper")

    lines = source.splitlines(keepends=True)
    _patch_pin_net(lines, _pin_line_index(lines, component.id, pin_name), old_net, target_net)
    node_id = component.ref + "." + pin_name
    _patch_net_nodes(lines, old_net, node_id, remove=True)
    _patch_net_nodes(lines, target_net, node_id, remove=False)
    changed = "".join(lines)
    result = preview_design(changed)
    if not result["ok"]:
        raise StudioInputError(f"Logical pin edit failed validation: {result['error']}")
    selected = next((c for c in result["components"] if c["ref"] == component.ref), None)
    if not selected or not any(p["name"] == pin_name and p["net"] == target_net for p in selected["pins"]):
        raise StudioInputError("The changed source did not preserve the requested pin connection")
    return changed


class StudioDocument:
    """In-process serialized compare-and-swap writes to one trusted YAML file."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.lock = threading.RLock()

    def _read_source(self) -> str:
        data = self.path.read_bytes()
        if len(data) > MAX_SOURCE_SIZE:
            raise StudioInputError("Source exceeds Studio's bounded document size")
        return data.decode("utf-8")

    def read(self) -> dict[str, Any]:
        with self.lock:
            source = self._read_source()
            return {"source": source, "source_hash": source_sha(source), "preview": preview_design(source)}

    def save(self, source: str, *, expected_hash: str) -> dict[str, Any]:
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
            raise StudioInputError("A valid expected design hash is required")
        result = preview_design(source)
        if not result["ok"]:
            raise StudioInputError(result["error"])
        with self.lock:
            current = self._read_source()
            if source_sha(current) != expected_hash:
                raise StudioConflictError("The project changed outside this editor; reload or compare before saving")
            if current == source:
                return {"source": source, "source_hash": expected_hash, "preview": result}
            mode = stat.S_IMODE(self.path.stat().st_mode)
            fd, tempname = tempfile.mkstemp(prefix=".zaptrace-studio-", suffix=".yaml", dir=self.path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    os.fchmod(stream.fileno(), mode)
                    stream.write(source.encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                if source_sha(self._read_source()) != expected_hash:
                    raise StudioConflictError("The project changed before the editor could save")
                os.replace(tempname, self.path)
            finally:
                if os.path.exists(tempname):
                    os.unlink(tempname)
            return {"source": source, "source_hash": source_sha(source), "preview": result}


def demo_project(base_directory: Path) -> Path:
    """First-run workspace: copy a genuine repository example once, never overwrite."""
    from importlib.resources import files

    path = base_directory / "zaptrace-studio" / "esp32-sensor" / "design.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        example = files("zaptrace.studio.assets").joinpath("esp32_demo.yaml").read_text(encoding="utf-8")
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(example)
    return path
