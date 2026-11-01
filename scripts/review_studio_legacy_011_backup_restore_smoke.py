#!/usr/bin/python3
"""Authentic 0.1.1 installed localhost import/backup -> 0.1.10 restore.

Runs ONLY inside a disposable Ubuntu container under /usr/bin/python3.
Each version runs in a separate interpreter process to prevent stale module
imports. Both source and user backup are temporary, non-GA engineering data.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import threading
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def request(
    base: str, token: str, route: str, data: bytes | None = None, content_type: str | None = None
) -> tuple[int, bytes]:
    headers = {"X-Review-Token": token}
    if data is not None:
        headers["Origin"] = base
    if content_type:
        headers["Content-Type"] = content_type
    req = Request(base + route, method="POST" if data is not None else "GET", data=data, headers=headers)
    try:
        with urlopen(req, timeout=48) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def await_native(base: str, token: str, key: str) -> dict:
    status: dict = {"state": "running"}
    for _ in range(1000):
        code, raw = request(base, token, "/api/jobs/" + key)
        if code != 200:
            raise RuntimeError(f"Native KiCad status request refused: {code}")
        status = json.loads(raw)
        if status.get("state") != "running":
            return status
        time.sleep(0.22)
    raise RuntimeError("Native KiCad import did not finish")


def multipart(board: bytes) -> tuple[str, bytes]:
    delim = "ZapTrace0110RealLegacyProofBoundary"
    parts = (
        (("name", ""), b"Legacy genuine private PCB"),
        (("board", "legacy-native.kicad_pcb"), board),
    )
    content = b""
    for key, payload in parts:
        name, filename = key
        content += (
            ("--" + delim + '\r\nContent-Disposition: form-data; name="' + name + '"').encode()
            + ('; filename="' + filename + '"').encode()
            if filename
            else ("--" + delim + '\r\nContent-Disposition: form-data; name="' + name + '"').encode()
        )
        content += b"\r\nContent-Type: application/octet-stream\r\n\r\n" + payload + b"\r\n"
    content += ("--" + delim + "--\r\n").encode()
    return "multipart/form-data; boundary=" + delim, content


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("legacy-export", "new-restore"))
    parser.add_argument("--installed-scripts", required=True, type=Path)
    parser.add_argument("--source-board", type=Path)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "legacy-export" and (args.source_board is None or not args.source_board.is_file()):
        parser.error("Legacy native PCB input must exist")
    sys.path.insert(0, str(args.installed_scripts.resolve()))
    from review_studio_local_server import ReviewLocalServer

    args.workspace.parent.mkdir(parents=True, exist_ok=True)
    server = ReviewLocalServer(("127.0.0.1", 0), args.workspace)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.09}, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        if args.action == "legacy-export":
            assert args.source_board is not None
            board = args.source_board.read_bytes()
            sha = digest(board)
            content_type, body = multipart(board)
            code, queued = request(base, server.secret, "/api/import", body, content_type)
            if code != 202:
                raise RuntimeError(f"Installed legacy 0.1.1 import rejected {code}: {queued[:240]!r}")
            job = json.loads(queued)
            state = await_native(base, server.secret, job["id"])
            if state["state"] != "complete":
                raise RuntimeError(f"Legacy real KiCad source verification failed: {state}")
            rows = json.loads((args.workspace / "projects.json").read_text())["projects"]
            matching = [row for row in rows if row.get("sha") == sha]
            if len(matching) != 1:
                raise RuntimeError("Legacy native source SHA not registered")
            row = matching[0]
            route = "/api/projects/export?key=" + quote(row["id"]) + "&sha=" + sha
            code, archive = request(base, server.secret, route)
            if code != 200:
                raise RuntimeError(f"Legacy source ZIP export failed {code}")
            with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                assert zipped.testzip() is None
                assert zipped.read("selected-input-copies/source.kicad_pcb") == board
                assert "review/evidence.json" in zipped.namelist()
                assert "README-LOCAL-BACKUP.txt" in zipped.namelist()
            args.backup.write_bytes(archive)
            print("REAL_011_LEGACY_PRIVATE_ZIP_SHA256=" + digest(archive), flush=True)
            print("REAL_011_LEGACY_NATIVE_SOURCE_SHA256=" + sha, flush=True)
            print("REAL_011_LEGACY_PRIVATE_ZIP_EXPORT_WITH_KICAD: PASS", flush=True)
        else:
            backup = args.backup.read_bytes()
            with zipfile.ZipFile(io.BytesIO(backup)) as zipped:
                original = zipped.read("selected-input-copies/source.kicad_pcb")
                assert "review/evidence.json" in zipped.namelist()
            code, queued = request(
                base,
                server.secret,
                "/api/projects/restore?name=Legacy%20Restored%20with%200110",
                backup,
                "application/zip",
            )
            if code != 202:
                raise RuntimeError(f"Installed 0.1.10 legacy restore rejected {code}: {queued[:240]!r}")
            job = json.loads(queued)
            state = await_native(base, server.secret, job["id"])
            if state["state"] != "complete":
                raise RuntimeError(f"Legacy ZIP KiCad revalidation failed: {state}")
            rows = json.loads((args.workspace / "projects.json").read_text())["projects"]
            matching = [row for row in rows if row.get("sha") == digest(original)]
            if len(matching) != 1:
                raise RuntimeError("Restored original PCB SHA missing from new native KiCad review")
            saved = list((args.workspace / "local-imports").glob("*/source.kicad_pcb"))
            assert len(saved) == 1 and digest(saved[0].read_bytes()) == digest(original)
            report = json.loads((Path(matching[0]["review"]) / "evidence.json").read_text())
            assert report["source_sha256"] == digest(original)
            print("REAL_011_TO_0110_LEGACY_PRIVATE_ZIP_RESTORED_SHA256=" + digest(original), flush=True)
            print("REAL_011_TO_0110_KICAD_REGENERATED_NATIVE_REVIEW: PASS", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=6)


if __name__ == "__main__":
    main()
