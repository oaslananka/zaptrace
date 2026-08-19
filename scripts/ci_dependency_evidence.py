#!/usr/bin/env python3
"""Emit machine-readable lock and MCP dependency identity evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import tomllib
from pathlib import Path
from typing import Any

from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dependency-evidence.json"
SUPPORTED = {
    "fastmcp": SpecifierSet(">=3.4,<4"),
    "mcp": SpecifierSet(">=1.28,<2"),
}


def lock_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locked_versions(path: Path) -> dict[str, str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        package["name"]: package["version"] for package in data.get("package", []) if package.get("name") in SUPPORTED
    }


def build_report(root: Path = ROOT) -> dict[str, Any]:
    lock = root / "uv.lock"
    locked = locked_versions(lock)
    dependencies: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for package, specifier in SUPPORTED.items():
        locked_version = locked.get(package, "")
        try:
            installed_version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            installed_version = ""
        supported = bool(locked_version and installed_version)
        if supported:
            supported = Version(locked_version) in specifier and Version(installed_version) in specifier
            supported = supported and locked_version == installed_version
        if not supported:
            errors.append(
                f"{package}: locked={locked_version or 'missing'} installed={installed_version or 'missing'} "
                f"supported={specifier}"
            )
        dependencies[package] = {
            "specifier": str(specifier),
            "locked_version": locked_version,
            "installed_version": installed_version,
            "supported": supported,
        }
    return {
        "schema_version": "1.0",
        "gate_id": "dependency-evidence-v1",
        "passed": not errors,
        "lock_path": "uv.lock",
        "lock_sha256": lock_sha256(lock),
        "dependencies": dependencies,
        "errors": errors,
    }


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report = build_report(root)
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report_json(report), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
