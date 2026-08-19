#!/usr/bin/env python3
"""Normalize cargo-audit JSON into stable ZapTrace security evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1
_NON_CLAIMS = [
    "A clean advisory scan does not prove the native extension is vulnerability-free.",
    "Cargo advisory evidence covers dependencies recorded in the supplied Cargo.lock only.",
    "Warnings require maintainer triage and do not replace independent security review.",
]


class CargoAuditEvidenceError(RuntimeError):
    """Raised when cargo-audit evidence cannot be normalized safely."""


def _workspace_root(path: Path) -> Path:
    if path.is_symlink():
        raise CargoAuditEvidenceError("workspace root must not be a symbolic link")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CargoAuditEvidenceError(f"workspace root does not exist: {path}") from exc
    if not resolved.is_dir():
        raise CargoAuditEvidenceError(f"workspace root is not a directory: {resolved}")
    return resolved


def _candidate(path: Path, workspace_root: Path) -> Path:
    return path if path.is_absolute() else workspace_root / path


def _require_within_workspace(path: Path, workspace_root: Path, label: str) -> Path:
    candidate = _candidate(path, workspace_root)
    if candidate.is_symlink():
        raise CargoAuditEvidenceError(f"{label} must not be a symbolic link")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(workspace_root)
    except FileNotFoundError as exc:
        raise CargoAuditEvidenceError(f"{label} does not exist: {candidate}") from exc
    except ValueError as exc:
        raise CargoAuditEvidenceError(f"{label} is outside workspace: {candidate}") from exc
    if not resolved.is_file():
        raise CargoAuditEvidenceError(f"{label} is not a file: {resolved}")
    return resolved


def _require_output_within_workspace(path: Path, workspace_root: Path, label: str) -> Path:
    candidate = _candidate(path, workspace_root)
    if candidate.is_symlink():
        raise CargoAuditEvidenceError(f"{label} must not be a symbolic link")
    try:
        parent = candidate.parent.resolve(strict=True)
        parent.relative_to(workspace_root)
    except FileNotFoundError as exc:
        raise CargoAuditEvidenceError(f"{label} parent does not exist: {candidate.parent}") from exc
    except ValueError as exc:
        raise CargoAuditEvidenceError(f"{label} is outside workspace: {candidate}") from exc
    if candidate.exists() and not candidate.is_file():
        raise CargoAuditEvidenceError(f"{label} is not a file: {candidate}")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_digest(report: dict[str, Any]) -> str:
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_raw_report(path: Path, workspace_root: Path) -> dict[str, Any]:
    """Load a contained, non-symlink cargo-audit JSON report."""
    root = _workspace_root(workspace_root)
    safe_path = _require_within_workspace(path, root, "cargo-audit input")
    try:
        data = json.loads(safe_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CargoAuditEvidenceError("cargo-audit output is not valid JSON") from exc
    if not isinstance(data, dict):
        raise CargoAuditEvidenceError("cargo-audit output is not a JSON object")
    return data


def _warning_categories(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    categories: dict[str, int] = {}
    for name, entries in raw.items():
        if isinstance(entries, list):
            categories[str(name)] = len(entries)
    return dict(sorted(categories.items()))


def _advisory_ids(vulnerabilities: Any) -> list[str]:
    if not isinstance(vulnerabilities, dict):
        return []
    entries = vulnerabilities.get("list", [])
    if not isinstance(entries, list):
        return []
    identifiers: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        advisory = entry.get("advisory")
        if isinstance(advisory, dict) and advisory.get("id"):
            identifiers.add(str(advisory["id"]))
    return sorted(identifiers)


def normalize_report(
    raw: dict[str, Any],
    lockfile: Path,
    cargo_audit_version: str,
    workspace_root: Path,
) -> dict[str, Any]:
    """Create deterministic advisory evidence from a contained Cargo.lock."""
    root = _workspace_root(workspace_root)
    safe_lockfile = _require_within_workspace(lockfile, root, "Cargo.lock")

    vulnerabilities = raw.get("vulnerabilities", {})
    if not isinstance(vulnerabilities, dict):
        raise CargoAuditEvidenceError("cargo-audit vulnerabilities field is invalid")
    count_raw = vulnerabilities.get("count", 0)
    found_raw = vulnerabilities.get("found", count_raw > 0)
    if not isinstance(count_raw, int) or count_raw < 0:
        raise CargoAuditEvidenceError("cargo-audit vulnerability count is invalid")
    if not isinstance(found_raw, bool):
        raise CargoAuditEvidenceError("cargo-audit vulnerability found flag is invalid")

    advisory_ids = _advisory_ids(vulnerabilities)
    warning_categories = _warning_categories(raw.get("warnings", {}))
    warning_count = sum(warning_categories.values())
    report: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "pass" if count_raw == 0 and not found_raw else "fail",
        "cargo_audit_version": cargo_audit_version.strip(),
        "cargo_lock_sha256": _sha256(safe_lockfile),
        "vulnerability_count": count_raw,
        "advisory_ids": advisory_ids,
        "warning_count": warning_count,
        "warning_categories": warning_categories,
        "non_claims": list(_NON_CLAIMS),
    }
    report["evidence_digest"] = _stable_digest(report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Cargo Advisory Evidence",
        "",
        f"- Status: **{report['status'].upper()}**",
        f"- cargo-audit: `{report['cargo_audit_version']}`",
        f"- Cargo.lock SHA-256: `{report['cargo_lock_sha256']}`",
        f"- Vulnerabilities: `{report['vulnerability_count']}`",
        f"- Warnings: `{report['warning_count']}`",
        f"- Evidence digest: `{report['evidence_digest']}`",
        "",
        "## Advisories",
        "",
    ]
    if report["advisory_ids"]:
        lines.extend(f"- `{identifier}`" for identifier in report["advisory_ids"])
    else:
        lines.append("- None reported")
    lines.extend(["", "## Non-claims", ""])
    lines.extend(f"- {claim}" for claim in report["non_claims"])
    return "\n".join(lines) + "\n"


def exit_code(report: dict[str, Any], strict: bool) -> int:
    return 1 if strict and report.get("status") != "pass" else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--lockfile", type=Path, required=True)
    parser.add_argument("--tool-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = _workspace_root(args.workspace_root)
        output = _require_output_within_workspace(args.output, root, "evidence output")
        markdown_output = (
            _require_output_within_workspace(args.markdown, root, "Markdown output")
            if args.markdown is not None
            else None
        )
    except CargoAuditEvidenceError:
        return 1

    try:
        report = normalize_report(
            load_raw_report(args.input, root),
            args.lockfile,
            args.tool_version,
            root,
        )
    except CargoAuditEvidenceError as exc:
        report = {
            "schema_version": _SCHEMA_VERSION,
            "status": "fail",
            "error": str(exc),
            "cargo_audit_version": args.tool_version.strip(),
            "non_claims": list(_NON_CLAIMS),
        }
        report["evidence_digest"] = _stable_digest(report)

    # The output path is workspace-contained and non-symlink after validation above.
    output.write_text(  # NOSONAR
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if markdown_output is not None:
        if "cargo_lock_sha256" in report:
            markdown = render_markdown(report)
        else:
            markdown = f"# Cargo Advisory Evidence\n\n- Status: **FAIL**\n- Error: {report['error']}\n"
        # The Markdown path is workspace-contained and non-symlink after validation above.
        markdown_output.write_text(  # NOSONAR
            markdown, encoding="utf-8"
        )
    return exit_code(report, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
