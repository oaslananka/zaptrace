from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci_bom_risk_gate import main


def test_main_accepts_repository_json_bom(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bom = tmp_path / "bom.json"
    bom.write_text(json.dumps([{"reference": "R1", "risk": "low"}]), encoding="utf-8")

    assert main([str(bom)], trusted_root=tmp_path) == 0
    assert "BOM risk gate PASSED" in capsys.readouterr().out


def test_main_accepts_repository_csv_bom(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bom = tmp_path / "bom.csv"
    bom.write_text("reference,mpn,risk\nR1,RC0402,low\n", encoding="utf-8")

    assert main([str(bom)], trusted_root=tmp_path) == 0
    assert "BOM risk gate PASSED" in capsys.readouterr().out


def test_main_writes_failure_comment_inside_trusted_root(tmp_path: Path) -> None:
    bom = tmp_path / "bom.json"
    comment = tmp_path / "reports" / "bom-risk.md"
    comment.parent.mkdir()
    bom.write_text(
        json.dumps([{"reference": "U1", "mpn": "OLD-1", "risk": "obsolete", "risk_reason": "EOL"}]),
        encoding="utf-8",
    )

    assert main([str(bom), "--max-risk", "medium", "--pr-comment", str(comment)], trusted_root=tmp_path) == 1
    rendered = comment.read_text(encoding="utf-8")
    assert "BOM Risk Gate FAILED" in rendered
    assert "`U1`" in rendered
    assert "`OLD-1`" in rendered


@pytest.mark.parametrize("candidate", ["../outside.json", "/tmp/outside.json"])
def test_main_rejects_bom_outside_trusted_root(
    tmp_path: Path, candidate: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([candidate], trusted_root=tmp_path) == 2
    assert "BOM path escapes repository root" in capsys.readouterr().err


def test_main_rejects_bom_symlink_escape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("[]\n", encoding="utf-8")
    link = trusted / "bom.json"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    assert main([str(link)], trusted_root=trusted) == 2
    assert "BOM path escapes repository root" in capsys.readouterr().err


def test_main_rejects_pr_comment_outside_trusted_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bom = tmp_path / "bom.json"
    bom.write_text(json.dumps([{"reference": "U1", "risk": "obsolete"}]), encoding="utf-8")

    assert main([str(bom), "--pr-comment", "/tmp/bom-risk.md"], trusted_root=tmp_path) == 2
    assert "PR comment path escapes repository root" in capsys.readouterr().err


def test_main_rejects_pr_comment_symlink_escape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    bom = trusted / "bom.json"
    bom.write_text(json.dumps([{"reference": "U1", "risk": "obsolete"}]), encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    reports = trusted / "reports"
    try:
        reports.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    assert main([str(bom), "--pr-comment", str(reports / "bom-risk.md")], trusted_root=trusted) == 2
    assert "PR comment path escapes repository root" in capsys.readouterr().err


def test_cli_loads_shared_helper_without_pythonpath() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, "scripts/ci_bom_risk_gate.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_missing_bom_error_does_not_echo_user_controlled_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "token=do-not-log.json"

    assert main([str(missing)], trusted_root=tmp_path) == 2
    stderr = capsys.readouterr().err
    assert "BOM file not found inside repository root" in stderr
    assert "do-not-log" not in stderr
