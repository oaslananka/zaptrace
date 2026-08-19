"""Typed session records, audit, ACL, and artifact-reference persistence."""

from __future__ import annotations

import json
import sqlite3
from contextlib import AbstractContextManager, closing
from typing import Any

from zaptrace.core.models import Design
from zaptrace.core.state_store_types import SessionRecord, StateStoreCorruptionError


class StateRecordMixin:
    """Repository methods mixed into the concrete SQLite connection owner."""

    def _connect(self, path: Any = None) -> sqlite3.Connection:
        raise NotImplementedError

    def transaction(self) -> AbstractContextManager[sqlite3.Connection]:
        raise NotImplementedError

    @staticmethod
    def _utc_now() -> str:
        raise NotImplementedError

    @staticmethod
    def _canonical_json_payload(value: Any) -> bytes:
        raise NotImplementedError

    @staticmethod
    def _canonical_design_payload(design: Design) -> bytes:
        raise NotImplementedError

    def _ensure_session(self, connection: sqlite3.Connection, session_id: str, timestamp: str) -> None:
        raise NotImplementedError

    def _store_blob(self, connection: sqlite3.Connection, payload: bytes, *, media_type: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> SessionRecord:
        try:
            metadata = json.loads(str(row["metadata_json"]))
        except ValueError as exc:
            raise StateStoreCorruptionError(
                f"stored session record metadata is invalid: {row['record_type']}/{row['record_id']}"
            ) from exc
        if not isinstance(metadata, dict):
            raise StateStoreCorruptionError(
                f"stored session record metadata is not an object: {row['record_type']}/{row['record_id']}"
            )
        return SessionRecord(
            session_id=str(row["session_id"]),
            record_type=str(row["record_type"]),
            record_id=str(row["record_id"]),
            design_name=str(row["design_name"]),
            content_id=str(row["content_id"]) if row["content_id"] else None,
            metadata=metadata,
            active=bool(row["active"]),
            protected=bool(row["protected"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _upsert_record_with_connection(
        self,
        connection: sqlite3.Connection,
        *,
        session_id: str,
        record_type: str,
        record_id: str,
        design_name: str,
        content_id: str | None,
        metadata: dict[str, Any],
        active: bool,
        protected: bool,
        timestamp: str,
    ) -> SessionRecord:
        existing = connection.execute(
            "SELECT created_at FROM session_records WHERE session_id = ? AND record_type = ? AND record_id = ?",
            (session_id, record_type, record_id),
        ).fetchone()
        created_at = str(existing["created_at"]) if existing is not None else timestamp
        connection.execute(
            "INSERT INTO session_records("
            "session_id, record_type, record_id, design_name, content_id, metadata_json, "
            "active, protected, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id, record_type, record_id) DO UPDATE SET "
            "design_name = excluded.design_name, content_id = excluded.content_id, "
            "metadata_json = excluded.metadata_json, active = excluded.active, "
            "protected = excluded.protected, updated_at = excluded.updated_at",
            (
                session_id,
                record_type,
                record_id,
                design_name,
                content_id,
                self._canonical_json_payload(metadata).decode("utf-8"),
                int(active),
                int(protected),
                created_at,
                timestamp,
            ),
        )
        return SessionRecord(
            session_id=session_id,
            record_type=record_type,
            record_id=record_id,
            design_name=design_name,
            content_id=content_id,
            metadata=metadata,
            active=active,
            protected=protected,
            created_at=created_at,
            updated_at=timestamp,
        )

    def upsert_session_record(
        self,
        session_id: str,
        record_type: str,
        record_id: str,
        metadata: dict[str, Any],
        *,
        design_name: str = "",
        content_id: str | None = None,
        active: bool = True,
        protected: bool = False,
    ) -> SessionRecord:
        """Insert or replace one typed JSON-safe session record."""
        timestamp = self._utc_now()
        with self.transaction() as connection:
            self._ensure_session(connection, session_id, timestamp)
            return self._upsert_record_with_connection(
                connection,
                session_id=session_id,
                record_type=record_type,
                record_id=record_id,
                design_name=design_name,
                content_id=content_id,
                metadata=metadata,
                active=active,
                protected=protected,
                timestamp=timestamp,
            )

    def upsert_design_record(
        self,
        session_id: str,
        record_type: str,
        record_id: str,
        design: Design,
        metadata: dict[str, Any],
        *,
        design_name: str,
        active: bool = True,
        protected: bool = False,
    ) -> SessionRecord:
        """Atomically store design content and one record referencing it."""
        timestamp = self._utc_now()
        with self.transaction() as connection:
            self._ensure_session(connection, session_id, timestamp)
            content_id = self._store_blob(
                connection,
                self._canonical_design_payload(design),
                media_type="application/vnd.zaptrace.design+json",
            )
            return self._upsert_record_with_connection(
                connection,
                session_id=session_id,
                record_type=record_type,
                record_id=record_id,
                design_name=design_name,
                content_id=content_id,
                metadata=metadata,
                active=active,
                protected=protected,
                timestamp=timestamp,
            )

    def list_session_records(
        self,
        session_id: str,
        *,
        record_type: str | None = None,
        active: bool | None = None,
    ) -> list[SessionRecord]:
        clauses = ["session_id = ?"]
        parameters: list[Any] = [session_id]
        if record_type is not None:
            clauses.append("record_type = ?")
            parameters.append(record_type)
        if active is not None:
            clauses.append("active = ?")
            parameters.append(int(active))
        query = "SELECT * FROM session_records WHERE " + " AND ".join(clauses) + " ORDER BY rowid"
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._record_from_row(row) for row in rows]

    def delete_session_record(self, session_id: str, record_type: str, record_id: str) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM session_records WHERE session_id = ? AND record_type = ? AND record_id = ?",
                (session_id, record_type, record_id),
            )
        return cursor.rowcount > 0

    def delete_session_records(
        self,
        session_id: str,
        record_type: str,
        *,
        design_name: str | None = None,
    ) -> int:
        query = "DELETE FROM session_records WHERE session_id = ? AND record_type = ?"
        parameters: list[Any] = [session_id, record_type]
        if design_name is not None:
            query += " AND design_name = ?"
            parameters.append(design_name)
        with self.transaction() as connection:
            cursor = connection.execute(query, parameters)
        return cursor.rowcount

    def upsert_object_access(self, payload: dict[str, Any]) -> None:
        timestamp = self._utc_now()
        object_type = str(payload["object_type"]).strip().lower()
        object_id = str(payload["object_id"]).strip()
        delegates = payload.get("delegates", [])
        delegates_json = self._canonical_json_payload(sorted(str(item) for item in delegates)).decode("utf-8")
        created_at = str(payload.get("created_at") or timestamp)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO object_access("
                "object_type, object_id, owner_principal, delegates_json, parent_object_type, "
                "parent_object_id, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(object_type, object_id) DO UPDATE SET "
                "owner_principal = excluded.owner_principal, delegates_json = excluded.delegates_json, "
                "parent_object_type = excluded.parent_object_type, parent_object_id = excluded.parent_object_id, "
                "updated_at = excluded.updated_at",
                (
                    object_type,
                    object_id,
                    str(payload["owner_principal"]),
                    delegates_json,
                    str(payload.get("parent_object_type") or "").strip().lower(),
                    str(payload.get("parent_object_id") or "").strip(),
                    created_at,
                    timestamp,
                ),
            )

    def load_object_access(self, object_type: str, object_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM object_access WHERE object_type = ? AND object_id = ?",
                (object_type.strip().lower(), object_id.strip()),
            ).fetchone()
        if row is None:
            return None
        try:
            delegates = json.loads(str(row["delegates_json"]))
        except ValueError as exc:
            raise StateStoreCorruptionError("stored object access delegates are invalid") from exc
        if not isinstance(delegates, list):
            raise StateStoreCorruptionError("stored object access delegates are not a list")
        return {
            "object_type": str(row["object_type"]),
            "object_id": str(row["object_id"]),
            "owner_principal": str(row["owner_principal"]),
            "delegates": [str(item) for item in delegates],
            "parent_object_type": str(row["parent_object_type"]),
            "parent_object_id": str(row["parent_object_id"]),
            "created_at": str(row["created_at"]),
        }

    def delete_object_access(self, object_type: str, object_id: str, *, cascade: bool = True) -> int:
        normalized_type = object_type.strip().lower()
        normalized_id = object_id.strip()
        removed = 0
        with self.transaction() as connection:
            pending = [(normalized_type, normalized_id)]
            while pending:
                current_type, current_id = pending.pop()
                if cascade:
                    children = connection.execute(
                        "SELECT object_type, object_id FROM object_access "
                        "WHERE parent_object_type = ? AND parent_object_id = ?",
                        (current_type, current_id),
                    ).fetchall()
                    pending.extend((str(row["object_type"]), str(row["object_id"])) for row in children)
                cursor = connection.execute(
                    "DELETE FROM object_access WHERE object_type = ? AND object_id = ?",
                    (current_type, current_id),
                )
                removed += cursor.rowcount
        return removed

    def append_object_authorization_event(self, event: dict[str, Any]) -> None:
        object_type = str(event.get("object_type") or "")
        object_id = str(event.get("object_id") or "")
        parent_type = str(event.get("parent_object_type") or "")
        parent_id = str(event.get("parent_object_id") or "")
        session_id = ""
        if object_type == "session":
            session_id = object_id
        elif parent_type == "session":
            session_id = parent_id
        if not session_id:
            session_id = f"object:{object_type}:{object_id}"
        payload = dict(event)
        payload["session_id"] = session_id
        self.append_audit_event(payload)

    def load_object_authorization_events(
        self,
        *,
        object_type: str | None = None,
        object_id: str | None = None,
        parent_object_type: str | None = None,
        parent_object_id: str | None = None,
        principal_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses = ["surface = 'object-authorization'"]
        parameters: list[Any] = []
        if object_type is not None:
            clauses.append("object_type = ?")
            parameters.append(object_type)
        if object_id is not None:
            clauses.append("object_id = ?")
            parameters.append(object_id)
        if principal_id is not None:
            clauses.append("principal_id = ?")
            parameters.append(principal_id)
        query = "SELECT payload_json FROM audit_events WHERE " + " AND ".join(clauses) + " ORDER BY rowid"
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                event = json.loads(str(row["payload_json"]))
            except ValueError as exc:
                raise StateStoreCorruptionError("stored object authorization event is invalid") from exc
            if not isinstance(event, dict):
                continue
            if parent_object_type is not None and event.get("parent_object_type") != parent_object_type:
                continue
            if parent_object_id is not None and event.get("parent_object_id") != parent_object_id:
                continue
            events.append(event)
        return events[-max(1, limit) :]

    def register_artifact_reference(
        self,
        session_id: str,
        artifact_id: str,
        reference_id: str,
        *,
        reference_kind: str,
    ) -> SessionRecord:
        return self.upsert_session_record(
            session_id,
            "artifact-reference",
            f"{artifact_id}:{reference_id}",
            {
                "artifact_id": artifact_id,
                "reference_id": reference_id,
                "reference_kind": reference_kind,
            },
            protected=True,
        )

    def release_artifact_reference(self, session_id: str, artifact_id: str, reference_id: str) -> bool:
        return self.delete_session_record(session_id, "artifact-reference", f"{artifact_id}:{reference_id}")

    def artifact_is_referenced(self, session_id: str, artifact_id: str) -> bool:
        return any(
            record.metadata.get("artifact_id") == artifact_id
            for record in self.list_session_records(session_id, record_type="artifact-reference", active=True)
        )

    def append_audit_event(self, event: dict[str, Any]) -> None:
        session_id = str(event.get("session_id") or "")
        event_id = str(event.get("event_id") or "")
        if not session_id or not event_id:
            raise ValueError("audit event requires session_id and event_id")
        timestamp = str(event.get("timestamp") or self._utc_now())
        raw_metadata = event.get("metadata")
        metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
        with self.transaction() as connection:
            self._ensure_session(connection, session_id, timestamp)
            connection.execute(
                "INSERT OR IGNORE INTO audit_events("
                "event_id, session_id, principal_id, surface, object_type, object_id, request_id, "
                "design_name, payload_json, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    session_id,
                    str(event.get("principal_id") or metadata.get("principal_id") or ""),
                    str(event.get("surface") or ""),
                    str(event.get("object_type") or metadata.get("target_object_type") or ""),
                    str(event.get("object_id") or metadata.get("target_object_id") or ""),
                    str(event.get("request_id") or metadata.get("request_id") or ""),
                    str(event.get("design_name") or metadata.get("design_name") or ""),
                    self._canonical_json_payload(event).decode("utf-8"),
                    timestamp,
                ),
            )

    def load_audit_events(self, session_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT payload_json FROM audit_events WHERE session_id = ? ORDER BY rowid"
        parameters: list[Any] = [session_id]
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(max(1, limit))
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except ValueError as exc:
                raise StateStoreCorruptionError("stored audit event payload is invalid") from exc
            if not isinstance(payload, dict):
                raise StateStoreCorruptionError("stored audit event payload is not an object")
            events.append(payload)
        return events
