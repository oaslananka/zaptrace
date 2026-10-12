#!/usr/bin/python3
"""Standalone, single-user Review Studio application entrypoint for Linux.

No repository, development environment or bundled user PCB is required.
All native KiCad analysis uses the host's KiCad 10 and system pcbnew bindings.
"""

from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from review_studio_local_server import ReviewLocalServer

APP_ID = "zaptrace-review-studio"


def user_workspace() -> Path:
    default = Path.home() / ".local" / "share"
    return Path(os.getenv("XDG_DATA_HOME") or default).expanduser() / APP_ID / "workspace"


def user_session_dir() -> Path:
    default = Path.home() / ".cache"
    # XDG_RUNTIME_DIR is not required: sandbox/private user cache is enough.
    return Path(os.getenv("XDG_CACHE_HOME") or default).expanduser() / APP_ID


def dependencies() -> tuple[list[str], list[str]]:
    passed, failed = [], []
    if sys.executable != "/usr/bin/python3":
        failed.append("Use Ubuntu's /usr/bin/python3 for the native KiCad pcbnew binding")
    else:
        passed.append("System Python /usr/bin/python3")
    cli = shutil.which("kicad-cli")
    if not cli:
        failed.append("Missing kicad-cli; install KiCad 10")
    else:
        try:
            value = subprocess.run(
                [cli, "version"], capture_output=True, text=True, timeout=6, check=True
            ).stdout.strip()
            match = re.match(r"^(\d+)\.(\d+)", value)
            if match and int(match.group(1)) == 10:
                passed.append("Native KiCad CLI " + value)
            else:
                failed.append("This build requires KiCad 10.x; detected " + value[:70])
        except (OSError, subprocess.SubprocessError):
            failed.append("Native KiCad CLI could not start")
    if importlib.util.find_spec("pcbnew") is None:
        failed.append("Missing KiCad pcbnew Python binding in /usr/bin/python3")
    else:
        passed.append("Native pcbnew Python binding installed")
    if shutil.which("xdg-open"):
        passed.append("System browser launcher xdg-open present")
    else:
        failed.append("Missing xdg-open; browser cannot be opened automatically")
    return passed, failed


def open_browser(url: str, *, disabled: bool) -> None:
    if disabled:
        return
    opener = shutil.which("xdg-open")
    if opener:
        try:
            subprocess.Popen(
                [opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
            )
        except OSError:
            print("Browser launcher unavailable. Open manually:", url, flush=True)


def active_port(state_path: Path) -> int | None:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        port = state.get("port")
        if not isinstance(port, int) or not 1 <= port < 65536:
            return None
        req = Request(f"http://127.0.0.1:{port}/api/health", headers={"Host": f"127.0.0.1:{port}"})
        with urlopen(req, timeout=1.2) as response:
            health = json.load(response)
        if health.get("service") == "KiCad native review" and health.get("fabApproved") is False:
            return port
    except (OSError, ValueError, KeyError, json.JSONDecodeError, URLError, TimeoutError):
        pass
    return None


def serve(workspace: Path, session: Path, no_browser: bool) -> int:
    os.umask(0o077)
    if workspace.is_symlink() or session.is_symlink():
        raise ValueError("Refusing symbolic links for private review data or app session directory")
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    session.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = session / "instance.lock"
    state_path = session / "instance.json"
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            port = active_port(state_path)
            if port is None:
                print("Another Review Studio session is starting. Try opening again in a few seconds.", file=sys.stderr)
                return 3
            url = f"http://127.0.0.1:{port}/"
            print("REUSE EXISTING LOCAL SESSION:", url, flush=True)
            open_browser(url, disabled=no_browser)
            return 0
        server = ReviewLocalServer(("127.0.0.1", 0), workspace)
        port = server.server_port
        current_state = {"port": port, "pid": os.getpid(), "version": 1}
        state_path.write_text(json.dumps(current_state) + "\n", encoding="utf-8")
        state_path.chmod(0o600)
        url = f"http://127.0.0.1:{port}/"
        print("ZAPTRACE REVIEW STUDIO:", url, flush=True)
        print("LOCAL ONLY · NO UPLOAD · NO FABRICATION AUTHORIZATION", flush=True)

        def stop(*_args: object) -> None:
            threading.Thread(target=server.shutdown, daemon=True).start()

        previous_int = signal.signal(signal.SIGINT, stop)
        previous_term = signal.signal(signal.SIGTERM, stop)
        try:
            open_browser(url, disabled=no_browser)
            server.serve_forever(poll_interval=0.2)
        finally:
            server.server_close()
            signal.signal(signal.SIGINT, previous_int)
            signal.signal(signal.SIGTERM, previous_term)
            try:
                on_disk = json.loads(state_path.read_text(encoding="utf-8"))
                if on_disk == current_state:
                    state_path.unlink(missing_ok=True)
            except (ValueError, OSError, json.JSONDecodeError):
                pass
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="ZapTrace Review Studio 0.1.10")
    parser.add_argument(
        "--doctor", action="store_true", help="Check KiCad 10 and desktop dependencies without starting"
    )
    parser.add_argument("--no-browser", action="store_true", help="Print the localhost URL without opening a browser")
    args = parser.parse_args()
    passed, failed = dependencies()
    if args.doctor or failed:
        for item in passed:
            print("PASS", item)
        for item in failed:
            print("MISSING", item, file=sys.stderr)
        if args.doctor or failed:
            return 1 if failed else 0
    return serve(user_workspace(), user_session_dir(), args.no_browser)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print("REVIEW STUDIO STARTUP BLOCKED:", exc, file=sys.stderr)
        raise SystemExit(2) from None
