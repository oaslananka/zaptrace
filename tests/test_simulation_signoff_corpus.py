"""Four-family simulation sign-off corpus and artifact contracts."""

from __future__ import annotations

from pathlib import Path

from zaptrace.benchmark.simulation_signoff_corpus import (
    DEFAULT_SIMULATION_SIGNOFF_MANIFEST,
    load_simulation_signoff_manifest,
    run_simulation_signoff_corpus,
)


def test_manifest_declares_domain_complete_four_family_corpus() -> None:
    manifest = load_simulation_signoff_manifest(DEFAULT_SIMULATION_SIGNOFF_MANIFEST)

    assert [item.family_id for item in manifest.families] == [
        "switching_regulator_module",
        "usb_c_power_sink",
        "lipo_charger_node",
        "esp32_usb_sensor",
    ]
    assert sum(item.require_live_simulation for item in manifest.families) == 1
    assert {domain for item in manifest.families for domain in item.required_domains} >= {
        "transient",
        "ac",
        "power-integrity",
        "thermal",
        "current-density",
        "signal-integrity",
    }


def test_corpus_writes_state_bound_family_reports_and_models(tmp_path: Path) -> None:
    report = run_simulation_signoff_corpus(
        tmp_path / "artifacts",
        trusted_output_root=tmp_path,
        require_live_simulation=False,
        evidence_identity={"source_commit": "c" * 40, "lock_sha256": "d" * 64},
    )

    assert report.passed is True
    assert report.corpus_version == "2026.07"
    assert report.family_count == 4
    assert report.evidence_family_count == 4
    assert report.report_sha256 == report.compute_sha256()
    assert len(list((tmp_path / "artifacts").glob("*/simulation-signoff.json"))) == 4
    assert len(list((tmp_path / "artifacts").glob("*/input-model.json"))) == 3
    for family in report.families:
        assert family.design_state_hash
        assert family.check_count >= 1
        assert family.report_sha256 == family.compute_sha256()
        assert all(check.status.value != "pass" or check.engine_status == "pass" for check in family.checks)


def test_require_live_simulation_fails_when_no_live_pass_is_present(tmp_path: Path, monkeypatch) -> None:
    import zaptrace.analysis.spice_sim as spice_sim

    real_which = spice_sim.shutil.which
    monkeypatch.setattr(
        spice_sim.shutil,
        "which",
        lambda name: None if name == "ngspice" else real_which(name),
    )
    assert spice_sim.ngspice_available() is False

    report = run_simulation_signoff_corpus(
        tmp_path / "artifacts",
        trusted_output_root=tmp_path,
        require_live_simulation=True,
    )

    assert report.passed is False
    assert report.live_simulation_pass_count == 0
    assert "at least one live ngspice gate must pass" in report.acceptance_failures


def test_golden_pass_and_fail_fixtures_are_schema_valid() -> None:
    from zaptrace.analysis.simulation_signoff import SimulationFamilyReport

    root = Path(__file__).resolve().parent / "fixtures/simulation-signoff"
    passed = SimulationFamilyReport.model_validate_json((root / "golden-pass.json").read_text(encoding="utf-8"))
    failed = SimulationFamilyReport.model_validate_json((root / "golden-fail.json").read_text(encoding="utf-8"))

    assert passed.blocked is False
    assert passed.human_review_required is False
    assert passed.live_simulation_pass_count == 1
    assert passed.checks[0].status.value == "pass"
    assert failed.blocked is True
    assert failed.repair_hints
    assert passed.report_sha256 == passed.compute_sha256()
    assert failed.report_sha256 == failed.compute_sha256()


def test_retained_spice_models_are_the_exact_gate_inputs(tmp_path: Path) -> None:
    from zaptrace.analysis.ac_stability_gate import build_ac_stability_netlist
    from zaptrace.analysis.usbc_inrush_gate import build_usbc_inrush_netlist

    run_simulation_signoff_corpus(
        tmp_path / "artifacts",
        trusted_output_root=tmp_path,
        require_live_simulation=False,
    )
    usb = (tmp_path / "artifacts/usb_c_power_sink/input-model.spice").read_text(encoding="utf-8")
    lipo = (tmp_path / "artifacts/lipo_charger_node/input-model.spice").read_text(encoding="utf-8")
    assert usb == build_usbc_inrush_netlist() + "\n"
    assert lipo == build_ac_stability_netlist() + "\n"
