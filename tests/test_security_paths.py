from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from zaptrace.security.paths import resolve_trusted_path


def test_resolve_trusted_path_accepts_relative_child(tmp_path: Path) -> None:
    target = tmp_path / "config" / "input.yaml"
    target.parent.mkdir()
    target.write_text("value: true\n", encoding="utf-8")

    assert resolve_trusted_path("config/input.yaml", trusted_root=tmp_path, label="config path") == target


@pytest.mark.parametrize("candidate", ["../outside.yaml", "/tmp/outside.yaml"])
def test_resolve_trusted_path_rejects_paths_outside_root(tmp_path: Path, candidate: str) -> None:
    with pytest.raises(ValueError, match="config path escapes repository root"):
        resolve_trusted_path(candidate, trusted_root=tmp_path, label="config path")


def test_resolve_trusted_path_rejects_symlink_escape(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("value: true\n", encoding="utf-8")
    link = trusted / "input.yaml"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="config path escapes repository root"):
        resolve_trusted_path(link, trusted_root=trusted, label="config path")


def test_resolve_trusted_path_can_require_child(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="artifact directory must be a child"):
        resolve_trusted_path(
            tmp_path,
            trusted_root=tmp_path,
            label="artifact directory",
            require_child=True,
        )


@pytest.mark.parametrize(
    "script",
    [
        "scripts/ci_pr_review_summary.py",
        "scripts/ci_kicad_roundtrip_scorecard.py",
    ],
)
def test_ci_script_resolves_security_helper_without_pythonpath(script: str) -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, script, "--help"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
