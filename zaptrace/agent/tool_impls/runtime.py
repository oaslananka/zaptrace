"""Shared session, path, library, and release-gate services for agent tools."""

from __future__ import annotations

import sys

from .deps import (
    Any,
    Autopilot,
    ERCResult,
    ERCRunner,
    LibraryLoader,
    Path,
    ReleaseEvidenceStatus,
    bind_release_approval,
    build_component_coverage,
    build_fab_profile_policy,
    build_release_evidence_identity,
    copy,
    make_design_mapping,
    os,
    release_design_state_hash,
    require_approved_fab_profile_policy,
    require_complete_component_coverage,
    require_current_validation,
)

_sessions: dict[str, dict[str, Any]] = {}
_library: LibraryLoader | None = None
_WORKSPACE: Path | None = None
_COMPATIBILITY_FACADE_MODULE = "zaptrace.agent._tool_impls"


def _get_erc_runner_type() -> Any:
    """Return the runner class, honoring compatibility-facade test overrides."""
    facade = sys.modules.get(_COMPATIBILITY_FACADE_MODULE)
    return getattr(facade, "ERCRunner", ERCRunner) if facade else ERCRunner


def _get_workspace() -> Path:
    """Return the sandboxed workspace root, honoring facade overrides."""
    global _WORKSPACE
    facade = sys.modules.get(_COMPATIBILITY_FACADE_MODULE)
    facade_value = getattr(facade, "_WORKSPACE", _WORKSPACE) if facade else _WORKSPACE
    if facade_value is not None:
        _WORKSPACE = Path(facade_value).resolve()
        return _WORKSPACE

    raw = os.environ.get("ZAPTRACE_WORKSPACE", "")
    _WORKSPACE = Path(raw).resolve() if raw else Path.cwd().resolve()
    if facade is not None:
        facade.__dict__["_WORKSPACE"] = _WORKSPACE
    return _WORKSPACE


def _validate_path(path: str | Path, must_exist: bool = False) -> Path:
    """Validate that *path* is inside the sandboxed workspace.

    Raises ``ValueError`` (user-facing) on:
      - Absolute paths outside the workspace root.
      - Relative paths that escape the workspace via ``..`` segments.
      - Symlinks that resolve outside the workspace.
      - Non-existent files (when *must_exist*).

    Returns the normalized absolute ``Path``.
    """
    workspace = os.path.realpath(os.fspath(_get_workspace()))
    raw_path = os.fspath(path)
    candidate = raw_path if os.path.isabs(raw_path) else os.path.join(workspace, raw_path)
    try:
        normalized = os.path.realpath(candidate, strict=must_exist)
    except OSError:
        if must_exist:
            raise ValueError(f"Path not found: {path}") from None
        normalized = os.path.realpath(candidate)

    try:
        inside_workspace = os.path.commonpath((workspace, normalized)) == workspace
    except ValueError:
        inside_workspace = False
    if not inside_workspace:
        raise ValueError(f"Path outside workspace: {path}")
    return Path(normalized)


def _get_autopilot() -> Autopilot:
    return Autopilot()


def _get_library() -> LibraryLoader:
    global _library
    facade = sys.modules.get(_COMPATIBILITY_FACADE_MODULE)
    facade_value = getattr(facade, "_library", _library) if facade else _library
    if facade_value is not None:
        _library = facade_value
        return facade_value
    library = LibraryLoader()
    _library = library
    if facade is not None:
        facade.__dict__["_library"] = library
    return library


def _get_state_store() -> Any | None:
    """Return the configured durable state store, if persistence is enabled."""
    if os.environ.get("ZAPTRACE_PERSISTENCE_DISABLED") == "1":
        return None
    from zaptrace.core.session_store import session_store_root

    root = session_store_root()
    if root is None:
        return None
    from zaptrace.core.state_store import SQLiteStateStore

    return SQLiteStateStore(root)


