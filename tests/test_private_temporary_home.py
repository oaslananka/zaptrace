from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from zaptrace.security.temporary import _remove_private_directory, private_subprocess_environment


def test_existing_home_is_preserved_without_creating_temporary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing_home = tmp_path / "existing-home"
    existing_home.mkdir()

    def fail_mkdtemp(*args: object, **kwargs: object) -> str:
        raise AssertionError("mkdtemp must not run when HOME is already configured")

    monkeypatch.setattr("zaptrace.security.temporary.tempfile.mkdtemp", fail_mkdtemp)

    with private_subprocess_environment(environ={"HOME": str(existing_home)}) as environment:
        assert environment["HOME"] == str(existing_home)

    assert existing_home.is_dir()


def test_missing_home_uses_owned_mode_0700_directory_and_cleans_it(tmp_path: Path) -> None:
    private_home: Path | None = None

    with private_subprocess_environment(environ={}, temporary_parent=tmp_path) as environment:
        private_home = Path(environment["HOME"])
        metadata = private_home.lstat()
        assert private_home.parent == tmp_path
        assert private_home.is_dir()
        assert not private_home.is_symlink()
        assert stat.S_IMODE(metadata.st_mode) == 0o700
        if hasattr(os, "geteuid"):
            assert metadata.st_uid == os.geteuid()

    assert private_home is not None
    assert not private_home.exists()


def test_private_home_is_cleaned_when_subprocess_scope_raises(tmp_path: Path) -> None:
    private_home: Path | None = None

    def fail_inside_private_home() -> None:
        nonlocal private_home
        with private_subprocess_environment(environ={}, temporary_parent=tmp_path) as environment:
            private_home = Path(environment["HOME"])
            (private_home / "artifact.txt").write_text("temporary", encoding="utf-8")
            raise RuntimeError("simulated failure")

    with pytest.raises(RuntimeError, match="simulated failure"):
        fail_inside_private_home()

    assert private_home is not None
    assert not private_home.exists()


def test_explicit_symlink_parent_is_rejected(tmp_path: Path) -> None:
    trusted_parent = tmp_path / "trusted"
    trusted_parent.mkdir()
    symlink_parent = tmp_path / "redirected"
    symlink_parent.symlink_to(trusted_parent, target_is_directory=True)

    with (
        pytest.raises(ValueError, match="symlink"),
        private_subprocess_environment(environ={}, temporary_parent=symlink_parent),
    ):
        pass


def test_precreated_symlink_result_is_rejected_without_following_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    redirected = tmp_path / "pretend-private-home"
    redirected.symlink_to(target, target_is_directory=True)

    monkeypatch.setattr("zaptrace.security.temporary.tempfile.mkdtemp", lambda **_kwargs: str(redirected))

    with (
        pytest.raises(ValueError, match="symlink"),
        private_subprocess_environment(environ={}, temporary_parent=tmp_path),
    ):
        pass

    assert marker.read_text(encoding="utf-8") == "keep"
    assert target.is_dir()
    assert not redirected.exists()


def test_cleanup_does_not_follow_directory_replacement_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target-after-create"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with private_subprocess_environment(environ={}, temporary_parent=tmp_path) as environment:
        private_home = Path(environment["HOME"])
        private_home.rmdir()
        private_home.symlink_to(target, target_is_directory=True)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert target.is_dir()
    assert not private_home.exists()


def test_non_sticky_world_writable_parent_is_rejected(tmp_path: Path) -> None:
    unsafe_parent = tmp_path / "unsafe-parent"
    unsafe_parent.mkdir(mode=0o777)
    unsafe_parent.chmod(0o777)

    with (
        pytest.raises(ValueError, match="sticky bit"),
        private_subprocess_environment(environ={}, temporary_parent=unsafe_parent),
    ):
        pass


def test_missing_temporary_parent_is_rejected(tmp_path: Path) -> None:
    missing_parent = tmp_path / "missing"

    with (
        pytest.raises(ValueError, match="unavailable"),
        private_subprocess_environment(environ={}, temporary_parent=missing_parent),
    ):
        pass


def test_non_directory_temporary_parent_is_rejected(tmp_path: Path) -> None:
    file_parent = tmp_path / "file-parent"
    file_parent.write_text("not a directory", encoding="utf-8")

    with (
        pytest.raises(ValueError, match="must be a directory"),
        private_subprocess_environment(environ={}, temporary_parent=file_parent),
    ):
        pass


def test_unavailable_created_path_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing_home = tmp_path / "not-created"
    monkeypatch.setattr(
        "zaptrace.security.temporary.tempfile.mkdtemp",
        lambda **_kwargs: str(missing_home),
    )

    with (
        pytest.raises(ValueError, match="HOME directory is unavailable"),
        private_subprocess_environment(environ={}, temporary_parent=tmp_path),
    ):
        pass


def test_created_non_directory_path_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_home = tmp_path / "not-a-directory"
    file_home.write_text("file", encoding="utf-8")
    monkeypatch.setattr(
        "zaptrace.security.temporary.tempfile.mkdtemp",
        lambda **_kwargs: str(file_home),
    )

    with (
        pytest.raises(ValueError, match="HOME path must be a directory"),
        private_subprocess_environment(environ={}, temporary_parent=tmp_path),
    ):
        pass

    assert not file_home.exists()


def test_created_directory_outside_parent_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trusted_parent = tmp_path / "trusted"
    trusted_parent.mkdir()
    outside_parent = tmp_path / "outside"
    outside_parent.mkdir()
    escaped_home = outside_parent / "escaped-home"
    escaped_home.mkdir()
    monkeypatch.setattr(
        "zaptrace.security.temporary.tempfile.mkdtemp",
        lambda **_kwargs: str(escaped_home),
    )

    with (
        pytest.raises(ValueError, match="escaped"),
        private_subprocess_environment(environ={}, temporary_parent=trusted_parent),
    ):
        pass

    assert not escaped_home.exists()


def test_mode_enforcement_fails_closed_when_permissions_do_not_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    insecure_home = tmp_path / "insecure-home"
    insecure_home.mkdir(mode=0o755)
    insecure_home.chmod(0o755)
    monkeypatch.setattr(
        "zaptrace.security.temporary.tempfile.mkdtemp",
        lambda **_kwargs: str(insecure_home),
    )
    monkeypatch.setattr(Path, "chmod", lambda _self, _mode: None)

    with (
        pytest.raises(ValueError, match="mode 0700"),
        private_subprocess_environment(environ={}, temporary_parent=tmp_path),
    ):
        pass


def test_owner_mismatch_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not hasattr(os, "geteuid"):
        pytest.skip("POSIX ownership check is unavailable")
    monkeypatch.setattr("zaptrace.security.temporary.os.geteuid", lambda: os.getuid() + 1)

    with (
        pytest.raises(ValueError, match="owned by the current process user"),
        private_subprocess_environment(environ={}, temporary_parent=tmp_path),
    ):
        pass


def test_remove_missing_private_directory_is_idempotent(tmp_path: Path) -> None:
    _remove_private_directory(tmp_path / "already-removed")
