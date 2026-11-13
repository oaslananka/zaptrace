"""Explicit per-user desktop launcher installation for the local Studio GUI.

Never edits desktop settings during package installation, Studio startup,
tests or an ordinary source preview. Only a user's explicit in-app action
invokes install_desktop_shortcut.
"""

from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path
from typing import Any

from zaptrace.studio.engine import StudioInputError


def _launcher_command() -> tuple[Path, str, Path]:
    # Prefer the installed GUI entrypoint on Windows, which has no console.
    scripts = Path(sysconfig.get_path("scripts"))
    installed = scripts / ("zaptrace-studio.exe" if sys.platform == "win32" else "zaptrace-studio")
    workdir = Path(__file__).resolve().parents[2]
    if installed.is_file() and not installed.is_symlink():
        return installed, "", workdir
    python = Path(sys.executable)
    if sys.platform == "win32":
        pythonw = python.with_name("pythonw.exe")
        if pythonw.is_file():
            python = pythonw
    return python, "-m zaptrace.studio.launcher", workdir


def _desktop_quote(value: str) -> str:
    # Desktop Entry Exec expands '%' sequences; prohibit their interpretation.
    if not value or any(character in value for character in ('"', "\\", "\n", "\r", "%", r"\`", "$")):
        raise StudioInputError("The Studio installation path cannot be safely quoted for a desktop launcher")
    return f'"{value}"'


def _guard_owned_desktop_path(output: Path) -> None:
    """An unrelated desktop entry, symlink or hardlink is never edited."""
    if any(part.is_symlink() for part in (output, *output.parents)):
        raise StudioInputError("Desktop launcher path is redirected; no files changed")
    if not output.exists():
        return
    if not output.is_file() or output.stat().st_size > 8192:
        raise StudioInputError("A different desktop launcher already uses this name")
    try:
        content = output.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise StudioInputError("Could not inspect the existing desktop launcher") from exc
    if not content.startswith("[Desktop Entry]\nType=Application\nName=ZapTrace Studio\n") or (
        "X-ZapTrace-Studio-Managed=true\n" not in content
    ):
        raise StudioInputError("An unrelated desktop launcher already uses this name")


def _install_xdg(target: Path, arguments: str, workdir: Path) -> dict[str, Any]:
    xdg = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    output = xdg / "applications" / "zaptrace-studio.desktop"
    _guard_owned_desktop_path(output)
    command = _desktop_quote(str(target)) + (" " + arguments if arguments else "")
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=ZapTrace Studio\n"
        "GenericName=Electronic Circuit Studio\n"
        "Comment=Open a local code-to-circuit workspace\n"
        f"Exec={command}\n"
        f"Path={workdir}\n"
        "Icon=applications-engineering\n"
        "Categories=Development;Electronics;\n"
        "Terminal=false\n"
        "StartupNotify=false\n"
        "X-ZapTrace-Studio-Managed=true\n"
    )
    _desktop_quote(str(workdir))  # reject unsafe desktop-entry path characters
    output.parent.mkdir(parents=True, exist_ok=True)
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output.parent,
            prefix=".zaptrace-studio-",
            delete=False,
        ) as stream:
            temp = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temp.chmod(0o644)
        _guard_owned_desktop_path(output)
        temp.replace(output)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return {"ok": True, "location": "Applications menu", "name": "ZapTrace Studio"}


def _install_windows(target: Path, arguments: str, workdir: Path) -> dict[str, Any]:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise StudioInputError("Windows user Start menu folder is unavailable")
    folder = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    if not folder.is_dir() or folder.is_symlink():
        raise StudioInputError("Windows user Start menu folder is unavailable")
    link = folder / "ZapTrace Studio.lnk"
    # Never overwrite an unknown shortcut (including an earlier manual one).
    if link.exists() or link.is_symlink():
        raise StudioInputError("A ZapTrace Studio shortcut already exists; no changes made")
    # Paths enter the PowerShell WScript COM client via environment variables,
    # never as interpolated command/script text.
    env = dict(os.environ)
    env.update(
        {
            "ZAPTRACE_SHORTCUT_LINK": str(link),
            "ZAPTRACE_SHORTCUT_EXE": str(target),
            "ZAPTRACE_SHORTCUT_ARGS": arguments,
            "ZAPTRACE_SHORTCUT_CWD": str(workdir),
        }
    )
    command = (
        "$ErrorActionPreference='Stop'; "
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:ZAPTRACE_SHORTCUT_LINK); "
        "$s.TargetPath=$env:ZAPTRACE_SHORTCUT_EXE; "
        "$s.Arguments=$env:ZAPTRACE_SHORTCUT_ARGS; "
        "$s.WorkingDirectory=$env:ZAPTRACE_SHORTCUT_CWD; "
        "$s.Description='ZapTrace Studio - local circuit editor'; "
        "$s.Save()"
    )
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StudioInputError("Windows could not create the user Start menu shortcut") from exc
    if not link.is_file():
        raise StudioInputError("Windows did not create a Start menu shortcut")
    return {"ok": True, "location": "Start menu", "name": "ZapTrace Studio"}


def install_desktop_shortcut() -> dict[str, Any]:
    """Install only after a CSRF-authorized, explicit user click in Studio."""
    target, args, workdir = _launcher_command()
    if not target.is_file() or not workdir.is_dir():
        raise StudioInputError("Studio launcher is unavailable on this installation")
    if sys.platform == "win32":
        return _install_windows(target, args, workdir)
    if sys.platform.startswith("linux"):
        return _install_xdg(target, args, workdir)
    raise StudioInputError("Desktop shortcut setup is not yet supported on this system")
