"""Per-user, opt-in Studio launcher and actual local HTTP desktop-session gates."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from zaptrace.studio import desktop
from zaptrace.studio.http import create_studio_server

FIXTURE = Path(__file__).parents[1] / "examples/esp32_i2c_sensor_node/design.yaml"


def _post(base: str, path: str, payload: dict, token: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json", "Origin": base[:-1]}
    if token is not None:
        headers["X-ZapTrace-Studio-Token"] = token
    request = Request(
        base + path,
        headers=headers,
        data=json.dumps(payload).encode(),
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.loads(error.read())


def test_launcher_is_not_installed_until_explicit_browser_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    source = tmp_path / "source.yaml"
    source.write_bytes(FIXTURE.read_bytes())
    studio = create_studio_server(source)
    worker = threading.Thread(target=studio.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{studio.server_port}/"
    desktop_file = tmp_path / "xdg" / "applications" / "zaptrace-studio.desktop"
    try:
        status, original = _post(base, "api/desktop/shortcut", {})
        assert status == 403
        assert original["error"]["code"] == "WRITE_DENIED"
        assert not desktop_file.exists()
        status, result = _post(base, "api/desktop/shortcut", {}, studio.session_token)
        assert status == 200
        assert result["location"] == "Applications menu"
        installed = desktop_file.read_text()
        assert installed.startswith("[Desktop Entry]\nType=Application\nName=ZapTrace Studio\n")
        assert "X-ZapTrace-Studio-Managed=true" in installed
        assert "Terminal=false" in installed
        assert "Exec=" in installed and "python" in installed
        assert "Path=" in installed
        if validator := shutil.which("desktop-file-validate"):
            subprocess.run([validator, str(desktop_file)], check=True, capture_output=True, timeout=8)
        status, _ = _post(base, "api/desktop/shortcut", {}, studio.session_token)
        assert status == 200
        assert desktop_file.read_text() == installed
        assert json.load(urlopen(base + "api/source", timeout=10))["desktop_mode"] is False
        status, wrong_mode = _post(base, "api/desktop/quit", {}, studio.session_token)
        assert status == 400
        assert "not running as a desktop" in wrong_mode["error"]["message"]
    finally:
        studio.shutdown()
        studio.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


@pytest.mark.parametrize("case", ["unrelated", "symlink_leaf", "symlink_directory"])
def test_launcher_does_not_overwrite_user_files_or_follow_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    xdg = tmp_path / "xdg"
    folder = xdg / "applications"
    folder.mkdir(parents=True)
    output = folder / "zaptrace-studio.desktop"
    protected = tmp_path / "owner-file.txt"
    protected.write_text("My unrelated shortcut/data")
    if case == "unrelated":
        output.write_text("Unrelated desktop entry")
    elif case == "symlink_leaf":
        output.symlink_to(protected)
    else:
        folder.rmdir()
        folder.symlink_to(tmp_path)
        output = folder / "zaptrace-studio.desktop"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    with pytest.raises(desktop.StudioInputError):
        desktop.install_desktop_shortcut()
    assert protected.read_text() == "My unrelated shortcut/data"
    if case == "unrelated":
        assert output.read_text() == "Unrelated desktop entry"


def test_windows_shortcut_uses_native_com_without_spawned_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appdata = tmp_path / "app data"
    location = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    location.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    target = tmp_path / "bin with spaces" / "pythonw.exe"
    target.parent.mkdir()
    target.write_bytes(b"mock executable")
    cwd = tmp_path / "source"
    cwd.mkdir()
    observed: list[tuple[Path, Path, str, Path]] = []

    def fake_com(link: Path, executable: Path, args: str, workdir: Path) -> None:
        observed.append((link, executable, args, workdir))
        assert executable == target
        assert args == "-m zaptrace.studio.launcher"
        assert workdir == cwd
        assert link.parent == location
        link.write_text("test-created native shortcut")

    monkeypatch.setattr(desktop, "_save_windows_shell_link", fake_com)
    assert desktop._install_windows(target, "-m zaptrace.studio.launcher", cwd)["location"] == "Start menu"
    assert len(observed) == 1
    with pytest.raises(desktop.StudioInputError, match="already exists"):
        desktop._install_windows(target, "-m zaptrace.studio.launcher", cwd)


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows ShellLink COM")
def test_real_windows_shell_link_can_be_created_without_shell(tmp_path: Path) -> None:
    """Optional Windows runner integration: no extra provider or dependency."""
    target = Path(sys.executable).with_name("pythonw.exe")
    if not target.is_file():
        pytest.skip("Windows GUI interpreter not installed")
    link = tmp_path / "ZapTrace Studio.lnk"
    desktop._save_windows_shell_link(link, target, "-m zaptrace.studio.launcher", tmp_path)
    assert link.is_file()
    assert link.stat().st_size > 100


def test_pythonw_without_standard_streams_can_serve_source_and_static_ui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows GUI pythonw.exe has no stderr; every HTTP route must still respond."""
    source = tmp_path / "design.yaml"
    source.write_bytes(FIXTURE.read_bytes())
    server = create_studio_server(source, desktop_mode=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}/"
    try:
        with monkeypatch.context() as patch:
            patch.setattr(sys, "stdout", None)
            patch.setattr(sys, "stderr", None)
            with urlopen(base, timeout=10) as response:
                assert response.status == 200
                assert b"ZapTrace" in response.read()
            with urlopen(base + "studio.js", timeout=10) as response:
                assert response.status == 200
                assert b"recent-projects" in response.read()
            with urlopen(base + "api/source", timeout=10) as response:
                result = json.load(response)
                assert result["desktop_mode"] is True
                assert result["source"] == source.read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


