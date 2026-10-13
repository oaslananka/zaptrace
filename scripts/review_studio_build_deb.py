#!/usr/bin/env python3
"""Build a source-verified Ubuntu 24.04/KiCad 10 .deb, without root or git.

Never includes build/, the developer venv, PCB snapshots or connected user data.
Produces a single uninstallable native local application package.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

VERSION = "0.1.12"
ACCEPTED_LOCAL_VERSIONS = frozenset(
    {
        "0.1.12",
        "0.1.13",
        "0.1.14",
        "0.1.15",
        "0.1.16",
        "0.1.17",
        "0.1.18",
        "0.1.19",
        "0.1.20",
        "0.1.21",
        "0.1.22",
        "0.1.23",
        "0.1.24",
        "0.1.25",
        "0.1.26",
        "0.1.27",
        "0.1.28",
        "0.1.29",
    }
)
PACKAGE = "zaptrace-review-studio"
APP_FILES = (
    "review_studio_app.py",
    "review_studio_local_server.py",
    "review_studio_library.py",
    "review_studio_workspace.py",
    "review_studio_native_kicad.py",
    "review_studio_schematic_eco.py",
    "review_studio_pcb_eco.py",
    "review_studio_change_diff.py",
    "review_studio_change_diff_template.html",
    "review_studio_native_copper_link.py",
    "review_studio_native_copper_bundle.py",
    "review_studio_native_copper_batch.py",
    "review_studio_schematic_pcb_parity.py",
    "review_studio_pcb_eco_template.html",
    "review_studio_workspace_template.html",
    "review_studio_native_template.html",
    "review_studio_native_report_template.html",
    "review_studio_native_report.css",
)
APP_ROOT = Path("usr/lib/zaptrace-review-studio/scripts")


def _write(dest: Path, data: bytes, executable: bool = False) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    dest.chmod(0o755 if executable else 0o644)


def build(root: Path, output_dir: Path, *, version: str = VERSION, epoch: int = 1700000000) -> Path:
    root = root.resolve()
    output_dir = output_dir.resolve()
    # Never ship a server with a native multi-net route endpoint when its
    # subprocess worker is missing. Historical 0.1.11 builds are frozen and
    # their manifests are never rewritten during this separate 0.1.12 RC.
    if (root / "scripts/review_studio_native_copper_batch.py").is_file() and (
        "review_studio_native_copper_batch.py" not in APP_FILES
    ):
        raise ValueError("Native multinet endpoint cannot be packaged without the matching KiCad worker")
    if not (root / "LICENSE").is_file():
        raise ValueError("Source license not present, distribution is blocked")
    if not shutil.which("dpkg-deb") or not shutil.which("desktop-file-validate"):
        raise RuntimeError("Build requires dpkg-deb and desktop-file-validate")
    if version not in ACCEPTED_LOCAL_VERSIONS:
        raise ValueError("Unsupported version for reviewed local release candidate")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{PACKAGE}_{version}_all.deb"
    with tempfile.TemporaryDirectory(prefix="zaptrace-release-") as temporary:
        stage = Path(temporary) / PACKAGE
        for filename in APP_FILES:
            src = root / "scripts" / filename
            if not src.is_file() or src.is_symlink():
                raise ValueError(f"Required packaged app resource missing or unsafe: {filename}")
            contents = src.read_bytes()
            if filename == "review_studio_app.py":
                original = b'"ZapTrace Review Studio 0.1.12"'
                if contents.count(original) != 1:
                    raise ValueError("Packaged application version source is not uniquely identifiable")
                contents = contents.replace(original, f'"ZapTrace Review Studio {version}"'.encode("ascii"))
            elif filename == "review_studio_workspace_template.html" and version != VERSION:
                # Only replace version labels in the candidate's staged UI.
                # Historical 0.1.12 on-disk artefacts and evidence are untouched.
                if contents.count(b"0.1.12") != 6:
                    raise ValueError("Unexpected version labels in local engineering workspace")
                contents = contents.replace(b"0.1.12", version.encode("ascii"))
            _write(stage / APP_ROOT / filename, contents)
        control = (
            f"Package: {PACKAGE}\nVersion: {version}\nSection: electronics\n"
            "Priority: optional\nArchitecture: all\nMaintainer: ZapTrace Contributors\n"
            "Depends: python3 (>= 3.12), kicad (>= 10.0), kicad (<< 11.0), xdg-utils\n"
            "Description: Local KiCad engineering design Review Studio\n"
            " Source-verified, localhost-only PCB and hierarchical schematic reviews.\n"
            " Reports native ERC and DRC, but never authorizes PCB manufacturing.\n"
            " Runtime: Ubuntu 24.04 LTS with native KiCad 10.x installed.\n"
        )
        _write(stage / "DEBIAN" / "control", control.encode("utf-8"))
        launcher = (
            "#!/bin/sh\n"
            "set -eu\n"
            "# The relative package layout also works when extracted without root.\n"
            'APP_BIN=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)\n'
            'exec /usr/bin/python3 -B "$APP_BIN/../lib/zaptrace-review-studio/scripts/review_studio_app.py" "$@"\n'
        )
        _write(stage / "usr/bin" / PACKAGE, launcher.encode("utf-8"), executable=True)
        entry = (
            "[Desktop Entry]\nVersion=1.0\nType=Application\n"
            "Name=ZapTrace Review Studio\nGenericName=KiCad Engineering Review\n"
            "Comment=Open locally verified native KiCad PCB and schematic analyses\n"
            f"Exec={PACKAGE}\nTryExec={PACKAGE}\nIcon=applications-engineering\n"
            "Categories=Development;Science;Electronics;\n"
            "Terminal=false\nStartupNotify=false\n"
            "Keywords=KiCad;PCB;DRC;ERC;Review;EDA;\n"
        )
        desktop = stage / "usr/share/applications" / f"{PACKAGE}.desktop"
        _write(desktop, entry.encode("utf-8"))
        subprocess.run(["desktop-file-validate", str(desktop)], check=True, capture_output=True, timeout=15)
        _write(stage / "usr/share/doc" / PACKAGE / "copyright", (root / "LICENSE").read_bytes())
        _write(
            stage / "usr/share/doc" / PACKAGE / "README.md",
            (root / "scripts" / "REVIEW_STUDIO_DISTRIBUTION.md").read_bytes(),
        )
        # Reproducible fixed epoch, sorted file creation and no personal source
        # data. Python bytecode is intentionally excluded from the archive.
        for path in sorted(stage.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_dir():
                path.chmod(0o755)
            os.utime(path, (epoch, epoch), follow_symlinks=False)
        stage.chmod(0o755)
        os.utime(stage, (epoch, epoch))
        candidate = Path(temporary) / archive.name
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "--build", str(stage), str(candidate)],
            check=True,
            capture_output=True,
            timeout=45,
            env={**os.environ, "SOURCE_DATE_EPOCH": str(epoch)},
        )
        produced = candidate.read_bytes()
        digest = hashlib.sha256(produced).hexdigest()
        manifest = archive.with_suffix(".sha256")
        statement = f"{digest}  {archive.name}\n"
        # Prior QA-accepted packages are immutable. A material content
        # change MUST use a new release version, never overwrite its bytes.
        if archive.exists() and archive.read_bytes() != produced:
            raise ValueError(f"Existing version {version} archive has different bytes; bump version before packaging")
        if manifest.exists() and manifest.read_text(encoding="ascii") != statement:
            raise ValueError(f"Existing version {version} SHA manifest differs; cannot overwrite")
        if not archive.exists():
            archive.write_bytes(produced)
        if not manifest.exists():
            manifest.write_text(statement, encoding="ascii")
    print("BUILT:", archive)
    print("SHA256:", digest)
    print("PACKAGE_BYTES:", archive.stat().st_size)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("build/distribution"))
    parser.add_argument("--candidate-version", choices=sorted(ACCEPTED_LOCAL_VERSIONS), default=VERSION)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.output_dir, version=args.candidate_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
