"""Review Studio tests — panel aggregation, workflow, and API routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from zaptrace.api.server import app
from zaptrace.core.models import Component, Design, DesignMeta, DRCResult, DRCViolation, Net, NetNode
from zaptrace.erc.models import ERCSeverity, ERCViolation
from zaptrace.review.panels import (
    _dfm_panel_items,
    _review_status_for_severity,
    collect_panels,
    collect_review_bundle,
)
from zaptrace.review.storage import (
    get_review_state_store,
    hydrate_review_session,
    review_sessions_for_design_session,
)
from zaptrace.review.workflow import (
    _REVIEW_SESSIONS,
    ChecklistStatus,
    DecisionType,
    ReviewStatus,
    ReviewTransitionError,
    add_waiver,
    approve_checklist_item,
    create_review_session,
    get_review_session,
    reject_checklist_item,
    remove_review_sessions_for_design_session,
    resolve_decision,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def design() -> Design:
    d = Design(meta=DesignMeta(name="ReviewBoard"))
    d.components["r1"] = Component(id="r1", ref="R1", type="resistor", value="10k", footprint="0603")
    d.components["c1"] = Component(id="c1", ref="C1", type="capacitor", value="100nF", footprint="0603")
    d.nets["n1"] = Net(
        id="n1",
        name="VCC",
        nodes=[NetNode(component_ref="R1", pin_name="1"), NetNode(component_ref="C1", pin_name="1")],
    )
    return d


@pytest.fixture
def design_with_erc(design: Design) -> Design:
    from zaptrace.erc.models import ERCResult

    # Use object.__setattr__ since erc_result is not a declared Design field
    object.__setattr__(
        design,
        "erc_result",
        ERCResult.from_violations(
            violations=[
                ERCViolation(
                    rule_id="ERC001",
                    severity=ERCSeverity.WARNING,
                    message="Unconnected pin R1-2",
                )
            ],
            design_name="ReviewBoard",
        ),
    )
    return design


@pytest.fixture
def design_with_drc(design: Design) -> Design:
    design.drc_result = DRCResult(
        design_name="ReviewBoard",
        violations=[
            DRCViolation(
                rule_id="DRC001",
                severity="error",  # type: ignore[arg-type]
                message="Track too close to board edge",
            ),
        ],
    )
    return design


@pytest.fixture
def baseline() -> Design:
    d = Design(meta=DesignMeta(name="ReviewBoard_base"))
    d.components["r1"] = Component(id="r1", ref="R1", type="resistor", value="10k", footprint="0603")
    return d


# ---------------------------------------------------------------------------
# Panel aggregation tests
# ---------------------------------------------------------------------------


class TestCollectPanels:
    def test_erc_panel_empty(self, design: Design) -> None:
        panels = collect_panels(design, panel_ids=["erc"])
        p = panels["erc"]
        assert p.panel_id == "erc"
        assert p.status == "pass"
        assert "No ERC violations" in p.summary

    def test_erc_panel_with_violations(self, design_with_erc: Design) -> None:
        panels = collect_panels(design_with_erc, panel_ids=["erc"])
        p = panels["erc"]
        assert p.status == "warning"
        assert len(p.items) == 1
        assert p.items[0]["rule_id"] == "ERC001"

    def test_drc_panel_with_violations(self, design_with_drc: Design) -> None:
        panels = collect_panels(design_with_drc, panel_ids=["drc"])
        p = panels["drc"]
        assert p.status == "fail"
        assert len(p.items) >= 1

    def test_bom_panel(self, design: Design) -> None:
        panels = collect_panels(design, panel_ids=["bom"])
        p = panels["bom"]
        assert p.panel_id == "bom"
        assert p.summary.startswith("2 line items")  # R1 + C1
        assert "export_csv" in p.actions

    def test_supply_panel_empty(self, design: Design) -> None:
        panels = collect_panels(design, panel_ids=["supply"])
        p = panels["supply"]
        assert p.status == "info"

    def test_assumptions_panel_surfaces_confirmation_risk(self, design: Design) -> None:
        object.__setattr__(
            design,
            "architecture_artifact",
            {
                "assumptions": [
                    {
                        "id": "ASM-1",
                        "text": "Antenna keepout remains valid for the selected enclosure",
                        "requires_confirmation": True,
                        "risk_level": "high",
                    }
                ]
            },
        )

        panel = collect_panels(design, panel_ids=["assumptions"])["assumptions"]

        assert panel.status == "warning"
        assert panel.items[0]["id"] == "ASM-1"
        assert panel.items[0]["requires_confirmation"] is True

    def test_proof_pack_panel_exposes_artifact_hashes(self, design: Design) -> None:
        object.__setattr__(
            design,
            "proof_manifest",
            {
                "check_records": [{"name": "erc", "status": "pass"}],
                "artifacts": [
                    {
                        "artifact_id": "gerber-top",
                        "path": "gerbers/top.gtl",
                        "sha256": "a" * 64,
                    }
                ],
            },
        )

        panel = collect_panels(design, panel_ids=["proof_pack"])["proof_pack"]

        artifact = next(item for item in panel.items if item.get("kind") == "artifact")
        assert artifact["artifact_id"] == "gerber-top"
        assert artifact["sha256"] == "a" * 64

    def test_proof_pack_panel_accepts_model_dump_sources_and_blocking_checks(self, design: Design) -> None:
        class ProofFixture:
            def model_dump(self, *, mode: str) -> dict:
                assert mode == "json"
                return {
                    "check_records": [{"name": "drc", "status": "fail"}],
                    "artifacts": [],
                }

        object.__setattr__(design, "proof_manifest", ProofFixture())

        panel = collect_panels(design, panel_ids=["proof_pack"])["proof_pack"]

        assert panel.status == "fail"
        assert panel.summary == "1 check(s), 0 artifact(s)"

    def test_assumptions_panel_accepts_model_dump_sources(self, design: Design) -> None:
        class ArchitectureFixture:
            def model_dump(self, *, mode: str) -> dict:
                assert mode == "json"
                return {
                    "assumptions": [
                        {
                            "id": "ASM-2",
                            "text": "Prototype enclosure material is provisional",
                            "confirmed": False,
                        }
                    ]
                }

        object.__setattr__(design, "architecture_artifact", ArchitectureFixture())

        panel = collect_panels(design, panel_ids=["assumptions"])["assumptions"]

        assert panel.status == "warning"
        assert panel.actions == ["confirm_assumption", "request_evidence"]

    def test_all_panels_returned(self, design: Design) -> None:
        panels = collect_panels(design)
        expected = {
            "requirements",
            "assumptions",
            "erc",
            "drc",
            "dfm",
            "bom",
            "supply",
            "manufacturing",
            "simulation",
            "layout_quality",
            "proof_pack",
            "decision_log",
        }
        assert expected.issubset(set(panels.keys()))

    def test_review_bundle_requires_layout_review_without_physical_evidence(self, design: Design) -> None:
        bundle = collect_review_bundle(design)
        assert bundle.design_name == "ReviewBoard"
        assert bundle.overall_status == "warning"
        assert bundle.panels["layout_quality"].status == "warning"
        assert len(bundle.non_claims) >= 2

    def test_review_bundle_overall_fail(self, design_with_drc: Design) -> None:
        bundle = collect_review_bundle(design_with_drc)
        assert bundle.overall_status == "fail"

    def test_state_hash_in_bundle(self, design: Design) -> None:
        bundle = collect_review_bundle(design)
        assert bundle.design_state_hash != ""


# ---------------------------------------------------------------------------
# Workflow tests
# ---------------------------------------------------------------------------


class TestReviewWorkflow:
    def test_create_session(self) -> None:
        rs = create_review_session("MyDesign", "abc123")
        assert rs.session_id.startswith("session-")
        assert rs.design_name == "MyDesign"
        assert len(rs.checklist) >= 8
        assert all(item.status == ChecklistStatus.PENDING for item in rs.checklist.values())

    def test_approve_item(self) -> None:
        rs = create_review_session("TestDesign")
        item_id = list(rs.checklist.keys())[0]
        result = approve_checklist_item(rs, item_id, decided_by="alice", reason="Looks good")
        assert result.status == ChecklistStatus.APPROVED
        assert result.decided_by == "alice"
        assert rs.updated_at != rs.created_at

    def test_reject_item(self) -> None:
        rs = create_review_session("TestDesign")
        item_id = list(rs.checklist.keys())[0]
        result = reject_checklist_item(rs, item_id, decided_by="bob", reason="Missing evidence")
        assert result.status == ChecklistStatus.REJECTED

    def test_waive_item(self) -> None:
        rs = create_review_session("TestDesign")
        item_id = list(rs.checklist.keys())[0]
        result = add_waiver(rs, item_id, decided_by="carol", reason="Non-critical", waiver_notes="Accepting risk")
        assert result.status == ChecklistStatus.WAIVED

    def test_approve_all_approved(self) -> None:
        rs = create_review_session("TestDesign")
        assert not rs.all_approved
        for item_id in rs.checklist:
            approve_checklist_item(rs, item_id, decided_by="alice")
        assert rs.all_approved

    def test_any_rejected(self) -> None:
        rs = create_review_session("TestDesign")
        assert not rs.any_rejected
        item_id = list(rs.checklist.keys())[0]
        reject_checklist_item(rs, item_id, decided_by="bob")
        assert rs.any_rejected

    def test_approve_decision(self) -> None:
        rs = create_review_session("ProdDesign")
        for item_id in rs.checklist:
            approve_checklist_item(rs, item_id, decided_by="alice")
        rec = resolve_decision(rs, DecisionType.APPROVE, decided_by="alice", reason="All clear")
        assert rec.decision == DecisionType.APPROVE
        assert rec.approval_id.startswith("approval-")
        assert len(rs.decisions) == 1

    def test_reject_decision(self) -> None:
        rs = create_review_session("FailDesign")
        rec = resolve_decision(rs, DecisionType.REJECT, decided_by="bob", reason="Blocking violations")
        assert rec.decision == DecisionType.REJECT
        assert rec.approval_id == ""

    def test_rollback_decision(self) -> None:
        rs = create_review_session("RollbackDesign")
        rec = resolve_decision(rs, DecisionType.ROLLBACK, decided_by="carol", reason="Wrong assumptions")
        assert rec.decision == DecisionType.ROLLBACK

    def test_unknown_item_raises(self) -> None:
        rs = create_review_session("TestDesign")
        with pytest.raises(KeyError):
            approve_checklist_item(rs, "nonexistent")

    def test_approve_requires_all_blocking_items_to_be_resolved(self) -> None:
        rs = create_review_session("GuardedDesign", "state-123")

        with pytest.raises(ReviewTransitionError, match="blocking checklist"):
            resolve_decision(rs, DecisionType.APPROVE, decided_by="reviewer-a", reason="Looks ready")

    def test_request_repair_is_state_bound_and_never_approves(self) -> None:
        rs = create_review_session("RepairDesign", "state-repair")

        rec = resolve_decision(
            rs,
            DecisionType.REQUEST_REPAIR,
            decided_by="reviewer-a",
            reason="Move the decoupling capacitor closer to U1",
        )

        assert rec.review_session_id == rs.session_id
        assert rec.design_state_hash == "state-repair"
        assert rec.approval_id == ""
        assert rs.status == ReviewStatus.REPAIR_REQUESTED

    def test_accept_risk_requires_explicit_waiver_and_rationale(self) -> None:
        rs = create_review_session("RiskDesign", "state-risk", panel_ids=["erc", "simulation"])
        approve_checklist_item(rs, "erc-review", decided_by="reviewer-a", reason="ERC clean")

        with pytest.raises(ReviewTransitionError, match="explicit waiver"):
            resolve_decision(
                rs,
                DecisionType.ACCEPT_RISK,
                decided_by="reviewer-a",
                reason="Accepting the unsupported simulation domain",
            )

        add_waiver(
            rs,
            "simulation-review",
            decided_by="reviewer-a",
            reason="Model unavailable",
            waiver_notes="Prototype-only run",
        )
        rec = resolve_decision(
            rs,
            DecisionType.ACCEPT_RISK,
            decided_by="reviewer-a",
            reason="Accepting the documented prototype risk",
            waiver_notes="Do not use for production fabrication",
        )

        assert rec.approval_id.startswith("approval-")
        assert rs.status == ReviewStatus.RISK_ACCEPTED

    def test_finalized_review_session_is_immutable(self) -> None:
        rs = create_review_session("ImmutableDesign", "state-final", panel_ids=["erc"])
        approve_checklist_item(rs, "erc-review", decided_by="reviewer-a", reason="ERC clean")
        resolve_decision(rs, DecisionType.APPROVE, decided_by="reviewer-a", reason="Approved")

        with pytest.raises(ReviewTransitionError, match="finalized"):
            reject_checklist_item(rs, "erc-review", decided_by="reviewer-b", reason="Changed mind")
        with pytest.raises(ReviewTransitionError, match="finalized"):
            resolve_decision(rs, DecisionType.REJECT, decided_by="reviewer-b", reason="Changed mind")

    def test_review_status_distinguishes_human_approval_from_pending(self) -> None:
        rs = create_review_session("StatusDesign", "state-status", panel_ids=["erc"])
        assert rs.status == ReviewStatus.PENDING

        approve_checklist_item(rs, "erc-review", decided_by="reviewer-a", reason="ERC clean")
        resolve_decision(rs, DecisionType.APPROVE, decided_by="reviewer-a", reason="Approved")

        assert rs.status == ReviewStatus.HUMAN_APPROVED

    def test_review_session_persists_and_hydrates_after_restart(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path / "state"))
        design_session_id = "persistent-review-session"
        rs = create_review_session(
            "PersistentReview",
            "state-persistent",
            panel_ids=["erc"],
            design_session_id=design_session_id,
            owner_principal="review-owner",
        )
        approve_checklist_item(rs, "erc-review", decided_by="review-owner", reason="ERC evidence reviewed")
        decision = resolve_decision(
            rs,
            DecisionType.APPROVE,
            decided_by="review-owner",
            reason="Current design state approved",
        )

        _REVIEW_SESSIONS.clear()
        restored = get_review_session(rs.session_id, design_session_id=design_session_id)

        assert restored is not None
        assert restored.session_id == rs.session_id
        assert restored.design_state_hash == "state-persistent"
        assert restored.checklist["erc-review"].status == ChecklistStatus.APPROVED
        assert restored.latest_decision is not None
        assert restored.latest_decision.decision_id == decision.decision_id
        assert restored.latest_decision.approval_id == decision.approval_id
        assert restored.status == ReviewStatus.HUMAN_APPROVED

    def test_review_persistence_disabled_is_explicitly_process_local(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path / "state"))
        monkeypatch.setenv("ZAPTRACE_PERSISTENCE_DISABLED", "1")
        review = create_review_session(
            "DisabledPersistenceReview",
            "state-disabled",
            panel_ids=["erc"],
            design_session_id="disabled-parent",
        )

        assert get_review_state_store() is None
        _REVIEW_SESSIONS.clear()
        assert get_review_session(review.session_id, design_session_id="disabled-parent") is None
        assert review_sessions_for_design_session("disabled-parent", _REVIEW_SESSIONS) == []

    def test_parentless_review_is_not_durable(self) -> None:
        review = create_review_session("ParentlessReview", "state-parentless", panel_ids=["erc"])

        _REVIEW_SESSIONS.clear()

        assert hydrate_review_session(review.session_id, "", _REVIEW_SESSIONS) is None

    def test_hydration_skips_unrelated_durable_records(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path / "state"))
        create_review_session(
            "StoredReview",
            "state-stored",
            panel_ids=["erc"],
            design_session_id="stored-parent",
        )
        _REVIEW_SESSIONS.clear()

        restored = hydrate_review_session("missing-review", "stored-parent", _REVIEW_SESSIONS)

        assert restored is None
        assert _REVIEW_SESSIONS == {}

    def test_review_session_listing_merges_cache_and_durable_records(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path / "state"))
        cached = create_review_session(
            "CachedReview",
            "state-cache",
            panel_ids=["erc"],
            design_session_id="shared-parent",
        )
        durable = create_review_session(
            "DurableReview",
            "state-durable",
            panel_ids=["erc"],
            design_session_id="shared-parent",
        )
        del _REVIEW_SESSIONS[durable.session_id]

        sessions = review_sessions_for_design_session("shared-parent", _REVIEW_SESSIONS)

        assert {session.session_id for session in sessions} == {cached.session_id, durable.session_id}
        assert durable.session_id in _REVIEW_SESSIONS

    def test_terminal_decision_requires_authenticated_identity_and_rationale(self) -> None:
        review = create_review_session("IdentityReview", "state-identity", panel_ids=["erc"])
        approve_checklist_item(review, "erc-review", decided_by="reviewer-a", reason="ERC clean")

        with pytest.raises(ReviewTransitionError, match="identity"):
            resolve_decision(review, DecisionType.APPROVE, decided_by="", reason="Approved")
        with pytest.raises(ReviewTransitionError, match="rationale"):
            resolve_decision(review, DecisionType.APPROVE, decided_by="reviewer-a", reason="")

    def test_review_cleanup_reports_durable_children_after_restart(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path / "state"))
        review = create_review_session(
            "DurableCleanupReview",
            "state-cleanup",
            panel_ids=["erc"],
            design_session_id="durable-cleanup-parent",
        )
        _REVIEW_SESSIONS.clear()

        removed = remove_review_sessions_for_design_session("durable-cleanup-parent")

        assert removed == [review.session_id]
        assert review.session_id not in _REVIEW_SESSIONS

    def test_review_cleanup_is_scoped_to_parent_design_session(self) -> None:
        first = create_review_session(
            "FirstReview",
            "state-first",
            panel_ids=["erc"],
            design_session_id="parent-first",
        )
        second = create_review_session(
            "SecondReview",
            "state-second",
            panel_ids=["erc"],
            design_session_id="parent-second",
        )

        removed = remove_review_sessions_for_design_session("parent-first")

        assert removed == [first.session_id]
        assert first.session_id not in _REVIEW_SESSIONS
        assert second.session_id in _REVIEW_SESSIONS

    def test_missing_reject_and_waiver_items_raise(self) -> None:
        review = create_review_session("MissingItemReview", panel_ids=["erc"])

        with pytest.raises(KeyError, match="missing"):
            reject_checklist_item(review, "missing", decided_by="reviewer-a", reason="Reject")
        with pytest.raises(KeyError, match="missing"):
            add_waiver(review, "missing", decided_by="reviewer-a", reason="Waive")

    def test_accept_risk_rejects_unresolved_blocking_items(self) -> None:
        review = create_review_session("UnresolvedRisk", panel_ids=["erc", "simulation"])
        add_waiver(
            review,
            "simulation-review",
            decided_by="reviewer-a",
            reason="Model unavailable",
            waiver_notes="Prototype only",
        )

        with pytest.raises(ReviewTransitionError, match="blocking checklist"):
            resolve_decision(
                review,
                DecisionType.ACCEPT_RISK,
                decided_by="reviewer-a",
                reason="Accept prototype risk",
            )


# ---------------------------------------------------------------------------
# API route tests (via TestClient)
# ---------------------------------------------------------------------------


client = TestClient(app)
_SESSION_HEADERS = {
    "X-ZapTrace-Session-Id": "test-session",
    "X-ZapTrace-Capabilities": "preview-write, sandbox-write, approved-commit, release-export",
}


def _load_design_via_api(client: TestClient, name: str = "ApiDesign") -> None:
    yaml = f"""
