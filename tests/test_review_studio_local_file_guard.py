"""User-selected review evidence never follows a replaced input file symlink."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.review_studio_local_file_guard import read_regular_bytes


def test_bounded_evidence_reader_accepts_regular_file(tmp_path: Path) -> None:
    evidence = tmp_path / "good.state.json"
    evidence.write_bytes(b'{"source":"local"}')
    assert read_regular_bytes(evidence, max_size=128) == b'{"source":"local"}'


def test_bounded_evidence_reader_rejects_link_directory_and_oversize(tmp_path: Path) -> None:
    evidence = tmp_path / "good.state.json"
    evidence.write_bytes(b"evidence")
    link = tmp_path / "untrusted.state.json"
    link.symlink_to(evidence)
    for invalid in (link, tmp_path, tmp_path / "absent.json"):
        with pytest.raises(ValueError, match="Missing/unsafe or oversized"):
            read_regular_bytes(invalid, max_size=128)
    with pytest.raises(ValueError, match="Missing/unsafe or oversized"):
        read_regular_bytes(evidence, max_size=3)


def test_bounded_evidence_reader_rejects_invalid_size_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        read_regular_bytes(tmp_path / "file.json", max_size=0)
