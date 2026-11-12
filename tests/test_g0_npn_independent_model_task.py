"""Independent-model proposal is not electrical or physical approval."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from defusedxml import ElementTree

from zaptrace.cli.main import cli

ROOT = Path(__file__).parents[1]
SPEC = ROOT / "benchmarks/g0-ai-engineering-tasks/npn-switch-base-drive-independent-model.json"
SOURCE = ROOT / "benchmarks/external/nitu-npn-transistor-switch/source"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _task() -> dict:
    return json.loads(SPEC.read_text(encoding="utf-8"))


def _files() -> tuple[Path, Path, Path]:
    board = next(SOURCE.glob("*.kicad_pcb"))
    return board, board.with_suffix(".kicad_sch"), board.with_suffix(".kicad_pro")


def test_independent_model_fixed_prompt_and_nominal_numbers_are_evidence_not_approval() -> None:
    task = _task()
    assert task["task_id"] == "g0-004-npn-switch-base-drive-reduction"
    assert task["reference_id"] == "nitu-npn-transistor-switch"
    assert task["license"] == "MIT"
    manifest = json.loads((ROOT / "benchmarks/human-reference-corpus/manifest.json").read_text())
    ref = next(x for x in manifest["references"] if x["reference_id"] == task["reference_id"])
    assert task["source_artifact_set_sha256"] == ref["artifact_set_sha256"]
    assert task["source_upstream_commit"] == ref["upstream_commit"]

    prompt = (ROOT / task["fixed_prompt_path"]).read_bytes()
    assert hashlib.sha256(prompt).hexdigest() == task["fixed_prompt_sha256"]
    assert b"820" in prompt and b"390" in prompt  # value 820 is in the option set, not preselected
    assert b" or NO_CHANGE" in prompt
    run = task["independent_model_run"]
    assert run["provider"] == "nvidia"
    assert run["model"] == "nvidia/nemotron-3-ultra-550b-a55b"
    assert run["tool_calls"] == []
    assert run["independent_proposal_observed"] is True
    assert run["token_usage"] == "unavailable"
    assert run["cost_usd"] is None
    assert run["wall_seconds"] > 0
    response = run["model_response"]
    assert (response["action"], response["reference"], response["from_value"], response["to_value"]) == (
        "EDIT",
        "R1",
        "390",
        "820",
    )
    assert response["functional_acceptance"] == response["human_signoff"] == "NOT_RUN"
    assert any("J2" in x or "load" in x.lower() for x in response["unverified_risks"])

    c = task["nominal_analysis"]
    feed_before = 1000 * (c["vcc_assumed_volts"] - c["vbe_assumed_volts"]) / c["r1_before_ohms"]
    feed_after = 1000 * (c["vcc_assumed_volts"] - c["vbe_assumed_volts"]) / c["r1_after_ohms"]
    pull_down = 1000 * c["vbe_assumed_volts"] / c["r2_pulldown_ohms"]
    net_after = feed_after - pull_down
    led_max = (
        1000
        * (c["vcc_assumed_volts"] - c["red_led_vf_assumed_range_volts"][0] - c["vce_sat_assumed_volts"])
        / c["r3_led_ohms"]
    )
    reduction = 100 * (1 - feed_after / feed_before)
    tentative_budget = c["forced_beta_heuristic"] * net_after
    assert reduction >= 50
    assert tentative_budget > led_max
    for key, exact in (
        ("nominal_base_feed_current_before_ma", feed_before),
        ("nominal_base_feed_current_after_ma", feed_after),
        ("nominal_base_current_after_pulldown_ma", net_after),
        ("nominal_reduction_percent", reduction),
        ("led_only_current_max_ma", led_max),
        ("tentative_forced_beta10_collector_budget_ma", tentative_budget),
    ):
        assert response[key] == pytest.approx(exact, abs=0.11)
    assert c["external_j2_load_current_ma"] is None
    assert c["external_load_saturation_qualified"] is False

    outcome = task["outcome"]
    assert outcome["independent_model_proposal_observed"] is True
    assert outcome["proposal_numeric_constraints_pass"] is True
    assert outcome["independently_scored_g0_success"] is False
    assert outcome["g0_verified"] is False
    assert outcome["attempt_status"] == "BLOCKED"
    assert outcome["functional_simulation"] == outcome["functional_measurement"] == "NOT_RUN"
    assert outcome["qualified_human_review"] == "NOT_RUN"
    assert outcome["manufacturing_approved"] is False


@pytest.fixture
def native_kicad_10() -> str:
    binary = shutil.which("kicad-cli")
    if binary is None:
        pytest.skip("Real native KiCad 10 required; never fake a model-engineering acceptance")
    probe = subprocess.run([binary, "version"], capture_output=True, text=True, timeout=15)
    if probe.returncode or not probe.stdout.startswith("10."):
        pytest.skip("Real native KiCad 10 required")
    return binary


def _native_graph(cli_binary: str, schematic: Path, project: Path, scratch: Path) -> dict[str, tuple]:
    scratch.mkdir()
    shutil.copyfile(schematic, scratch / schematic.name)
    shutil.copyfile(project, scratch / project.name)
    netlist = scratch / "native.xml"
    run = subprocess.run(
        [
            cli_binary,
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadxml",
            "--output",
            str(netlist),
            str(scratch / schematic.name),
        ],
        capture_output=True,
        text=True,
        timeout=70,
    )
    assert run.returncode == 0, run.stderr
    root = ElementTree.parse(netlist).getroot()
    assert root is not None
    return {
        (x.get("name") or ""): tuple(sorted((n.get("ref"), n.get("pin")) for n in x.findall("node")))
        for x in root.findall("./nets/net")
    }


def test_real_native_npn_model_eco_and_parity_repair_preserve_sources(tmp_path: Path, native_kicad_10: str) -> None:
    task = _task()
    proposal = task["independent_model_run"]["model_response"]
    board, schematic, project = _files()
    original_hash = {p.name: _sha(p) for p in (board, schematic, project)}
    original_record = task["native_source_review"]["direct_source_preserving_resistor_eco"]
    assert _sha(board) == original_record["original_pcb_sha256"]
    assert _sha(schematic) == original_record["original_schematic_sha256"]
    assert _sha(project) == original_record["original_project_sha256"]
    runner = CliRunner()
    direct_path = tmp_path / "independent-model-eco"
    direct = runner.invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            proposal["reference"],
            "--from-value",
            proposal["from_value"],
            "--to-value",
            proposal["to_value"],
            "--output-dir",
            str(direct_path),
            "--json",
        ],
    )
    assert direct.exit_code == 0, direct.output
    report = json.loads(direct.output)
    assert report["native_kicad_version"] == "10.0.8"
    assert report["canonical_nets_preserved"] is True
    assert report["g0_verified"] is False
    assert report["native_candidate_clean"] is False
    assert report["attempt_status"] == "human-review-required-existing-native-findings"
    assert report["original_pcb_sha256"] == original_record["original_pcb_sha256"]
    assert report["candidate_pcb_sha256"] == original_record["candidate_pcb_sha256"]
    assert report["candidate_schematic_sha256"] == original_record["candidate_schematic_sha256"]
    er = report["native_review"]["electrical_review"]
    nr = report["native_review"]
    assert er["baseline_schematic_parity_issues"] == er["candidate_schematic_parity_issues"] == 8
    assert er["baseline_erc_violations"] == er["candidate_erc_violations"] == 0
    assert nr["baseline_violations"] == nr["candidate_violations"] == 0
    assert nr["baseline_unconnected_items"] == nr["candidate_unconnected_items"] == 0
    assert json.loads((direct_path / "eco-review.json").read_text()) == report

    repaired = tmp_path / "parity-repair"
    parity_run = runner.invoke(
        cli,
        [
            "kicad",
            "parity-repair-preview",
            str(board),
            "--reference-map",
            "+5V=TP1",
            "--reference-map",
            "GND=TP2",
            "--reference-map",
            "BASE=TP3",
            "--reference-map",
            "COLL=TP4",
            "--output-dir",
            str(repaired),
            "--json",
        ],
    )
    assert parity_run.exit_code == 0, parity_run.output
    repaired_report = json.loads(parity_run.output)
    chain = task["native_source_review"]["sequential_testpoint_parity_repair_then_resistor_eco"]
    assert repaired_report["candidate_pcb_sha256"] == chain["parity"]["candidate_pcb_sha256"]
    pe = repaired_report["native_review"]["electrical_review"]
    assert pe["baseline_schematic_parity_issues"] == 8
    assert pe["candidate_schematic_parity_issues"] == 0
    assert repaired_report["native_candidate_clean"] is True
    final_path = tmp_path / "parity-repaired-npn-eco"
    combined = runner.invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(repaired / board.name),
            "--reference",
            proposal["reference"],
            "--from-value",
            proposal["from_value"],
            "--to-value",
            proposal["to_value"],
            "--output-dir",
            str(final_path),
            "--json",
        ],
    )
    assert combined.exit_code == 0, combined.output
    final_report = json.loads(combined.output)
    assert final_report["candidate_pcb_sha256"] == chain["eco"]["candidate_pcb_sha256"]
    assert final_report["candidate_schematic_sha256"] == chain["eco"]["candidate_schematic_sha256"]
    assert final_report["native_candidate_clean"] is True
    assert final_report["g0_verified"] is False
    assert final_report["manufacturing_approved"] is False
    fe = final_report["native_review"]["electrical_review"]
    assert fe["baseline_schematic_parity_issues"] == fe["candidate_schematic_parity_issues"] == 0
    assert fe["baseline_erc_violations"] == fe["candidate_erc_violations"] == 0
    assert final_report["native_review"]["baseline_violations"] == 0
    assert final_report["native_review"]["candidate_violations"] == 0
    assert _native_graph(native_kicad_10, schematic, project, tmp_path / "source-netlist") == _native_graph(
        native_kicad_10, final_path / schematic.name, final_path / project.name, tmp_path / "final-netlist"
    )
    assert all(_sha(p) == original_hash[p.name] for p in (board, schematic, project))
