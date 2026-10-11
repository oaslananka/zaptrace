#!/usr/bin/env python3
"""Generate an optional system-compatible, local-only Review Studio launcher.

Default output goes into build/. Install to XDG Applications only with explicit
--install, never by running the native test or workspace build.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def desktop_entry(repo: Path) -> str:
    root = repo.resolve()
    script = root / "scripts" / "review_studio_local_launch.sh"
    if not script.is_file():
        raise ValueError("Review Studio local launcher is missing")
    if any(ch in str(root) for ch in ("\n", "\r", "%")):
        raise ValueError("Unsupported path in desktop entry")
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=ZapTrace Review Studio\n"
        "GenericName=KiCad Engineering Review\n"
        "Comment=Inspect source-verified KiCad PCB and schematic evidence on this device\n"
        f'Exec=/bin/bash "{script}"\n'
        f"Path={root}\n"
        "Icon=applications-engineering\n"
        "Categories=Development;Engineering;Electronics;\n"
        "Terminal=true\n"
        "StartupNotify=true\n"
        "Keywords=KiCad;PCB;DRC;ERC;ZapTrace;\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/Review Studio.desktop"))
    parser.add_argument(
        "--install", action="store_true", help="Explicitly install under user XDG applications directory"
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if args.install:
        base = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        output = base / "applications" / "zaptrace-review-studio.desktop"
    else:
        output = args.output
    body = desktop_entry(repo)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body, encoding="utf-8")
    output.chmod(0o755)
    print(f"GENERATED LOCAL DESKTOP ENTRY: {output.resolve()}")
    print("USER DESKTOP MENU CHANGED" if args.install else "NOT INSTALLED: no desktop/applications settings modified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