meta:
  name: {name}
components:
  r1:
    ref: R1
    type: resistor
    value: 10k
    footprint: "0603"
  c1:
    ref: C1
    type: capacitor
    value: 100nF
    footprint: "0603"
nets:
  n1:
    name: VCC
    nodes:
      - component_ref: R1
        pin_name: "1"
      - component_ref: C1
        pin_name: "1"
"""
    resp = client.post("/api/v1/designs/parse/str", params={"yaml_content": yaml}, headers=_SESSION_HEADERS)
    assert resp.status_code == 200, resp.text


def _start_review_via_api(name: str = "ApiDesign") -> dict:
    _load_design_via_api(client, name)
    response = client.post(f"/api/v1/review/session/{name}", headers=_SESSION_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()["session"]


def _approve_all_review_items(session: dict, *, spoofed_actor: str = "spoofed-reviewer") -> None:
    session_id = session["session_id"]
    for item_id in session["checklist"]:
        response = client.post(
            f"/api/v1/review/session/{session_id}/checklist/{item_id}/approve",
            params={"decided_by": spoofed_actor, "reason": "Evidence reviewed"},
            headers=_SESSION_HEADERS,
        )
        assert response.status_code == 200, response.text
        assert response.json()["item"]["decided_by"] == "local-development"


class TestReviewApi:
    def test_bundle_endpoint(self) -> None:
        _load_design_via_api(client)
        resp = client.get("/api/v1/review/bundle/ApiDesign", headers=_SESSION_HEADERS)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        bundle = data["bundle"]
        assert bundle["design_name"] == "ApiDesign"
        assert "erc" in bundle["panels"]
        assert "bom" in bundle["panels"]

    def test_panels_endpoint_subset(self) -> None:
        _load_design_via_api(client)
        resp = client.get("/api/v1/review/bundle/ApiDesign/panels?panel_ids=erc,bom", headers=_SESSION_HEADERS)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert set(data["panels"].keys()) == {"erc", "bom"}

    def test_start_review_session(self) -> None:
        _load_design_via_api(client)
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert data["session"]["session_id"].startswith("session-")
        assert len(data["session"]["checklist"]) >= 8
        assert data["session"]["review_status"] == "human-review-required"
        assert data["session"]["finalized"] is False

    def test_review_workflow_via_api(self) -> None:
        _load_design_via_api(client)
        # Start session
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        session_id = resp.json()["session"]["session_id"]
        item_id = list(resp.json()["session"]["checklist"].keys())[0]

        # Approve item
        resp = client.post(
            f"/api/v1/review/session/{session_id}/checklist/{item_id}/approve",
            params={"decided_by": "test-user", "reason": "Looks good"},
            headers=_SESSION_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["item"]["status"] == "approved"

        # Get session
        resp = client.get(f"/api/v1/review/session/{session_id}", headers=_SESSION_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["session"]["review_status"] == "human-review-required"
        assert resp.json()["session"]["finalized"] is False

    def test_reject_via_api(self) -> None:
        _load_design_via_api(client)
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        session_id = resp.json()["session"]["session_id"]
        item_id = list(resp.json()["session"]["checklist"].keys())[0]

        resp = client.post(
            f"/api/v1/review/session/{session_id}/checklist/{item_id}/reject",
            params={"decided_by": "test-user", "reason": "Not acceptable"},
            headers=_SESSION_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["item"]["status"] == "rejected"

    def test_waive_via_api(self) -> None:
        _load_design_via_api(client)
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        session_id = resp.json()["session"]["session_id"]
        item_id = list(resp.json()["session"]["checklist"].keys())[0]

        resp = client.post(
            f"/api/v1/review/session/{session_id}/checklist/{item_id}/waive",
            params={"decided_by": "test-user", "reason": "Low risk", "waiver_notes": "Accepting"},
            headers=_SESSION_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["item"]["status"] == "waived"

    def test_decide_approve_via_api_uses_authenticated_principal(self) -> None:
        review = _start_review_via_api()
        _approve_all_review_items(review)

        resp = client.post(
            f"/api/v1/review/session/{review['session_id']}/decide",
            params={"decision": "approve", "decided_by": "spoofed-lead", "reason": "Release ready"},
            headers=_SESSION_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"]["decision"] == "approve"
        assert data["decision"]["decided_by"] == "local-development"
        assert data["decision"]["approval_id"].startswith("approval-")
        assert data["review_status"] == "human-approved"

        fetched = client.get(
            f"/api/v1/review/session/{review['session_id']}",
            headers=_SESSION_HEADERS,
        )
        assert fetched.status_code == 200
        assert fetched.json()["session"]["review_status"] == "human-approved"
        assert fetched.json()["session"]["finalized"] is True

    def test_decide_approve_returns_conflict_before_blocking_items_are_resolved(self) -> None:
        review = _start_review_via_api("BlockedApproval")

        resp = client.post(
            f"/api/v1/review/session/{review['session_id']}/decide",
            params={"decision": "approve", "reason": "Premature approval"},
            headers=_SESSION_HEADERS,
        )

        assert resp.status_code == 409
        assert "blocking checklist" in resp.json()["detail"]

    def test_request_repair_via_api_records_authenticated_reviewer(self) -> None:
        review = _start_review_via_api("RepairApiDesign")

        resp = client.post(
            f"/api/v1/review/session/{review['session_id']}/decide",
            params={
                "decision": "request-repair",
                "decided_by": "spoofed-reviewer",
                "reason": "Move C1 next to the regulator input",
            },
            headers=_SESSION_HEADERS,
        )

        assert resp.status_code == 200, resp.text
        decision = resp.json()["decision"]
        assert decision["decision"] == "request-repair"
        assert decision["decided_by"] == "local-development"
        assert decision["approval_id"] == ""
        assert resp.json()["review_status"] == "repair-requested"

    def test_accept_risk_via_api_requires_explicit_waiver(self) -> None:
        review = _start_review_via_api("RiskApiDesign")
        session_id = review["session_id"]
        for item_id in review["checklist"]:
            endpoint = "waive" if item_id == "simulation-review" else "approve"
            resp = client.post(
                f"/api/v1/review/session/{session_id}/checklist/{item_id}/{endpoint}",
                params={
                    "decided_by": "spoofed-reviewer",
                    "reason": "Model unavailable" if endpoint == "waive" else "Evidence reviewed",
                    "waiver_notes": "Prototype-only" if endpoint == "waive" else "",
                },
                headers=_SESSION_HEADERS,
            )
            assert resp.status_code == 200, resp.text

        resp = client.post(
            f"/api/v1/review/session/{session_id}/decide",
            params={
                "decision": "accept-risk",
                "decided_by": "spoofed-lead",
                "reason": "Accept documented prototype-only simulation risk",
                "waiver_notes": "Not approved for production fabrication",
            },
            headers=_SESSION_HEADERS,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["decision"]["decided_by"] == "local-development"
        assert resp.json()["review_status"] == "risk-accepted"

    def test_decide_reject_via_api(self) -> None:
        _load_design_via_api(client)
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        session_id = resp.json()["session"]["session_id"]

        resp = client.post(
            f"/api/v1/review/session/{session_id}/decide",
            params={"decision": "reject", "decided_by": "lead", "reason": "Unresolved violations"},
            headers=_SESSION_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["decision"]["decision"] == "reject"
        assert resp.json()["decision"]["decided_by"] == "local-development"
        assert resp.json()["review_status"] == "rejected"

    @pytest.mark.parametrize("endpoint", ["approve", "reject", "waive"])
    def test_unknown_checklist_item_returns_not_found(self, endpoint: str) -> None:
        review = _start_review_via_api(f"UnknownItem-{endpoint}")

        response = client.post(
            f"/api/v1/review/session/{review['session_id']}/checklist/missing/{endpoint}",
            params={"reason": "No such item", "waiver_notes": "Not applicable"},
            headers=_SESSION_HEADERS,
        )

        assert response.status_code == 404
        assert "Checklist item not found" in response.json()["detail"]

    def test_finalized_session_rejects_api_mutation(self) -> None:
        review = _start_review_via_api("FinalizedApiReview")
        _approve_all_review_items(review)
        decision = client.post(
            f"/api/v1/review/session/{review['session_id']}/decide",
            params={"decision": "approve", "reason": "Approved"},
            headers=_SESSION_HEADERS,
        )
        assert decision.status_code == 200

        mutation = client.post(
            f"/api/v1/review/session/{review['session_id']}/checklist/erc-review/reject",
            params={"reason": "Changed mind"},
            headers=_SESSION_HEADERS,
        )

        assert mutation.status_code == 409
        assert "finalized" in mutation.json()["detail"]

    def test_terminal_decision_without_rationale_returns_conflict(self) -> None:
        review = _start_review_via_api("MissingRationaleApiReview")

        response = client.post(
            f"/api/v1/review/session/{review['session_id']}/decide",
            params={"decision": "reject"},
            headers=_SESSION_HEADERS,
        )

        assert response.status_code == 409
        assert "rationale" in response.json()["detail"]

    @pytest.mark.parametrize("decision", ["invalid_decision", "waive"])
    def test_decide_invalid_decision(self, decision: str) -> None:
        _load_design_via_api(client)
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        session_id = resp.json()["session"]["session_id"]

        resp = client.post(
            f"/api/v1/review/session/{session_id}/decide",
            params={"decision": decision},
            headers=_SESSION_HEADERS,
        )
        assert resp.status_code == 400

    def test_session_not_found(self) -> None:
        resp = client.get("/api/v1/review/session/nonexistent", headers=_SESSION_HEADERS)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "OBJECT_NOT_AUTHORIZED"

    def test_diff_endpoint(self) -> None:
        _load_design_via_api(client, "DesignA")
        _load_design_via_api(client, "DesignB")
        resp = client.get("/api/v1/review/diff/DesignA/DesignB", headers=_SESSION_HEADERS)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert "changes" in data


def test_benchmark_panel_no_evidence_is_info(design: Design) -> None:
    panels = collect_panels(design, panel_ids=["benchmark"])
    panel = panels["benchmark"]

    assert panel.status == "info"
    assert panel.summary == "No benchmark evidence"
    assert any(item.get("kind") == "non_claim" for item in panel.items)


def test_benchmark_panel_passes_clean_report(design: Design) -> None:
    object.__setattr__(
        design,
        "benchmark_report",
        {
            "passed": True,
            "caught_count": 3,
            "missed_count": 0,
            "results": [{"mutation_id": "MUT-001", "caught": True}],
            "non_claims": ["Benchmark pass is regression evidence only."],
        },
    )

    panel = collect_panels(design, panel_ids=["benchmark"])["benchmark"]

    assert panel.status == "pass"
    assert "3 caught / 0 missed" in panel.summary
    assert any(item.get("message") == "Benchmark pass is regression evidence only." for item in panel.items)


def test_benchmark_panel_surfaces_blocking_missed_failure(design: Design) -> None:
    object.__setattr__(
        design,
        "benchmark_report",
        {
            "passed": False,
            "caught_count": 2,
            "missed_count": 1,
            "results": [
                {"mutation_id": "MUT-001", "caught": True},
                {"mutation_id": "MUT-002", "caught": False, "expected_detector": "current-density.violation"},
            ],
            "non_claims": ["Human review remains required before fabrication."],
        },
    )

    panel = collect_panels(design, panel_ids=["benchmark"])["benchmark"]
    bundle = collect_review_bundle(design, panel_ids=["benchmark"])

    assert panel.status == "fail"
    assert "2 caught / 1 missed" in panel.summary
    assert any(item.get("caught") is False for item in panel.items)
    assert any(item.get("kind") == "non_claim" for item in panel.items)
    assert bundle.overall_status == "fail"


def test_benchmark_panel_uses_result_fallback_and_normalizes_items(design: Design) -> None:
    object.__setattr__(
        design,
        "benchmark_result",
        {
            "cases": ["external evidence unavailable", {"status": "pass"}],
        },
    )

    panel = collect_panels(design, panel_ids=["benchmark"])["benchmark"]

    assert panel.status == "pass"
    assert panel.summary == "0 blocking benchmark item(s)"
    assert {"message": "external evidence unavailable"} in panel.items
    assert any(item.get("message") == "Benchmark evidence does not imply fabrication approval." for item in panel.items)


def test_review_session_includes_benchmark_checklist_item() -> None:
    session = create_review_session("BenchmarkReview")

    assert "benchmark-review" in session.checklist
    assert session.checklist["benchmark-review"].panel_id == "benchmark"


def test_dfm_panel_helpers_preserve_severity_precedence(design: Design) -> None:
    assert _review_status_for_severity("pass", "info") == "pass"
    assert _review_status_for_severity("pass", "warning") == "warning"
    assert _review_status_for_severity("warning", "error") == "fail"
    assert _review_status_for_severity("fail", "warning") == "fail"

    class Finding:
        def __init__(self, severity: str, message: str) -> None:
            self.severity = severity
            self.message = message

        def model_dump(self, *, mode: str) -> dict[str, str]:
            assert mode == "json"
            return {"severity": self.severity, "message": self.message}

    class Result:
        profile_name = "fixture-profile"
        findings = [Finding("warning", "review"), Finding("error", "block")]

    object.__setattr__(design, "dfm_result", [Result()])
    items, status = _dfm_panel_items(design)
    assert status == "fail"
    assert [item["profile"] for item in items] == ["fixture-profile", "fixture-profile"]
    panel = collect_panels(design, panel_ids=["dfm"])["dfm"]
    assert panel.status == "fail"
    assert panel.summary == "2 finding(s)"
