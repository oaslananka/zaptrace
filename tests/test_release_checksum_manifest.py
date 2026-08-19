from __future__ import annotations

from pathlib import Path

import pytest

from scripts import generate_checksum_manifest
from scripts.generate_checksum_manifest import (
    _resolve_manifest_cli_path,
    build_manifest,
    main,
    sha256_file,
    write_manifest,
)


def test_checksum_manifest_is_sorted_and_excludes_itself(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "release-artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "b.whl").write_text("b", encoding="utf-8")
    (artifact_dir / "a.tar.gz").write_text("a", encoding="utf-8")
    output = artifact_dir / "SHA256SUMS"

    write_manifest(artifact_dir, output)

    lines = output.read_text(encoding="utf-8").splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == ["a.tar.gz", "b.whl"]
    assert all("SHA256SUMS" not in line for line in lines)
    assert lines[0].startswith(sha256_file(artifact_dir / "a.tar.gz"))


def test_empty_manifest_is_empty(tmp_path: Path) -> None:
    assert build_manifest(tmp_path, tmp_path / "SHA256SUMS") == ""


def test_resolve_manifest_cli_path_rejects_parent_escape(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()

    with pytest.raises(ValueError, match="escapes trusted root"):
        _resolve_manifest_cli_path("../outside", trusted_root=trusted, field="artifact_dir")


def test_resolve_manifest_cli_path_rejects_symlink_escape(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = trusted / "release-artifacts"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes trusted root"):
        _resolve_manifest_cli_path(link, trusted_root=trusted, field="artifact_dir")


def test_main_rejects_output_outside_artifact_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_dir = tmp_path / "release-artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "package.whl").write_text("wheel", encoding="utf-8")
    monkeypatch.setattr(generate_checksum_manifest, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(["release-artifacts", "--output", "outside/SHA256SUMS"])

    assert exc_info.value.code == 2
    assert not (tmp_path / "outside" / "SHA256SUMS").exists()


def test_main_defaults_manifest_inside_artifact_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_dir = tmp_path / "release-artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "package.whl").write_text("wheel", encoding="utf-8")
    monkeypatch.setattr(generate_checksum_manifest, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["release-artifacts"]) == 0
    assert (artifact_dir / "SHA256SUMS").is_file()
    assert not (tmp_path / "SHA256SUMS").exists()
