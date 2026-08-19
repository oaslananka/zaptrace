"""Private temporary HOME environments for external tool execution."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

_PRIVATE_HOME_PREFIX = "zaptrace-private-home-"
_PRIVATE_MODE = 0o700


def _trusted_temporary_parent(temporary_parent: Path | None) -> Path:
    raw_parent = Path(tempfile.gettempdir()) if temporary_parent is None else temporary_parent
    if temporary_parent is not None and raw_parent.is_symlink():
        raise ValueError("temporary parent must not be a symlink")
    try:
        parent = raw_parent.resolve(strict=True)
    except OSError as exc:
        raise ValueError("temporary parent is unavailable") from exc
    metadata = parent.stat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("temporary parent must be a directory")
    mode = stat.S_IMODE(metadata.st_mode)
    if mode & stat.S_IWOTH and not mode & stat.S_ISVTX:
        raise ValueError("world-writable temporary parent must use the sticky bit")
    return parent


def _validate_private_directory(path: Path, parent: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError("private HOME directory is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError("private HOME directory must not be a symlink")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("private HOME path must be a directory")
    if path.parent.resolve(strict=True) != parent:
        raise ValueError("private HOME directory escaped the trusted temporary parent")

    path.chmod(_PRIVATE_MODE)
    metadata = path.lstat()
    if stat.S_IMODE(metadata.st_mode) != _PRIVATE_MODE:
        raise ValueError("private HOME directory must use mode 0700")
    if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
        raise ValueError("private HOME directory must be owned by the current process user")


def _remove_private_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        path.unlink(missing_ok=True)
        return
    shutil.rmtree(path)


@contextmanager
def private_subprocess_environment(
    *,
    environ: Mapping[str, str] | None = None,
    temporary_parent: Path | None = None,
) -> Iterator[dict[str, str]]:
    """Yield a subprocess environment with a private HOME when HOME is absent.

    Existing HOME values are preserved. A missing or blank HOME is replaced by
    an owned mode-0700 directory created atomically below a validated temporary
    parent and removed when the subprocess scope exits.
    """

    environment = dict(os.environ if environ is None else environ)
    if environment.get("HOME", "").strip():
        yield environment
        return

    parent = _trusted_temporary_parent(temporary_parent)
    private_home = Path(tempfile.mkdtemp(prefix=_PRIVATE_HOME_PREFIX, dir=str(parent)))
    try:
        _validate_private_directory(private_home, parent)
        environment["HOME"] = str(private_home)
        yield environment
    finally:
        _remove_private_directory(private_home)
