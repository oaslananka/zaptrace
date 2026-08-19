"""Object-level authorization for session-scoped runtime resources."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4


class ObjectAccessDeniedError(PermissionError):
    """Raised when a principal cannot access a protected object."""


@dataclass(frozen=True)
class RequestPrincipal:
    """Resolved caller identity used for object authorization."""

    principal_id: str
    actor: str
    scopes: frozenset[str] = frozenset()
    authenticated: bool = False
    local_development: bool = False

    @property
    def is_admin(self) -> bool:
        return "object-admin" in self.scopes


@dataclass
class ObjectAccessRecord:
    """Ownership and delegation metadata for one protected object."""

    object_type: str
    object_id: str
    owner_principal: str
    delegates: set[str] = field(default_factory=set)
    parent_object_type: str = ""
    parent_object_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["delegates"] = sorted(self.delegates)
        return payload


_OBJECT_ACCESS: dict[tuple[str, str], ObjectAccessRecord] = {}
_OBJECT_AUTHORIZATION_EVENTS: list[dict[str, Any]] = []
_TARGET_OBJECT_DENIED = "principal is not authorized for the target object"
_DELEGATE_PRINCIPAL_REQUIRED = "delegate principal is required"


def _persistent_state_store() -> Any | None:
    if os.environ.get("ZAPTRACE_PERSISTENCE_DISABLED") == "1":
        return None
    from zaptrace.core.session_store import session_store_root

    root = session_store_root()
    if root is None:
        return None
    from zaptrace.core.state_store import SQLiteStateStore

    return SQLiteStateStore(root)


def _record_from_payload(payload: dict[str, Any]) -> ObjectAccessRecord:
    return ObjectAccessRecord(
        object_type=str(payload["object_type"]),
        object_id=str(payload["object_id"]),
        owner_principal=str(payload["owner_principal"]),
        delegates={str(item) for item in payload.get("delegates", [])},
        parent_object_type=str(payload.get("parent_object_type") or ""),
        parent_object_id=str(payload.get("parent_object_id") or ""),
        created_at=str(payload.get("created_at") or datetime.now(UTC).isoformat()),
    )


def _persist_object_access(record: ObjectAccessRecord) -> None:
    store = _persistent_state_store()
    if store is not None:
        store.upsert_object_access(record.to_dict())


def generate_secure_object_id(prefix: str) -> str:
    """Generate an opaque, cryptographically strong object identifier."""
    return f"{prefix}-{token_urlsafe(24)}"


def _key(object_type: str, object_id: str) -> tuple[str, str]:
    return object_type.strip().lower(), object_id.strip()


def get_object_access(object_type: str, object_id: str) -> ObjectAccessRecord | None:
    """Return access metadata, hydrating durable ownership on cache miss."""
    key = _key(object_type, object_id)
    record = _OBJECT_ACCESS.get(key)
    if record is not None:
        return record
    store = _persistent_state_store()
    payload = store.load_object_access(*key) if store is not None else None
    if payload is None:
        return None
    record = _record_from_payload(payload)
    _OBJECT_ACCESS[key] = record
    return record


def _record_authorization_event(
    *,
    principal: RequestPrincipal,
    object_type: str,
    object_id: str,
    action: str,
    decision: str,
    reason: str,
    request_id: str,
) -> dict[str, Any]:
    access = _OBJECT_ACCESS.get(_key(object_type, object_id))
    event = {
        "event_id": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "surface": "object-authorization",
        "principal_id": principal.principal_id,
        "actor": principal.actor,
        "authenticated": principal.authenticated,
        "object_type": object_type,
        "object_id": object_id,
        "parent_object_type": access.parent_object_type if access is not None else "",
        "parent_object_id": access.parent_object_id if access is not None else "",
        "action": action,
        "decision": decision,
        "reason": reason,
        "request_id": request_id,
    }
    _OBJECT_AUTHORIZATION_EVENTS.append(event)
    store = _persistent_state_store()
    if store is not None:
        store.append_object_authorization_event(event)
    return event


def object_authorization_events(
    *,
    object_type: str | None = None,
    object_id: str | None = None,
    parent_object_type: str | None = None,
    parent_object_id: str | None = None,
    principal_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return recent persisted and in-memory authorization decisions."""
    persisted: list[dict[str, Any]] = []
    store = _persistent_state_store()
    if store is not None:
        persisted = store.load_object_authorization_events(
            object_type=object_type,
            object_id=object_id,
            parent_object_type=parent_object_type,
            parent_object_id=parent_object_id,
            principal_id=principal_id,
            limit=limit,
        )
    events = list(_OBJECT_AUTHORIZATION_EVENTS)
    if object_type is not None:
        events = [event for event in events if event["object_type"] == object_type]
    if object_id is not None:
        events = [event for event in events if event["object_id"] == object_id]
    if parent_object_type is not None:
        events = [event for event in events if event["parent_object_type"] == parent_object_type]
    if parent_object_id is not None:
        events = [event for event in events if event["parent_object_id"] == parent_object_id]
    if principal_id is not None:
        events = [event for event in events if event["principal_id"] == principal_id]
    combined: dict[str, dict[str, Any]] = {}
    for event in [*persisted, *events]:
        combined[str(event.get("event_id") or repr(event))] = event
    ordered = sorted(combined.values(), key=lambda event: str(event.get("timestamp") or ""))
    return ordered[-max(1, limit) :]


