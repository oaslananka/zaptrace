"""Browser-first ZapTrace Studio runtime used by CLI and desktop application launchers."""

from __future__ import annotations

import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path


def serve_studio(
    project: Path | None = None,
    *,
    port: int = 0,
    no_browser: bool = False,
    announce: Callable[[str, str], None] | None = None,
    desktop_mode: bool = False,
) -> None:
    """Run one local Studio, leaving other open projects and sessions untouched."""
    from zaptrace.studio.engine import StudioInputError, demo_project, preview_design
    from zaptrace.studio.http import create_studio_server

    document = project if project is not None else demo_project(Path.home() / "ZapTrace Studio Projects")
    try:
        design = preview_design(document.read_text(encoding="utf-8"))
        if not design["ok"]:
            raise StudioInputError(design["error"])
        server = create_studio_server(document, port=port, desktop_mode=desktop_mode)
    except OSError as exc:
        raise StudioInputError(f"Cannot open Studio project: {exc}") from exc

    url = f"http://127.0.0.1:{server.server_port}/"
    if announce:
        announce(url, str(document.resolve()))
    try:
        if not no_browser:
            webbrowser.open(url)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    """GUI-script entry: double-click from a desktop launcher, no terminal needed."""
    from zaptrace.studio.engine import StudioInputError

    try:
        serve_studio(desktop_mode=True)
    except (StudioInputError, OSError) as exc:
        message = f"ZapTrace Studio could not open.\n\n{exc}"
        try:
            from tkinter import Tk, messagebox

            window = Tk()
            window.withdraw()
            messagebox.showerror("ZapTrace Studio", message, parent=window)
            window.destroy()
        except Exception:
            # tkinter may be absent or lack a display; keep failure explicit
            # when a console exists, without starting an unmanaged process.
            if sys.stderr is not None:
                print(message, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