def _persistent_design_identity(session: dict[str, Any], design_name: str) -> dict[str, Any]:
    designs = session.get("designs", {})
    store = getattr(designs, "store", None)
    session_id = str(getattr(designs, "session_id", ""))
    current_identity = getattr(store, "current_design_identity", None)
    if not session_id or not callable(current_identity):
        return {}
    identity = current_identity(session_id, design_name)
    if identity is None:
        return {}
    content_id = str(getattr(identity, "content_id", ""))
    version_id = str(getattr(identity, "version_id", ""))
    if not content_id or not version_id:
        return {}
    return {
        "persistent_content_id": content_id,
        "persistent_version_id": version_id,
    }


def _set_design(session: dict[str, Any], design_name: str, design: Any, *, operation: str) -> None:
    """Commit one design with an explicit lineage operation when available."""
    designs = session.setdefault("designs", {})
    commit_design = getattr(designs, "commit_design", None)
    if callable(commit_design):
        commit_design(design_name, design, operation=operation)
    else:
        designs[design_name] = design


def _json_safe(value: Any) -> Any:
    """Convert known runtime values into deterministic JSON-compatible evidence."""
    from dataclasses import asdict, is_dataclass
    from enum import Enum

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    return {"unrestorable_type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _persist_snapshot(
    session_id: str,
    design_name: str,
    label: str,
    design: Any,
    ancillary: dict[str, Any],
) -> None:
    store = _get_state_store()
    if store is None:
        return
    store.upsert_design_record(
        session_id,
        "snapshot",
        f"{design_name}:{label}",
        design,
        {"label": label, "ancillary": _json_safe(ancillary)},
        design_name=design_name,
    )


def _persist_transaction(session_id: str, record: dict[str, Any]) -> None:
    store = _get_state_store()
    if store is None:
        return
    public = {key: _json_safe(value) for key, value in record.items() if key != "candidate_design"}
    candidate = record.get("candidate_design")
    if candidate is not None:
        store.upsert_design_record(
            session_id,
            "transaction",
            str(record["transaction_id"]),
            candidate,
            public,
            design_name=str(record.get("design_name") or ""),
        )
    else:
        store.upsert_session_record(
            session_id,
            "transaction",
            str(record["transaction_id"]),
            public,
            design_name=str(record.get("design_name") or ""),
        )


def _persist_transaction_history(session_id: str, record: dict[str, Any]) -> None:
    store = _get_state_store()
    if store is None:
        return
    store.upsert_session_record(
        session_id,
        "transaction-history",
        str(record["transaction_id"]),
        {key: _json_safe(value) for key, value in record.items() if key != "candidate_design"},
        design_name=str(record.get("design_name") or ""),
    )


def _delete_persistent_session(session_id: str) -> bool:
    store = _get_state_store()
    return bool(store and store.delete_session(session_id))


def _delete_persistent_record(session_id: str, record_type: str, record_id: str) -> bool:
    store = _get_state_store()
    return bool(store and store.delete_session_record(session_id, record_type, record_id))


def _delete_persistent_records(session_id: str, record_type: str, *, design_name: str | None = None) -> int:
    store = _get_state_store()
    return int(store.delete_session_records(session_id, record_type, design_name=design_name)) if store else 0


def _persist_evidence_record(
    session: dict[str, Any],
    design_name: str,
    record_type: str,
    metadata: dict[str, Any],
    *,
    protected: bool = False,
) -> None:
    designs = session.get("designs", {})
    session_id = str(getattr(designs, "session_id", ""))
    store = _get_state_store()
    if store is None or not session_id:
        return
    store.upsert_session_record(
        session_id,
        record_type,
        design_name,
        _json_safe(metadata),
        design_name=design_name,
        protected=protected,
    )


