"""Tests for transaction-safe design state."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from zaptrace.agent import _tool_impls as tools
from zaptrace.core.state import design_state_hash

_DESIGN_YAML = """meta:
  name: TxDesign
components:
  r1:
    ref: R1
    type: resistor
    value: 10k
"""


def setup_function() -> None:
    tools._sessions.clear()


def _load_design(session_id: str = "tx-test") -> None:
    tools.tool_design_parse_str(_DESIGN_YAML, session_id=session_id)


def test_preview_transaction_returns_json_safe_semantic_diff_without_mutating_primary() -> None:
    _load_design()
    before = tools._get_session("tx-test")["designs"]["TxDesign"]
    before_hash = design_state_hash(before)

    preview = tools.tool_design_transaction_preview(
        "TxDesign",
        "board_update",
        {"width_mm": 120},
        reason="try a wider board",
        session_id="tx-test",
    )

    assert preview["state"] == "previewed"
    assert preview["parent_state_hash"] == before_hash
    assert preview["preview_state_hash"] != before_hash
    assert preview["semantic_diff"][0]["type"] == "board_changed"
    assert preview["semantic_diff"][0]["ref"] == "board"
    json.dumps(preview)

    current = tools._get_session("tx-test")["designs"]["TxDesign"]
    assert current.board.width_mm == 100.0
    assert design_state_hash(current) == before_hash


def test_validate_and_commit_transaction_requires_explicit_approval() -> None:
    _load_design()
    preview = tools.tool_design_transaction_preview(
        "TxDesign",
        "board_update",
        {"width_mm": 120},
        session_id="tx-test",
    )
    validated = tools.tool_design_transaction_validate(preview["transaction_id"], session_id="tx-test")
    assert validated["state"] == "validated"
    assert validated["validation"]["status"] == "passed"

    with pytest.raises(ValueError, match="approval_id is required"):
        tools.tool_design_transaction_commit(preview["transaction_id"], approval_id="", session_id="tx-test")

    committed = tools.tool_design_transaction_commit(
        preview["transaction_id"],
        approval_id="approval-123",
        session_id="tx-test",
    )
    assert committed["state"] == "committed"
    assert committed["approval_id"] == "approval-123"
    design = tools._get_session("tx-test")["designs"]["TxDesign"]
    assert design.board.width_mm == 120.0
    assert committed["committed_state_hash"] == design_state_hash(design)
    assert tools._get_session("tx-test")["transaction_history"][-1]["state"] == "committed"


def test_rollback_rejects_preview_without_mutating_primary() -> None:
    _load_design()
    before = tools._get_session("tx-test")["designs"]["TxDesign"]
    before_hash = design_state_hash(before)
    preview = tools.tool_design_transaction_preview(
        "TxDesign",
        "component_add",
        {"component_id": "c1", "ref": "C1", "type_name": "capacitor", "value": "100n", "footprint": "0603"},
        session_id="tx-test",
    )

    rolled_back = tools.tool_design_transaction_rollback(preview["transaction_id"], session_id="tx-test")

    assert rolled_back["state"] == "rolled_back"
    design = tools._get_session("tx-test")["designs"]["TxDesign"]
    assert "c1" not in design.components
    assert design_state_hash(design) == before_hash


def test_failed_validation_rejects_transaction_and_keeps_primary_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _load_design()
    before = tools._get_session("tx-test")["designs"]["TxDesign"]
    before_hash = design_state_hash(before)
    preview = tools.tool_design_transaction_preview(
        "TxDesign",
        "board_update",
        {"layers": 4},
        session_id="tx-test",
    )

    class FakeRunner:
        def run(self, _design):
            return SimpleNamespace(passed=False, total_errors=1, total_warnings=0, total_info=0)

    monkeypatch.setattr(tools, "ERCRunner", FakeRunner)
    validated = tools.tool_design_transaction_validate(preview["transaction_id"], session_id="tx-test")

    assert validated["state"] == "rejected"
    assert validated["validation"]["status"] == "failed"
    design = tools._get_session("tx-test")["designs"]["TxDesign"]
    assert design.board.layers == 2
    assert design_state_hash(design) == before_hash


def test_primary_state_change_blocks_stale_transaction_commit() -> None:
    _load_design()
    preview = tools.tool_design_transaction_preview(
        "TxDesign",
        "board_update",
        {"width_mm": 120},
        session_id="tx-test",
    )
    tools.tool_design_transaction_validate(preview["transaction_id"], session_id="tx-test")
    # Mutate primary outside the transaction to simulate a stale preview.
    tools._get_session("tx-test")["designs"]["TxDesign"].board.width_mm = 130

    with pytest.raises(ValueError, match="Primary design state changed"):
        tools.tool_design_transaction_commit(
            preview["transaction_id"],
            approval_id="approval-123",
            session_id="tx-test",
        )


def test_design_commit_reports_exact_removed_snapshot_count() -> None:
    _load_design()
    tools.tool_design_snapshot("TxDesign", label="first", session_id="tx-test")
    tools.tool_design_snapshot("TxDesign", label="second", session_id="tx-test")

    committed = tools.tool_design_commit("TxDesign", session_id="tx-test")

    assert committed == {
        "design": "TxDesign",
        "removed_snapshots": 2,
        "remaining_snapshots": 0,
    }


def test_design_commit_removes_only_named_snapshot() -> None:
    _load_design()
    tools.tool_design_snapshot("TxDesign", label="first", session_id="tx-test")
    tools.tool_design_snapshot("TxDesign", label="second", session_id="tx-test")

    committed = tools.tool_design_commit("TxDesign", label="first", session_id="tx-test")

    assert committed["removed_snapshots"] == 1
    assert committed["remaining_snapshots"] == 1
    assert tools.tool_design_list_snapshots("TxDesign", session_id="tx-test")["snapshots"][0]["label"] == "second"


def test_preview_component_remove_uses_bounded_operation_dispatch() -> None:
    _load_design()

    preview = tools.tool_design_transaction_preview(
        "TxDesign",
        "component_remove",
        {"component_id": "r1"},
        session_id="tx-test",
    )

    assert preview["state"] == "previewed"
    assert preview["operation"] == "component_remove"
    assert any(entry["type"] == "component_removed" for entry in preview["semantic_diff"])
    assert "r1" in tools._get_session("tx-test")["designs"]["TxDesign"].components


def test_preview_rejects_unknown_transaction_operation() -> None:
    _load_design()

    with pytest.raises(ValueError, match="Unsupported transaction operation"):
        tools.tool_design_transaction_preview(
            "TxDesign",
            "unknown",
            {},
            session_id="tx-test",
        )


def test_snapshot_and_rollback_survive_process_restart(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path))
    session_id = "restart-snapshot"
    _load_design(session_id)
    tools.tool_design_snapshot("TxDesign", label="before-width", session_id=session_id)
    tools.tool_board_update("TxDesign", width_mm=145, session_id=session_id)

    tools._sessions.clear()
    snapshots = tools.tool_design_list_snapshots("TxDesign", session_id=session_id)
    assert [item["label"] for item in snapshots["snapshots"]] == ["before-width"]

    restored = tools.tool_design_rollback("TxDesign", "before-width", session_id=session_id)
    assert restored["restored_from"] == "before-width"
    tools._sessions.clear()
    assert tools.tool_design_inspect("TxDesign", session_id=session_id)["board"]["width_mm"] == 100.0


def test_transaction_lifecycle_survives_process_restarts(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path))
    session_id = "restart-transaction"
    _load_design(session_id)
    preview = tools.tool_design_transaction_preview(
        "TxDesign",
        "board_update",
        {"width_mm": 120},
        reason="restart-safe preview",
        session_id=session_id,
    )

    tools._sessions.clear()
    listed = tools.tool_design_transaction_list(session_id=session_id)
    assert listed["transactions"][0]["transaction_id"] == preview["transaction_id"]

    validated = tools.tool_design_transaction_validate(preview["transaction_id"], session_id=session_id)
    assert validated["state"] == "validated"
    tools._sessions.clear()

    committed = tools.tool_design_transaction_commit(
        preview["transaction_id"], approval_id="approval-restart", session_id=session_id
    )
    assert committed["state"] == "committed"
    tools._sessions.clear()
    assert tools.tool_design_inspect("TxDesign", session_id=session_id)["board"]["width_mm"] == 120.0
    history = tools._get_session(session_id)["transaction_history"]
    assert history[-1]["approval_id"] == "approval-restart"


def test_capability_audit_events_survive_process_restart(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from zaptrace.security.policy import record_audit_event

    monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path))
    session_id = "restart-audit"
    session = tools._get_session(session_id)
    record_audit_event(
        session,
        surface="test",
        session_id=session_id,
        actor="reviewer-a",
        tool="design_transaction_commit",
        capability="approved-commit",
        decision="allow",
        reason="restart test",
        metadata={"principal_id": "principal-a", "request_id": "request-a", "design_name": "TxDesign"},
    )

    tools._sessions.clear()
    events = tools.tool_audit_list_events(session_id=session_id)["events"]

    assert events[-1]["actor"] == "reviewer-a"
    assert events[-1]["metadata"]["request_id"] == "request-a"


def test_validation_evidence_includes_persistent_design_identity(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from zaptrace.erc.models import ERCResult

    monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path))
    session_id = "persistent-evidence"
    _load_design(session_id)
    session = tools._get_session(session_id)

    evidence = tools._record_erc_evidence(
        session,
        "TxDesign",
        ERCResult.from_violations([], "TxDesign"),
    )

    assert evidence["persistent_content_id"].startswith("sha256:")
    assert evidence["persistent_version_id"].startswith("version-")
