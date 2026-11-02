"""Negative and genuine native KiCad acceptance for local unapproved candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.ai_native_candidate_oracles import run_local_oracles
from scripts.ai_native_candidate_pilot import write_local_candidate

INTENT = "USB-C powered STM32 MCU board, 3.3V rail at 100 mA, I2C temperature sensor"


def test_integrity_rejects_tampered_design_before_oracle_runs(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    (candidate / "design.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="SHA mismatch"):
        run_local_oracles(candidate, tmp_path / "should-not-exist")
    assert not (tmp_path / "should-not-exist").exists()


def test_oracle_input_symlink_and_existing_output_refused(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    alias = tmp_path / "symlink"
    alias.symlink_to(candidate, target_is_directory=True)
    with pytest.raises(ValueError):
        run_local_oracles(alias, tmp_path / "unused")
    preexisting = tmp_path / "preexisting"
    preexisting.mkdir()
    (preexisting / "important").write_text("KEEP")
    with pytest.raises(ValueError):
        run_local_oracles(candidate, preexisting)
    assert (preexisting / "important").read_text() == "KEEP"


def test_native_kicad_report_and_missing_simulation_remain_unapproved(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    result = run_local_oracles(candidate, tmp_path / "oracles")
    assert result["fabrication_approved"] is False
    assert result["native_erc"]["status"] in {"blocked", "not_checked"}
    assert result["simulation"]["status"] in {"not_checked", "blocked", "dc_only_passed_not_transient_qualified"}
    assert result["physical_routing_drc"] == "not_checked"
    evidence = tmp_path / "oracles/oracle-evidence.json"
    assert json.loads(evidence.read_text())["candidate_id"] == result["candidate_id"]
    for name, expected in result["source_sha256"].items():
        assert hashlib.sha256((candidate / name).read_bytes()).hexdigest() == expected
    if result["native_erc"]["status"] != "not_checked":
        assert result["native_erc"]["ignored_checks"] or (
            result["native_erc"]["errors"] or result["native_erc"]["warnings"]
        )


def test_portable_native_library_reimports_every_pad_including_mask(tmp_path: Path) -> None:
    from scripts.ai_native_pilot_kicad_lib import prepare_pilot_kicad_libraries
    from zaptrace.core.models import Design
    from zaptrace.kicad.importer import load_kicad_footprint
    from zaptrace.synthesis.candidate import compile_intent
    from zaptrace.synthesis.footprint_resolver import resolve_footprints

    source_design, _ = compile_intent(INTENT)
    source_hash = hashlib.sha256(json.dumps(source_design.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    design = Design.model_validate(source_design.model_dump(mode="json"))
    assert resolve_footprints(design).fully_resolved
    folder = tmp_path / "kicad"
    folder.mkdir()
    library = prepare_pilot_kicad_libraries(design, folder)
    assert len(library) == 12
    assert (folder / "fp-lib-table").is_file()
    assert len(list((folder / "ZapTracePilot.pretty").glob("*.kicad_mod"))) == 12
    sensor = load_kicad_footprint(folder / "ZapTracePilot.pretty/ZT_U3.kicad_mod")
    assert sensor is not None
    source_sensor = design.components["U3"].footprint_def
    assert source_sensor is not None
    assert any(pad.id == "9" and not pad.solder_paste for pad in sensor.pads)
    assert any(pad.id == "9" and not pad.solder_paste for pad in source_sensor.pads)
    assert all(item["status"].endswith("not_fabrication_approved") for item in library)
    assert (
        hashlib.sha256(json.dumps(source_design.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        == source_hash
    )


def test_pilot_native_library_rejects_unresolved_geometry_or_malicious_pad_id(tmp_path: Path) -> None:
    from scripts.ai_native_pilot_kicad_lib import prepare_pilot_kicad_libraries
    from zaptrace.synthesis.candidate import compile_intent
    from zaptrace.synthesis.footprint_resolver import resolve_footprints

    design, _ = compile_intent(INTENT)
    assert resolve_footprints(design).fully_resolved
    assert design.components["C1"].footprint_def is not None
    design.components["C1"].footprint_def.pads[0].id = '1") (pad "FAKE'
    folder = tmp_path / "invalid"
    folder.mkdir()
    with pytest.raises(ValueError, match="unsafe or anonymous physical pad"):
        prepare_pilot_kicad_libraries(design, folder)


def test_native_pin_pad_parser_rejects_false_match_and_preserves_true_scoped_result(tmp_path: Path) -> None:
    from scripts.ai_native_pilot_pin_parity import crosscheck_native_pin_pad_net
    from zaptrace.core.models import Net, NetNode
    from zaptrace.synthesis.candidate import compile_intent

    design, _ = compile_intent(INTENT)
    design.components = {"R1": design.components["R1"]}
    design.nets = {"CC1": Net(id="CC1", name="CC1", nodes=[NetNode(component_ref="R1", pin_name="1")])}
    target = tmp_path / "native.xml"
    target.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<export version="E"><design><source>isolated-native-example</source></design>'
        '<nets><net name="CC1"><node ref="R1" pin="1"/></net></nets></export>\n'
    )
    correct = crosscheck_native_pin_pad_net(design, target)
    assert correct["status"] == "scoped_pin_pad_net_match_not_engineering_approval"
    assert correct["matched_native_nodes"] == correct["native_nodes"] == 1
    assert correct["full_project_electrically_approved"] is False
    target.write_text(target.read_text().replace('pin="1"', 'pin="9"'))
    wrong = crosscheck_native_pin_pad_net(design, target)
    assert wrong["status"] == "blocked"
    assert "unexpected_native_net_node" in {reason["code"] for reason in wrong["reasons"]}
    assert "expected_net_node_missing_from_native" in {reason["code"] for reason in wrong["reasons"]}


def test_native_pilot_requires_complete_actual_component_pin_maps(tmp_path: Path) -> None:
    from scripts.ai_native_pilot_pin_parity import crosscheck_native_pin_pad_net
    from zaptrace.core.models import Design
    from zaptrace.synthesis.footprint_resolver import resolve_footprints

    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    design = Design.model_validate_json((candidate / "design.json").read_bytes())
    assert resolve_footprints(design).fully_resolved
    oracle = run_local_oracles(candidate, tmp_path / "oracle")
    native_xml = tmp_path / "oracle/kicad/native-netlist.xml"
    if oracle["native_erc"]["status"] == "not_checked":
        pytest.skip("Native KiCad executable absent")
    parity = crosscheck_native_pin_pad_net(design, native_xml)
    assert parity["status"] == oracle["native_pin_pad_net_parity"]["status"] == "blocked"
    assert parity["full_project_electrically_approved"] is False
    assert parity["matched_native_nodes"] == parity["native_nodes"] == 52
    reasons = {x["code"] for x in parity["reasons"]}
    assert reasons == {"repeated_physical_pad_id_requires_more_evidence"}
    assert any(x["ref"] == "J1" for x in parity["reasons"])
    assert parity["full_project_electrically_approved"] is False
    assert oracle["local_inspection_library"]["component_count"] == 12
    assert oracle["native_erc"]["errors"] == 0
    if str(oracle["native_erc"].get("kicad_version", "")).startswith("10."):
        assert oracle["native_erc"]["warnings"] == 0
        assert oracle["native_erc"]["status"] == "blocked"
    assert oracle["fabrication_approved"] is False


def test_strict_native_erc_enables_default_ignored_checks_without_waiving_anything(tmp_path: Path) -> None:

    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    result = run_local_oracles(candidate, tmp_path / "native-oracle")
    strict = result["native_erc_four_default_ignored_enabled"]
    if strict["status"] == "not_checked":
        pytest.skip("No native KiCad CLI")
    assert set(strict["rule_severities_after"]) == {
        "footprint_filter",
        "simulation_model_issue",
        "single_global_label",
        "four_way_junction",
    }
    assert set(strict["rule_severities_after"].values()) == {"warning"}
    assert strict["ignored_checks"] == []
    assert strict["violations"] == []
    assert strict["cli_exit"] == 0
    assert strict["status"] == "scoped_native_erc_complete_not_electrical_signoff"
    assert strict["source_schematic_sha256"] == result["native_erc"]["schematic_sha256"]
    assert strict["strict_schematic_sha256"] == result["native_erc"]["schematic_sha256"]
    assert strict["simulation_run"] is False
    assert strict["fabrication_approved"] is False
    assert result["native_erc"]["status"] == "blocked"  # default KiCad ignored four
    assert result["native_pin_pad_net_parity"]["status"] == "blocked"
    assert result["fabrication_approved"] is False


def test_strict_native_erc_fails_closed_on_unexpected_ignored_check(tmp_path: Path, monkeypatch) -> None:
    from scripts import ai_native_pilot_strict_erc as module
    from scripts.ai_native_pilot_kicad_lib import prepare_pilot_kicad_libraries
    from zaptrace.export.kicad import export_kicad_schematic
    from zaptrace.synthesis.candidate import compile_intent
    from zaptrace.synthesis.footprint_resolver import resolve_footprints

    design, _ = compile_intent(INTENT)
    resolve_footprints(design)
    original_dir = tmp_path / "real-source"
    original_dir.mkdir()
    prepare_pilot_kicad_libraries(design, original_dir)
    schematic = export_kicad_schematic(design, original_dir)["schematic"]
    real_run = module.subprocess.run

    def malformed_extra_ignore(args, **kwargs):
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "$schema": "https://schemas.kicad.org/erc.v1.json",
                    "sheets": [{"violations": []}],
                    "ignored_checks": [{"key": "unexpected_security_rule", "description": "not checked"}],
                    "included_severities": ["error", "warning", "exclusion"],
                    "kicad_version": "10.0.7",
                }
            )
        )
        return subprocess.CompletedProcess(args, 0)

    import subprocess

    monkeypatch.setattr(module.subprocess, "run", malformed_extra_ignore)
    try:
        report = module.verify_expanded_erc(schematic, "kicad-cli", tmp_path / "test")
    finally:
        monkeypatch.setattr(module.subprocess, "run", real_run)
    assert report["status"] == "blocked"
    assert report["ignored_checks"]
    assert report["fabrication_approved"] is False
