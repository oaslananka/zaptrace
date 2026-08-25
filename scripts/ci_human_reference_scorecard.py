#!/usr/bin/env python3
"""Validate the human-reference corpus and emit deterministic scorecard evidence."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zaptrace.benchmark.human_reference import (
    HumanReferenceError,
    load_human_reference_attempt,
    load_human_reference_corpus,
    load_human_reference_rubric,
    score_human_reference_attempt,
)

MAX_ERROR_CHARS = 4096
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_OUTPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DEFAULT_MANIFEST = Path("benchmarks/human-reference-corpus/manifest.json")
_DEFAULT_RUBRIC = Path("benchmarks/human-reference-corpus/rubric.json")
_DEFAULT_ATTEMPT = Path("benchmarks/human-reference-corpus/attempt.example.json")


def _bounded(value: str) -> str:
    return value[-MAX_ERROR_CHARS:]


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _validated_input_path(root: Path, raw: Path, *, label: str, allow_temp: bool = False) -> Path:
    root_resolved = root.resolve(strict=True)
    candidate = raw if raw.is_absolute() else root_resolved / raw
    lexical = Path(os.path.abspath(candidate))
    current = lexical
    while True:
        if current.is_symlink():
            raise HumanReferenceError(f"{label} path contains symbolic link: {current.name}")
        if current == root_resolved or current.parent == current:
            break
        current = current.parent
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise HumanReferenceError(f"cannot resolve {label} {raw}: {_bounded(str(exc))}") from exc
    allowed = _is_relative_to(resolved, root_resolved)
    if allow_temp:
        allowed = allowed or _is_relative_to(resolved, Path(tempfile.gettempdir()).resolve(strict=True))
    if not allowed:
        raise HumanReferenceError(f"{label} is outside allowed roots: {raw.name}")
    if not resolved.is_file():
        raise HumanReferenceError(f"{label} is not a regular file: {raw.name}")
    return resolved


class ValidatedOutputPath:
    """One output target proven to remain beneath an allowed existing directory."""

    __slots__ = ("allowed_root", "relative_parent_parts", "filename")

    def __init__(self, *, allowed_root: Path, relative_parent_parts: tuple[str, ...], filename: str) -> None:
        self.allowed_root = allowed_root
        self.relative_parent_parts = relative_parent_parts
        self.filename = filename

    @property
    def parent(self) -> Path:
        return self.allowed_root.joinpath(*self.relative_parent_parts)

    @property
    def path(self) -> Path:
        return self.parent / self.filename


def _resolve_output_path(root: Path, raw: Path) -> ValidatedOutputPath:
    root_resolved = root.resolve(strict=True)
    if ".." in raw.parts:
        raise ValueError(f"output path contains traversal components: {raw.name}")
    filename = raw.name
    if not _OUTPUT_NAME_RE.fullmatch(filename):
        raise ValueError(f"output filename is not allowed: {filename}")

    candidate = raw if raw.is_absolute() else root_resolved / raw
    lexical = Path(os.path.abspath(candidate))
    parent_lexical = lexical.parent
    allowed_roots = (root_resolved, Path(tempfile.gettempdir()).resolve(strict=True))
    allowed_root = next((allowed for allowed in allowed_roots if parent_lexical.is_relative_to(allowed)), None)
    if allowed_root is None:
        raise ValueError(f"output path is outside allowed roots: {filename}")

    current = parent_lexical
    while current != allowed_root:
        if current.is_symlink():
            raise ValueError(f"output path contains symbolic link: {current.name}")
        current = current.parent
    if lexical.is_symlink():
        raise ValueError(f"output path contains symbolic link: {filename}")

    try:
        parent_resolved = parent_lexical.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"output parent cannot be resolved: {parent_lexical.name}") from exc
    if not parent_resolved.is_dir() or not parent_resolved.is_relative_to(allowed_root):
        raise ValueError(f"output parent is outside allowed roots: {parent_lexical.name}")
    if lexical.exists() and not lexical.is_file():
        raise ValueError(f"output path is not a regular file: {filename}")

    relative_parent = parent_resolved.relative_to(allowed_root)
    return ValidatedOutputPath(
        allowed_root=allowed_root,
        relative_parent_parts=relative_parent.parts,
        filename=filename,
    )


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _open_validated_parent(target: ValidatedOutputPath) -> int:
    directory_fd = os.open(target.allowed_root, _directory_open_flags())
    try:
        for part in target.relative_parent_parts:
            next_fd = os.open(part, _directory_open_flags(), dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
    except OSError:
        os.close(directory_fd)
        raise
    return directory_fd


def _write_text_safely(target: ValidatedOutputPath, content: str) -> None:
    """Atomically replace one validated output without following symlinks."""
    parent_path = target.allowed_root
    for part in target.relative_parent_parts:
        parent_path = parent_path / part

    if os.name != "posix":
        parent_path.mkdir(parents=True, exist_ok=True)
        destination = parent_path / target.filename
        temporary_path = parent_path / f".zaptrace-{secrets.token_hex(12)}.tmp"
        try:
            temporary_path.write_text(content, encoding="utf-8", newline="\n")
            temporary_path.replace(destination)
        except OSError as exc:
            raise HumanReferenceError(f"cannot safely write output {target.filename}: {_bounded(str(exc))}") from exc
        finally:
            if temporary_path.exists():
                with contextlib.suppress(OSError):
                    temporary_path.unlink()
        return

    directory_fd = -1
    temporary_name = f".zaptrace-{secrets.token_hex(12)}.tmp"
    temporary_created = False
    try:
        directory_fd = _open_validated_parent(target)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(temporary_name, flags, 0o600, dir_fd=directory_fd)
        temporary_created = True
        with os.fdopen(file_fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target.filename, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        temporary_created = False
    except OSError as exc:
        raise HumanReferenceError(f"cannot safely write output {target.filename}: {_bounded(str(exc))}") from exc
    finally:
        if temporary_created and directory_fd >= 0:
            with contextlib.suppress(OSError):
                os.unlink(temporary_name, dir_fd=directory_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _display_path(root: Path, path: Path) -> str:
    root_resolved = root.resolve(strict=True)
    if _is_relative_to(path, root_resolved):
        return path.relative_to(root_resolved).as_posix()
    return path.name


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        raise HumanReferenceError(f"cannot resolve source commit: {_bounded(detail)}")
    return commit


def _canonical_digest_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _canonical_digest_value(item)
            for key, item in sorted(value.items())
            if key not in {"generated_at", "evidence_digest"}
        }
    if isinstance(value, list):
        return [_canonical_digest_value(item) for item in value]
    return value


def _evidence_digest(report: dict[str, Any]) -> str:
    payload = json.dumps(_canonical_digest_value(report), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def build_evidence(
    root: str | Path,
    manifest: str | Path,
    rubric: str | Path,
    attempt: str | Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build source-identity-bound corpus, rubric, attempt, and scorecard evidence."""
    root_path = Path(root).resolve(strict=True)
    manifest_path = _validated_input_path(root_path, Path(manifest), label="human reference manifest")
    rubric_path = _validated_input_path(root_path, Path(rubric), label="human reference rubric")
    attempt_path = _validated_input_path(root_path, Path(attempt), label="human reference attempt", allow_temp=True)

    corpus = load_human_reference_corpus(manifest_path)
    rubric_model = load_human_reference_rubric(rubric_path)
    attempt_model = load_human_reference_attempt(attempt_path)
    expected_rubric_path = _display_path(root_path, rubric_path)
    if corpus.rubric_path != expected_rubric_path:
        raise HumanReferenceError(
            f"corpus rubric_path mismatch: expected {corpus.rubric_path}, observed {expected_rubric_path}"
        )

    timestamp = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    scorecard = score_human_reference_attempt(corpus, rubric_model, attempt_model, generated_at=timestamp)
    reviewed_count = sum(reference.zaptrace_review_status == "reviewed" for reference in corpus.references)
    pending_count = sum(reference.zaptrace_review_status == "pending-human-review" for reference in corpus.references)
    passed = (
        len(corpus.references) >= 6
        and len(rubric_model.dimensions) == 8
        and scorecard.overall_status == "blocked"
        and scorecard.total_score == 0
        and reviewed_count == 0
        and pending_count == len(corpus.references)
    )
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "gate_id": "human-reference-scorecard-v1",
        "generated_at": timestamp,
        "source_commit": _source_commit(root_path),
        "manifest_path": _display_path(root_path, manifest_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "rubric_path": _display_path(root_path, rubric_path),
        "rubric_sha256": _sha256_file(rubric_path),
        "attempt_path": _display_path(root_path, attempt_path),
        "attempt_sha256": _sha256_file(attempt_path),
        "corpus_id": corpus.corpus_id,
        "corpus_version": corpus.corpus_version,
        "rubric_id": rubric_model.rubric_id,
        "rubric_version": rubric_model.rubric_version,
        "reference_count": len(corpus.references),
        "rubric_dimension_count": len(rubric_model.dimensions),
        "reviewed_reference_count": reviewed_count,
        "pending_review_reference_count": pending_count,
        "example_scorecard_status": scorecard.overall_status,
        "example_total_score": scorecard.total_score,
        "passed": passed,
        "scorecard": scorecard.model_dump(mode="json"),
        "errors": [] if passed else ["committed example or review-state invariants did not match the gate contract"],
        "non_claims": [
            *scorecard.non_claims,
            "CI success validates contracts and determinism; it does not approve the example attempt",
            "no qualified ZapTrace human review is recorded for the initial corpus",
        ],
    }
    report["evidence_digest"] = _evidence_digest(report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render bounded human-readable scorecard gate evidence."""
    status = "PASS" if report.get("passed") else "FAIL"
    lines = [
        "# Human reference scorecard evidence",
        "",
        f"- Contract status: **{status}**",
        f"- Source commit: `{report.get('source_commit', '')}`",
        f"- Manifest SHA-256: `{report.get('manifest_sha256', '')}`",
        f"- Rubric SHA-256: `{report.get('rubric_sha256', '')}`",
        f"- Attempt SHA-256: `{report.get('attempt_sha256', '')}`",
        f"- Evidence digest: `{report.get('evidence_digest', '')}`",
        f"- Human-engineered upstream references: `{report.get('reference_count', 0)}`",
        f"- Rubric dimensions: `{report.get('rubric_dimension_count', 0)}`",
        f"- Pending human review: `{report.get('pending_review_reference_count', 0)}`",
        f"- Example scorecard is blocked: `{report.get('example_scorecard_status') == 'blocked'}`",
        f"- Example total score: `{report.get('example_total_score', 0)}`",
        "",
    ]
    errors = report.get("errors") or []
    if report.get("error"):
        errors = [*errors, report["error"]]
    if errors:
        lines.extend(["## Errors", "", *(f"- {error}" for error in errors), ""])
    lines.extend(["## Non-claims", "", *(f"- {claim}" for claim in report.get("non_claims", []))])
    return "\n".join(lines).rstrip() + "\n"


def _failure_report(root: Path, manifest: Path, rubric: Path, attempt: Path, error: Exception) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "gate_id": "human-reference-scorecard-v1",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_commit": "",
        "manifest_path": manifest.name,
        "manifest_sha256": "",
        "rubric_path": rubric.name,
        "rubric_sha256": "",
        "attempt_path": attempt.name,
        "attempt_sha256": "",
        "corpus_id": "unknown",
        "corpus_version": "unknown",
        "rubric_id": "unknown",
        "rubric_version": "unknown",
        "reference_count": 0,
        "rubric_dimension_count": 0,
        "reviewed_reference_count": 0,
        "pending_review_reference_count": 0,
        "example_scorecard_status": "blocked",
        "example_total_score": 0,
        "passed": False,
        "scorecard": None,
        "errors": [],
        "error": _bounded(str(error)),
        "non_claims": [
            "validation did not complete",
            "CI failure evidence is not a qualified engineering review",
        ],
    }
    with contextlib.suppress(HumanReferenceError, OSError):
        report["source_commit"] = _source_commit(root.resolve(strict=True))
    report["evidence_digest"] = _evidence_digest(report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path, default=_DEFAULT_MANIFEST)
    parser.add_argument("--rubric", type=Path, default=_DEFAULT_RUBRIC)
    parser.add_argument("--attempt", type=Path, default=_DEFAULT_ATTEMPT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve(strict=True)
    output = _resolve_output_path(root, args.output)
    markdown = _resolve_output_path(root, args.markdown)
    try:
        report = build_evidence(root, args.manifest, args.rubric, args.attempt)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report = _failure_report(root, args.manifest, args.rubric, args.attempt, exc)
    _write_text_safely(output, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write_text_safely(markdown, render_markdown(report))
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
