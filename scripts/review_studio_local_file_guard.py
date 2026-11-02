"""Fail-closed bounded reads for user-selected local Review Studio evidence files."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def read_regular_bytes(path: Path, *, max_size: int) -> bytes:
    """Open one existing regular file without following a substituted leaf symlink."""
    if max_size <= 0:
        raise ValueError("Evidence file size limit must be positive")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_size:
                raise ValueError("Missing/unsafe or oversized review input")
            content = stream.read(max_size + 1)
            if len(content) > max_size:
                raise ValueError("Missing/unsafe or oversized review input")
            return content
    except (OSError, OverflowError) as exc:
        raise ValueError("Missing/unsafe or oversized review input") from exc
