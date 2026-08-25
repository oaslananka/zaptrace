from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.ci_architecture_compiler_gate import build_gate_report, main

CORPUS = Path("tests/fixtures/architecture/prompts.yaml")


def test_architecture_compiler_gate_passes_committed_corpus() -> None:
    report = build_gate_report(CORPUS, minimum_ready_cases=5, allowed_root=Path.cwd())

    assert report["passed"] is True
    assert report["case_count"] == 8
    assert report["ready_case_count"] == 5
    assert report["passed_case_count"] == 8
    assert report["status_counts"] == {"needs-clarification": 2, "ready": 5, "unsafe-blocked": 1}
    assert report["schema_sha256"]
    assert report["errors"] == []


def test_architecture_compiler_gate_detects_expected_result_drift(tmp_path: Path) -> None:
    cases = yaml.safe_load(CORPUS.read_text(encoding="utf-8"))
    cases[0]["expected_subsystems"] = ["SUBSYS-NOT-REAL"]
    drifted = tmp_path / "prompts.yaml"
    drifted.write_text(yaml.safe_dump(cases, sort_keys=False), encoding="utf-8")

    report = build_gate_report(drifted, minimum_ready_cases=5, allowed_root=tmp_path)

    assert report["passed"] is False
    assert report["failed_case_count"] == 1
    assert any("esp32-usb-i2c-sensor" in error for error in report["errors"])


def test_architecture_compiler_gate_rejects_corpus_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside allowed root"):
        build_gate_report(outside, allowed_root=workspace)


def test_architecture_compiler_gate_rejects_symlinked_corpus(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.yaml"
    corpus.write_text(CORPUS.read_text(encoding="utf-8"), encoding="utf-8")
    link = tmp_path / "linked.yaml"
    try:
        link.symlink_to(corpus)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="symbolic link"):
        build_gate_report(link, allowed_root=tmp_path)


def test_architecture_compiler_gate_cli_is_deterministic(tmp_path: Path) -> None:
    first_report = tmp_path / "first.json"
    second_report = tmp_path / "second.json"
    first_schema = tmp_path / "first-schema.json"
    second_schema = tmp_path / "second-schema.json"

    assert (
        main(
            [
                "--corpus",
                str(CORPUS),
                "--minimum-ready-cases",
                "5",
                "--schema-output",
                str(first_schema),
                "--output",
                str(first_report),
                "--strict",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--corpus",
                str(CORPUS),
                "--minimum-ready-cases",
                "5",
                "--schema-output",
                str(second_schema),
                "--output",
                str(second_report),
                "--strict",
            ]
        )
        == 0
    )

    assert first_report.read_bytes() == second_report.read_bytes()
    assert first_schema.read_bytes() == second_schema.read_bytes()
    assert json.loads(first_report.read_text(encoding="utf-8"))["passed"] is True


def test_architecture_compiler_gate_strict_mode_fails_ready_shortfall(tmp_path: Path) -> None:
    output = tmp_path / "report.json"

    code = main(
        [
            "--corpus",
            str(CORPUS),
            "--minimum-ready-cases",
            "6",
            "--output",
            str(output),
            "--strict",
        ]
    )

    assert code == 1
    assert json.loads(output.read_text(encoding="utf-8"))["ready_case_shortfall"] == 1


def test_quality_workflow_enforces_architecture_compiler_snapshot() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "scripts/ci_architecture_compiler_gate.py" in workflow
    assert "docs/schemas/electronics-architecture-v1.schema.json" in workflow
    assert "docs/reports/architecture-compiler-coverage-2026-07-27.json" in workflow
    assert "architecture-compiler-evidence" in workflow
