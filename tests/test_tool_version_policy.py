from __future__ import annotations

import re
from pathlib import Path


def _locked_package_version(name: str) -> str:
    lock = Path("uv.lock").read_text(encoding="utf-8")
    pattern = re.compile(rf'^name = "{re.escape(name)}"\nversion = "([^"]+)"', re.MULTILINE)
    match = pattern.search(lock)
    assert match, f"{name} not found in uv.lock"
    return match.group(1)


def test_pre_commit_ruff_matches_uv_lock() -> None:
    config = Path(".pre-commit-config.yaml").read_text(encoding="utf-8")
    locked_ruff = _locked_package_version("ruff")
    assert f"rev: v{locked_ruff}" in config
