"""Shared filename policy for generated manufacturing artifacts."""

from __future__ import annotations

import re
from pathlib import Path

_SAFE_EXPORT_STEM_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_export_stem(value: str, *, fallback: str = "board") -> str:
    """Return a single safe filename stem for caller-provided export metadata.

    The returned value contains no path separators, leading dots, or empty
    components. It is suitable only as a filename stem beneath an already
    trusted and validated output directory.
    """
    cleaned = _SAFE_EXPORT_STEM_RE.sub("_", value.strip()).strip("._-")
    return cleaned[:128] or fallback


def resolve_output_artifact(
    output_dir: Path,
    stem: str,
    suffix: str,
    *,
    fallback: str = "board",
) -> Path:
    """Return a canonical artifact path beneath a trusted output directory.

    ``output_dir`` must already have passed the caller's workspace policy. The
    helper sanitizes request-derived metadata into one filename component,
    rejects path-like suffixes, and returns the canonical path so later symlink
    swaps cannot redirect a write through the original directory alias.
    """
    if not suffix.startswith(".") or suffix in {".", ".."} or "/" in suffix or "\\" in suffix:
        raise ValueError("artifact suffix must be a single filename suffix")

    # Sonar S2083 and CodeQL py/path-injection: the root is trusted by
    # contract; request-derived data is reduced to one separator-free
    # filename component before path creation.
    # codeql[py/path-injection]
    root = output_dir.resolve()  # NOSONAR
    # codeql[py/path-injection]
    root.mkdir(parents=True, exist_ok=True)  # NOSONAR
    candidate = root / f"{safe_export_stem(stem, fallback=fallback)}{suffix}"  # NOSONAR
    # codeql[py/path-injection]
    resolved = candidate.resolve()  # NOSONAR
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"artifact path escapes output directory: {stem!r}") from exc
    return resolved
