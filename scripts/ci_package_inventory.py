#!/usr/bin/env python3
"""Inspect built wheel and sdist archives for prohibited generated artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = ROOT / "dist"
DEFAULT_OUTPUT = ROOT / "package-inventory.json"
_DISTRIBUTION_STEMS = ("zaptrace_eda", "zaptrace")

_DEBUG_BUILD_EXTENSIONS = frozenset({".pdb", ".obj", ".ilk", ".exp", ".lib", ".a", ".pyc"})
_NATIVE_EXTENSIONS = frozenset({".so", ".pyd", ".dylib", ".dll"})
_GENERATED_DIRECTORIES = frozenset({"build", "dist", "target", "__pycache__", ".pytest_cache", ".ruff_cache"})
_ALLOWED_NATIVE_RE = re.compile(r"^(?:[^/]+/)?zaptrace/_core[^/]*\.(?:so|pyd)$")


def archive_members(path: Path) -> tuple[str, ...]:
    if path.suffix in {".whl", ".zip"}:
        with zipfile.ZipFile(path) as archive:
            return tuple(sorted(info.filename for info in archive.infolist() if not info.is_dir()))
    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            return tuple(sorted(member.name for member in archive.getmembers() if member.isfile()))
    raise ValueError(f"unsupported distribution archive: {path.name}")


def validate_members(members: Iterable[str]) -> list[str]:
    errors: list[str] = []
    for raw in sorted(set(members)):
        member = PurePosixPath(raw.replace("\\", "/"))
        normalized = member.as_posix()
        if raw.startswith(("/", "\\")) or member.is_absolute() or ".." in member.parts:
            errors.append(f"{raw}: unsafe archive path")
            continue
        generated = next((part for part in member.parts[:-1] if part in _GENERATED_DIRECTORIES), None)
        if generated is not None:
            errors.append(f"{normalized}: package member is inside generated directory {generated}")
        suffix = member.suffix.lower()
        if suffix in _DEBUG_BUILD_EXTENSIONS:
            errors.append(f"{normalized}: prohibited debug/build extension {suffix}")
        elif suffix in _NATIVE_EXTENSIONS and _ALLOWED_NATIVE_RE.fullmatch(normalized) is None:
            errors.append(f"{normalized}: unexpected native library in package")
    return errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_dist(dist_dir: Path = DEFAULT_DIST) -> dict[str, Any]:
    wheels = sorted({path for stem in _DISTRIBUTION_STEMS for path in dist_dir.glob(f"{stem}-*.whl")})
    sdists = sorted({path for stem in _DISTRIBUTION_STEMS for path in dist_dir.glob(f"{stem}-*.tar.gz")})
    if not wheels:
        raise ValueError(f"no ZapTrace wheel found in {dist_dir}")
    if not sdists:
        raise ValueError(f"no ZapTrace source distribution found in {dist_dir}")

    archives: list[dict[str, Any]] = []
    all_errors: list[str] = []
    for path in [*wheels, *sdists]:
        members = archive_members(path)
        errors = validate_members(members)
        all_errors.extend(f"{path.name}: {error}" for error in errors)
        archives.append(
            {
                "path": path.name,
                "sha256": _sha256(path),
                "member_count": len(members),
                "errors": errors,
            }
        )
    return {
        "schema_version": "1.0",
        "gate_id": "package-inventory-v1",
        "passed": not all_errors,
        "archive_count": len(archives),
        "archives": archives,
        "errors": all_errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    report = inspect_dist(args.dist_dir.resolve())
    output = args.output.resolve()
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
