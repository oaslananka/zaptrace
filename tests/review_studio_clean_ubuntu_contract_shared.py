"""Shared fail-closed assertions for versioned Ubuntu package proof fixtures."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest


def assert_sha_bound_report(report: Callable[..., Path], files: tuple[Path, ...]) -> None:
    text = report(*files).read_text()
    assert "NOT public GA" in text
    assert "16 -> 16 existing physical DRC" in text
    assert f"PACKAGE_SHA256={hashlib.sha256(files[0].read_bytes()).hexdigest()}" in text
    assert "fabrication approval" not in text.lower()
    assert len([line for line in text.splitlines() if " sha256=" in line]) == 7


def assert_missing_proof_rejected(
    report: Callable[..., Path], files: tuple[Path, ...], index: int, omitted: str
) -> None:
    path = files[index]
    source = path.read_text()
    assert omitted in source
    path.write_text(source.replace(omitted, "UNVERIFIED"))
    with pytest.raises(ValueError, match="not proved"):
        report(*files)
    assert not files[-1].exists()


def assert_old_sha_rejected(report: Callable[..., Path], files: tuple[Path, ...]) -> None:
    modified = files[2].read_text().replace("PACKAGE_SHA256=", "OLD_PACKAGE_SHA256=", 1)
    files[2].write_text(modified)
    with pytest.raises(ValueError, match="not bound to the exact package SHA-256"):
        report(*files)
    assert not files[-1].exists()


def assert_modified_package_and_symlink_rejected(report: Callable[..., Path], files: tuple[Path, ...]) -> None:
    files[0].write_bytes(files[0].read_bytes() + b"changed post-signoff")
    with pytest.raises(ValueError, match="SHA manifest"):
        report(*files)
    with files[0].with_suffix(".sha256").open("w") as checksum:
        digest = hashlib.sha256(files[0].read_bytes()).hexdigest()
        checksum.write(f"{digest}  {files[0].name}\n")
    gate = files[1]
    backup = gate.with_suffix(".original")
    gate.rename(backup)
    gate.symlink_to(backup)
    with pytest.raises(ValueError, match="regular files"):
        report(*files)
