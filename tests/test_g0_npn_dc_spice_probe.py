"""Source-bound illustrative ngspice DC cases never imply external load approval."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import g0_npn_dc_spice_probe as probe

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "benchmarks/external/nitu-npn-transistor-switch/source"
EVIDENCE = ROOT / "benchmarks/g0-ai-engineering-tasks/npn-switch-assumed-load-ngspice.json"


def test_assumed_dc_models_are_explicit_and_not_physical_acceptance() -> None:
    record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert record["schema_version"] == "g0-npn-illustrative-ngspice-dc-v1"
    assert record["source_reference_id"] == "nitu-npn-transistor-switch"
    assert record["bjt_model_status"] == "ASSUMED_UNQUALIFIED"
    assert record["red_led_model_status"] == "ASSUMED_UNQUALIFIED"
    assert record["external_load_status"] == "UNSPECIFIED_IN_ORIGINAL_SOURCE"
    assert record["verified_real_load_limit_ma"] is None
    assert record["qualified_human_approval"] == "NOT_RUN"
    assert record["physical_measurement"] == "NOT_RUN"
    assert record["transient_flyback_simulation"] == "NOT_RUN"
    assert record["manufacturing_approved"] is False
    assert record["g0_verified"] is False
    assert record["independent_ai_task_accepted"] is False
    assert record["simulated_load_ohms"] == [None, 1000, 220, 100, 47, 22, 10]
    assert record["assumed_transistor_beta_f"] == [50, 150]
    assert record["r1_ohms"] == [390, 820]
    assert len(record["cases"]) == 34
    assert {r["switch_state"] for r in record["cases"]} == {"CLOSED", "OPEN"}
    assert all(r["engine"] == "ngspice" for r in record["cases"])
    assert all(r["converged"] for r in record["cases"])
    assert all(r["qualified_load_status"] == "NOT_RUN" for r in record["cases"])
    assert all(r["v_collector_v"] >= 0 for r in record["cases"])
    assert all(r["i_collector_ma"] > 0 for r in record["cases"] if r["switch_state"] == "CLOSED")
    assert all(abs(r["i_collector_ma"]) < 0.01 for r in record["cases"] if r["switch_state"] == "OPEN")
    source_sha = record["original_source_sha256"]
    assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in SOURCE.glob("*.kicad_*")} == source_sha


def test_real_simulation_exposes_assumed_model_sensitivity_and_load_limit() -> None:
    if not probe.shared_ngspice_available():
        pytest.skip("ngspice shared library unavailable: no synthetic PASS substitution")
    binary = shutil.which("kicad-cli")
    if not binary:
        pytest.skip("Real KiCad CLI unavailable: source graph cannot be checked")
    version = subprocess.run([binary, "version"], capture_output=True, text=True, timeout=15)
    if version.returncode or not version.stdout.startswith("10."):
        pytest.skip("Only real KiCad 10 source validation qualifies this SPICE run")
    record = probe.simulate_source_bound_npn(SOURCE)
    cases = record["cases"]
    assert len(cases) == 34
    assert record["engine_version"].startswith("42") or record["engine_version"].split(".")[0].isdigit()
    scenario = {
        (r["r1_ohms"], r["assumed_beta_f"], r["external_load_ohms"]): r for r in cases if r["switch_state"] == "CLOSED"
    }
    open_cases = [r for r in cases if r["switch_state"] == "OPEN"]
    assert len(open_cases) == 6
    assert all(r["r1_ohms"] == 820 for r in open_cases)
    assert all(r["v_collector_v"] > 4 for r in open_cases)
    assert all(abs(r["i_led_ma"]) < 0.01 for r in open_cases)
    assert scenario[(820, 50, None)]["v_collector_v"] < 0.1
    assert scenario[(820, 50, 220)]["v_collector_v"] < 0.2
    assert scenario[(820, 50, 22)]["v_collector_v"] > 1.0
    assert scenario[(820, 150, 22)]["v_collector_v"] > 0.3
    assert scenario[(820, 50, 10)]["v_collector_v"] > 2.0
    assert scenario[(820, 150, 10)]["v_collector_v"] > 1.0
    assert scenario[(390, 50, 22)]["v_collector_v"] < scenario[(820, 50, 22)]["v_collector_v"]
    for beta in record["assumed_transistor_beta_f"]:
        baseline = scenario[(390, beta, None)]["i_r1_feed_ma"]
        candidate = scenario[(820, beta, None)]["i_r1_feed_ma"]
        assert candidate < baseline
        assert 100 * (1 - candidate / baseline) > 45
    assert all(r["qualified_load_status"] == "NOT_RUN" for r in cases)
    stored = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert record["original_source_sha256"] == stored["original_source_sha256"]
    assert record["source_native_kicad_version"] == stored["source_native_kicad_version"]
    pinned_cases = {
        (x["switch_state"], x["r1_ohms"], x["assumed_beta_f"], x["external_load_ohms"]): x for x in stored["cases"]
    }
    for result in cases:
        key = (result["switch_state"], result["r1_ohms"], result["assumed_beta_f"], result["external_load_ohms"])
        pinned = pinned_cases[key]
        assert result["spice_deck_sha256"] == pinned["spice_deck_sha256"]
        if record["engine_version"] == stored["engine_version"]:
            for measurement in (
                "v_collector_v",
                "v_base_v",
                "i_r1_feed_ma",
                "i_led_ma",
                "i_collector_ma",
                "transistor_dissipation_mw",
            ):
                assert result[measurement] == pytest.approx(pinned[measurement], abs=0.02)


def test_stale_or_edited_original_source_fails_closed(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    for original in SOURCE.glob("*.kicad_*"):
        (tmp_path / original.name).write_bytes(original.read_bytes())
    schematic = next(tmp_path.glob("*.kicad_sch"))
    schematic.write_text(
        schematic.read_text(encoding="utf-8").replace('(property "Value" "390"', '(property "Value" "470"', 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="source|R1|hash|modified"):
        probe.verify_native_source(tmp_path)


def test_archived_onsemi_saturation_conditions_are_not_silently_approved() -> None:
    record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    review = record["datasheet_condition_review"]
    assert review["document"] == "PN2222/D, November 2000, Rev. 0"
    assert review["component"] == "PN2222A"
    assert review["kicad_original_datasheet_url"] == "https://www.onsemi.com/pub/Collateral/PN2222-D.PDF"
    assert review["archival_mirror_url"].startswith("https://media.digikey.com/")
    assert review["reference_status"] == "HISTORIC_ARCHIVAL_DOCUMENT_NOT_LIVE_PART_QUALIFICATION"
    assert review["saturation_test_points"] == [
        {"i_base_ma": 15, "i_collector_ma": 150, "vce_sat_max_v": 0.3},
        {"i_base_ma": 50, "i_collector_ma": 500, "vce_sat_max_v": 1.0},
    ]
    assert review["manufacturer_specific_bjt_spice_model"] == "NOT_RETRIEVED_OR_VERIFIED"
    assert review["real_load_approved"] is False
    assert review["manufacturer_saturation_guarantee_established"] is False
    assert review["exact_orderable_sku_and_board_ambient"] == "UNKNOWN"
    points = {x["r1_ohms"]: x for x in review["conditional_base_drive_review"]}
    assert set(points) == {390, 820}
    assert points[390]["idealized_upper_bound_base_feed_ma"] == pytest.approx(12.818869, abs=0.000001)
    assert points[820]["idealized_upper_bound_base_feed_ma"] == pytest.approx(6.097189, abs=0.000001)
    assert all(x["status"] == "CONDITIONS_NOT_REPRODUCED" for x in points.values())
    assert all(not x["can_supply_15ma_test_point"] for x in points.values())
    assert all(not x["can_supply_50ma_test_point"] for x in points.values())
    assert all(not x["published_150ma_saturation_guarantee_applicable"] for x in points.values())
    assert review["qualified_human_approval"] == "NOT_RUN"


def test_historic_thermal_rating_screen_remains_warning_only() -> None:
    record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    limits = record["datasheet_condition_review"]["thermal_reference"]
    assert limits["max_p_dis_25c_mw"] == 625
    assert limits["derating_above_25c_mw_per_c"] == 5
    assert limits["max_junction_to_ambient_c_per_w"] == 200
    assert limits["reference_package"] == "TO-92"
    assert limits["illustrative_50c_rating_mw"] == 500
    assert limits["comparison_status"] == "NOT_A_TEMPERATURE_DEPENDENT_SPICE_OR_THERMAL_MODEL"
    warn = limits["warning_cases"]
    assert len(warn) == 3
    assert {(r["r1_ohms"], r["assumed_beta_f"], r["external_load_ohms"]) for r in warn} == {
        (390, 50, 10),
        (820, 50, 10),
        (820, 150, 10),
    }
    assert all(r["screening_margin_mw_if_27c_solution_persisted"] < 0 for r in warn)
    assert all(r["status"] == "INVESTIGATE_NOT_A_THERMAL_PREDICTION" for r in warn)
    # Safety contract: even an unflagged condition is NOT evidence of approved hardware.
    unflagged_22 = [
        r
        for r in record["cases"]
        if r["r1_ohms"] == 820
        and r["assumed_beta_f"] == 50
        and r["external_load_ohms"] == 22
        and r["switch_state"] == "CLOSED"
    ]
    assert len(unflagged_22) == 1
    assert unflagged_22[0]["v_collector_v"] > 1.0
    assert unflagged_22[0]["qualified_load_status"] == "NOT_RUN"
    assert not record["datasheet_condition_review"]["real_load_approved"]
    assert not record["g0_verified"]


def test_q1_supplier_pinout_and_actual_pcb_nets_not_assembly_signoff() -> None:
    record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    q1 = record["source_q1_pinout"]
    assert q1["status"] == "SOURCE_NUMBERED_PAD_AND_SYMBOL_PINS_CONSISTENT"
    assert q1["footprint"] == "Package_TO_SOT_THT:TO-92_Inline"
    assert q1["reference"] == "Q1"
    assert q1["source_value"] == "PN2222A"
    assert q1["published_PN2222A_TO92_EBC_mapping"] == {"1": "E", "2": "B", "3": "C"}
    assert q1["source_symbol_pin_number_to_function"] == {"1": "E", "2": "B", "3": "C"}
    assert q1["source_pcb_pad_net_names"] == {"1": "GND", "2": "Net-(Q1-B)", "3": "Net-(D1-K)"}
    assert q1["physical_orientation_verified"] is False
    assert q1["exact_supplier_sku_selected"] is False
    assert q1["manufacturer_spice_model_verified"] is False
    assert q1["source_j2_external_load_identified"] is False
    assert q1["manufacturing_or_human_approval"] == "NOT_RUN"


def test_verified_supplier_pdf_identity_does_not_select_part_or_spice() -> None:
    record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    supplier = record["supplier_pdf_byte_identity"]
    assert supplier["status"] == "EXACT_PINNED_SUPPLIER_PDF_BYTES"
    assert supplier["source_id"] == "onsemi-fairchild-pn2222a-2014"
    assert supplier["sha256"] == "f1eda8482f5f227f5c80c8ba750ae28ff2159139e268158bd656bc8f0db0a6d2"
    assert supplier["part_qualification"] is False
    assert supplier["model_qualification"] is False
    docs = record["reviewed_PN2222A_document_provenance"]
    assert docs["onsemi-fairchild-pn2222a-2014"]["orderable_candidates"] == [
        "PN2222ABU",
        "PN2222ATA",
        "PN2222ATF",
        "PN2222ATFR",
    ]
    assert docs["onsemi-fairchild-pn2222a-2014"]["pinout"] == {"1": "E", "2": "B", "3": "C"}
    assert docs["onsemi-pn2222-2000-archive"]["pinout"] == {"1": "E", "2": "B", "3": "C"}
    assert docs["onsemi-pn2222-2000-archive"]["sha256"] == (
        "9e61ab90e7ff3e204d6f09c09f00a7a6a0967f11070d6a7f89d7dd5fee16482e"
    )
    readiness = record["manufacturer_component_readiness"]
    assert readiness["source_pinout_consistent_with_reviewed_documents"] is True
    assert readiness["exact_orderable_part"] is None
    assert readiness["exact_orderable_part_status"] == "NOT_SELECTED_OR_QUALIFIED"
    assert readiness["supplier_model"] is None
    assert readiness["supplier_model_status"] == "NOT_RETRIEVED_OR_VERIFIED"
    assert readiness["external_j2_load"] is None
    assert readiness["external_j2_load_status"] == "NOT_SPECIFIED"
    assert readiness["physical_assembly_review"] == "NOT_RUN"
    assert readiness["functional_hardware_review"] == "NOT_RUN"
    assert readiness["qualified_load_status"] == "NOT_RUN"


def test_supplier_document_identity_rejects_missing_or_wrong_pdf(tmp_path: Path) -> None:
    no_supplier = probe.verify_supplier_pdf(None)
    assert no_supplier["status"] == "NOT_SUPPLIED_THIS_RUN"
    assert not no_supplier["part_qualification"]
    with pytest.raises(ValueError, match="not a recognized complete PDF"):
        probe.verify_supplier_pdf(b"")
    with pytest.raises(ValueError, match="unexpectedly large"):
        probe.verify_supplier_pdf(b"%PDF-1.4" + b" " * 5_000_001)
    wrong_document = tmp_path / "other-mosfet.pdf"
    wrong_document.write_bytes(b"%PDF-1.4\n" + b"This is NOT a PN2222A datasheet. " * 400)
    with pytest.raises(ValueError, match="do not trust a URL"):
        probe.verify_supplier_pdf(wrong_document.read_bytes())


def test_q1_symbol_pin_drift_fails_closed_on_original_source_copy(tmp_path: Path) -> None:
    original_board = next(SOURCE.glob("*.kicad_pcb"))
    original_schematic = original_board.with_suffix(".kicad_sch")
    board = tmp_path / original_board.name
    schematic = tmp_path / original_schematic.name
    board.write_bytes(original_board.read_bytes())
    schematic.write_bytes(original_schematic.read_bytes())
    assert probe.verify_q1_source_pinout(schematic, board)["source_pcb_pad_net_names"]["3"] == "Net-(D1-K)"
    data = board.read_text(encoding="utf-8")
    old = '(property "Sim.Pins" "1=E 2=B 3=C"'
    assert old in data
    board.write_text(data.replace(old, '(property "Sim.Pins" "1=C 2=B 3=E"', 1), encoding="utf-8")
    with pytest.raises(ValueError, match="model/pin assignment"):
        probe.verify_q1_source_pinout(schematic, board)


def test_supplier_pdf_cli_reports_actionable_error_without_emitting_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def reject_supplier(_source: Path, *, supplier_pdf_bytes: bytes | None = None) -> dict:
        raise ValueError("Supplier document not recognized; please use the reviewed PDF revision")

    outfile = tmp_path / "untrusted.json"
    monkeypatch.setattr(probe, "simulate_source_bound_npn", reject_supplier)
    monkeypatch.setattr(
        sys,
        "argv",
        ["g0_npn_dc_spice_probe.py", "--output-json", str(outfile)],
    )
    with pytest.raises(SystemExit) as raised:
        probe.main()
    assert raised.value.code == 2
    assert "Supplier document not recognized" in capsys.readouterr().err
    assert not outfile.exists()