def _claim_object(
    *,
    object_type: str,
    object_id: str,
    principal: RequestPrincipal,
    action: str,
    request_id: str,
    parent_object_type: str,
    parent_object_id: str,
) -> ObjectAccessRecord:
    record = ObjectAccessRecord(
        object_type=object_type,
        object_id=object_id,
        owner_principal=principal.principal_id,
        parent_object_type=parent_object_type.strip().lower(),
        parent_object_id=parent_object_id.strip(),
    )
    _OBJECT_ACCESS[(object_type, object_id)] = record
    _persist_object_access(record)
    _record_authorization_event(
        principal=principal,
        object_type=object_type,
        object_id=object_id,
        action=action,
        decision="allow",
        reason="object claimed by principal",
        request_id=request_id,
    )
    return record


def _direct_access_decision(record: ObjectAccessRecord, principal: RequestPrincipal) -> tuple[bool, str]:
    if principal.is_admin:
        return True, "administrator override"
    if principal.principal_id == record.owner_principal:
        return True, "object owner"
    if principal.principal_id in record.delegates:
        return True, "delegated object access"
    return False, "principal is not owner, delegate, or administrator"


def _parent_access_decision(
    record: ObjectAccessRecord,
    principal: RequestPrincipal,
    *,
    action: str,
    request_id: str,
    direct_allowed: bool,
    direct_reason: str,
) -> tuple[bool, str]:
    if not record.parent_object_type or not record.parent_object_id:
        return direct_allowed, direct_reason
    try:
        authorize_object(
            object_type=record.parent_object_type,
            object_id=record.parent_object_id,
            principal=principal,
            action=f"parent:{action}",
            request_id=request_id,
        )
    except ObjectAccessDeniedError:
        return False, "principal is not authorized for the parent object"
    if direct_allowed:
        return True, direct_reason
    return True, "access inherited from authorized parent object"


def authorize_object(
    *,
    object_type: str,
    object_id: str,
    principal: RequestPrincipal,
    action: str,
    request_id: str,
    allow_claim: bool = False,
    parent_object_type: str = "",
    parent_object_id: str = "",
) -> ObjectAccessRecord:
    """Authorize access, optionally claiming an unowned object for the caller."""
    normalized_type, normalized_id = _key(object_type, object_id)
    if not normalized_id:
        _record_authorization_event(
            principal=principal,
            object_type=normalized_type,
            object_id=normalized_id,
            action=action,
            decision="deny",
            reason="empty object identifier",
            request_id=request_id,
        )
        raise ObjectAccessDeniedError("object identifier is required")

    record = get_object_access(normalized_type, normalized_id)
    if record is None and allow_claim:
        return _claim_object(
            object_type=normalized_type,
            object_id=normalized_id,
            principal=principal,
            action=action,
            request_id=request_id,
            parent_object_type=parent_object_type,
            parent_object_id=parent_object_id,
        )
    if record is None:
        _record_authorization_event(
            principal=principal,
            object_type=normalized_type,
            object_id=normalized_id,
            action=action,
            decision="deny",
            reason="object is not registered for this principal",
            request_id=request_id,
        )
        raise ObjectAccessDeniedError(_TARGET_OBJECT_DENIED)

    direct_allowed, direct_reason = _direct_access_decision(record, principal)
    allowed, reason = _parent_access_decision(
        record,
        principal,
        action=action,
        request_id=request_id,
        direct_allowed=direct_allowed,
        direct_reason=direct_reason,
    )
    _record_authorization_event(
        principal=principal,
        object_type=normalized_type,
        object_id=normalized_id,
        action=action,
        decision="allow" if allowed else "deny",
        reason=reason,
        request_id=request_id,
    )
    if not allowed:
        raise ObjectAccessDeniedError(_TARGET_OBJECT_DENIED)
    return record


