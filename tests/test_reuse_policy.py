from __future__ import annotations

import json
from pathlib import Path

from scripts import ci_reuse_check

ROOT = Path(__file__).resolve().parents[1]


def test_reuse_tool_is_pinned_through_reproducible_uvx() -> None:
    script = (ROOT / "scripts" / "ci_reuse_check.py").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'EXPECTED_REUSE_VERSION = "6.2.0"' in script
    assert '"--from", f"reuse=={EXPECTED_REUSE_VERSION}", "reuse"' in script
    assert "reuse==6.2.0" not in pyproject


def test_vendor_footprints_override_project_license() -> None:
    config = (ROOT / "REUSE.toml").read_text(encoding="utf-8")
    attribution = (ROOT / "data" / "footprints" / "vendor" / "ATTRIBUTION.md").read_text(encoding="utf-8")

    assert 'path = "data/footprints/vendor/*.kicad_mod"' in config
    assert 'precedence = "override"' in config
    assert 'SPDX-License-Identifier = "CC-BY-SA-4.0"' in config
    assert "KiCad project contributors" in config
    assert (ROOT / "LICENSES" / "CC-BY-SA-4.0.txt").is_file()
    assert "Creative Commons Attribution-ShareAlike 4.0 International" in attribution


def test_repository_hygiene_runs_reuse_gate_and_uploads_evidence() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "astral-sh/setup-uv@fac544c07dec837d0ccb6301d7b5580bf5edae39" in workflow
    assert "python scripts/ci_reuse_check.py" in workflow
    assert "Install license compliance tool" not in workflow
    assert "--output reuse-compliance.json" in workflow
    assert "--strict" in workflow
    assert "reuse-compliance.json" in workflow.split("Upload repository policy evidence", 1)[1]


def test_contributor_docs_publish_exact_reuse_command() -> None:
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    dependency = (ROOT / "docs" / "development" / "dependency-management.md").read_text(encoding="utf-8")

    command = "python scripts/ci_reuse_check.py --strict"
    assert command in contributing
    assert command in dependency


def test_checker_report_records_tool_and_result(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "reuse.json"

    monkeypatch.setattr(ci_reuse_check, "_reuse_version", lambda: "reuse 6.2.0")
    monkeypatch.setattr(ci_reuse_check, "_run_reuse_lint", lambda _root: (0, "Successfully parsed project"))

    assert ci_reuse_check.main(["--root", str(tmp_path), "--output", str(output), "--strict"]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report == {
        "errors": [],
        "gate_id": "reuse-spdx-v1",
        "output": "Successfully parsed project",
        "passed": True,
        "return_code": 0,
        "schema_version": "1.0",
        "strict": True,
        "tool_version": "reuse 6.2.0",
    }


def test_checker_fails_when_reuse_reports_uncovered_file(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "reuse.json"

    monkeypatch.setattr(ci_reuse_check, "_reuse_version", lambda: "reuse 6.2.0")
    monkeypatch.setattr(
        ci_reuse_check,
        "_run_reuse_lint",
        lambda _root: (1, "* Missing copyright and licensing information for: uncovered.py"),
    )

    assert ci_reuse_check.main(["--root", str(tmp_path), "--output", str(output), "--strict"]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert report["return_code"] == 1
    assert "uncovered.py" in report["output"]


def test_checker_invokes_pinned_uvx_command(monkeypatch, tmp_path: Path) -> None:
    observed: dict[str, object] = {}

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return Result()

    monkeypatch.setattr(ci_reuse_check.shutil, "which", lambda _name: "/usr/bin/uvx")
    monkeypatch.setattr(ci_reuse_check.subprocess, "run", fake_run)

    assert ci_reuse_check._run_reuse_lint(tmp_path) == (0, "ok")
    assert observed["command"] == ["/usr/bin/uvx", "--from", "reuse==6.2.0", "reuse", "lint"]
    assert observed["cwd"] == tmp_path
    assert observed["check"] is False


def test_real_reuse_lint_rejects_new_uncovered_file(tmp_path: Path) -> None:
    (tmp_path / "REUSE.toml").write_text("version = 1\n", encoding="utf-8")
    licenses = tmp_path / "LICENSES"
    licenses.mkdir()
    (licenses / "MIT.txt").write_text((ROOT / "LICENSES" / "MIT.txt").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "uncovered.py").write_text("print('uncovered')\n", encoding="utf-8")

    code, output = ci_reuse_check._run_reuse_lint(tmp_path)

    assert code == 1
    assert "uncovered.py" in output
    assert "missing" in output.lower()


def test_public_maturity_evidence_marks_enforced_reuse_complete() -> None:
    maturity = (ROOT / "docs" / "repo-maturity-report.md").read_text(encoding="utf-8")
    gaps = (ROOT / "docs" / "openssf-gap-analysis.md").read_text(encoding="utf-8")

    assert "License hygiene | Passed" in maturity
    assert "SPDX/REUSE | Passed" in gaps
    assert "github.com/oaslananka/zaptrace/issues/318" not in maturity
    assert "github.com/oaslananka/zaptrace/issues/318" not in gaps
