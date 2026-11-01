"""Optional desktop shortcut stays opt-in and never edits user XDG state."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

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