def _hydrate_persistent_record(store: Any, session: dict[str, Any], record: Any) -> None:
    if record.record_type == "snapshot" and record.content_id:
        label = str(record.metadata.get("label") or record.record_id)
        session.setdefault("snapshots", {}).setdefault(record.design_name, {})[label] = store.load_design_content(
            record.content_id
        )
        ancillary = record.metadata.get("ancillary")
        if isinstance(ancillary, dict):
            session.setdefault("snapshots_ancillary", {}).setdefault(record.design_name, {})[label] = ancillary
        return
    if record.record_type == "transaction":
        transaction = dict(record.metadata)
        if record.content_id:
            transaction["candidate_design"] = store.load_design_content(record.content_id)
        session.setdefault("transactions", {})[record.record_id] = transaction
        return
    if record.record_type == "transaction-history":
        session.setdefault("transaction_history", []).append(dict(record.metadata))
        return
    target_key = {
        "erc-evidence": "erc_evidence",
        "drc-evidence": "drc_evidence",
        "validation-status": "validation_status",
        "release-evidence": "release_approvals",
    }.get(record.record_type)
    if target_key is not None:
        session.setdefault(target_key, {})[record.design_name] = dict(record.metadata)


def _hydrate_persistent_session(session_id: str, session: dict[str, Any]) -> None:
    store = _get_state_store()
    if store is None:
        return
    events = store.load_audit_events(session_id)
    if events:
        session["audit_events"] = events
    for record in store.list_session_records(session_id):
        _hydrate_persistent_record(store, session, record)


def _persist_audit_event(event: dict[str, Any]) -> None:
    store = _get_state_store()
    if store is not None:
        store.append_audit_event(_json_safe(event))


def _get_session(session_id: str) -> dict[str, Any]:
    from zaptrace.agent.execution import SessionDestroyedError, is_session_destroyed

    if is_session_destroyed(session_id):
        raise SessionDestroyedError(f"Session '{session_id}' has been destroyed")
    if session_id not in _sessions:
        session = {"designs": make_design_mapping(session_id)}
        _hydrate_persistent_session(session_id, session)
        _sessions[session_id] = session
    return _sessions[session_id]


def _persist_design(
    session: dict[str, Any],
    design_name: str,
    *,
    operation: str = "in-place-persist",
) -> None:
    designs = session.get("designs", {})
    persist = getattr(designs, "persist", None)
    if callable(persist):
        persist(design_name, operation=operation)


def _record_erc_evidence(session: dict[str, Any], design_name: str, result: ERCResult) -> dict[str, Any]:
    """Record ERC evidence bound to the exact design state it evaluated."""
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    evidence = {
        "status": ReleaseEvidenceStatus.PASS if result.passed else ReleaseEvidenceStatus.FAIL,
        "design_state_hash": release_design_state_hash(design),
        "passed": bool(result.passed),
        "total_errors": result.total_errors,
        "total_warnings": result.total_warnings,
        "total_info": result.total_info,
    }
    evidence.update(_persistent_design_identity(session, design_name))
    session.setdefault("erc_evidence", {})[design_name] = evidence
    _persist_evidence_record(session, design_name, "erc-evidence", evidence)
    return evidence


def _record_drc_evidence(
    session: dict[str, Any],
    design_name: str,
    result: Any,
    *,
    fab_profile: str | None,
) -> dict[str, Any]:
    """Record DRC and fabrication-profile evidence for the evaluated state."""
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    evidence = {
        "status": ReleaseEvidenceStatus.PASS if result.passed else ReleaseEvidenceStatus.FAIL,
        "design_state_hash": release_design_state_hash(design),
        "passed": bool(result.passed),
        "total_violations": result.total_violations,
        "fab_profile": (fab_profile or "").strip(),
    }
    evidence.update(_persistent_design_identity(session, design_name))
    session.setdefault("drc_evidence", {})[design_name] = evidence
    _persist_evidence_record(session, design_name, "drc-evidence", evidence)
    return evidence


def _record_validation_status(session: dict[str, Any], design_name: str) -> dict[str, Any]:
    """Store the current view of independently state-bound ERC and DRC evidence."""
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")

    status = {
        "design_state_hash": release_design_state_hash(design),
        "erc": copy.deepcopy(session.get("erc_evidence", {}).get(design_name)),
        "drc": copy.deepcopy(session.get("drc_evidence", {}).get(design_name)),
    }
    status.update(_persistent_design_identity(session, design_name))
    session.setdefault("validation_status", {})[design_name] = status
    _persist_evidence_record(session, design_name, "validation-status", status)
    return status


