#!/usr/bin/env python3
"""Actual installed Ubuntu KiCad 10/private HTTP copper proof, not a mock.

Run with /usr/bin/python3 -B and a full portable KiCad project ZIP made from
a known original ESP32 export. Requires installed package sources; does not
import the developer checkout, never changes the original ZIP and deletes
only its own disposable session.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from review_studio_local_file_guard import read_regular_bytes


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def call(base: str, token: str, endpoint: str, data: dict | None = None) -> tuple[int, bytes]:
    origin = base
    headers = {"X-Review-Token": token}
    if data is not None:
        headers.update({"Content-Type": "application/json", "Origin": origin})
    request = Request(
        base + endpoint,
        method="POST" if data is not None else "GET",
        data=json.dumps(data).encode() if data is not None else None,
        headers=headers,
    )
    try:
        with urlopen(request, timeout=35) as reply:
            return reply.status, reply.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def smoke(package: Path, portable: Path) -> None:
    assert package.is_dir() and package.name == "scripts", "Installed .deb scripts directory required"
    assert (package / "review_studio_native_copper_link.py").is_file()
    assert (package / "review_studio_native_copper_bundle.py").is_file()
    sys.path.insert(0, str(package.resolve()))
    from review_studio_local_server import ReviewLocalServer

    raw = read_regular_bytes(portable, max_size=34 * 1024 * 1024)
    original_sha = sha(raw)
    headers = {"project_base64": base64.b64encode(raw).decode(), "project_sha256": original_sha}
    with tempfile.TemporaryDirectory(prefix="zaptrace-installed-copper-qa-") as temp:
        workspace = Path(temp) / "workspace"
        server = ReviewLocalServer(("127.0.0.1", 0), workspace)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.09}, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            status, _ = call(base, "not-a-valid-token", "/api/native-copper/inspect", headers)
            assert status == 403, "Unauthorized native KiCad source access must be rejected"
            status, body = call(base, server.secret, "/api/native-copper/inspect", headers)
            assert status == 200, (status, body[:280])
            items = json.loads(body)
            assert items["mode"] == "read_only_native_kicad_links"
            assert items["archive_sha256"] == original_sha
            assert items["physical_drc_count"] == 16
            assert items["unconnected_count"] == 37 and items["schematic_parity_count"] == 0
            assert len(items["links"]) == 37
            target = next(
                link
                for link in items["links"]
                if any("Pad 2 [VCC_3V3] of U1" in item["label"] for item in link["pads"])
                and any("Pad 3 [VCC_3V3] of U1" in item["label"] for item in link["pads"])
            )
            pair = [item["uuid"] for item in target["pads"]]
            payload = {**headers, "start_pad_uuid": pair[0], "end_pad_uuid": pair[1], "waypoints": []}
            status, queued = call(base, server.secret, "/api/native-copper", payload)
            assert status == 202, (status, queued)
            queued_job = json.loads(queued)
            result: dict = {"state": "running"}
            for _ in range(560):
                status, result_raw = call(base, server.secret, "/api/jobs/" + queued_job["id"])
                assert status == 200
                result = json.loads(result_raw)
                if result["state"] != "running":
                    break
                time.sleep(0.2)
            assert result["state"] == "complete", result
            approved = result["native_copper"]
            assert approved["before_unconnected"] == 37 and approved["after_unconnected"] == 36
            assert approved["before_violations"] == approved["after_violations"] == 16
            assert approved["fabApproved"] is False and approved["automatic_complete_routing"] is False
            assert approved["archive_sha256"] == original_sha
            route = "/api/native-copper/result/" + queued_job["id"]
            status, zipped = call(base, server.secret, route + "/native-copper-project.zip")
            assert status == 200, "Native project ZIP must be downloadable only by the owner"
            assert approved["download_sha256"]["native-copper-project.zip"] == sha(zipped)
            with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
                assert archive.testzip() is None
                for name in (
                    "EVIDENCE.json",
                    "baseline-drc.json",
                    "candidate-drc.json",
                    "before.svg",
                    "after.svg",
                    "PREVIEW.html",
                    "ESP32_I2C_Sensor_Board.kicad_pcb",
                    "ESP32_I2C_Sensor_Board.kicad_sch",
                    "ESP32_I2C_Sensor_Board.kicad_pro",
                ):
                    assert name in archive.namelist(), name
                evidence = json.loads(archive.read("EVIDENCE.json"))
                assert evidence["source_sha256"] == evidence["source_asset_sha256"]["ESP32_I2C_Sensor_Board.kicad_pcb"]
                assert evidence["native_drc"]["after_unconnected"] == 36
                assert evidence["native_drc"]["new_findings"] == 0
                assert evidence["native_drc"]["schematic_parity"] == 0
                assert evidence["fabApproved"] is False
                assert archive.read("before.svg") != archive.read("after.svg")
                assert archive.read("PREVIEW.html").count(b"data:image/svg+xml;base64,") == 2
                assert len(json.loads(archive.read("candidate-drc.json"))["unconnected_items"]) == 36
            status, _ = call(base, "bad-token", route + "/native-copper-project.zip")
            assert status == 403
            status, discarded = call(base, server.secret, "/api/native-copper/discard", {"id": queued_job["id"]})
            assert status == 200 and json.loads(discarded)["state"] == "discarded"
            status, _ = call(base, server.secret, route + "/EVIDENCE.json")
            assert status == 404, "Discarded private native evidence must be unavailable"
            assert not list((workspace / "native-copper-working").glob("*/project"))
            assert not list((workspace / "native-copper-results").glob("*/EVIDENCE.json"))
            assert sha(read_regular_bytes(portable, max_size=34 * 1024 * 1024)) == original_sha, (
                "Original KiCad source ZIP changed"
            )
            print("INSTALLED_KICAD_NATIVE_COPPER_VERIFIED=37->36,16->16,PARITY=0")
            print("INSTALLED_KICAD_SOURCE_SHA256=" + original_sha)
            print("INSTALLED_KICAD_COPPER_PRIVATE_BUNDLE_DOWNLOAD_AND_DISCARD: PASS")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-scripts", type=Path, required=True)
    parser.add_argument("--portable-project-zip", type=Path, required=True)
    args = parser.parse_args()
    smoke(args.installed_scripts, args.portable_project_zip)


if __name__ == "__main__":
    main()
