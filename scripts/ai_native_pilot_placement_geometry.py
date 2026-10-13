"""Source-pinned physical geometry remediation for the exact local STM32 pilot.

Existing arbitrary two-sided MCU pad generator is unsafe for LQFP48. Replace
ONLY on an isolated candidate copy with SHA-pinned original KiCad LQFP art.
No manufacturer/IPC/fab signoff is inferred by this physical substitution.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from zaptrace.core.models import Design
from zaptrace.kicad.importer import load_kicad_footprint

_VENDOR_ROOT = Path(__file__).resolve().parents[1] / "data" / "footprints" / "vendor"
_FOOTPRINTS = {
    "U2": (
        "STM32F103C8T6",
        "STM32F103C8T6-LQFP48",
        "LQFP-48_7x7mm_P0.5mm.kicad_mod",
        "ec36273cf5fa99acf022c2f5af17310d123fa4b5ccfe98a2f562fedabe7f3f46",
        48,
    ),
    "U3": (
        "SHT31-DIS-B2.5kS",
        "SHT31-DIS-DFN8",
        "Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm.kicad_mod",
        "2380f3b4d6982902f05e8940603f19f7cfbc1bdfd6ae0f78ebd281c1a3f30a8f",
        9,
    ),
}


def require_pinned_physical_packages(design: Design) -> dict[str, dict]:
    if set(design.components) != {"C1", "C2", "C3", "J1", "R1", "R2", "R3", "R4", "R5", "U1", "U2", "U3"}:
        raise ValueError("Unsupported physical package verification scope")
    report: dict[str, dict] = {}
    for ref, (mpn, footprint_name, filename, expected_sha, pad_count) in _FOOTPRINTS.items():
        comp = design.components[ref]
        if (
            comp.ref != ref
            or comp.mpn != mpn
            or comp.footprint != footprint_name
            or comp.footprint_def is not None
            or comp.footprint_asset
        ):
            raise ValueError("Physical source part/geometry contract was modified: " + ref)
        path = _VENDOR_ROOT / filename
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
            raise ValueError("Original vendor land-pattern checksum mismatch: " + ref)
        fp = load_kicad_footprint(path)
        if fp is None or len(fp.pads) != pad_count or len({p.id for p in fp.pads}) != pad_count:
            raise ValueError("Source KiCad footprint physical pad inventory mismatch: " + ref)
        if ref == "U2" and (
            set(p.id for p in fp.pads) != {str(i) for i in range(1, 49)}
            or fp.courtyard != (10.3, 10.3)
            or comp.package_pin_map.get("42") != "PB6"
            or comp.package_pin_map.get("43") != "PB7"
        ):
            raise ValueError("STM32 source LQFP48 geometry/pin-function contract not proven")
        if ref == "U3" and (
            set(p.id for p in fp.pads) != {str(i) for i in range(1, 10)}
            or not any(p.id == "9" and not p.solder_paste for p in fp.pads)
        ):
            raise ValueError("SHT31 source thermal/paste pad contract not proven")
        comp.footprint_def = fp
        from zaptrace.kicad.verified_vendor import resolve_verified_footprint

        asset = {"U1": "ap2112-sot23-5", "U2": "stm32-lqfp48", "U3": "sht31-dfn8"}.get(ref)
        if asset is not None:
            if fp != resolve_verified_footprint(asset):
                raise ValueError(f"{ref} pinned native package differs from its source pad model")
            if ref == "U2" and (
                comp.package_pin_map.get("5") != "PD0"
                or comp.package_pin_map.get("6") != "PD1"
                or any(
                    node.component_ref == "U2" and node.pin_name in {"PD0", "PD1"}
                    for net in design.nets.values()
                    for node in net.nodes
                )
            ):
                raise ValueError("Unmodeled U2 PD0/PD1 pins must remain electrically unconnected")
            comp.footprint_asset = asset
        report[ref] = {
            "part": mpn,
            "source": filename,
            "sha256": expected_sha,
            "pad_count": pad_count,
            "evidence": "exact KiCad official vendored library geometry, not physical assembly approval",
        }
    regulator = design.components["U1"]
    from zaptrace.kicad.verified_vendor import resolve_verified_footprint

    if (
        regulator.mpn != "AP2112K-3.3TRG1"
        or regulator.footprint_def != resolve_verified_footprint("ap2112-sot23-5")
        or regulator.footprint_asset
    ):
        raise ValueError("Unverified regulator physical footprint inventory")
    regulator.footprint_asset = "ap2112-sot23-5"
    report["U1"] = {
        "part": regulator.mpn,
        "source": "SOT-23-5.kicad_mod",
        "sha256": "2a5c9e030fb192cd2393b5f95872fe796deb29ae7570c83050e19f7b78ceea71",
        "pad_count": 5,
        "evidence": "exact source package artwork, regulator pinout/part fabrication NOT approved",
    }
    return report


def place_gct_receptacle_at_provisional_board_edge(design: Design) -> dict:
    """Align KiCad vendor Dwgs.User PCB Edge line to *provisional* bottom outline.

    GCT USB4105 vendored footprint documents its intended PCB edge as a
    Dwgs.User line at relative Y=3.675 mm; manual manufacturer review of
    mating envelope and stack-up is still required.
    """
    from zaptrace.core.board import canonical_board_definition

    ref = design.components["J1"]
    if ref.mpn != "USB4105-15-A-120" or ref.footprint_def is None:
        raise ValueError("Missing original GCT physical package")
    board = canonical_board_definition(design)
    if board.width != 100 or board.height != 80:
        raise ValueError("Unsupported pilot mechanical envelope")
    positions = design.placement
    if positions is None or set(positions) != set(design.components):
        raise ValueError("Missing deterministic complete baseline placement")
    x = board.width / 2
    y = board.height - 3.675
    positions["J1"] = (x, y)
    if any(
        x + pad.position[0] < 0
        or x + pad.position[0] > board.width
        or y + pad.position[1] < 0
        or y + pad.position[1] > board.height
        for pad in ref.footprint_def.pads
    ):
        raise ValueError("USB-C physical pads extend beyond initial PCB boundary")
    return {
        "ref": "J1",
        "position_mm": [x, y],
        "board_edge": "bottom_y_80",
        "vendor_kicad_pcb_edge_marker_relative_y_mm": 3.675,
        "board_edge_alignment_status": "provisional_dwg_marker_matches_edge",
        "manufacturer_mechanical_and_mating_envelope_approved": False,
    }
