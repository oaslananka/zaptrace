"""Tests for structured KiCad oracle CI evidence."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from scripts import ci_kicad_oracle


def test_oracle_summary_writes_explicit_skipped_status(tmp_path: Path) -> None:
    output = tmp_path / "summary.json"
    ci_kicad_oracle._CHECKS.clear()
    ci_kicad_oracle._SKIP_REASONS.clear()
    ci_kicad_oracle._record_check("detect", "skipped", "kicad-cli not found on PATH")

    ci_kicad_oracle._write_summary(output, status="skipped")

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["kicad_oracle"] == "skip-unapproved"
    assert data["raw_status"] == "skipped"
    assert data["skip_approval_id"] == ""
    assert data["skip_reason"] == "kicad-cli not found on PATH"
    assert data["checks"][0]["status"] == "skipped"


def test_oracle_summary_marks_skip_approved_when_approval_id_present(tmp_path: Path) -> None:
    output = tmp_path / "summary.json"
    ci_kicad_oracle._CHECKS.clear()
    ci_kicad_oracle._SKIP_REASONS.clear()
    ci_kicad_oracle._record_check("detect", "skipped", "kicad-cli not found on PATH")

    ci_kicad_oracle._write_summary(output, status="skipped", skip_approval_id="APPROVAL-42")

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["kicad_oracle"] == "skip-approved"
    assert data["raw_status"] == "skipped"
    assert data["skip_approval_id"] == "APPROVAL-42"


def test_oracle_summary_writes_failed_status(tmp_path: Path) -> None:
    output = tmp_path / "summary.json"
    ci_kicad_oracle._CHECKS.clear()
    ci_kicad_oracle._SKIP_REASONS.clear()
    ci_kicad_oracle._record_check("pcb_drc", "failed", "DRC reported violations", errors=1)

    ci_kicad_oracle._write_summary(output, status="failed", version="9.0.0", cli_path="/usr/bin/kicad-cli")

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["kicad_oracle"] == "failed"
    assert data["version"] == "9.0.0"
    assert data["checks"][0]["errors"] == 1


def test_oracle_overall_status_fails_if_any_check_failed() -> None:
    ci_kicad_oracle._CHECKS.clear()
    ci_kicad_oracle._SKIP_REASONS.clear()
    ci_kicad_oracle._record_check("pcb_export_svg", "passed", "ok")
    ci_kicad_oracle._record_check("pcb_drc", "failed", "DRC reported violations")
    assert ci_kicad_oracle._overall_status() == "failed"


def test_oracle_overall_status_requires_release_gate_skip_for_partial_skips() -> None:
    ci_kicad_oracle._CHECKS.clear()
    ci_kicad_oracle._SKIP_REASONS.clear()
    ci_kicad_oracle._record_check("pcb_export_svg", "passed", "ok")
    ci_kicad_oracle._record_check("pcb_drc", "skipped", "kicad-cli lacks pcb drc")
    assert ci_kicad_oracle._overall_status() == "skipped"


def test_oracle_summary_includes_commands_and_hashes(tmp_path: Path) -> None:
    output = tmp_path / "summary.json"
    artifact = tmp_path / "oracle.txt"
    artifact.write_text("oracle evidence", encoding="utf-8")
    ci_kicad_oracle._CHECKS.clear()
    ci_kicad_oracle._SKIP_REASONS.clear()
    ci_kicad_oracle._record_check(
        "pcb_drc",
        "passed",
        "DRC report generated",
        command=["kicad-cli", "pcb", "drc"],
        report_path=str(artifact),
        report_sha256=ci_kicad_oracle._sha256_file(artifact),
    )

    ci_kicad_oracle._write_summary(output, status="passed", version="9.0.0", cli_path="/usr/bin/kicad-cli")

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["commands"] == [["kicad-cli", "pcb", "drc"]]
    assert data["artifact_hashes"][str(artifact)] == ci_kicad_oracle._sha256_file(artifact)
    assert data["skip_policy"].startswith("skips are explicit")


def test_kicad_subprocess_uses_ephemeral_private_home_when_home_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_home: Path | None = None

    def fake_run(*_args: object, env: dict[str, str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal observed_home
        observed_home = Path(env["HOME"])
        assert observed_home.is_dir()
        assert not observed_home.is_symlink()
        if os.name == "posix":
            assert stat.S_IMODE(observed_home.stat().st_mode) == 0o700
        return subprocess.CompletedProcess(["kicad-cli", "--version"], 0, "9.0.0", "")

    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setattr(ci_kicad_oracle, "KICAD_CLI", "/usr/bin/kicad-cli")
    monkeypatch.setattr(ci_kicad_oracle.subprocess, "run", fake_run)

    result = ci_kicad_oracle._run_kicad_cli(["--version"])

    assert result.returncode == 0
    assert observed_home is not None
    assert not observed_home.exists()


def test_main_rejects_output_outside_trusted_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside.json"

    assert ci_kicad_oracle.main(["--check", "--output", str(outside)], trusted_root=trusted) == 2
    assert "escapes repository root" in capsys.readouterr().err
