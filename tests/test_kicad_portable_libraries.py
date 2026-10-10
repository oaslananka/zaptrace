"""Project-local KiCad libraries must only resolve actual verified packages."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from zaptrace.core.parser import parse_file
from zaptrace.export.kicad import export_kicad, export_kicad_pcb
from zaptrace.kicad.verified_vendor import _PINNED_FOOTPRINTS

_EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"


@pytest.mark.parametrize(
    "untrusted_member",
    [
        "ZapTrace.kicad_sym",
        "sym-lib-table",
        "ZapTrace.pretty",
        "fp-lib-table",
        "ZapTrace.pretty/SOT-223-3_TabPin2.kicad_mod",
    ],
)
def test_portable_libraries_reject_symlinks_outside_workspace(tmp_path: Path, untrusted_member: str) -> None:
    """Never overwrite an external file or copy verified copper outside root."""
    export_dir = tmp_path / "output"
    external = tmp_path / "external"
    export_dir.mkdir()
    external.mkdir()
    target = external / "sentinel"
    target.write_text("MUST-NOT-OVERWRITE", encoding="utf-8")
    forged = export_dir / untrusted_member
    forged.parent.mkdir(parents=True, exist_ok=True)
    forged.symlink_to(external if untrusted_member == "ZapTrace.pretty" else target)

    design = parse_file(_EXAMPLE)
    with pytest.raises(ValueError, match="output member escapes output directory"):
        export_kicad(design, export_dir)
    assert target.read_text(encoding="utf-8") == "MUST-NOT-OVERWRITE"
    assert not (external / "SOT-223-3_TabPin2.kicad_mod").exists()


def test_library_member_resolution_does_not_create_workspace(tmp_path: Path) -> None:
    """Export initializes the trusted root; path checking alone never writes."""
    from zaptrace.export.path_policy import resolve_output_member

    output = tmp_path / "not-created"
    assert resolve_output_member(output, "sym-lib-table") == output / "sym-lib-table"
    assert not output.exists()


@pytest.mark.parametrize("bad_member", ["", ".", "..", "../outside", "a/b", "a\\b"])
def test_portable_library_output_member_rejects_path_fragments(tmp_path: Path, bad_member: str) -> None:
    from zaptrace.export.path_policy import resolve_output_member

    with pytest.raises(ValueError, match="single path component"):
        resolve_output_member(tmp_path / "output", bad_member)


def test_verified_assets_are_portable_and_byte_identical(tmp_path: Path) -> None:
    design = parse_file(_EXAMPLE)
    # The demo source intentionally has no precomputed board placement.
    design.placement = {"U3": (20.0, 15.0)}
    files = export_kicad(design, tmp_path)
    for key in ("schematic", "pcb", "project", "symbol_library", "symbol_library_table", "footprint_library_table"):
        assert files[key].is_file()

    sym_table = files["symbol_library_table"].read_text(encoding="utf-8")
    fp_table = files["footprint_library_table"].read_text(encoding="utf-8")
    assert "${KIPRJMOD}/ZapTrace.kicad_sym" in sym_table
    assert "${KIPRJMOD}/ZapTrace.pretty" in fp_table
    assert '(symbol "ZapTrace_U3"' in files["symbol_library"].read_text(encoding="utf-8")

    schematic = files["schematic"].read_text(encoding="utf-8")
    pcb = files["pcb"].read_text(encoding="utf-8")
    assert '(lib_id "ZapTrace:ZapTrace_U3")' in schematic
    assert '(property "Footprint" "ZapTrace:SOT-223-3_TabPin2"' in schematic
    assert '(footprint "ZapTrace:SOT-223-3_TabPin2"' in pcb

    for asset in {comp.footprint_asset for comp in design.components.values()} - {None}:
        filename, digest = _PINNED_FOOTPRINTS[asset]
        source = Path(__file__).resolve().parents[1] / "data" / "footprints" / "vendor" / filename
        copied = tmp_path / "ZapTrace.pretty" / filename
        assert copied.read_bytes() == source.read_bytes()
        assert hashlib.sha256(copied.read_bytes()).hexdigest() == digest

    # Physical J1 source file is pinned; this is NOT electrical/DRC or fab acceptance.
    assert '(property "Footprint" "ZapTrace:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal"' in schematic
    assert (
        tmp_path / "ZapTrace.pretty" / "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.kicad_mod"
    ).is_file()
    assert '(property "Footprint" "ZapTrace:D_SOD-323"' in schematic
    assert (tmp_path / "ZapTrace.pretty" / "D_SOD-323.kicad_mod").is_file()


def test_standalone_pcb_export_includes_pinned_local_footprints(tmp_path: Path) -> None:
    design = parse_file(_EXAMPLE)
    design.placement = {"U3": (20.0, 15.0)}
    files = export_kicad_pcb(design, tmp_path)
    assert files["footprint_library_table"].is_file()
    assert (tmp_path / "ZapTrace.pretty" / "SOT-223-3_TabPin2.kicad_mod").is_file()
    pcb_text = files["pcb"].read_text(encoding="utf-8")
    assert '(footprint "ZapTrace:SOT-223-3_TabPin2"' in pcb_text


def test_verified_assets_reject_forged_in_memory_geometry(tmp_path: Path) -> None:
    design = parse_file(_EXAMPLE)
    design.components["U3"].footprint_def.pads[0].size = (99.0, 99.0)
    with pytest.raises(ValueError, match="Verified footprint geometry conflicts"):
        export_kicad(design, tmp_path)


def test_verified_assets_reject_wrong_digest_on_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asset_id = "ams1117-sot223-tabpin2"
    filename, _digest = _PINNED_FOOTPRINTS[asset_id]
    design = parse_file(_EXAMPLE)
    monkeypatch.setitem(_PINNED_FOOTPRINTS, asset_id, (filename, "0" * 64))
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        export_kicad(design, tmp_path)


def test_real_kicad10_erc_uses_verified_j1_footprint_without_link_warning(tmp_path: Path) -> None:
    binary = shutil.which("kicad-cli")
    if binary is None:
        pytest.skip("KiCad CLI not installed")
    version = subprocess.run([binary, "version"], capture_output=True, text=True, timeout=10, check=True)
    if not version.stdout.startswith("10."):
        pytest.skip(f"Requires the independently verified KiCad 10 ERC contract, got {version.stdout!r}")

    design = parse_file(_EXAMPLE)
    files = export_kicad(design, tmp_path)
    output = tmp_path / "erc.json"
    run = subprocess.run(
        [
            binary,
            "sch",
            "erc",
            "--format",
            "json",
            "--severity-all",
            "--exit-code-violations",
            "--output",
            str(output),
            str(files["schematic"]),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    sheets = report["sheets"]
    warnings = (
        sheets.get("violations", [])
        if isinstance(sheets, dict)
        else [v for sheet in sheets for v in sheet.get("violations", [])]
    )
    # A verified J1 library reference resolves this metadata warning.
    # Clean schematic ERC does NOT mean correct copper, routing or fab approval.
    assert warnings == []
