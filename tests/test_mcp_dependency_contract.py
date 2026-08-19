from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = {
    "fastmcp": SpecifierSet(">=3.4,<4"),
    "mcp": SpecifierSet(">=1.28,<2"),
}


def _locked_versions() -> dict[str, Version]:
    data = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    return {package["name"]: Version(package["version"]) for package in data["package"] if package["name"] in SUPPORTED}


def test_locked_and_installed_mcp_versions_match_supported_line() -> None:
    locked = _locked_versions()

    assert set(locked) == set(SUPPORTED)
    for package, supported in SUPPORTED.items():
        installed = Version(importlib.metadata.version(package))
        assert locked[package] in supported
        assert installed in supported
        assert installed == locked[package]
