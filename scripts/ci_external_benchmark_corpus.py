#!/usr/bin/env python3
"""Validate pinned external benchmark provenance and deterministic task evidence."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zaptrace.benchmark.external import (
    ExternalBenchmarkError,
    external_manifest_sha256,
    validate_external_corpus,
)

MAX_ERROR_CHARS = 4096
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _bounded(value: str) -> str:
    return value[-MAX_ERROR_CHARS:]


def _validated_manifest_path(root: Path, manifest: Path) -> Path:
    root_resolved = root.resolve(strict=True)
    candidate = manifest if manifest.is_absolute() else root_resolved / manifest
    lexical = Path(os.path.abspath(candidate))
    current = lexical
    while True:
        if current.is_symlink():
            raise ExternalBenchmarkError(f"manifest path contains symbolic link: {current}")
        if current == root_resolved or current.parent == current:
            break
        current = current.parent
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise ExternalBenchmarkError(f"cannot resolve external benchmark manifest {manifest}: {exc}") from exc
    if not resolved.is_relative_to(root_resolved):
        raise ExternalBenchmarkError(f"external benchmark manifest escapes repository root: {manifest}")
    if not resolved.is_file():
        raise ExternalBenchmarkError(f"external benchmark manifest is not a regular file: {manifest}")
    return resolved


def _source_commit(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    commit = completed.stdout.strip().lower()
    if completed.returncode != 0 or not _COMMIT_RE.fullmatch(commit):
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown git error"
        raise ExternalBenchmarkError(f"cannot resolve source commit: {detail}")
    return commit


def _canonical_digest_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _canonical_digest_value(item)
            for key, item in sorted(value.items())
            if key not in {"generated_at", "evidence_digest", "elapsed_seconds", "runtime_ms"}
        }
    if isinstance(value, list):
        return [_canonical_digest_value(item) for item in value]
    return value


def _evidence_digest(report: dict[str, Any]) -> str:
    canonical = _canonical_digest_value(report)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def build_evidence(
    root: str | Path,
    manifest: str | Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build source-identity-bound external corpus evidence."""
    root_path = Path(root).resolve(strict=True)
    manifest_path = _validated_manifest_path(root_path, Path(manifest))
    corpus_report = validate_external_corpus(root_path, manifest_path=manifest_path)
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "gate_id": "external-benchmark-corpus-v1",
        "generated_at": generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_commit": _source_commit(root_path),
        "manifest_path": manifest_path.relative_to(root_path).as_posix(),
        "manifest_sha256": external_manifest_sha256(manifest_path),
        **corpus_report.model_dump(mode="json"),
    }
    report["evidence_digest"] = _evidence_digest(report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render concise human-readable external corpus evidence."""
    status = "PASS" if report.get("passed") else "FAIL"
    lines = [
        "# External benchmark corpus evidence",
        "",
        f"- Status: **{status}**",
        f"- Source commit: `{report.get('source_commit', '')}`",
        f"- Manifest SHA-256: `{report.get('manifest_sha256', '')}`",
        f"- Evidence digest: `{report.get('evidence_digest', '')}`",
        f"- Fixtures: `{report.get('fixture_count', 0)}`",
        f"- Files: `{report.get('file_count', 0)}`",
        "",
        "## Fixture results",
        "",
    ]
    for fixture in report.get("fixtures", []):
        lines.extend(
            [
                f"### `{fixture.get('fixture_id', 'unknown')}`",
                "",
                f"- Status: `{fixture.get('status', 'unknown')}`",
                f"- Source digest: `{fixture.get('source_digest', '')}`",
                f"- Task run hash: `{fixture.get('task_run_hash', '')}`",
                f"- Canonical run hash: `{fixture.get('canonical_run_hash', '')}`",
                f"- Task status: `{fixture.get('task_status', 'not-run')}`",
                "",
            ]
        )
    errors = report.get("errors") or []
    if report.get("error"):
        errors = [*errors, report["error"]]
    if errors:
        lines.extend(["## Errors", ""])
        lines.extend(f"- {error}" for error in errors)
        lines.append("")
    lines.extend(["## Non-claims", ""])
    lines.extend(f"- {claim}" for claim in report.get("non_claims", []))
    return "\n".join(lines).rstrip() + "\n"


def _failure_report(root: Path, manifest: Path, error: Exception) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "gate_id": "external-benchmark-corpus-v1",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_commit": "",
        "manifest_path": manifest.as_posix(),
        "manifest_sha256": "",
        "corpus_id": "unknown",
        "fixture_count": 0,
        "file_count": 0,
        "passed_fixture_count": 0,
        "failed_fixture_count": 0,
        "hash_mismatch_count": 0,
        "size_mismatch_count": 0,
        "passed": False,
        "fixtures": [],
        "errors": [],
        "error": _bounded(str(error)),
        "non_claims": [
            "validation did not complete",
            "repository-controlled reruns are not independent third-party reproduction",
        ],
    }
    with contextlib.suppress(ExternalBenchmarkError, OSError):
        report["source_commit"] = _source_commit(root.resolve(strict=True))
    report["evidence_digest"] = _evidence_digest(report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/external/manifest.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = build_evidence(args.root, args.manifest)
    except (ExternalBenchmarkError, OSError, ValueError, subprocess.SubprocessError) as exc:
        report = _failure_report(args.root, args.manifest, exc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