def _require_release_gate(
    session: dict[str, Any],
    design_name: str,
    approval_id: str | None,
    *,
    session_id: str = "",
    fab_profile_skip_reason: str | None = None,
    fab_profile_skip_approval_id: str | None = None,
    risky_package_reviewed: bool = False,
    risky_package_approval_id: str | None = None,
) -> dict[str, Any]:
    """Require complete current evidence and bind approval to its identity."""
    if not approval_id or not approval_id.strip():
        raise ValueError("approval_id is required for release-export operations")
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")

    validation = session.get("validation_status", {}).get(design_name)
    current_hash = release_design_state_hash(design)
    from zaptrace.review.evidence import resolve_engineering_review_evidence

    engineering_review = resolve_engineering_review_evidence(
        session_id,
        design_name,
        current_hash,
        approval_id,
    )
    review_status = str(engineering_review["status"])
    if review_status in {"rejected", "repair-requested", "rolled-back"}:
        raise ValueError(f"Release export for '{design_name}' is blocked by engineering review status={review_status}")
    if review_status == "stale-review" and engineering_review["approval_id_matched"]:
        raise ValueError(f"Release export for '{design_name}' received a stale engineering review approval")

    erc, drc = require_current_validation(
        design_name=design_name,
        current_hash=current_hash,
        validation=validation,
    )
    component_coverage = build_component_coverage(
        design,
        risky_package_reviewed=risky_package_reviewed,
        risky_package_approval_id=(risky_package_approval_id or "").strip(),
    )
    require_complete_component_coverage(design_name=design_name, coverage=component_coverage)
    fab_profile_policy = build_fab_profile_policy(
        fab_profile=str(drc.get("fab_profile") or ""),
        skip_reason=fab_profile_skip_reason or "",
        skip_approval_id=fab_profile_skip_approval_id or "",
    )
    require_approved_fab_profile_policy(design_name=design_name, policy=fab_profile_policy)

    evidence_identity = build_release_evidence_identity(
        design_state_hash=current_hash,
        erc=erc,
        drc=drc,
        component_coverage=component_coverage,
        fab_profile_status=fab_profile_policy["status"],
        fab_profile=fab_profile_policy["fab_profile"],
        fab_profile_skip_reason=fab_profile_policy["skip_reason"],
        fab_profile_skip_approval_id=fab_profile_policy["skip_approval_id"],
        engineering_review=engineering_review,
    )
    approval_binding = bind_release_approval(
        session.setdefault("release_approval_bindings", {}),
        approval_id=approval_id,
        evidence_identity=evidence_identity,
    )
    gate = {
        "status": ReleaseEvidenceStatus.PASS,
        "automated_gate_status": ReleaseEvidenceStatus.PASS,
        "approval_id": approval_id.strip(),
        "approval_binding": approval_binding,
        "validation": validation,
        "component_coverage": component_coverage,
        "fab_profile_policy": fab_profile_policy,
        "engineering_review": engineering_review,
        "fabrication_status": review_status,
        "evidence_identity": evidence_identity,
    }
    gate.update(_persistent_design_identity(session, design_name))
    session.setdefault("release_approvals", {})[design_name] = gate
    _persist_evidence_record(session, design_name, "release-evidence", gate, protected=True)
    return gate


__all__ = [
    "_WORKSPACE",
    "_get_autopilot",
    "_get_erc_runner_type",
    "_get_library",
    "_delete_persistent_record",
    "_delete_persistent_session",
    "_delete_persistent_records",
    "_get_state_store",
    "_hydrate_persistent_record",
    "_hydrate_persistent_session",
    "_persist_audit_event",
    "_persist_evidence_record",
    "_persist_snapshot",
    "_persist_transaction",
    "_persist_transaction_history",
    "_persistent_design_identity",
    "_set_design",
    "_get_session",
    "_get_workspace",
    "_library",
    "_persist_design",
    "_record_drc_evidence",
    "_record_erc_evidence",
    "_record_validation_status",
    "_require_release_gate",
    "_sessions",
    "_validate_path",
]