def delegate_object_access(
    *,
    object_type: str,
    object_id: str,
    principal: RequestPrincipal,
    delegate_principal: str,
    request_id: str,
) -> ObjectAccessRecord:
    """Grant a principal access to an object; only owner/admin may delegate."""
    record = get_object_access(object_type, object_id)
    if record is None:
        record = authorize_object(
            object_type=object_type,
            object_id=object_id,
            principal=principal,
            action="delegate",
            request_id=request_id,
        )
    if not principal.is_admin and principal.principal_id != record.owner_principal:
        _record_authorization_event(
            principal=principal,
            object_type=record.object_type,
            object_id=record.object_id,
            action="delegate",
            decision="deny",
            reason="only owner or administrator may delegate access",
            request_id=request_id,
        )
        raise ObjectAccessDeniedError("only owner or administrator may delegate object access")
    normalized_delegate = delegate_principal.strip()
    if not normalized_delegate:
        _record_authorization_event(
            principal=principal,
            object_type=record.object_type,
            object_id=record.object_id,
            action="delegate",
            decision="deny",
            reason=_DELEGATE_PRINCIPAL_REQUIRED,
            request_id=request_id,
        )
        raise ValueError(_DELEGATE_PRINCIPAL_REQUIRED)
    record.delegates.add(normalized_delegate)
    _persist_object_access(record)
    _record_authorization_event(
        principal=principal,
        object_type=record.object_type,
        object_id=record.object_id,
        action="delegate",
        decision="allow",
        reason=f"delegated access to {normalized_delegate}",
        request_id=request_id,
    )
    return record


def revoke_object_access(
    *,
    object_type: str,
    object_id: str,
    principal: RequestPrincipal,
    delegate_principal: str,
    request_id: str,
) -> ObjectAccessRecord:
    """Revoke delegated access; only owner/admin may revoke."""
    normalized_type, normalized_id = _key(object_type, object_id)
    record = get_object_access(normalized_type, normalized_id)
    if record is None:
        _record_authorization_event(
            principal=principal,
            object_type=normalized_type,
            object_id=normalized_id,
            action="revoke-delegate",
            decision="deny",
            reason="object is not registered for this principal",
            request_id=request_id,
        )
        raise ObjectAccessDeniedError(_TARGET_OBJECT_DENIED)
    if not principal.is_admin and principal.principal_id != record.owner_principal:
        _record_authorization_event(
            principal=principal,
            object_type=record.object_type,
            object_id=record.object_id,
            action="revoke-delegate",
            decision="deny",
            reason="only owner or administrator may revoke access",
            request_id=request_id,
        )
        raise ObjectAccessDeniedError("only owner or administrator may revoke object access")
    normalized_delegate = delegate_principal.strip()
    if not normalized_delegate:
        _record_authorization_event(
            principal=principal,
            object_type=record.object_type,
            object_id=record.object_id,
            action="revoke-delegate",
            decision="deny",
            reason=_DELEGATE_PRINCIPAL_REQUIRED,
            request_id=request_id,
        )
        raise ValueError(_DELEGATE_PRINCIPAL_REQUIRED)
    record.delegates.discard(normalized_delegate)
    _persist_object_access(record)
    _record_authorization_event(
        principal=principal,
        object_type=record.object_type,
        object_id=record.object_id,
        action="revoke-delegate",
        decision="allow",
        reason=f"revoked delegated access from {normalized_delegate}",
        request_id=request_id,
    )
    return record


def remove_object_access(object_type: str, object_id: str, *, cascade: bool = True) -> None:
    """Remove access metadata and optionally remove child object records."""
    normalized_type, normalized_id = _key(object_type, object_id)
    _OBJECT_ACCESS.pop((normalized_type, normalized_id), None)
    store = _persistent_state_store()
    if store is not None:
        store.delete_object_access(normalized_type, normalized_id, cascade=cascade)
    if cascade:
        child_keys = [
            key
            for key, record in _OBJECT_ACCESS.items()
            if record.parent_object_type == normalized_type and record.parent_object_id == normalized_id
        ]
        for child_type, child_id in child_keys:
            remove_object_access(child_type, child_id, cascade=True)


def reset_object_authorization_state() -> None:
    """Clear in-memory ACL and audit state for isolated tests."""
    _OBJECT_ACCESS.clear()
    _OBJECT_AUTHORIZATION_EVENTS.clear()
