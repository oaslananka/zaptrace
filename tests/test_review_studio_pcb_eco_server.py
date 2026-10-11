"""Localhost-only native PCB ECO security, real KiCad DRC, private artifacts."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "review_studio_eco_server_test_helper", Path(__file__).with_name("test_review_studio_schematic_eco_server.py")
)
assert SPEC is not None and SPEC.loader is not None
HELPERS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPERS)
await_job = HELPERS.await_job
fetch = HELPERS.fetch
local_studio = HELPERS.local_studio

CLEAN = Path(__file__).parent / "fixtures/review_studio_native_eco_placement.kicad_pcb"
COPPER = Path(__file__).resolve().parents[1] / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"


def make_payload(board: Path = CLEAN, *, ref: str = "R1", dx: float = 1, dy: float = 0.5) -> dict:
    raw = board.read_bytes()
    return {
        "source_base64": base64.b64encode(raw).decode(),
        "original_sha256": hashlib.sha256(raw).hexdigest(),
        "reference": ref,
        "dx": dx,
        "dy": dy,
    }


def test_real_native_kicad_pcb_localhost_eco_safe_and_private(tmp_path: Path) -> None:
    if not shutil.which("kicad-cli"):
        pytest.skip("Native KiCad CLI required")
    original = CLEAN.read_bytes()
    with local_studio(tmp_path) as (server, url):
        token = server.secret
        code, page = fetch(url + "/", token)
        assert code == 200 and b'id="pcbEcoForm"' in page and b'id="pcbEcoPreview"' in page
        status, _ = fetch(url + "/api/pcb-eco", "bogus-token", data=make_payload())
        assert status == 403
        code, raw = fetch(url + "/api/pcb-eco", token, data=make_payload())
        assert code == 202, raw
        job = json.loads(raw)
        result = await_job(url, token, job["id"])
        assert result["state"] == "complete", result
        assert result["pcb_eco"]["ref"] == "R1"
        assert result["pcb_eco"]["old_mm"] == [20, 20]
        assert result["pcb_eco"]["new_mm"] == [21, 20.5]
        assert result["pcb_eco"]["fabApproved"] is False
        route = url + "/api/pcb-eco/result/" + job["id"]
        code, manifest_raw = fetch(route + "/ECO_EVIDENCE.json", token)
        report = json.loads(manifest_raw)
        assert code == 200 and report["native_drc"]["new_drc_rules"] == 0
        assert report["source_sha256"] == hashlib.sha256(original).hexdigest()
        code, html = fetch(route + "/PREVIEW.html", token)
        assert code == 200 and html.count(b"data:image/svg+xml;base64,") == 2
        assert b"NOT FABRICATION APPROVED" in html
        code, new = fetch(route + "/source.kicad_pcb", token)
        assert code == 200 and new != original and new.startswith(b"(kicad_pcb")
        assert new == (tmp_path / "workspace/pcb-eco-results" / job["id"] / "source.kicad_pcb").read_bytes()
        assert CLEAN.read_bytes() == original
        assert not list((tmp_path / "workspace/pcb-eco-working").glob("*/source.kicad_pcb"))
        code, _ = fetch(route + "/source.kicad_pcb", "bad-token")
        assert code == 403
        code, _ = fetch(route + "/../source.kicad_pcb", token)
        assert code in (403, 404)
        code, dropped = fetch(url + "/api/pcb-eco/discard", token, data={"id": job["id"]})
        assert code == 200 and json.loads(dropped)["state"] == "discarded"
        code, _ = fetch(route + "/PREVIEW.html", token)
        assert code == 404
        assert not list((tmp_path / "workspace/pcb-eco-results").glob("*/ECO_EVIDENCE.json"))
    assert CLEAN.read_bytes() == original


def test_invalid_pcb_browser_sha_grid_and_unknown_footprint_refuse(tmp_path: Path) -> None:
    with local_studio(tmp_path) as (server, url):
        token = server.secret
        for wrong in (
            {**make_payload(), "original_sha256": "0" * 64},
            {**make_payload(), "dx": 1.004},
            {**make_payload(), "dx": 0, "dy": 0},
            {**make_payload(), "reference": "R0"},
            {**make_payload(), "source_base64": "%%%"},
        ):
            code, _ = fetch(url + "/api/pcb-eco", token, data=wrong)
            assert code == 400
        code, raw = fetch(url + "/api/pcb-eco", token, data=make_payload(ref="R99"))
        assert code == 202
        job = json.loads(raw)
        assert await_job(url, token, job["id"])["state"] == "failed"
        assert not list((tmp_path / "workspace/pcb-eco-results").glob("*/ECO_EVIDENCE.json"))
        assert not list((tmp_path / "workspace/pcb-eco-working").glob("*/source.kicad_pcb"))


def test_routed_sensor_footprint_cannot_be_moved_using_browser(tmp_path: Path) -> None:
    if not COPPER.is_file():
        pytest.skip("Real routed KiCad PCB fixture unavailable")
    sha = hashlib.sha256(COPPER.read_bytes()).hexdigest()
    with local_studio(tmp_path) as (server, url):
        code, body = fetch(url + "/api/pcb-eco", server.secret, data=make_payload(COPPER))
        assert code == 202
        result = await_job(url, server.secret, json.loads(body)["id"])
        assert result["state"] == "failed"
        assert "drag-routing" in result["message"]
    assert hashlib.sha256(COPPER.read_bytes()).hexdigest() == sha


def test_real_project_rule_context_browser_eco_returns_private_bundle(tmp_path: Path) -> None:
    """Matching .kicad_pro source stays intact and travels with the approved copy."""
    import io
    import zipfile

    original_project = (Path(__file__).resolve().parents[1] / "tests/fixtures/kicad_project/top.kicad_pro").read_bytes()
    request = {
        **make_payload(),
        "source_filename": "sensor.kicad_pcb",
        "project_filename": "sensor.kicad_pro",
        "project_base64": base64.b64encode(original_project).decode(),
        "project_sha256": hashlib.sha256(original_project).hexdigest(),
    }
    with local_studio(tmp_path) as (server, url):
        token = server.secret
        status, raw = fetch(url + "/api/pcb-eco", token, data=request)
        assert status == 202, raw
        job = json.loads(raw)
        result = await_job(url, token, job["id"])
        assert result["state"] == "complete", result
        assert result["pcb_eco"]["rule_context"] == "project"
        route = url + "/api/pcb-eco/result/" + job["id"]
        status, evidence = fetch(route + "/ECO_EVIDENCE.json", token)
        assert status == 200
        report = json.loads(evidence)
        assert report["rule_context"]["mode"] == "project"
        assert report["rule_context"]["project_sha256"] == hashlib.sha256(original_project).hexdigest()
        status, bundle = fetch(route + "/source.project.zip", token)
        assert status == 200
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            assert set(archive.namelist()) == {"source.kicad_pcb", "source.kicad_pro", "ECO_EVIDENCE.json"}
            assert archive.read("source.kicad_pro") == original_project
            assert archive.read("source.kicad_pcb") != CLEAN.read_bytes()
        status, _ = fetch(route + "/source.project.zip", "invalid")
        assert status == 403
        code, removed = fetch(url + "/api/pcb-eco/discard", token, data={"id": job["id"]})
        assert code == 200 and json.loads(removed)["state"] == "discarded"
        assert fetch(route + "/source.project.zip", token)[0] == 404
    assert (
        CLEAN.is_file()
        and original_project
        == (Path(__file__).resolve().parents[1] / "tests/fixtures/kicad_project/top.kicad_pro").read_bytes()
    )


def test_project_rule_upload_mismatch_and_tampering_fail_closed(tmp_path: Path) -> None:
    original_project = (Path(__file__).resolve().parents[1] / "tests/fixtures/kicad_project/top.kicad_pro").read_bytes()
    correct = {
        **make_payload(),
        "source_filename": "sensor.kicad_pcb",
        "project_filename": "sensor.kicad_pro",
        "project_base64": base64.b64encode(original_project).decode(),
        "project_sha256": hashlib.sha256(original_project).hexdigest(),
    }
    wrong = [
        {**correct, "project_filename": "different.kicad_pro"},
        {**correct, "source_filename": "../sensor.kicad_pcb"},
        {**correct, "project_sha256": "0" * 64},
        {**correct, "project_base64": "%%not-base64"},
        {**correct, "project_base64": base64.b64encode(b"not a JSON project").decode()},
        {**correct, "rules_filename": "sensor.kicad_dru"},
        {**correct, "project_filename": "sensor.KICAD_PRO"},
        {**correct, "project_filename": "sensor.kicad_pro", "source_filename": "sensor2.kicad_pcb"},
    ]
    with local_studio(tmp_path) as (server, url):
        for bad in wrong:
            code, _ = fetch(url + "/api/pcb-eco", server.secret, data=bad)
            assert code == 400, bad.keys()
        assert not list((tmp_path / "workspace/pcb-eco-results").glob("*/source.kicad_pcb"))


def test_custom_kicad_rules_browser_probe_preserves_original_and_downloads_bundle(tmp_path: Path) -> None:
    import io
    import zipfile

    project = (Path(__file__).resolve().parents[1] / "tests/fixtures/kicad_project/top.kicad_pro").read_bytes()
    rules = b'(version 1)\n(rule "ALLOW_FOOTPRINT_COURTYARD" (constraint courtyard_clearance (min 0.1mm)))\n'
    payload = {
        **make_payload(),
        "source_filename": "sensor.kicad_pcb",
        "project_filename": "sensor.kicad_pro",
        "project_base64": base64.b64encode(project).decode(),
        "project_sha256": hashlib.sha256(project).hexdigest(),
        "rules_filename": "sensor.kicad_dru",
        "rules_base64": base64.b64encode(rules).decode(),
        "rules_sha256": hashlib.sha256(rules).hexdigest(),
    }
    with local_studio(tmp_path) as (server, url):
        status, start = fetch(url + "/api/pcb-eco", server.secret, data=payload)
        assert status == 202, start
        job = json.loads(start)
        done = await_job(url, server.secret, job["id"])
        assert done["state"] == "complete", done
        assert done["pcb_eco"]["rule_context"] == "project_with_custom_rules"
        assert done["pcb_eco"]["custom_rule_loader_probe_passed"] is True
        route = url + "/api/pcb-eco/result/" + job["id"]
        code, packed = fetch(route + "/source.project.zip", server.secret)
        assert code == 200
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            assert set(archive.namelist()) == {
                "source.kicad_pcb",
                "source.kicad_pro",
                "source.kicad_dru",
                "ECO_EVIDENCE.json",
            }
            assert archive.read("source.kicad_dru") == rules
            assert archive.read("source.kicad_pro") == project
            evidence = json.loads(archive.read("ECO_EVIDENCE.json"))
            assert evidence["rule_context"]["effective_rules_independently_verified"] is False
            assert evidence["rule_context"]["custom_rules_sha256"] == hashlib.sha256(rules).hexdigest()
        status, _ = fetch(url + "/api/pcb-eco/discard", server.secret, data={"id": job["id"]})
        assert status == 200
    assert CLEAN.is_file()


def test_invalid_custom_kicad_rules_fail_closed_after_async_native_probe(tmp_path: Path) -> None:
    project = (Path(__file__).resolve().parents[1] / "tests/fixtures/kicad_project/top.kicad_pro").read_bytes()
    rules = b"(version 1)\n(rule broken (constraint clearance (min INVALID)))\n"
    payload = {
        **make_payload(),
        "source_filename": "sensor.kicad_pcb",
        "project_filename": "sensor.kicad_pro",
        "project_base64": base64.b64encode(project).decode(),
        "project_sha256": hashlib.sha256(project).hexdigest(),
        "rules_filename": "sensor.kicad_dru",
        "rules_base64": base64.b64encode(rules).decode(),
        "rules_sha256": hashlib.sha256(rules).hexdigest(),
    }
    with local_studio(tmp_path) as (server, url):
        code, start = fetch(url + "/api/pcb-eco", server.secret, data=payload)
        assert code == 202, start
        job = json.loads(start)
        status = await_job(url, server.secret, job["id"])
        assert status["state"] == "failed"
        assert not list((tmp_path / "workspace/pcb-eco-results").glob("*/source.kicad_pcb"))
        assert not list((tmp_path / "workspace/pcb-eco-working").glob("*/source.kicad_pcb"))