def test_desktop_studio_can_quit_and_cleanly_stop_server(tmp_path: Path) -> None:
    source = tmp_path / "original.yaml"
    source.write_bytes(FIXTURE.read_bytes())
    studio = create_studio_server(source, desktop_mode=True)
    worker = threading.Thread(target=studio.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{studio.server_port}/"
    try:
        assert json.load(urlopen(base + "api/source", timeout=10))["desktop_mode"] is True
        status, result = _post(base, "api/desktop/quit", {}, studio.session_token)
        assert status == 200
        assert result == {"ok": True, "closed": True}
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert source.read_bytes() == FIXTURE.read_bytes()
    finally:
        studio.server_close()


def test_cli_launch_keeps_existing_no_browser_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    from click.testing import CliRunner

    from zaptrace.cli.main import cli

    observed: list[tuple[Path | None, int, bool, bool]] = []

    def fake_serve(
        project: Path | None = None,
        *,
        port: int = 0,
        no_browser: bool = False,
        announce: object = None,
        desktop_mode: bool = False,
    ) -> None:
        observed.append((project, port, no_browser, desktop_mode))

    monkeypatch.setattr("zaptrace.studio.launcher.serve_studio", fake_serve)
    result = CliRunner().invoke(cli, ["studio", "--no-browser", "--port", "18764"])
    assert result.exit_code == 0, result.output
    assert observed == [(None, 18764, True, False)]


def test_gui_entry_calls_local_studio_without_console(monkeypatch: pytest.MonkeyPatch) -> None:
    from zaptrace.studio import launcher

    observed: list[bool] = []

    def fake_serve(*args: object, desktop_mode: bool = False, **kwargs: object) -> None:
        observed.append(desktop_mode)

    monkeypatch.setattr(launcher, "serve_studio", fake_serve)
    launcher.main()
    assert observed == [True]


def test_installed_package_registers_clickable_gui_entrypoint() -> None:
    import tomllib

    settings = tomllib.loads((FIXTURE.parents[2] / "pyproject.toml").read_text())
    assert settings["project"]["gui-scripts"]["zaptrace-studio"] == "zaptrace.studio.launcher:main"
    assert sys.version_info >= (3, 12)
