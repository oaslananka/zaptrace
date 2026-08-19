#!/usr/bin/env python3
"""Migrate legacy component YAML into strict schema v2 without trust inflation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from zaptrace.library.loader import LIBRARY_ROOT
from zaptrace.library.migration import migrate_record


def migrate_file(path: Path, *, write: bool) -> bool:
    """Migrate one YAML file and optionally replace it atomically."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("top-level YAML is not a component mapping")
    migrated, changed = migrate_record(raw)
    if write and changed:
        rendered = yaml.safe_dump(
            migrated,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)
    return changed


def migrate_library(root: Path, *, write: bool) -> dict[str, Any]:
    """Migrate every component file and return deterministic evidence."""

    changed: list[str] = []
    unchanged: list[str] = []
    errors: list[dict[str, str]] = []
    for path in sorted(root.rglob("*.yaml")):
        relative = path.relative_to(root).as_posix()
        try:
            was_changed = migrate_file(path, write=write)
        except (OSError, ValueError, yaml.YAMLError, ValidationError) as exc:
            errors.append({"path": relative, "reason": str(exc)})
            continue
        (changed if was_changed else unchanged).append(relative)
    return {
        "schema_version": "1.0",
        "component_schema_version": "2.0",
        "mode": "write" if write else "check",
        "component_count": len(changed) + len(unchanged) + len(errors),
        "changed_count": len(changed),
        "unchanged_count": len(unchanged),
        "error_count": len(errors),
        "changed": changed,
        "errors": errors,
        "non_claims": [
            "migration does not verify manufacturer data",
            "migration does not create source hashes or human review approvals",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, default=LIBRARY_ROOT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Rewrite changed component YAML files")
    mode.add_argument("--check", action="store_true", help="Check for schema drift without rewriting files")
    parser.add_argument("--output", type=Path, help="Write migration evidence JSON")
    parser.add_argument("--strict", action="store_true", help="Return non-zero for validation errors or check drift")
    args = parser.parse_args(argv)

    report = migrate_library(args.library_root, write=args.write)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"component schema migration: components={report['component_count']} "
        f"changed={report['changed_count']} errors={report['error_count']}"
    )
    blocked = bool(report["error_count"]) or (args.strict and not args.write and bool(report["changed_count"]))
    if blocked:
        for error in report["errors"]:
            print(f"{error['path']}: {error['reason']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
