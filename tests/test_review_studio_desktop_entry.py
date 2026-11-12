"""Optional desktop shortcut stays opt-in and never edits user XDG state."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/review_studio_desktop_entry.py"
spec = importlib.util.spec_from_file_location("review_desktop_entry", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_local_desktop_entry_opens_only_repo_launcher(tmp_path: Path) -> None:
    repo = SCRIPT.parents[1]
    body = module.desktop_entry(repo)
    assert "Name=ZapTrace Review Studio" in body
    assert "Terminal=true" in body
    assert 'Exec=/bin/bash "' + str(repo) + '/scripts/review_studio_local_launch.sh"' in body
    assert "Path=" + str(repo) in body
    assert "Icon=applications-engineering" in body
    assert "https://" not in body and "curl " not in body
    if validator := shutil.which("desktop-file-validate"):
        output = tmp_path / "Review Studio.desktop"
        output.write_text(body)
        subprocess.run([validator, str(output)], check=True, capture_output=True, timeout=4)


def test_user_desktop_settings_are_never_modified_by_normal_build() -> None:
    source = SCRIPT.read_text()
    assert "if args.install:" in source
    assert "else:" in source
    assert 'default=Path("build/Review Studio.desktop")' in source
    assert "NOT INSTALLED" in source


def test_desktop_entry_rejects_aliased_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Even explicit CLI output must not write outside a symlinked directory."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "user-data.txt").write_text("owner data")
    alias = tmp_path / "link"
    alias.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr("sys.argv", ["desktop", "--output", str(alias / "launch.desktop")])
    with pytest.raises(ValueError, match="Unsafe desktop entry output"):
        module.main()
    assert [p.name for p in outside.iterdir()] == ["user-data.txt"]


def test_desktop_entry_preserves_unrelated_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "notes.desktop"
    target.write_text("This file belongs to a user.\n")
    monkeypatch.setattr("sys.argv", ["desktop", "--output", str(target)])
    with pytest.raises(ValueError, match="Unrecognized desktop entry"):
        module.main()
    assert target.read_text() == "This file belongs to a user.\n"


def test_desktop_entry_replaces_owned_hardlink_without_editing_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = SCRIPT.parents[1]
    old_entry = module.desktop_entry(repo).replace(
        "Comment=Inspect source-verified", "Comment=Older source-verified", 1
    )
    original = tmp_path / "other-owned.desktop"
    original.write_text(old_entry)
    target = tmp_path / "launcher.desktop"
    target.hardlink_to(original)
    monkeypatch.setattr("sys.argv", ["desktop", "--output", str(target)])
    assert module.main() == 0
    assert target.read_text() == module.desktop_entry(repo)
    assert original.read_text() == old_entry


def test_desktop_entry_rejects_shell_quote_inside_repository_path(tmp_path: Path) -> None:
    unsafe = tmp_path / 'unsafe"repository'
    (unsafe / "scripts").mkdir(parents=True)
    (unsafe / "scripts" / "review_studio_local_launch.sh").write_text("#!/bin/sh\n")
    with pytest.raises(ValueError, match="Unsupported path"):
        module.desktop_entry(unsafe)


@pytest.mark.parametrize("case", ["symlink_leaf", "parent_reference"])
def test_desktop_entry_blocks_other_indirect_output_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    original = tmp_path / "original-user-data.txt"
    original.write_text("do not overwrite")
    output = tmp_path / "launcher.desktop"
    if case == "symlink_leaf":
        output.symlink_to(original)
    else:
        (tmp_path / "nested").mkdir()
        output = tmp_path / "nested" / ".." / "launcher.desktop"
    monkeypatch.setattr("sys.argv", ["desktop", "--output", str(output)])
    with pytest.raises(ValueError, match="Unsafe desktop entry output"):
        module.main()
    assert original.read_text() == "do not overwrite"


def test_desktop_entry_install_stays_opt_in_and_can_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The existing explicit XDG install and repeat-update path still works."""
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.setattr("sys.argv", ["desktop", "--install"])
    target = xdg / "applications" / "zaptrace-review-studio.desktop"
    assert module.main() == 0
    assert target.read_text() == module.desktop_entry(SCRIPT.parents[1])
    assert target.stat().st_mode & 0o111 == 0o111
    assert module.main() == 0
    assert target.read_text() == module.desktop_entry(SCRIPT.parents[1])
