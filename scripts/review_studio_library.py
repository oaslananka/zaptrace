#!/usr/bin/env python3
"""Explicit local-only review export/forget lifecycle with strict ownership.

External source checkout, manually registered outside reviews and package files
can never be removed through this module. Only an imported UUID-owned review
and its UUID-owned selected-source staging directory qualify for deletion.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import zipfile
from pathlib import Path

from review_studio_workspace import _read_projects, managed_paths, render_workspace

MAX_EXPORT_BYTES = 80 * 1024 * 1024
MAX_EXPORT_FILES = 350
CONFIRM = "DELETE_LOCAL_REVIEW_AND_STAGED_COPIES"
HEX = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _record(workspace: Path, key: str, expected_sha: str) -> tuple[list[dict], dict, Path, Path]:
    if (
        not isinstance(key, str)
        or not ID.fullmatch(key)
        or not isinstance(expected_sha, str)
        or not HEX.fullmatch(expected_sha)
    ):
        raise ValueError("Invalid source review identification")
    manifest = workspace / "projects.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("projects"), list):
        raise ValueError("Review library manifest is invalid")
    rows = data["projects"]
    matching = [row for row in rows if isinstance(row, dict) and row.get("id") == key]
    if len(matching) != 1 or matching[0].get("sha") != expected_sha:
        raise ValueError("Registered review or selected source checksum changed")
    # Verify that the current evidence and context still matches the registry.
    _read_projects(workspace)
    review = Path(matching[0]["review"])
    paths = managed_paths(workspace, review)
    if paths is None:
        raise ValueError("Only completed, locally imported native reviews may be managed here")
    return rows, matching[0], paths[0], paths[1]


def export_review(workspace: Path, key: str, sha: str) -> bytes:
    """ZIP of one verified native review and its explicitly selected source copies."""
    _, row, review, staged = _record(workspace, key, sha)
    source = staged / "source.kicad_pcb"
    if source.is_symlink() or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != sha:
        raise ValueError("Selected source PCB bytes differ from the registered KiCad review")
    items: list[tuple[str, Path]] = []
    size = 0
    for label, base in (("review", review), ("selected-input-copies", staged)):
        for path in sorted(base.rglob("*")):
            if path.is_symlink():
                raise ValueError("Unsafe symbolic link in a local review backup")
            relative = path.relative_to(base).as_posix()
            if label == "selected-input-copies":
                canonical = {"source.kicad_pcb", "source.kicad_sch", "source.kicad_pro", "source.kicad_dru"}
                if relative not in canonical:
                    if relative == "source.kicad_prl":
                        # KiCad generates this potentially privacy-sensitive local
                        # GUI/session state file. It is NOT a selected source.
                        continue
                    from review_studio_workspace import safe_sheet_path

                    try:
                        safe_sheet_path(relative)
                    except ValueError:
                        continue
            if path.is_symlink():
                raise ValueError("Unsafe symbolic link in a local review backup")
            if path.is_dir():
                continue
            if not path.is_file() or not path.resolve().is_relative_to(base.resolve()):
                raise ValueError("Unsafe local review backup member")
            size += path.stat().st_size
            items.append((label + "/" + path.relative_to(base).as_posix(), path))
            if len(items) > MAX_EXPORT_FILES or size > MAX_EXPORT_BYTES:
                raise ValueError("Local review exceeds the bounded ZIP backup limit")
    intro = (
        "ZAPTRACE REVIEW STUDIO LOCAL BACKUP\n"
        f"Source SHA256: {sha}\n"
        f"Review label: {row['name']}\n"
        "Contents: native KiCad review evidence and user-selected source copies.\n"
        "This ZIP may contain sensitive PCB and schematic design information.\n"
        "Backup does not certify safe routing, ERC/DRC success or fabrication readiness.\n"
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(
        stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, strict_timestamps=False
    ) as archive:
        archive.writestr("README-LOCAL-BACKUP.txt", intro)
        for destination, file in items:
            archive.write(file, arcname=destination)
    return stream.getvalue()


def delete_review(workspace: Path, key: str, sha: str, confirmation: str) -> dict[str, str]:
    """Remove only our imported review plus selected-source copies, after explicit confirmation.

    Manifest updates are atomic and verified before any user files are removed.
    A manually registered external snapshot is never deleted or unregistered.
    """
    if confirmation != CONFIRM:
        raise ValueError("Explicit review and selected-source deletion confirmation required")
    rows, selected, review, staged = _record(workspace, key, sha)
    manifest = workspace / "projects.json"
    previous = manifest.read_bytes()
    updated = [row for row in rows if row is not selected]
    temporary = manifest.with_suffix(".json.deleted.tmp")
    temporary.write_text(
        json.dumps({"version": 1, "projects": updated}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(manifest)
    try:
        render_workspace(workspace)
    except Exception:
        rollback = manifest.with_suffix(".json.rollback.tmp")
        rollback.write_bytes(previous)
        rollback.replace(manifest)
        raise
    # All paths have been checked against the user-owned import directories.
    shutil.rmtree(review)
    shutil.rmtree(staged)
    return {
        "state": "deleted",
        "message": "Local review and selected input copies deleted; original external sources untouched",
    }


def validate_restore_backup(payload: bytes) -> dict[str, bytes]:
    """Parse Review Studio private ZIP inputs; never restore its executable HTML.

    Return only canonical, bounded KiCad source copies. Every report, plot and
    HTML file from a ZIP is ignored; the caller *must* rerun installed native
    KiCad ERC/DRC on these sources before showing a project card.
    """
    from review_studio_workspace import safe_sheet_path

    if not isinstance(payload, bytes) or not 500 <= len(payload) <= MAX_EXPORT_BYTES:
        raise ValueError("Select a valid bounded Review Studio ZIP backup")
    sources: dict[str, bytes] = {}
    header: bytes | None = None
    used: set[str] = set()
    bytes_total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_EXPORT_FILES:
                raise ValueError("Invalid or corrupted Review Studio backup ZIP")
            for member in infos:
                filename = member.filename
                if filename in used or "\\" in filename or "\x00" in filename:
                    raise ValueError("Duplicate or unsafe ZIP backup member")
                used.add(filename)
                parts = filename.split("/")
                if any(segment in {"", ".", ".."} for segment in parts):
                    raise ValueError("Unsafe ZIP backup member path")
                mode = member.external_attr >> 16
                if (mode & 0o170000) == 0o120000:
                    raise ValueError("Symbolic links in ZIP backups are forbidden")
                if member.is_dir():
                    raise ValueError("Review ZIP must contain files rather than directory entries")
                bytes_total += member.file_size
                if member.file_size > MAX_EXPORT_BYTES or bytes_total > MAX_EXPORT_BYTES:
                    raise ValueError("Review backup exceeds safe decompressed size")
                # Archive-member limits are checked BEFORE any decompression.
                if filename.startswith("selected-input-copies/"):
                    if parts[0] != "selected-input-copies" or len(parts) < 2:
                        raise ValueError("Unsafe original source path in ZIP")
                    basename = "/".join(parts[1:])
                    if basename == "source.kicad_prl":
                        # Prior 0.1.1 exports included KiCad's generated GUI
                        # session; ignore it rather than blocking migration.
                        continue
                    if basename not in {"source.kicad_pcb", "source.kicad_sch", "source.kicad_pro", "source.kicad_dru"}:
                        safe_sheet_path(basename)
                    if len(sources) >= 36:
                        raise ValueError("More KiCad files than the native import limit")
                    data = archive.read(member)
                    sources[basename] = data
                elif filename == "README-LOCAL-BACKUP.txt":
                    if member.file_size > 4096:
                        raise ValueError("Review ZIP format header exceeds limit")
                    header = archive.read(member)
                elif filename.startswith("review/"):
                    # DO NOT use HTML, SVG, JS, evidence.json or reports from
                    # untrusted ZIP input. Fresh native KiCad will replace them.
                    continue
                else:
                    raise ValueError("Unexpected Review Studio ZIP member")
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, OSError) as exc:
        raise ValueError("Corrupt or unsupported Review Studio ZIP backup") from exc
    if header is None:
        raise ValueError("Review Studio ZIP backup format header is missing")
    try:
        note = header.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid Review Studio backup header") from exc
    match = re.search(r"(?m)^Source SHA256: ([0-9a-f]{64})$", note)
    board = sources.get("source.kicad_pcb")
    if not note.startswith("ZAPTRACE REVIEW STUDIO LOCAL BACKUP\n") or match is None or board is None:
        raise ValueError("ZIP was not created as a Review Studio source backup")
    if hashlib.sha256(board).hexdigest() != match.group(1) or not board.lstrip().startswith(b"(kicad_pcb"):
        raise ValueError("Backed-up KiCad PCB does not match the recorded source SHA256")
    if not 100 < len(board) <= 10 * 1024 * 1024:
        raise ValueError("Backed-up KiCad PCB is outside the native import size limit")
    if "source.kicad_sch" in sources:
        schematic = sources["source.kicad_sch"]
        if not 100 < len(schematic) <= 4 * 1024 * 1024 or not schematic.lstrip().startswith(b"(kicad_sch"):
            raise ValueError("Backed-up root schematic is invalid")
    children = [
        name
        for name in sources
        if name not in {"source.kicad_pcb", "source.kicad_sch", "source.kicad_pro", "source.kicad_dru"}
    ]
    if len(children) > 32 or children and "source.kicad_sch" not in sources:
        raise ValueError("Restoring hierarchical KiCad sheets requires a root schematic")
    total = 0
    for name in children:
        data = sources[name]
        total += len(data)
        if len(data) < 100 or total > 16 * 1024 * 1024 or not data.lstrip().startswith(b"(kicad_sch"):
            raise ValueError("Invalid hierarchical KiCad schematic in backup")
    if "source.kicad_pro" in sources:
        settings = sources["source.kicad_pro"]
        if len(settings) > 3 * 1024 * 1024:
            raise ValueError("Native KiCad project settings exceed import limit")
        try:
            if not isinstance(json.loads(settings.decode("utf-8")), dict):
                raise ValueError("Native project settings must be a JSON object")
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid KiCad project settings in backup") from exc
    if "source.kicad_dru" in sources and len(sources["source.kicad_dru"]) > 512 * 1024:
        raise ValueError("Native KiCad rule file exceeds import limit")
    return sources
