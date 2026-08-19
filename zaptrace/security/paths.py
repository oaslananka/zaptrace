"""Contained filesystem path resolution for trusted repository boundaries."""

from __future__ import annotations

from pathlib import Path


def resolve_trusted_path(
    value: str | Path,
    *,
    trusted_root: str | Path,
    label: str,
    require_child: bool = False,
) -> Path:
    """Resolve *value* inside *trusted_root* and reject traversal or symlink escapes."""
    root = Path(trusted_root).resolve(strict=True)
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes repository root: {value}") from exc
    if require_child and resolved == root:
        raise ValueError(f"{label} must be a child of the repository root")
    return resolved
