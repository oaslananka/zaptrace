from __future__ import annotations

import tomllib
from pathlib import Path

from zaptrace.versioning import python_to_cargo_version


def _pyproject_version() -> str:
    return tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _cargo_manifest_version(path: str) -> str:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return data["package"]["version"]


def _cargo_lock_package_version(package_name: str) -> str:
    data = tomllib.loads(Path("zaptrace_core/Cargo.lock").read_text(encoding="utf-8"))
    for package in data["package"]:
        if package["name"] == package_name:
            return package["version"]
    raise AssertionError(f"package not found in Cargo.lock: {package_name}")


def test_rust_extension_version_matches_python_package() -> None:
    assert _cargo_manifest_version("zaptrace_core/Cargo.toml") == python_to_cargo_version(_pyproject_version())


def test_rust_lock_version_matches_cargo_manifest() -> None:
    assert _cargo_lock_package_version("zaptrace-core") == _cargo_manifest_version("zaptrace_core/Cargo.toml")
