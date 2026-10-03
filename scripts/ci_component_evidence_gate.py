"""Fail-closed CI gate for part-level component evidence manifests."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

from zaptrace.library.evidence_manifest import (
    ComponentEvidenceReport,
    load_component_evidence_manifest,
    validate_component_evidence_manifest,
)
from zaptrace.library.loader import LIBRARY_ROOT, LibraryLoader

DEFAULT_MANIFEST = Path("config/component-evidence-manifest.json")


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _allowed_output_roots(workspace: Path) -> tuple[Path, ...]:
    """Return workspace plus CI temp dirs (RUNNER_TEMP/TMPDIR/TEMP/TMP) that exist."""
    roots: list[Path] = [workspace.resolve(strict=True)]
    candidates = [tempfile.gettempdir()]
    candidates.extend(os.environ.get(name, "") for name in ("RUNNER_TEMP", "TMPDIR", "TEMP", "TMP"))
    for candidate in candidates:
        if not candidate:
            continue
        try:
            resolved = Path(candidate).resolve(strict=True)
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _resolve_output_cli_path(raw: Path | None, *, label: str) -> Path | None:
    """Confine a CLI output path to the workspace or a CI temp dir."""
    if raw is None:
        return None
    root = Path.cwd()
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve(strict=False)
    parent = resolved.parent.resolve(strict=False)
    allowed = _allowed_output_roots(root)
    if not any(_is_relative_to(parent, allowed_root) for allowed_root in allowed):
        raise ValueError(f"{label} is outside allowed roots")
    if resolved.exists() and resolved.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link")
    return resolved


def _markdown(summary: dict[str, object]) -> str:
    status = "blocked" if summary["blocked"] else "passed"
    return "\n".join(
        [
            "# Component Evidence Gate",
            "",
            f"Status: **{status}**",
            "",
            f"Verified components: `{summary['verified_component_count']}`",
            f"Manifest entries: `{summary['manifest_component_count']}`",
            f"Bound verified components: `{summary['bound_verified_component_count']}`",
            f"Evidence violations: `{summary['violation_count']}`",
            f"Library load errors: `{summary['library_error_count']}`",
            f"Evidence as-of date: `{summary['as_of']}`",
            f"Manifest digest: `{summary['manifest_digest']}`",
            "",
            "This gate validates evidence binding only; it does not prove complete-board release safety.",
            "",
        ]
    )


def build_gate_summary(
    report: ComponentEvidenceReport,
    *,
    as_of: date,
    library_errors: list[object],
) -> dict[str, object]:
    """Build stable machine-readable output for CI and proof-pack consumers."""

    return {
        "schema_version": "1.0",
        "gate": "component-evidence",
        "blocked": (not report.passed) or bool(library_errors),
        "as_of": as_of.isoformat(),
        "verified_component_count": report.verified_component_count,
        "manifest_component_count": report.manifest_component_count,
        "bound_verified_component_count": report.bound_verified_component_count,
        "manifest_digest": report.manifest_digest,
        "violation_count": len(report.violations),
        "violations": [violation.model_dump(mode="json") for violation in report.violations],
        "library_error_count": len(library_errors),
        "library_errors": [
            {
                "path": str(getattr(error, "path", "")),
                "reason": str(getattr(error, "reason", error)),
            }
            for error in library_errors
        ],
        "report": report.model_dump(mode="json"),
    }


def _write_gate_outputs(summary: dict[str, object], *, output: Path | None, markdown: Path | None) -> None:
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(  # NOSONAR -- output path is confined to allowed roots in main().
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if markdown:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        with markdown.open(  # NOSONAR -- markdown path is confined to allowed roots in main().
            "a", encoding="utf-8"
        ) as handle:
            handle.write(_markdown(summary))


def _gate_exit(summary: dict[str, object], *, strict: bool) -> int:
    if summary["blocked"]:
        print(
            "Component evidence gate FAILED: "
            f"violations={summary['violation_count']} library_errors={summary['library_error_count']}",
            file=sys.stderr,
        )
        return 1 if strict else 0
    print(
        "Component evidence gate PASSED: "
        f"verified={summary['verified_component_count']} bound={summary['bound_verified_component_count']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate part-level component evidence bindings")
    parser.add_argument("--library-root", type=Path, default=LIBRARY_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    loader = LibraryLoader(args.library_root)
    specs = loader.load_all()
    library_errors = loader.load_errors()
    manifest = load_component_evidence_manifest(args.manifest, allowed_root=Path.cwd())
    report = validate_component_evidence_manifest(
        specs,
        manifest,
        repository_root=Path.cwd(),
        as_of=args.as_of,
    )
    summary = build_gate_summary(report, as_of=args.as_of, library_errors=library_errors)

    try:
        output_path = _resolve_output_cli_path(args.output, label="Output path")
        markdown_path = _resolve_output_cli_path(args.markdown, label="Markdown path")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    _write_gate_outputs(summary, output=output_path, markdown=markdown_path)
    return _gate_exit(summary, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
