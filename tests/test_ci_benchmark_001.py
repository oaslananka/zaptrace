from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci_benchmark_001 import (
    FAIL,
    PASS,
    _bom_risk_evidence_errors,
    _fab_profile_evidence_errors,
    _proof_pack_evidence_errors,
    _resolve_benchmark_input,
    build_report,
    load_spec,
    main,
    validate_spec,
)
from zaptrace import __version__


def test_benchmark_001_spec_contract_passes() -> None:
    spec = load_spec(Path("benchmarks/001-esp32-sensor/requirements.yaml"))
    checks = validate_spec(spec, root=Path.cwd())
    report = build_report(spec, checks)

    assert report["schema_version"] == "2.0"
    identity = report["evidence_identity"]
    assert identity["mode"] == "snapshot"
    assert identity["package_version"] == __version__
    assert len(identity["source_commit"]) == 40
    assert len(identity["identity_sha256"]) == 64
    assert report["status"] == PASS
    assert report["blocked"] is False
    assert report["benchmark"]["id"] == "benchmark-001-esp32-sensor"
    assert report["benchmark"]["release_gate"]["milestone_readiness"] == "M1"
    assert {check["name"] for check in report["checks"]} >= {
        "metadata",
        "board-requirements",
        "acceptance-thresholds",
        "release-gate-link",
        "scoring-evidence",
    }


def test_main_writes_json_and_markdown(tmp_path) -> None:
    output = tmp_path / "benchmark-001-report.json"
    markdown = tmp_path / "benchmark-001-report.md"

    code = main(["--output", str(output), "--markdown", str(markdown), "--strict"])

    assert code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == PASS
    assert report["evidence_identity"]["mode"] == "snapshot"
    assert "Evidence identity" in markdown.read_text(encoding="utf-8")
    assert "Benchmark 001 Release Gate Summary" in markdown.read_text(encoding="utf-8")


def test_missing_function_blocks_release(tmp_path) -> None:
    source = Path("benchmarks/001-esp32-sensor/requirements.yaml")
    spec_path = tmp_path / "requirements.yaml"
    text = source.read_text(encoding="utf-8")
    text = text.replace("    - id: i2c_sensor\n", "    - id: removed_i2c_sensor\n")
    spec_path.write_text(text, encoding="utf-8")

    spec = load_spec(spec_path)
    checks = validate_spec(spec, root=Path.cwd())
    report = build_report(spec, checks)

    assert report["status"] == FAIL
    assert "board-requirements" in report["blocking_checks"]


def test_scoring_evidence_requires_committed_proof_and_bom(tmp_path) -> None:
    source = Path("benchmarks/001-esp32-sensor/requirements.yaml")
    spec_path = tmp_path / "requirements.yaml"
    text = source.read_text(encoding="utf-8")
    text = text.replace(
        "  bom_risk_report: docs/reports/benchmark-001-bom-risk-sample.json\n",
        "  bom_risk_report: docs/reports/missing-bom-risk.json\n",
    )
    spec_path.write_text(text, encoding="utf-8")

    spec = load_spec(spec_path)
    checks = validate_spec(spec, root=Path.cwd())
    report = build_report(spec, checks)

    assert report["status"] == FAIL
    assert "scoring-evidence" in report["blocking_checks"]


