"""Historical KiCad backup acceptance never clobbers unrelated paths."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from review_studio_legacy_011_backup_restore_smoke import write_fresh_backup  # noqa: E402
from review_studio_local_file_guard import read_regular_bytes  # noqa: E402


def test_historical_local_backup_creates_only_fresh_zip(tmp_path: Path) -> None:
    target = tmp_path / "backup.zip"
    write_fresh_backup(target, b"bounded private data")
    assert read_regular_bytes(target, max_size=100) == b"bounded private data"
    with pytest.raises(FileExistsError):
        write_fresh_backup(target, b"modified")
    assert target.read_bytes() == b"bounded private data"


def test_historical_local_backup_rejects_symlink_and_non_zip(tmp_path: Path) -> None:
    source = tmp_path / "protected.bin"
    source.write_bytes(b"preserve original")
    link = tmp_path / "backup.zip"
    link.symlink_to(source)
    with pytest.raises(FileExistsError):
        write_fresh_backup(link, b"replacement")
    assert source.read_bytes() == b"preserve original"
    with pytest.raises(ValueError, match="ZIP"):
        write_fresh_backup(tmp_path / "unsafe.txt", b"new data")
    with pytest.raises(ValueError, match="ZIP"):
        write_fresh_backup(tmp_path / "too-big.zip", b"X" * (34 * 1024 * 1024 + 1))
