"""Strict isolated KiCad ERC library packaging for source-backed pilot geometry.

Generated footprints reproduce geometry for inspection and are NOT
manufacturer-qualified component packages or production release artifacts.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from zaptrace.core.models import Component, Design, Pad
from zaptrace.export.kicad import _build_pad
from zaptrace.kicad.importer import load_kicad_footprint

_REF = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,48}\Z")
_PAD_ID = re.compile(r"[A-Za-z0-9_.-]{1,32}\Z")


def _pad_signature(pad: Pad) -> tuple[Any, ...]:
    return (
        pad.id,
        str(pad.shape),
        tuple(round(v, 5) for v in pad.position),
        tuple(round(v, 5) for v in pad.size),
        str(pad.layer),
        round(pad.drill, 5) if pad.drill is not None else None,
        tuple(round(v, 5) for v in pad.drill_slot) if pad.drill_slot else None,
        pad.plated,
        pad.solder_paste,
        round(pad.rotation, 5),
        round(pad.roundrect_rratio, 5) if pad.roundrect_rratio is not None else None,
    )


_PASSIVE_REFS = {f"R{i}" for i in range(1, 6)} | {f"C{i}" for i in range(1, 4)}


def _verified_pilot_0402_courtyard(component: Component) -> tuple[float, float] | None:
    """Only replay the candidate's bounded 0402 courtyard, not donor copper art.

    The physical pad model is an inspection-only IPC-style seed. The small-
    component 0.15 mm minimum is KiCad KLC F5.3, not a fab approval.
    """
    if component.ref not in _PASSIVE_REFS:
        return None
    fp = component.footprint_def
    if fp is None or fp.source != "IPC-7351B" or fp.courtyard != (2.0, 1.5):
        raise ValueError(f"{component.ref}: unsupported source-derived 0402 courtyard")
    expected = {
        "1": ((-0.55, 0.0), (0.6, 0.7)),
        "2": ((0.55, 0.0), (0.6, 0.7)),
    }
    if (
        component.type not in {"resistor", "capacitor"}
        or len(fp.pads) != 2
        or {
            pad.id: (tuple(pad.position), tuple(pad.size))
            for pad in fp.pads
            if pad.rotation == 0 and str(pad.shape) == "rect"
        }
        != expected
    ):
        raise ValueError(f"{component.ref}: 0402 pad model changed without courtyard qualification")
    width, height = fp.courtyard
    for pad in fp.pads:
        if (
            width / 2 - abs(pad.position[0]) - pad.size[0] / 2 < 0.14999
            or height / 2 - abs(pad.position[1]) - pad.size[1] / 2 < 0.14999
        ):
            raise ValueError(f"{component.ref}: 0402 courtyard violates 0.15 mm pad envelope clearance")
    if (
        len(fp.outline) != 1
        or fp.outline[0].type != "rect"
        or fp.outline[0].params
        != {
            "x": -0.7,
            "y": -0.45,
            "width": 1.4,
            "height": 0.9,
        }
    ):
        raise ValueError(f"{component.ref}: 0402 source body envelope changed")
    return width, height


def _checked_native_pad_contents(component: Component, dest: Path, name: str) -> None:
    geometry = component.footprint_def
    if geometry is None or not geometry.pads or len(geometry.pads) > 128:
        raise ValueError(f"{component.ref}: cannot make native footprint without bounded pad geometry")
    lines = [
        f'(footprint "{name}"',
        "  (version 20241229)",
        '  (generator "zaptrace_local_oracle")',
        '  (layer "F.Cu")',
        '  (property "Reference" "REF**" (at 0 -2 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))',
        f'  (property "Value" "{name}" (at 0 3 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))',
    ]
    for ordinal, pad in enumerate(geometry.pads):
        # KiCad's SHA-pinned GCT USB4105 has two anonymous non-plated
        # alignment holes. A blank copper/plated pad is never permitted.
        mechanical = (
            pad.id == ""
            and component.mpn == "USB4105-15-A-120"
            and not pad.plated
            and (pad.drill is not None or pad.drill_slot is not None)
            and geometry.source == "KiCad:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal"
        )
        if not _PAD_ID.fullmatch(pad.id) and not mechanical:
            raise ValueError(f"{component.ref}: unsafe or anonymous physical pad identifier")
        if not all(math.isfinite(v) and abs(v) < 10000 for v in (*pad.position, *pad.size, pad.rotation)):
            raise ValueError(f"{component.ref}: non-finite or out-of-bounds physical geometry")
        if any(v <= 0 for v in pad.size):
            raise ValueError(f"{component.ref}: physical pad must have positive dimensions")
        _build_pad(lines, pad, component, {}, None, pad_ordinal=ordinal)
    courtyard = _verified_pilot_0402_courtyard(component)
    if courtyard is not None:
        width, height = courtyard
        lines.append(
            f"  (fp_rect (start {-width / 2:g} {-height / 2:g})"
            f" (end {width / 2:g} {height / 2:g})"
            ' (stroke (width 0.05) (type solid)) (fill none) (layer "F.CrtYd"))'
        )
    lines.append(")")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    exported = load_kicad_footprint(dest)
    if exported is None:
        raise ValueError(f"{component.ref}: generated KiCad footprint is not parseable")
    original_signatures = Counter(_pad_signature(p) for p in geometry.pads)
    reimported_signatures = Counter(_pad_signature(p) for p in exported.pads)
    if original_signatures != reimported_signatures:
        raise ValueError(f"{component.ref}: generated KiCad pads do not match source geometry")
    if courtyard is not None and exported.courtyard != courtyard:
        raise ValueError(f"{component.ref}: generated native 0402 courtyard differs from source")


def prepare_pilot_kicad_libraries(design: Design, folder: Path) -> list[dict[str, str]]:
    """Create an inspection-only project-local footprint library.

    Design is an isolated in-memory deserialization of a SHA-bound candidate.
    Local KiCad library IDs do not mutate the source candidate artifacts.
    """
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Native oracle project directory must be real")
    pretty = folder / "ZapTracePilot.pretty"
    pretty.mkdir()
    inventory: list[dict[str, str]] = []
    refs: set[str] = set()
    for component in design.components.values():
        if not _REF.fullmatch(component.ref) or component.ref in refs:
            raise ValueError("Unsafe or duplicate native footprint reference")
        refs.add(component.ref)
        if component.footprint_asset:
            expected_assets = {
                "U1": "ap2112-sot23-5",
                "U2": "stm32-lqfp48",
                "U3": "sht31-dfn8",
            }
            if expected_assets.get(component.ref) != component.footprint_asset:
                raise ValueError("Unexpected verified asset in isolated pilot")
            from zaptrace.kicad.verified_vendor import verified_footprint_bytes

            filename, _content = verified_footprint_bytes(component.footprint_asset)
            original_library_hint = component.footprint
            component.footprint = "ZapTrace:" + filename.removesuffix(".kicad_mod")
            inventory.append(
                {
                    "ref": component.ref,
                    "original_hint": original_library_hint,
                    "local_id": component.footprint,
                    "geometry_source": component.footprint_def.source if component.footprint_def else "",
                    "status": "sha_pinned_original_complete_land_pattern_not_fabrication_approved",
                }
            )
            continue
        stem = "ZT_" + component.ref
        mod = pretty / (stem + ".kicad_mod")
        original_library_hint = component.footprint
        _checked_native_pad_contents(component, mod, stem)
        component.footprint = "ZapTracePilot:" + stem
        inventory.append(
            {
                "ref": component.ref,
                "original_hint": original_library_hint,
                "local_id": component.footprint,
                "geometry_source": component.footprint_def.source if component.footprint_def else "",
                "status": "inspection_only_generated_geometry_not_fabrication_approved",
            }
        )
    (folder / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        '  (lib (name "ZapTracePilot")(type "KiCad")'
        '(uri "' + "$" + '{KIPRJMOD}/ZapTracePilot.pretty")(options "")'
        '(descr "Locally generated unapproved geometry from a SHA-bound candidate"))\n'
        ")\n",
        encoding="utf-8",
    )
    (folder / "portable-library-manifest.json").write_text(
        json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return inventory