def test_resolve_benchmark_input_accepts_relative_file_inside_root(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence" / "proof.yaml"
    artifact.parent.mkdir()
    artifact.write_text("checks: []\n", encoding="utf-8")

    assert (
        _resolve_benchmark_input(
            "evidence/proof.yaml",
            root=tmp_path,
            field="scoring_evidence.proof_pack_manifest",
            allowed_suffixes={".yaml", ".yml"},
        )
        == artifact
    )


@pytest.mark.parametrize("candidate", ["../outside.json", "/tmp/outside.json"])
def test_resolve_benchmark_input_rejects_paths_outside_root(tmp_path: Path, candidate: str) -> None:
    with pytest.raises(ValueError, match="escapes benchmark root"):
        _resolve_benchmark_input(
            candidate,
            root=tmp_path,
            field="scoring_evidence.bom_risk_report",
            allowed_suffixes={".json"},
        )


def test_resolve_benchmark_input_rejects_symlink_escape(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = trusted / "report.json"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="escapes benchmark root"):
        _resolve_benchmark_input(
            "report.json",
            root=trusted,
            field="scoring_evidence.bom_risk_report",
            allowed_suffixes={".json"},
        )


def test_resolve_benchmark_input_rejects_wrong_suffix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must use one of"):
        _resolve_benchmark_input(
            "evidence/report.yaml",
            root=tmp_path,
            field="scoring_evidence.bom_risk_report",
            allowed_suffixes={".json"},
        )


def test_scoring_evidence_reports_escaped_paths_as_invalid(tmp_path: Path) -> None:
    source = Path("benchmarks/001-esp32-sensor/requirements.yaml")
    spec = load_spec(source)
    spec["scoring_evidence"]["bom_risk_report"] = "../outside.json"

    check = next(item for item in validate_spec(spec, root=tmp_path) if item.name == "scoring-evidence")

    assert check.status == FAIL
    assert check.details is not None
    assert any("escapes benchmark root" in item for item in check.details["invalid"])


def test_expected_artifact_rejects_path_outside_root(tmp_path: Path) -> None:
    spec = load_spec(Path("benchmarks/001-esp32-sensor/requirements.yaml"))
    committed = next(item for item in spec["expected_artifacts"] if item.get("stage") == "committed")
    committed["path"] = "../outside.yaml"

    check = next(item for item in validate_spec(spec, root=tmp_path) if item.name == "expected-artifacts")

    assert check.status == FAIL
    assert check.details is not None
    assert any("escapes benchmark root" in item for item in check.details["invalid_paths"])


def test_resolve_benchmark_input_rejects_empty_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-empty path"):
        _resolve_benchmark_input(
            "",
            root=tmp_path,
            field="scoring_evidence.bom_risk_report",
            allowed_suffixes={".json"},
        )


def test_fab_profile_evidence_reports_mismatch_and_missing_limits() -> None:
    errors = _fab_profile_evidence_errors(
        {"fab_profile": {"name": "wrong", "layers": 4}},
        {"fab_profile": "jlcpcb-2layer", "layers": 2},
    )

    assert errors == [
        "fab profile evidence must match board target fab_profile",
        "fab profile evidence layers must match board target layers",
        "fab profile evidence missing min_clearance_mm",
        "fab profile evidence missing min_trace_width_mm",
        "fab profile evidence missing min_drill_mm",
    ]
    assert _fab_profile_evidence_errors({"fab_profile": []}, {}) == ["scoring_evidence.fab_profile must be a mapping"]


def test_proof_pack_evidence_reports_invalid_and_small_manifests(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("checks: [", encoding="utf-8")
    too_small = tmp_path / "small.yaml"
    too_small.write_text("checks: []\n", encoding="utf-8")

    malformed_errors = _proof_pack_evidence_errors({"proof_pack_manifest": malformed.name}, root=tmp_path)
    small_errors = _proof_pack_evidence_errors({"proof_pack_manifest": too_small.name}, root=tmp_path)

    assert malformed_errors
    assert "invalid YAML" in malformed_errors[0]
    assert small_errors == ["proof-pack manifest must define at least 6 required checks"]


def test_bom_risk_evidence_reports_malformed_and_incomplete_json(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text("{}", encoding="utf-8")

    malformed_errors = _bom_risk_evidence_errors({"bom_risk_report": malformed.name}, root=tmp_path)
    incomplete_errors = _bom_risk_evidence_errors({"bom_risk_report": incomplete.name}, root=tmp_path)

    assert malformed_errors
    assert "not valid JSON" in malformed_errors[0]
    assert incomplete_errors == [
        "BOM risk report missing provider",
        "BOM risk report missing highest_risk",
        "BOM risk report missing blocked",
        "BOM risk report missing items",
        "BOM risk report missing provenance",
        "BOM risk report must include item-level scoring evidence",
    ]


def test_main_rejects_spec_outside_repository_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    outside = tmp_path / "requirements.yaml"
    outside.write_text(
        Path("benchmarks/001-esp32-sensor/requirements.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    code = main(["--spec", str(outside), "--strict"])

    assert code == 2
    assert "escapes benchmark root" in capsys.readouterr().err


def test_main_resolves_default_spec_from_repository_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    code = main(["--strict"])

    assert code == 0
    assert '"status": "pass"' in capsys.readouterr().out
