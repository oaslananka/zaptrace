#!/usr/bin/env python3
"""Validate issue-form labels and tracked repository artifact hygiene."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_GITHUB_DIR = ".github"
DEFAULT_LABEL_INVENTORY = ROOT / _GITHUB_DIR / "label-taxonomy.json"
DEFAULT_OUTPUT = ROOT / "repository-policy.json"

_LABEL_TOKEN_RE = re.compile(r"^(?P<label>(?:type|priority|area|status|size)[:/][A-Za-z0-9_.-]+)(?:\s+-.*)?$")
_PROHIBITED_EXTENSIONS = frozenset(
    {".pdb", ".obj", ".ilk", ".exp", ".lib", ".a", ".dll", ".so", ".dylib", ".pyd", ".pyc"}
)
_GENERATED_DIRECTORIES = frozenset({"build", "dist", "target", "__pycache__", ".pytest_cache", ".ruff_cache"})
_TEXT_EXTENSIONS = frozenset(
    {
        "",
        ".c",
        ".cfg",
        ".cpp",
        ".css",
        ".csv",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".kicad_pcb",
        ".kicad_pro",
        ".kicad_sch",
        ".md",
        ".py",
        ".rs",
        ".rst",
        ".sh",
        ".toml",
        ".ts",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)
_MAX_TRACKED_BINARY_BYTES = 1024 * 1024


def load_label_inventory(path: Path = DEFAULT_LABEL_INVENTORY) -> frozenset[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    values = raw.get("labels") if isinstance(raw, dict) else None
    if not isinstance(values, list) or not values or not all(isinstance(value, str) and value for value in values):
        raise ValueError("label inventory must contain a non-empty string list")
    if len(values) != len(set(values)):
        raise ValueError("label inventory contains duplicate labels")
    return frozenset(values)


def _inline_form_labels(path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    labels: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.startswith("labels:"):
            value = line.partition(":")[2].strip()
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError) as exc:
                errors.append(f"{path}:{line_number}: labels must be an inline string list ({exc})")
                continue
            if not isinstance(parsed, list) or not all(isinstance(item, str) and item for item in parsed):
                errors.append(f"{path}:{line_number}: labels must be an inline string list")
                continue
            labels.extend(parsed)
            continue
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        candidate = stripped[2:].strip()
        match = _LABEL_TOKEN_RE.fullmatch(candidate)
        if match:
            labels.append(match.group("label"))
    return labels, errors


def validate_issue_forms(root: Path, labels: frozenset[str]) -> list[str]:
    forms_root = root / _GITHUB_DIR / "ISSUE_TEMPLATE"
    errors: list[str] = []
    form_paths = sorted(path for path in forms_root.glob("*.yml") if path.name != "config.yml")
    if not form_paths:
        return [f"no issue forms found under {forms_root}"]
    for path in form_paths:
        references, parse_errors = _inline_form_labels(path)
        errors.extend(parse_errors)
        lines = path.read_text(encoding="utf-8").splitlines()
        top_level = next((line for line in lines if line.startswith("labels:")), None)
        if top_level is None:
            errors.append(f"{path}: missing top-level labels")
        for label in references:
            if re.match(r"^(type|priority|area|status|size):", label):
                errors.append(f"{path}: colon-based label is not allowed: {label}")
            if label not in labels:
                errors.append(f"{path}: referenced label is missing from canonical inventory: {label}")
    return errors


def validate_tracked_artifacts(paths: Iterable[str], *, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for raw_path in sorted(set(paths)):
        normalized = raw_path.replace("\\", "/").lstrip("./")
        pure = PurePosixPath(normalized)
        suffix = pure.suffix.lower()
        if suffix in _PROHIBITED_EXTENSIONS:
            errors.append(f"{normalized}: prohibited artifact extension {suffix}")
        generated_parts = [part for part in pure.parts[:-1] if part in _GENERATED_DIRECTORIES]
        if generated_parts:
            errors.append(f"{normalized}: tracked file is inside generated directory {generated_parts[0]}")
        disk_path = root / normalized
        try:
            size = disk_path.stat().st_size
        except OSError:
            continue
        if size > _MAX_TRACKED_BINARY_BYTES and suffix not in _TEXT_EXTENSIONS:
            errors.append(f"{normalized}: unexpected large binary ({size} bytes)")
    return errors


def tracked_files(root: Path = ROOT) -> tuple[str, ...]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return tuple(item.decode("utf-8") for item in proc.stdout.split(b"\0") if item)


def build_report(root: Path = ROOT, tracked_paths: Iterable[str] | None = None) -> dict[str, Any]:
    labels = load_label_inventory(root / _GITHUB_DIR / "label-taxonomy.json")
    paths = tuple(tracked_paths) if tracked_paths is not None else tracked_files(root)
    issue_form_errors = validate_issue_forms(root, labels)
    artifact_errors = validate_tracked_artifacts(paths, root=root)
    errors = [*issue_form_errors, *artifact_errors]
    return {
        "schema_version": "1.0",
        "gate_id": "repository-policy-v1",
        "passed": not errors,
        "label_count": len(labels),
        "issue_form_count": len(list((root / _GITHUB_DIR / "ISSUE_TEMPLATE").glob("*.yml"))) - 1,
        "tracked_file_count": len(paths),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report = build_report(root)
    output = args.output if args.output.is_absolute() else root / args.output
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
