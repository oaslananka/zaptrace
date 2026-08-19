"""REST integration tests for complete current release evidence."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zaptrace.api.server import app

client = TestClient(app)


def _headers(session_id: str) -> dict[str, str]:
    return {
        "X-ZapTrace-Session-Id": session_id,
        "X-ZapTrace-Capabilities": "release-export",
        "X-ZapTrace-Actor": "pytest",
        "X-ZapTrace-Reason": "release evidence integration",
    }


def _create_validated_design(session_id: str, *, fab_profile: str | None = None) -> dict[str, str]:
    headers = _headers(session_id)
    yaml = """meta: {name: RestReleaseEvidence}
components:
  r1: {ref: R1, type: resistor, value: 10k, footprint: '0603', position: [10.0, 20.0]}
nets: {}
"""
    parsed = client.post("/api/v1/designs/parse/str", params={"yaml_content": yaml}, headers=headers)
    assert parsed.status_code == 200
    erc = client.post("/api/v1/erc/validate/RestReleaseEvidence", headers=headers)
    assert erc.status_code == 200
    drc = client.post(
        "/api/v1/drc/run/RestReleaseEvidence",
        params={"fab_profile": fab_profile} if fab_profile else {},
        headers=headers,
    )
    assert drc.status_code == 200
    return headers


def test_rest_drc_result_exposes_state_bound_evidence() -> None:
    headers = _create_validated_design("api-release-profiled", fab_profile="jlcpcb-2layer")

    response = client.get("/api/v1/drc/result/RestReleaseEvidence", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence"]["status"] == "pass"
    assert payload["evidence"]["fab_profile"] == "jlcpcb-2layer"
    assert payload["evidence"]["design_state_hash"] == payload["validation_status"]["design_state_hash"]


def test_rest_release_export_requires_approved_profile_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import zaptrace.agent._tool_impls as tool_impls

    monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(tool_impls, "_WORKSPACE", None)
    headers = _create_validated_design("api-release-unapproved-skip")

    response = client.post(
        "/api/v1/release/RestReleaseEvidence/kicad",
        params={
            "output_dir": str(tmp_path / "unapproved"),
            "approval_id": "REST-RELEASE-1",
            "fab_profile_skip_reason": "Prototype-only export",
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert "unapproved fabrication-profile skip" in response.json()["detail"]


def test_rest_release_export_returns_complete_evidence_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zaptrace.agent._tool_impls as tool_impls

    monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(tool_impls, "_WORKSPACE", None)
    headers = _create_validated_design("api-release-approved-skip")

    response = client.post(
        "/api/v1/release/RestReleaseEvidence/kicad",
        params={
            "output_dir": str(tmp_path / "approved"),
            "approval_id": "REST-RELEASE-2",
            "fab_profile_skip_reason": "Prototype-only export",
            "fab_profile_skip_approval_id": "REST-FAB-SKIP-1",
        },
        headers=headers,
    )

    assert response.status_code == 200
    gate = response.json()["release_gate"]
    assert gate["status"] == "pass"
    assert gate["fab_profile_policy"]["status"] == "skip-approved"
    assert gate["fab_profile_policy"]["skip_approval_id"] == "REST-FAB-SKIP-1"
    assert gate["component_coverage"]["status"] == "pass"
    assert gate["component_coverage"]["bom_accounted_component_count"] == 1
    assert gate["component_coverage"]["pick_and_place_accounted_component_count"] == 1
    assert len(gate["evidence_identity"]["evidence_identity_hash"]) == 64
    assert gate["approval_binding"]["approval_id"] == "REST-RELEASE-2"


def test_rest_drc_rejects_fabrication_profile_paths(tmp_path: Path) -> None:
    profile = tmp_path / "attacker-profile.yaml"
    profile.write_text("name: attacker\nmanufacturer: attacker\n", encoding="utf-8")
    headers = _headers("api-release-profile-path")
    yaml = """meta: {name: RestProfilePath}
components: {}
nets: {}
"""
    parsed = client.post("/api/v1/designs/parse/str", params={"yaml_content": yaml}, headers=headers)
    assert parsed.status_code == 200

    response = client.post(
        "/api/v1/drc/run/RestProfilePath",
        params={"fab_profile": str(profile)},
        headers=headers,
    )

    assert response.status_code == 404
    assert "Built-in profile not found" in response.json()["detail"]


def test_rest_drc_missing_design_returns_not_found() -> None:
    response = client.post("/api/v1/drc/run/MissingDesign", headers=_headers("api-release-missing-drc"))

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_rest_release_missing_design_returns_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import zaptrace.agent._tool_impls as tool_impls

    monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(tool_impls, "_WORKSPACE", None)
    response = client.post(
        "/api/v1/release/MissingDesign/kicad",
        params={
            "output_dir": str(tmp_path / "missing"),
            "approval_id": "REST-MISSING-1",
            "fab_profile_skip_reason": "Prototype-only export",
            "fab_profile_skip_approval_id": "REST-FAB-SKIP-MISSING-1",
        },
        headers=_headers("api-release-missing-export"),
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
