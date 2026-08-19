"""Fail-closed edge cases for simulation sign-off evidence and corpus output."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.ci_simulation_signoff import main
from zaptrace.analysis.simulation_signoff import (
    SimulationCheckEvidence,
    SimulationDomain,
    SimulationEvidenceMethod,
    SimulationEvidenceStatus,
    SimulationFamilyReport,
    SimulationModelEvidence,
    SimulationRiskClass,
    normalize_simulation_gate,
    resolve_simulation_output_path,
    simulation_family_report_json,
)
from zaptrace.benchmark.simulation_signoff_corpus import (
    SimulationSignoffFamilySpec,
    SimulationSignoffManifest,
    _prepare_output_dir,
    _status,
    load_simulation_signoff_manifest,
    run_simulation_signoff_corpus,
)
from zaptrace.proof import ProofManifest, attach_simulation_signoff_evidence


def _report() -> SimulationFamilyReport:
    check = normalize_simulation_gate(
        check_id="analytical",
        domain=SimulationDomain.THERMAL,
        engine_status="pass",
        method=SimulationEvidenceMethod.ANALYTICAL,
        summary="analytical margin recorded",
        models=[],
    )
    return SimulationFamilyReport.build(
        family_id="fixture",
        title="Fixture",
        design_state_hash="a" * 64,
        models=[],
        checks=[check],
        assumptions=[],
    )


def _spec(family_id: str, *, live: bool = False, domains: list[str] | None = None) -> SimulationSignoffFamilySpec:
    return SimulationSignoffFamilySpec(
        family_id=family_id,
        simulation_gate="gate",
        require_live_simulation=live,
        required_domains=["thermal"] if domains is None else domains,
    )


def test_check_rejects_pass_when_engine_failed() -> None:
    with pytest.raises(ValidationError, match="engine did not pass"):
        SimulationCheckEvidence(
            check_id="bad-pass",
            domain=SimulationDomain.THERMAL,
            method=SimulationEvidenceMethod.ANALYTICAL,
            engine_status="fail",
            status=SimulationEvidenceStatus.PASS,
            risk_class=SimulationRiskClass.LOW,
            blocking=False,
            human_review_required=False,
            summary="invalid",
        )


def test_check_rejects_false_live_simulation_claim() -> None:
    with pytest.raises(ValidationError, match="requires an identified ngspice engine pass"):
        SimulationCheckEvidence(
            check_id="bad-live",
            domain=SimulationDomain.AC,
            method=SimulationEvidenceMethod.ANALYTICAL,
            engine_status="pass",
            status=SimulationEvidenceStatus.HUMAN_REVIEW_REQUIRED,
            risk_class=SimulationRiskClass.MODERATE,
            blocking=False,
            human_review_required=True,
            live_simulation_passed=True,
            summary="invalid",
        )


def test_unknown_engine_status_fails_closed_to_review() -> None:
    evidence = normalize_simulation_gate(
        check_id="unknown",
        domain=SimulationDomain.THERMAL,
        engine_status="indeterminate",
        method=SimulationEvidenceMethod.HEURISTIC,
        summary="producer returned an unknown status",
        models=[],
    )
    assert evidence.status == SimulationEvidenceStatus.HUMAN_REVIEW_REQUIRED
    assert evidence.risk_class == SimulationRiskClass.HIGH


def test_output_resolver_supports_relative_path_and_rejects_non_json(tmp_path: Path) -> None:
    assert resolve_simulation_output_path("report.json", trusted_root=tmp_path) == tmp_path / "report.json"
    with pytest.raises(ValueError, match="must be JSON"):
        resolve_simulation_output_path("report.txt", trusted_root=tmp_path, require_json=True)


def test_report_json_rejects_tampered_report() -> None:
    report = _report()
    report.assumptions.append("tampered")
    with pytest.raises(ValueError, match="hash-valid"):
        simulation_family_report_json(report)


@pytest.mark.parametrize("domains", [[], ["thermal", "thermal"]])
def test_family_spec_rejects_missing_or_duplicate_domains(domains: list[str]) -> None:
    with pytest.raises(ValidationError, match="non-empty and unique"):
        _spec("family", domains=domains)


def test_manifest_rejects_too_few_duplicate_or_no_live_families() -> None:
    too_few = [_spec("a", live=True)]
    duplicate = [_spec("a", live=True), _spec("a"), _spec("b")]
    no_live = [_spec("a"), _spec("b"), _spec("c")]

    with pytest.raises(ValidationError, match="at least three"):
        SimulationSignoffManifest(corpus_version="1", families=too_few, non_claims=[])
    with pytest.raises(ValidationError, match="must be unique"):
        SimulationSignoffManifest(corpus_version="1", families=duplicate, non_claims=[])
    with pytest.raises(ValidationError, match="must require live"):
        SimulationSignoffManifest(corpus_version="1", families=no_live, non_claims=[])


def test_manifest_loader_rejects_path_outside_package(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes trusted package root"):
        load_simulation_signoff_manifest(path)


def test_output_directory_rejects_root_file_and_unowned_content(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        _prepare_output_dir(tmp_path, trusted_root=tmp_path)
    file_path = tmp_path / "file"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        _prepare_output_dir(file_path, trusted_root=tmp_path)
    unowned = tmp_path / "unowned"
    unowned.mkdir()
    (unowned / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="not corpus-owned"):
        _prepare_output_dir(unowned, trusted_root=tmp_path)
    assert (unowned / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_marker_owned_output_is_cleaned_without_following_symlinks(tmp_path: Path) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / ".zaptrace-simulation-signoff-output").write_text("marker\n", encoding="utf-8")
    (owned / "old.txt").write_text("old", encoding="utf-8")
    nested = owned / "nested"
    nested.mkdir()
    (nested / "old.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("safe", encoding="utf-8")
    (owned / "outside-link").symlink_to(outside)

    result = _prepare_output_dir(owned, trusted_root=tmp_path)

    assert result == owned
    assert sorted(item.name for item in owned.iterdir()) == [".zaptrace-simulation-signoff-output"]
    assert outside.read_text(encoding="utf-8") == "safe"


def test_status_helper_preserves_pass_review_and_failure() -> None:
    assert _status(False, False) == "pass"
    assert _status(False, True) == "human-review-required"
    assert _status(True, False) == "fail"


def test_corpus_records_missing_runner_and_incomplete_evidence(tmp_path: Path, monkeypatch) -> None:
    import zaptrace.benchmark.simulation_signoff_corpus as corpus

    manifest = SimulationSignoffManifest(
        corpus_version="1",
        families=[
            _spec("switching_regulator_module", live=True, domains=["transient"]),
            _spec("usb_c_power_sink", domains=["missing-domain"]),
            _spec("lipo_charger_node", domains=["ac"]),
        ],
        non_claims=[],
    )
    runners = dict(corpus._FAMILY_RUNNERS)
    runners.pop("switching_regulator_module")
    monkeypatch.setattr(corpus, "load_simulation_signoff_manifest", lambda _path: manifest)
    monkeypatch.setattr(corpus, "_FAMILY_RUNNERS", runners)

    report = run_simulation_signoff_corpus(
        tmp_path / "artifacts",
        trusted_output_root=tmp_path,
        require_live_simulation=False,
    )

    assert report.passed is False
    assert any("no simulation sign-off runner" in item for item in report.acceptance_failures)
    assert any("missing required domain" in item for item in report.acceptance_failures)
    assert "not every declared family produced evidence" in report.acceptance_failures


def test_proof_attachment_ignores_empty_or_missing_model_paths(tmp_path: Path) -> None:
    report = _report()
    report.models = [
        SimulationModelEvidence(
            model_id="missing",
            source="fixture:test",
            version="1",
            model_sha256="b" * 64,
            method=SimulationEvidenceMethod.ANALYTICAL,
            binding="family-fixture",
            degraded=True,
            confidence=0.5,
            artifact_path="",
            netlist_path="missing.spice",
        )
    ]
    report.report_sha256 = report.compute_sha256()
    report_path = tmp_path / "simulation-signoff.json"
    report_path.write_text("{}\n", encoding="utf-8")
    manifest = ProofManifest(name="proof", design_path="missing.yaml")

    attach_simulation_signoff_evidence(manifest, report, report_path=report_path)

    assert set(manifest.references) == {"simulation-signoff.json"}


def test_cli_rejects_wrong_markdown_extension(tmp_path: Path) -> None:
    code = main(
        [
            "--trusted-output-root",
            str(tmp_path),
            "--artifact-dir",
            str(tmp_path / "artifacts"),
            "--output",
            str(tmp_path / "report.json"),
            "--markdown",
            str(tmp_path / "report.txt"),
        ]
    )
    assert code == 2


def test_family_report_rejects_duplicate_model_and_check_ids() -> None:
    report = _report()
    payload = report.model_dump(mode="json")
    payload["models"] = [
        {
            "model_id": "duplicate",
            "source": "fixture:a",
            "version": "1",
            "model_sha256": "1" * 64,
            "method": "analytical",
            "binding": "fixture",
            "degraded": True,
            "confidence": 0.5,
        },
        {
            "model_id": "duplicate",
            "source": "fixture:b",
            "version": "1",
            "model_sha256": "2" * 64,
            "method": "analytical",
            "binding": "fixture",
            "degraded": True,
            "confidence": 0.5,
        },
    ]
    payload["report_sha256"] = ""
    with pytest.raises(ValidationError, match="model ids must be unique"):
        SimulationFamilyReport.model_validate(payload)

    payload = report.model_dump(mode="json")
    payload["checks"].append(dict(payload["checks"][0]))
    payload["check_count"] = 2
    payload["human_review_count"] = 2
    payload["report_sha256"] = ""
    with pytest.raises(ValidationError, match="check ids must be unique"):
        SimulationFamilyReport.model_validate(payload)


def test_family_report_rejects_unknown_model_reference() -> None:
    report = _report()
    payload = report.model_dump(mode="json")
    payload["checks"][0]["model_ids"] = ["missing-model"]
    payload["report_sha256"] = ""
    with pytest.raises(ValidationError, match="unknown model ids"):
        SimulationFamilyReport.model_validate(payload)


def test_family_report_rejects_inconsistent_counts_flags_hints_and_hash() -> None:
    report = _report()
    for field_name, invalid_value, message in (
        ("check_count", 99, "check_count"),
        ("blocked", True, "blocked"),
        ("human_review_required", False, "human_review_required"),
        ("repair_hints", ["invented"], "repair_hints"),
    ):
        payload = report.model_dump(mode="json")
        payload[field_name] = invalid_value
        payload["report_sha256"] = ""
        with pytest.raises(ValidationError, match=message):
            SimulationFamilyReport.model_validate(payload)

    payload = report.model_dump(mode="json")
    payload["report_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="hash does not match"):
        SimulationFamilyReport.model_validate(payload)
