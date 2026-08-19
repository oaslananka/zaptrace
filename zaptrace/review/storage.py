"""Optional durable storage adapter for Review Studio sessions."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zaptrace.review.workflow import ReviewSession

_REVIEW_RECORD_TYPE = "review-session"


def get_review_state_store() -> Any | None:
    """Return the configured SQLite state store without changing in-memory defaults."""
    if os.environ.get("ZAPTRACE_PERSISTENCE_DISABLED") == "1":
        return None
    from zaptrace.core.session_store import session_store_root

    root = session_store_root()
    if root is None:
        return None
    from zaptrace.core.state_store import SQLiteStateStore

    return SQLiteStateStore(root)


def persist_review_session(session: ReviewSession) -> None:
    """Upsert one complete review session under its parent design session."""
    if not session.design_session_id:
        return
    store = get_review_state_store()
    if store is None:
        return
    store.upsert_session_record(
        session.design_session_id,
        _REVIEW_RECORD_TYPE,
        session.session_id,
        session.model_dump(mode="json"),
        design_name=session.design_name,
        protected=True,
    )


def hydrate_review_session(
    session_id: str,
    design_session_id: str,
    cache: dict[str, ReviewSession],
) -> ReviewSession | None:
    """Hydrate one parent-scoped review record into the process cache."""
    if not design_session_id:
        return None
    store = get_review_state_store()
    if store is None:
        return None
    from zaptrace.review.workflow import ReviewSession

    for record in store.list_session_records(design_session_id, record_type=_REVIEW_RECORD_TYPE):
        if record.record_id != session_id:
            continue
        restored = ReviewSession.model_validate(record.metadata)
        cache[session_id] = restored
        return restored
    return None


def review_sessions_for_design_session(
    design_session_id: str,
    cache: dict[str, ReviewSession],
) -> list[ReviewSession]:
    """Return cached and durable review sessions for one parent design session."""
    sessions = {
        session.session_id: session for session in cache.values() if session.design_session_id == design_session_id
    }
    store = get_review_state_store()
    if store is None or not design_session_id:
        return list(sessions.values())

    from zaptrace.review.workflow import ReviewSession

    for record in store.list_session_records(design_session_id, record_type=_REVIEW_RECORD_TYPE):
        if record.record_id in sessions:
            continue
        restored = ReviewSession.model_validate(record.metadata)
        cache[restored.session_id] = restored
        sessions[restored.session_id] = restored
    return list(sessions.values())
