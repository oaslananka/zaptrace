"""Authenticated read-only native schematic/PCB comparison via localhost bridge."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1]
SCH = SOURCE / "build/source-reference-readonly/ESP32_I2C_Sensor_Board.kicad_sch"
PCB = SOURCE / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"
HELPER_SPEC = importlib.util.spec_from_file_location(
    "review_studio_audit_http_fixture", Path(__file__).with_name("test_review_studio_schematic_eco_server.py")
)
assert HELPER_SPEC is not None and HELPER_SPEC.loader is not None
HELPERS = importlib.util.module_from_spec(HELPER_SPEC)
HELPER_SPEC.loader.exec_module(HELPERS)
local_studio = HELPERS.local_studio
fetch = HELPERS.fetch


def payload() -> dict:
    files = {"schematic": SCH.read_bytes(), "pcb": PCB.read_bytes()}
    return {
        k + suffix: value
        for k, raw in files.items()
        for suffix, value in (
            ("_base64", base64.b64encode(raw).decode()),
            ("_sha256", hashlib.sha256(raw).hexdigest()),
        )
    }


def test_native_schematic_pcb_browser_api_reports_real_discrepancies_without_mutating_source(tmp_path: Path) -> None:
    snapshot = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (SCH, PCB)}
    with local_studio(tmp_path) as (server, url):
        endpoint = url + "/api/schematic-pcb-audit"
        blocked, _ = fetch(endpoint, "invalid-capability", data=payload())
        assert blocked == 403
        code, body = fetch(endpoint, server.secret, data=payload())
        assert code == 200, body
        report = json.loads(body)
        assert report["source_sha256"] == {"schematic": snapshot[SCH], "pcb": snapshot[PCB]}
        assert report["component_counts"] == {"schematic": 14, "pcb": 14, "shared_references": 14}
        assert [x["reference"] for x in report["component_field_discrepancies"]] == ["J1", "TP1", "TP2", "U2", "U3"]
        assert report["automatic_sync_authorized"] is False
        assert report["linkage_uuid_verified"] is False
        assert report["fabApproved"] is False
        assert report["pin_net_correspondence"].startswith("not_verified_")
        assert not list((tmp_path / "workspace").glob(".zaptrace-audit-*"))
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == value for p, value in snapshot.items())


@pytest.mark.parametrize(
    "field,change",
    [
        ("schematic_sha256", "0" * 64),
        ("pcb_sha256", "0" * 64),
        ("schematic_base64", "invalid%%%base64"),
        ("pcb_base64", "invalid%%%base64"),
        ("pcb_base64", base64.b64encode(b"not a native PCB" * 15).decode()),
    ],
)
def test_native_parity_bridge_rejects_invalid_unverified_sources(tmp_path: Path, field: str, change: str) -> None:
    with local_studio(tmp_path) as (server, url):
        code, _ = fetch(url + "/api/schematic-pcb-audit", server.secret, data={**payload(), field: change})
        assert code == 400
        assert not list((tmp_path / "workspace").glob(".zaptrace-audit-*"))


def test_native_parity_bridge_rejects_unknown_fields(tmp_path: Path) -> None:
    with local_studio(tmp_path) as (server, url):
        code, _ = fetch(url + "/api/schematic-pcb-audit", server.secret, data={**payload(), "approve_and_sync": True})
        assert code == 400
        assert not list((tmp_path / "workspace").glob(".zaptrace-audit-*"))
