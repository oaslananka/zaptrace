"""Shared fail-closed SHA-bound real Ubuntu installed-package acceptance checks."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Callable
from pathlib import Path


def check(log: str, *required: str) -> None:
    absent = [item for item in required if item not in log]
    if absent:
        raise ValueError("Independent acceptance logs have not proved: " + "; ".join(absent))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_report(
    package: Path,
    gate: Path,
    copper: Path,
    older: Path,
    installed: Path,
    legacy: Path,
    lifecycle: Path,
    ubuntu_browser: Path,
    output: Path,
    *,
    version: str,
    requirements: Callable[[Path, str], dict[str, tuple[str, ...]]],
    build_lines: Callable[[str, str], list[str]],
) -> Path:
    files = [package, gate, copper, older, installed, legacy, lifecycle, ubuntu_browser]
    if any(not path.is_file() or path.is_symlink() for path in files):
        raise ValueError("All exact-package and genuine Ubuntu logs must be readable regular files")
    if package.name != f"zaptrace-review-studio_{version}_all.deb":
        raise ValueError(f"Native Review Studio release version must be {version}")
    actual = sha(package)
    if package.with_suffix(".sha256").read_text().strip() != f"{actual}  {package.name}":
        raise ValueError("Debian package SHA manifest does not match exact tested bytes")
    content = [path.read_text(encoding="utf-8") for path in files[1:]]
    gate_log, copper_log, older_log, installed_log, legacy_log, lifecycle_log, ubuntu_browser_log = content
    group_names = ("gate", "copper", "older", "installed", "legacy", "lifecycle", "ubuntu_browser")
    required = requirements(package, actual)
    if set(required) != set(group_names):
        raise ValueError("Independent Ubuntu release evidence inventory mismatch")
    for name, log in zip(group_names, content, strict=True):
        check(log, *required[name])
    marker = f"PACKAGE_SHA256={actual}"
    for name, log in zip(
        (
            "Chrome copper",
            "Chrome regressions",
            "Ubuntu installed",
            "Legacy ZIP",
            "APT lifecycle",
            "Ubuntu installed browser",
        ),
        (copper_log, older_log, installed_log, legacy_log, lifecycle_log, ubuntu_browser_log),
        strict=True,
    ):
        if marker not in log.splitlines():
            raise ValueError(f"{name} proof not bound to the exact package SHA-256")
    lines = build_lines(marker, gate_log)
    for key, file in zip(
        (
            "9-stage-gate",
            "chrome-copper",
            "chrome-existing",
            "ubuntu-native",
            "legacy-private-zip",
            "apt-upgrade-remove",
            "ubuntu-installed-chrome",
        ),
        files[1:],
        strict=True,
    ):
        lines.append(key + " sha256=" + sha(file))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n")
    print("SHA_BOUND_REAL_UBUNTU_ACCEPTANCE_WRITTEN", output)
    print("PACKAGE_SHA256=" + actual)
    return output


def main_with_report(report: Callable[..., Path], description: str) -> int:
    parser = argparse.ArgumentParser(description=description)
    names = ("package", "gate", "copper", "older", "installed", "legacy", "lifecycle", "ubuntu_browser", "output")
    for name in names:
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    report(*(getattr(args, name) for name in names))
    return 0
