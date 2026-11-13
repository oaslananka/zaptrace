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
            parts.append(
                {
                    "ref": component.ref,
                    "id": component.id,
                    "type": component.type,
                    "value": component.value,
                    "footprint": component.footprint,
                    "pins": component.pins,
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
            "routed": bool(design.routing and design.routing.traces),
            "generated_placement": any(not item["source_placed"] for item in parts),
            "engineering": {
                "erc": "not_checked",
                "drc": viewer.review.drc_state,
                "fabrication": "human_review_required",
            },
            "parse_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except StudioInputError as error:
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
        with path.open("x", encoding="utf-8") as stream:
            stream.write(example)
    return path
