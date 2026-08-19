"""Public types and stable failures for the persistent state backend."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class StateStoreError(RuntimeError):
    """Base error for durable-state failures."""


class StateStoreSchemaError(StateStoreError):
    """Raised when the database schema cannot be trusted or migrated."""


class StateStoreCorruptionError(StateStoreError):
    """Raised when SQLite reports corrupt or unreadable state."""


@dataclass(frozen=True)
class SessionRecord:
    """One durable typed record associated with a session."""

    session_id: str
    record_type: str
    record_id: str
    design_name: str
    content_id: str | None
    metadata: dict[str, Any]
    active: bool
    protected: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DesignIdentity:
    """Stable content identity plus immutable mutation-lineage identity."""

    session_id: str
    design_name: str
    content_id: str
    version_id: str
    parent_version_id: str | None
    operation: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
