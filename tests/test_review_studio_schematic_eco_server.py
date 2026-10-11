"""Authenticated native KiCad ECO browser API with source isolation and deletion."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("eco_local_server", SCRIPTS / "review_studio_local_server.py")
assert SPEC is not None and SPEC.loader is not None
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)
ReviewLocalServer = SERVER.ReviewLocalServer

FIXTURE = Path(__file__).parent / "fixtures/review_studio_native_eco_sensor.kicad_sch"


@contextmanager
def local_studio(root: Path):
    server = ReviewLocalServer(("127.0.0.1", 0), root / "workspace")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=6)


def fetch(url: str, token: str, *, data: dict | None = None, method: str | None = None) -> tuple[int, bytes]:
    headers = {"X-Review-Token": token}
    if data is not None:
        headers["Content-Type"] = "application/json"
        headers["Origin"] = url.split("/api/")[0]
    req = Request(
        url,
        headers=headers,
        method=method or ("POST" if data is not None else "GET"),
        data=json.dumps(data).encode() if data is not None else None,
    )
    try:
        with urlopen(req, timeout=22) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def payload(ref: str = "R1", value: str = "10k") -> dict:
    original = FIXTURE.read_bytes()
    return {
        "source_base64": base64.b64encode(original).decode(),
        "original_sha256": hashlib.sha256(original).hexdigest(),
        "reference": ref,
        "value": value,
    }


def await_job(base: str, token: str, job_id: str) -> dict:
    for _ in range(650):
        code, body = fetch(base + "/api/jobs/" + job_id, token)
        assert code == 200
        result = json.loads(body)
        if result["state"] != "running":
            return result
        time.sleep(0.18)
    pytest.fail("Native KiCad ECO job did not complete within 117 seconds")


def test_localhost_eco_schematic_authoring_is_authenticated_and_safe(tmp_path: Path) -> None:
    if not shutil.which("kicad-cli"):
        pytest.skip("Native KiCad 10 is required for actual ECO")
    with local_studio(tmp_path) as (server, base):
        secret = server.secret
        code, html = fetch(base + "/", secret)
        assert code == 200 and b'id="ecoForm"' in html and b'id="ecoPreview"' in html
        assert b"window.__REVIEW_LOCAL__=" in html
        code, _ = fetch(base + "/api/eco/result/" + "a" * 32 + "/PREVIEW.html", secret)
        assert code == 404
        code, _ = fetch(base + "/api/eco", "bad-token", data=payload())
        assert code == 403
        expected = payload()
        original = FIXTURE.read_bytes()
        code, started = fetch(base + "/api/eco", secret, data=expected)
        assert code == 202, started
        job = json.loads(started)
        assert job["state"] == "running"
        result = await_job(base, secret, job["id"])
        assert result["state"] == "complete", result
        assert result["eco"] == {
            "id": job["id"],
            "reference": "R1",
            "old_value": "4.7k",
            "new_value": "10k",
            "fabApproved": False,
            "pcbSynchronized": False,
        }
        code, source = fetch(base + f"/api/eco/result/{job['id']}/source.kicad_sch", secret)
        assert code == 200 and source != original and b'(property "Value" "10k"' in source
        code, presentation = fetch(base + f"/api/eco/result/{job['id']}/PREVIEW.html", secret)
        assert code == 200 and presentation.count(b"data:image/svg+xml;base64,") == 2
        assert b"NOT FABRICATION APPROVED" in presentation and b'id="zoomFit"' in presentation
        code, evidence_bytes = fetch(base + f"/api/eco/result/{job['id']}/ECO_EVIDENCE.json", secret)
        evidence = json.loads(evidence_bytes)
        assert code == 200 and evidence["net_topology_unchanged"] is True
        assert evidence["original_sha256"] == expected["original_sha256"]
        assert evidence["native_erc_original"] == evidence["native_erc_after"]
        assert FIXTURE.read_bytes() == original
        assert not list((tmp_path / "workspace/eco-working").glob("*/source.kicad_sch"))
        code, _ = fetch(base + f"/api/eco/result/{job['id']}/source.kicad_sch", "wrong-token")
        assert code == 403
        code, _ = fetch(base + f"/api/eco/result/{job['id']}/../source.kicad_sch", secret)
        assert code in (403, 404)
        code, outcome = fetch(base + "/api/eco/discard", secret, data={"id": job["id"]})
        assert code == 200 and json.loads(outcome)["state"] == "discarded"
        code, _ = fetch(base + f"/api/eco/result/{job['id']}/PREVIEW.html", secret)
        assert code == 404
        assert not list((tmp_path / "workspace/eco-results").glob("*/ECO_EVIDENCE.json"))
        assert FIXTURE.read_bytes() == original


def test_eco_api_rejects_bad_sha_and_unsafe_changes_before_spawning_worker(tmp_path: Path) -> None:
    with local_studio(tmp_path) as (server, base):
        for changed in (
            {**payload(), "original_sha256": "0" * 64},
            payload("R99", "10k"),
            payload("R1", "<script>"),
            {**payload(), "source_base64": "!!!!"},
        ):
            code, result = fetch(base + "/api/eco", server.secret, data=changed)
            if changed["reference"] == "R99":
                # Structurally valid but absent component ref is rejected by native worker.
                assert code == 202
                job = json.loads(result)
                assert await_job(base, server.secret, job["id"])["state"] == "failed"
            else:
                assert code == 400, result
        assert not list((tmp_path / "workspace/eco-results").glob("*/ECO_EVIDENCE.json"))
        assert not list((tmp_path / "workspace/eco-working").glob("*/source.kicad_sch"))
        assert FIXTURE.read_bytes().startswith(b"(kicad_sch")
