"""RS-274X Gerber format exporter.

Generates review-grade, experimental Gerber artifacts from a :class:`~zaptrace.core.models.Design`.
Output layers:

- ``*.GTL`` — Top copper (signal)
- ``*.GBL`` — Bottom copper (signal)
- ``*.GTO`` — Top overlay (silkscreen)
- ``*.GTS`` — Top solder mask
- ``*.GBS`` — Bottom solder mask
- ``*.GKO`` — Board outline
- ``*.GPT`` — Top paste (stencil)

All coordinates use RS-274X format with 3.6 integer/decimal resolution (microns).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from zaptrace import __version__
from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design, TraceSegment
from zaptrace.export.path_policy import safe_export_stem

# ---------------------------------------------------------------------------
# RS-274X constants
# ---------------------------------------------------------------------------

_UNITS = "MOMM\n"  # millimeters
_FORMAT = "%FSLAX36Y36*%\n"  # absolute, 3 integer + 6 decimal
_EOF = "M02*\n"

# ---------------------------------------------------------------------------
# Aperture management
# ---------------------------------------------------------------------------


class _ApertureManager:
    """Manages Gerber aperture definitions.

    Apertures are assigned incrementing D-codes (D10+). Circular apertures
    get ``C``, rectangular get ``R``, and obround gets ``OB``.
    """

    def __init__(self) -> None:
        self._next_code = 10
        self._cache: dict[tuple[str, ...], int] = {}

    def _allocate(self) -> int:
        code = self._next_code
        self._next_code += 1
        return code

    def define_circle(self, diameter_mm: float) -> int:
        key = ("C", f"{diameter_mm:.6f}")
        if key in self._cache:
            return self._cache[key]
        code = self._allocate()
        self._cache[key] = code
        return code

    def define_rect(self, width_mm: float, height_mm: float) -> int:
        key = ("R", f"{width_mm:.6f}", f"{height_mm:.6f}")
        if key in self._cache:
            return self._cache[key]
        code = self._allocate()
        self._cache[key] = code
        return code

    def define_obround(self, width_mm: float, height_mm: float) -> int:
        key = ("OB", f"{width_mm:.6f}", f"{height_mm:.6f}")
        if key in self._cache:
            return self._cache[key]
        code = self._allocate()
        self._cache[key] = code
        return code

    def header_lines(self) -> list[str]:
        lines: list[str] = []
        for key, code in sorted(self._cache.items(), key=lambda x: x[1]):
            shape = key[0]
            dims = key[1:]
            if shape == "C":
                lines.append(f"%ADD{code}C,{dims[0]}*%\n")
            elif shape == "R":
                lines.append(f"%ADD{code}R,{dims[0]}X{dims[1]}*%\n")
            elif shape == "OB":
                lines.append(f"%ADD{code}OB,{dims[0]}X{dims[1]}*%\n")
        return lines


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------


def _fmt_xy(x_mm: float, y_mm: float) -> str:
    """Format coordinates in RS-274X 3.6 format (microns as integer)."""
    ix = int(round(x_mm * 1_000_000))
    iy = int(round(y_mm * 1_000_000))
    return f"X{ix}Y{iy}"


# ---------------------------------------------------------------------------
# Layer content builders (all work with list[str])
# ---------------------------------------------------------------------------


def _file_function(layer_name: str) -> str:
    mapping = {
        "TOP": "Copper,L1,Top",
        "BOTTOM": "Copper,L2,Bot",
        "OUTLINE": "Profile,NP",
        "TOP_SILK": "Legend,Top",
        "TOP_MASK": "Soldermask,Top",
        "BOTTOM_MASK": "Soldermask,Bot",
        "TOP_PASTE": "Paste,Top",
    }
    return mapping.get(layer_name, f"Other,{layer_name}")


def _header_list(layer_name: str) -> list[str]:
    """Build the Gerber header block as a list of lines with X2 attributes."""
    return [
        "G04 ZapTrace generated*\n",
        f"%TF.GenerationSoftware,ZapTrace,zaptrace,{__version__}*%\n",
        f"%TF.FileFunction,{_file_function(layer_name)}*%\n",
        "%TF.FilePolarity,Positive*%\n",
        _UNITS,
        _FORMAT,
        f"%LN{layer_name}*%\n",
        "%LPC*%\n",
    ]


def _traces_list(traces: list[TraceSegment], apertures: _ApertureManager, layer_name: str) -> list[str]:
    """Build trace segment draw commands as lines."""
    lines: list[str] = []
    for seg in traces:
        if seg.layer != layer_name:
            continue
        d_code = apertures.define_circle(seg.width)
        lines.append(f"D{d_code}*\n")
        lines.append(f"{_fmt_xy(seg.start[0], seg.start[1])}D02*\n")
        lines.append(f"{_fmt_xy(seg.end[0], seg.end[1])}D01*\n")
    return lines


def _pads_list(pads: list[tuple[str, float, float, float, float, str]], apertures: _ApertureManager) -> list[str]:
    """Build component pad flash commands as lines.

    Each pad tuple: (layer, x_mm, y_mm, width_mm, height_mm, shape)
    """
    lines: list[str] = []
    for _layer, x, y, w, h, shape in pads:
        d_code: int
        if shape == "circle" or (shape == "rect" and abs(w - h) < 0.001):
            d_code = apertures.define_circle(max(w, h))
        elif shape == "oval":
            d_code = apertures.define_obround(w, h)
        else:
            d_code = apertures.define_rect(w, h)
        lines.append(f"D{d_code}*\n")
        lines.append(f"{_fmt_xy(x, y)}D03*\n")
    return lines


def _outline_list(width_mm: float, height_mm: float) -> list[str]:
    """Build rectangular board outline as Gerber lines."""
    lines: list[str] = []
    lines.append(f"%ADD10C,{0.1:.6f}*%\n")
    lines.append("D10*\n")
    corners = [(0, 0), (width_mm, 0), (width_mm, height_mm), (0, height_mm), (0, 0)]
    for i, (x, y) in enumerate(corners):
        cmd = "D02" if i == 0 else "D01"
        lines.append(f"{_fmt_xy(x, y)}{cmd}*\n")
    return lines


def _polygon_list(
    polygon: list[tuple[float, float]],
    apertures: _ApertureManager,
    aperture_diameter: float = 0.1,
) -> list[str]:
    """Render a filled polygon region in Gerber (G36/G37 region mode).

    The polygon is drawn as a filled area using the aperture as
    the stroke for region-mode filling.  The actual fill width
    is controlled by the aperture diameter.
    """
    if not polygon or len(polygon) < 3:
        return []
    lines: list[str] = []
    d_code = apertures.define_circle(aperture_diameter)
    lines.append(f"D{d_code}*\n")
    lines.append("G36*\n")  # Start region
    for i, (x, y) in enumerate(polygon):
        cmd = "D02" if i == 0 else "D01"
        lines.append(f"{_fmt_xy(x, y)}{cmd}*\n")
    # Close polygon back to first point
    first = polygon[0]
    lines.append(f"{_fmt_xy(first[0], first[1])}D01*\n")
    lines.append("G37*\n")  # End region
    return lines


def _thermal_relief_list(
    reliefs: list,
    apertures: _ApertureManager,
    spoke_width: float = 0.3,
    gap: float = 0.2,
) -> list[str]:
    """Render thermal relief spokes as Gerber draw commands."""
    if not reliefs:
        return []
    lines: list[str] = []
    d_code = apertures.define_circle(spoke_width)
    lines.append(f"D{d_code}*\n")
    for r in reliefs:
        try:
            px, py = r.pad_position
            pd = getattr(r, "pad_diameter", 0.45)
        except (TypeError, IndexError):
            continue
        spoke_len = pd / 2 + 0.1  # extend slightly past pad edge
        spoke_gap = pd / 2 + gap
        for angle_deg in (45, 135, 225, 315):
            rad = math.radians(angle_deg)
            sx = px + spoke_gap * math.cos(rad)
            sy = py + spoke_gap * math.sin(rad)
            ex = px + spoke_len * math.cos(rad)
            ey = py + spoke_len * math.sin(rad)
            lines.append(f"{_fmt_xy(sx, sy)}D02*\n")
            lines.append(f"{_fmt_xy(ex, ey)}D01*\n")
    return lines


def _silk_list(design: Design) -> list[str]:
    """Build silkscreen layer lines (component outlines + refs)."""
    lines: list[str] = []
    for comp in design.components.values():
        pos = comp.position or (0.0, 0.0)
        # Reference designator text
        lines.append(f"G04 Reference: {comp.ref}*\n")
        lines.append(f"{_fmt_xy(pos[0], pos[1])}D02*\n")
    return lines


# ---------------------------------------------------------------------------
# Copper pour rendering
# ---------------------------------------------------------------------------


# Layer name mapping: Gerber layer keys → pour layer identifiers
_LAYER_TO_POUR: dict[str, tuple[str, ...]] = {
    "top": ("top", "F.Cu", "F_Cu", "1"),
    "bottom": ("bottom", "B.Cu", "B_Cu", "2"),
}


def _add_copper_pour(
    lines: list[str],
    design: Design,
    apertures: _ApertureManager,
    layer_name: str,
) -> None:
    """Render copper pour areas for *layer_name* into *lines*."""
    pour_names = _LAYER_TO_POUR.get(layer_name, (layer_name,))
    for pour_key in sorted(design.copper_pours):
        pour = design.copper_pours[pour_key]
        if pour.layer not in pour_names:
            continue
        if not pour.polygon or len(pour.polygon) < 3:
            continue
        lines.extend(_polygon_list(pour.polygon, apertures, 0.1))
        # Cutouts (negative areas)
        for cutout in pour.cutouts:
            lines.extend(_polygon_list(cutout, apertures, 0.1))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _collect_gerber_pads(design: Design) -> list[tuple[str, float, float, float, float, str]]:
    pads: list[tuple[str, float, float, float, float, str]] = []
    for comp in design.components.values():
        if not comp.footprint_def or not comp.position:
            continue
        cx, cy = comp.position
        for pad in comp.footprint_def.pads:
            layer = "top" if pad.layer.value in ("top", "all") else "bottom"
            pads.append((layer, cx + pad.position[0], cy + pad.position[1], pad.size[0], pad.size[1], pad.shape.value))
    return pads


def _gerber_copper_lines(
    design: Design,
    layer_name: str,
    pads: list[tuple[str, float, float, float, float, str]],
    apertures: _ApertureManager,
) -> list[str]:
    lines = _header_list(layer_name.upper())
    _add_copper_pour(lines, design, apertures, layer_name)
    traces = design.routing.traces if design.routing else []
    lines.extend(_traces_list(traces, apertures, layer_name))
    lines.extend(_pads_list([pad for pad in pads if pad[0] == layer_name], apertures))
    for pour in design.copper_pours.values():
        if pour.layer == layer_name and pour.thermal_reliefs:
            lines.extend(_thermal_relief_list(pour.thermal_reliefs, apertures))
    _insert_after_lpc(lines, apertures.header_lines())
    lines.append(_EOF)
    return lines


def _gerber_pad_layer_lines(
    layer_name: str, pads: list[tuple[str, float, float, float, float, str]], apertures: _ApertureManager
) -> list[str]:
    copper_layer = "top" if layer_name == "top_paste" else layer_name.replace("_mask", "")
    header_name = "TOP_PASTE" if layer_name == "top_paste" else layer_name.upper()
    lines = _header_list(header_name)
    lines.extend(_pads_list([pad for pad in pads if pad[0] == copper_layer], apertures))
    _insert_after_lpc(lines, apertures.header_lines())
    lines.append(_EOF)
    return lines


def _render_gerber_layer(
    design: Design,
    layer_name: str,
    pads: list[tuple[str, float, float, float, float, str]],
    width: float,
    height: float,
) -> str:
    apertures = _ApertureManager()
    if layer_name == "outline":
        lines = [*_header_list("OUTLINE"), *_outline_list(width, height), _EOF]
    elif layer_name in ("top", "bottom"):
        lines = _gerber_copper_lines(design, layer_name, pads, apertures)
    elif layer_name in ("top_mask", "bottom_mask", "top_paste"):
        lines = _gerber_pad_layer_lines(layer_name, pads, apertures)
    elif layer_name == "top_silk":
        lines = [*_header_list("TOP_SILK"), *_silk_list(design), _EOF]
    else:
        lines = [*_header_list(layer_name.upper()), _EOF]
    return "".join(lines)


def generate_gerber(design: Design, output_dir: str | Path | None = None, prefix: str = "") -> dict[str, str]:
    """Generate Gerber files for all PCB layers."""
    use_files = output_dir is not None
    out_dir = Path(output_dir) if output_dir else Path()
    if use_files:
        out_dir.mkdir(parents=True, exist_ok=True)
    prefix = safe_export_stem(prefix or design.meta.name or "board")
    board = canonical_board_definition(design)
    pads = _collect_gerber_pads(design)
    layer_configs = [
        ("top", prefix + ".GTL"),
        ("bottom", prefix + ".GBL"),
        ("outline", prefix + ".GKO"),
        ("top_silk", prefix + ".GTO"),
        ("top_mask", prefix + ".GTS"),
        ("bottom_mask", prefix + ".GBS"),
        ("top_paste", prefix + ".GPT"),
    ]
    result: dict[str, str] = {}
    for layer_name, filename in layer_configs:
        content = _render_gerber_layer(design, layer_name, pads, board.width, board.height)
        if use_files:
            filepath = out_dir / filename
            filepath.write_text(content, encoding="utf-8")
            result[layer_name] = str(filepath)
        else:
            result[layer_name] = content
    return result


def _insert_after_lpc(lines: list[str], insert_lines: list[str]) -> None:
    """Insert lines after the first %LPC...% line."""
    for i, line in enumerate(lines):
        if line.startswith("%LPC"):
            for _j, h in enumerate(reversed(insert_lines)):
                lines.insert(i + 1, h)
            break


_LAYER_JOB_METADATA: dict[str, dict[str, str]] = {
    "top": {"filename_suffix": ".GTL", "function": "Copper,L1,Top", "polarity": "Positive"},
    "bottom": {"filename_suffix": ".GBL", "function": "Copper,L2,Bot", "polarity": "Positive"},
    "outline": {"filename_suffix": ".GKO", "function": "Profile,NP", "polarity": "Positive"},
    "top_silk": {"filename_suffix": ".GTO", "function": "Legend,Top", "polarity": "Positive"},
    "top_mask": {"filename_suffix": ".GTS", "function": "Soldermask,Top", "polarity": "Positive"},
    "bottom_mask": {"filename_suffix": ".GBS", "function": "Soldermask,Bot", "polarity": "Positive"},
    "top_paste": {"filename_suffix": ".GPT", "function": "Paste,Top", "polarity": "Positive"},
}


def generate_gerber_job_file(design: Design, gerber_files: Mapping[str, str | Path]) -> str:
    """Generate a deterministic Gerber Job File JSON document."""
    board = canonical_board_definition(design)
    files: list[dict[str, Any]] = []
    for layer, path in sorted(gerber_files.items()):
        metadata = _LAYER_JOB_METADATA.get(layer, {})
        files.append(
            {
                "layer": layer,
                "path": Path(path).name,
                "function": metadata.get("function", layer),
                "polarity": metadata.get("polarity", "Positive"),
            }
        )
    job = {
        "schema_version": "1.0",
        "format": "Gerber Job File",
        "generator": "zaptrace.export.gerber",
        "tool_version": __version__,
        "design": design.meta.name,
        "board": {
            "width_mm": board.width,
            "height_mm": board.height,
            "layers": board.layers,
        },
        "files": files,
    }
    return json.dumps(job, indent=2, sort_keys=True) + "\n"


def write_gerber_job_file(design: Design, gerber_files: Mapping[str, str | Path], output_path: str | Path) -> Path:
    """Write a Gerber Job File and return the output path."""
    out = Path(output_path)
    if out.suffix.lower() != ".gbrjob":
        raise ValueError(f"unexpected Gerber Job File suffix: {out.suffix}")
    resolved = out.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # nosemgrep: python.lang.security.audit.path-traversal.path-traversal-write
    resolved.write_text(generate_gerber_job_file(design, gerber_files), encoding="utf-8")
    return resolved


def validate_gerber_x2_attributes(content: str) -> dict[str, bool | list[str]]:
    """Validate required Gerber X2 file attributes in a Gerber document."""
    required = ["%TF.GenerationSoftware", "%TF.FileFunction", "%TF.FilePolarity"]
    missing = [token for token in required if token not in content]
    return {
        "passed": not missing,
        "missing_attributes": missing,
        "required_attributes": required,
    }


def _component_pads_for_layer(
    design: Design,
    layer: str,
) -> list[tuple[str, float, float, float, float, str]]:
    """Return positioned component-pad tuples for one copper layer."""
    pads: list[tuple[str, float, float, float, float, str]] = []
    for component in design.components.values():
        if component.footprint_def is None or component.position is None:
            continue
        component_x, component_y = component.position
        for pad in component.footprint_def.pads:
            if pad.layer.value not in (layer, "all"):
                continue
            pads.append(
                (
                    layer,
                    component_x + pad.position[0],
                    component_y + pad.position[1],
                    pad.size[0],
                    pad.size[1],
                    pad.shape.value,
                )
            )
    return pads


def generate_copper_layer(design: Design, layer: str = "top") -> str:
    """Generate Gerber content for a single copper layer.

    Args:
        design: The design with routing data.
        layer: Layer name (``"top"`` or ``"bottom"``).

    Returns:
        RS-274X Gerber string.
    """
    lines: list[str] = _header_list(layer.upper())
    apertures = _ApertureManager()

    # Copper pour / flood fill
    _add_copper_pour(lines, design, apertures, layer)

    traces = design.routing.traces if design.routing else []
    lines.extend(_traces_list(traces, apertures, layer))

    # Pads
    lines.extend(_pads_list(_component_pads_for_layer(design, layer), apertures))

    # Thermal reliefs for pads in the pour
    pour_names = _LAYER_TO_POUR.get(layer, (layer,))
    for pour in design.copper_pours.values():
        if pour.layer in pour_names and pour.thermal_reliefs:
            lines.extend(
                _thermal_relief_list(pour.thermal_reliefs, apertures),
            )

    # Insert aperture definitions
    header = apertures.header_lines()
    _insert_after_lpc(lines, header)

    lines.append(_EOF)
    return "".join(lines)


def generate_board_outline(width_mm: float, height_mm: float) -> str:
    """Generate Gerber content for board outline layer.

    Args:
        width_mm: Board width in mm.
        height_mm: Board height in mm.

    Returns:
        RS-274X Gerber string.
    """
    lines = _header_list("OUTLINE")
    lines.extend(_outline_list(width_mm, height_mm))
    lines.append(_EOF)
    return "".join(lines)
