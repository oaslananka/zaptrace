"""Resolve the package version without a duplicated source-tree fallback."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from zaptrace.versioning import read_project_version

_DISTRIBUTION_NAME = "zaptrace-eda"


def resolve_runtime_version(source_root: str | Path | None = None) -> str:
    """Prefer the checked-out source version, then installed distribution metadata."""
    resolved_root = Path(source_root).resolve() if source_root is not None else Path(__file__).resolve().parents[1]
    if (resolved_root / "pyproject.toml").is_file():
        return read_project_version(resolved_root)
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return "0.0.0.dev0"


__version__ = resolve_runtime_version()
