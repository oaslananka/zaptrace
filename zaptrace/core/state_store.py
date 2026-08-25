"""Durable local session state backed by the Python standard-library SQLite driver."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from zaptrace.core.models import Design
from zaptrace.core.state_store_records import StateRecordMixin
from zaptrace.core.state_store_schema import (
    _BUSY_TIMEOUT_MS,
    _DATABASE_NAME,
    _MIGRATION_CHECKSUMS,
    _MIGRATIONS,
    SCHEMA_VERSION,
)
from zaptrace.core.state_store_types import (
    DesignIdentity,
    SessionRecord,
    StateStoreCorruptionError,
    StateStoreError,
    StateStoreSchemaError,
)

_PRAGMA_USER_VERSION = "PRAGMA user_version"


class SQLiteStateStore(StateRecordMixin):
    """Versioned SQLite state store for controlled local deployments."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / _DATABASE_NAME
        self._validate_sqlite_header(self.database_path)
        try:
            self._initialize()
        except sqlite3.DatabaseError as exc:
            raise StateStoreCorruptionError(f"state database integrity check failed: {exc}") from exc
        self.database_path.chmod(0o600)
        self._import_legacy_filesystem()

    @staticmethod
    def _validate_sqlite_header(path: Path) -> None:
        if not path.exists() or path.stat().st_size == 0:
            return
        try:
            header = path.read_bytes()[:16]
        except OSError as exc:
            raise StateStoreCorruptionError(f"state database integrity check failed: {exc}") from exc
        if header != b"SQLite format 3\x00":
            raise StateStoreCorruptionError("state database integrity check failed: invalid SQLite header")

    def _connect(self, path: Path | None = None) -> sqlite3.Connection:
        connection = sqlite3.connect(path or self.database_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            current_version = int(connection.execute(_PRAGMA_USER_VERSION).fetchone()[0])
            if current_version > SCHEMA_VERSION:
                raise StateStoreSchemaError(
                    f"state database uses newer schema version {current_version}; supported maximum is {SCHEMA_VERSION}"
                )

            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            for version in range(current_version + 1, SCHEMA_VERSION + 1):
                self._apply_migration(connection, version)

            self._verify_migration_checksums(connection)

        self.integrity_check()

    def _apply_migration(self, connection: sqlite3.Connection, version: int) -> None:
        sql = _MIGRATIONS[version]
        checksum = _MIGRATION_CHECKSUMS[version]
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, checksum, applied_at) "
                "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (version, checksum),
            )
            connection.execute(f"PRAGMA user_version = {version}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _verify_migration_checksums(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT version, checksum FROM schema_migrations ORDER BY version").fetchall()
        recorded = {int(row["version"]): str(row["checksum"]) for row in rows}
        for version in range(1, SCHEMA_VERSION + 1):
            expected = _MIGRATION_CHECKSUMS[version]
            if recorded.get(version) != expected:
                raise StateStoreSchemaError(f"migration checksum mismatch for schema version {version}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Open one serialized write transaction and close it deterministically."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def schema_version(self) -> int:
        with closing(self._connect()) as connection:
            return int(connection.execute(_PRAGMA_USER_VERSION).fetchone()[0])

    def integrity_check(self) -> str:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise StateStoreCorruptionError(f"state database integrity check failed: {exc}") from exc
        result = str(row[0]) if row is not None else "missing quick_check result"
        if result.lower() != "ok":
            raise StateStoreCorruptionError(f"state database integrity check failed: {result}")
        return result

    def delete_session(self, session_id: str) -> bool:
        """Delete one durable session and all session-scoped state atomically."""
        with self.transaction() as connection:
            existed = (
                connection.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone() is not None
            )
            connection.execute("DELETE FROM design_heads WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM session_records WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM audit_events WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM design_versions WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            connection.execute(
                "DELETE FROM content_blobs WHERE NOT EXISTS ("
                "SELECT 1 FROM design_versions WHERE design_versions.content_id = content_blobs.content_id"
                ") AND NOT EXISTS ("
                "SELECT 1 FROM session_records WHERE session_records.content_id = content_blobs.content_id"
                ")"
            )
        return existed

    def session_exists(self, session_id: str) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return row is not None

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _canonical_json_payload(value: Any) -> bytes:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @staticmethod
    def _canonical_design_payload(design: Design) -> bytes:
        payload = json.dumps(
            design.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return payload.encode("utf-8")

    @staticmethod
    def _identity_from_row(row: sqlite3.Row) -> DesignIdentity:
        return DesignIdentity(
            session_id=str(row["session_id"]),
            design_name=str(row["design_name"]),
            content_id=str(row["content_id"]),
            version_id=str(row["version_id"]),
            parent_version_id=str(row["parent_version_id"]) if row["parent_version_id"] else None,
            operation=str(row["operation"]),
            created_at=str(row["created_at"]),
        )

    def _ensure_session(self, connection: sqlite3.Connection, session_id: str, timestamp: str) -> None:
        connection.execute(
            "INSERT INTO sessions(session_id, created_at, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at",
            (session_id, timestamp, timestamp),
        )

    def _store_blob(self, connection: sqlite3.Connection, payload: bytes, *, media_type: str) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        content_id = f"sha256:{digest}"
        connection.execute(
            "INSERT OR IGNORE INTO content_blobs(content_id, media_type, payload, size_bytes, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (content_id, media_type, payload, len(payload), self._utc_now()),
        )
        return content_id

    def _store_design_with_connection(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        design_name: str,
        design: Design,
        *,
        operation: str,
        record_duplicate: bool = True,
    ) -> DesignIdentity:
        timestamp = self._utc_now()
        self._ensure_session(connection, session_id, timestamp)
        payload = self._canonical_design_payload(design)
        content_id = self._store_blob(connection, payload, media_type="application/vnd.zaptrace.design+json")
        current = connection.execute(
            "SELECT v.* FROM design_heads h JOIN design_versions v ON v.version_id = h.version_id "
            "WHERE h.session_id = ? AND h.design_name = ?",
            (session_id, design_name),
        ).fetchone()
        if current is not None and str(current["content_id"]) == content_id and not record_duplicate:
            return self._identity_from_row(current)

        version_id = f"version-{uuid4()}"
        parent_version_id = str(current["version_id"]) if current is not None else None
        connection.execute(
            "INSERT INTO design_versions("
            "version_id, session_id, design_name, content_id, parent_version_id, operation, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (version_id, session_id, design_name, content_id, parent_version_id, operation, timestamp),
        )
        connection.execute(
            "INSERT INTO design_heads(session_id, design_name, version_id, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(session_id, design_name) DO UPDATE SET "
            "version_id = excluded.version_id, updated_at = excluded.updated_at",
            (session_id, design_name, version_id, timestamp),
        )
        return DesignIdentity(
            session_id=session_id,
            design_name=design_name,
            content_id=content_id,
            version_id=version_id,
            parent_version_id=parent_version_id,
            operation=operation,
            created_at=timestamp,
        )

    def store_design(
        self,
        session_id: str,
        design_name: str,
        design: Design,
        *,
        operation: str,
        record_duplicate: bool = True,
    ) -> DesignIdentity:
        with self.transaction() as connection:
            return self._store_design_with_connection(
                connection,
                session_id,
                design_name,
                design,
                operation=operation,
                record_duplicate=record_duplicate,
            )

    def store_design_content(self, design: Design) -> str:
        """Store a design payload without changing any design head."""
        with self.transaction() as connection:
            return self._store_blob(
                connection,
                self._canonical_design_payload(design),
                media_type="application/vnd.zaptrace.design+json",
            )

    def load_design_content(self, content_id: str) -> Design:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT payload FROM content_blobs WHERE content_id = ?", (content_id,)).fetchone()
        if row is None:
            raise KeyError(f"content blob not found: {content_id}")
        try:
            return Design.model_validate_json(bytes(row["payload"]))
        except ValueError as exc:
            raise StateStoreCorruptionError(f"stored design payload is invalid: {content_id}") from exc

    def replace_session_designs(
        self,
        session_id: str,
        designs: dict[str, Design],
        *,
        operation: str,
    ) -> dict[str, DesignIdentity]:
        """Replace current design heads in one atomic SQLite transaction."""
        with self.transaction() as connection:
            timestamp = self._utc_now()
            self._ensure_session(connection, session_id, timestamp)
            names = sorted(designs)
            if names:
                placeholders = ",".join("?" for _ in names)
                delete_query = (
                    f"DELETE FROM design_heads WHERE session_id = ? "
                    f"AND design_name NOT IN ({placeholders})"  # nosec: B608
                )
                connection.execute(delete_query, (session_id, *names))
            else:
                connection.execute("DELETE FROM design_heads WHERE session_id = ?", (session_id,))

            identities: dict[str, DesignIdentity] = {}
            for design_name in names:
                identities[design_name] = self._store_design_with_connection(
                    connection,
                    session_id,
                    design_name,
                    designs[design_name],
                    operation=operation,
                )
            return identities

    def current_design_identity(self, session_id: str, design_name: str) -> DesignIdentity | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT v.* FROM design_heads h JOIN design_versions v ON v.version_id = h.version_id "
                "WHERE h.session_id = ? AND h.design_name = ?",
                (session_id, design_name),
            ).fetchone()
        return self._identity_from_row(row) if row is not None else None

    def list_design_versions(self, session_id: str, design_name: str) -> list[DesignIdentity]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM design_versions WHERE session_id = ? AND design_name = ? ORDER BY rowid",
                (session_id, design_name),
            ).fetchall()
        return [self._identity_from_row(row) for row in rows]

    def load_designs(self, session_id: str) -> dict[str, Design]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT h.design_name, b.payload FROM design_heads h "
                "JOIN design_versions v ON v.version_id = h.version_id "
                "JOIN content_blobs b ON b.content_id = v.content_id "
                "WHERE h.session_id = ? ORDER BY h.design_name",
                (session_id,),
            ).fetchall()
        designs: dict[str, Design] = {}
        for row in rows:
            try:
                design = Design.model_validate_json(bytes(row["payload"]))
            except ValueError as exc:
                raise StateStoreCorruptionError(
                    f"stored design payload is invalid for session {session_id!r}: {exc}"
                ) from exc
            designs[str(row["design_name"])] = design
        return designs

    @staticmethod
    def _read_json_object(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _legacy_design_manifests(self) -> list[Path]:
        candidates = [
            *self.root.glob("sessions/*/designs/*/manifest.json"),
            *self.root.glob("*/designs/*/manifest.json"),
        ]
        canonical_root = self.root.resolve()
        manifests: list[Path] = []
        for candidate in sorted(set(candidates)):
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(canonical_root)
            except (FileNotFoundError, RuntimeError, ValueError):
                continue
            if resolved == self.database_path:
                continue
            manifests.append(resolved)
        return manifests

    def _import_legacy_filesystem(self) -> None:
        for manifest_path in self._legacy_design_manifests():
            manifest = self._read_json_object(manifest_path)
            if manifest is None:
                continue
            session_id = manifest.get("session_id")
            design_name = manifest.get("design_name")
            if not isinstance(session_id, str) or not session_id:
                continue
            if not isinstance(design_name, str) or not design_name:
                continue
            if self.current_design_identity(session_id, design_name) is not None:
                continue
            current_path = manifest_path.parent / "current.json"
            try:
                resolved_current = current_path.resolve(strict=True)
                resolved_current.relative_to(self.root)
                design = Design.model_validate_json(resolved_current.read_text(encoding="utf-8"))
            except (OSError, RuntimeError, ValueError):
                continue
            self.store_design(
                session_id,
                design_name,
                design,
                operation="legacy-filesystem-import",
                record_duplicate=False,
            )

    def backup_to(self, destination: Path) -> Path:
        """Create and validate an online SQLite backup."""
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination == self.database_path:
            raise ValueError("backup destination must differ from the active database")
        destination.unlink(missing_ok=True)
        with closing(self._connect()) as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
        destination.chmod(0o600)
        self._validate_database_file(destination)
        return destination

    def restore_from_backup(self, backup: Path) -> None:
        """Validate a backup and atomically replace the active database."""
        backup = backup.resolve(strict=True)
        self._validate_database_file(backup)
        with NamedTemporaryFile(prefix="zaptrace-state-", suffix=".sqlite3", dir=self.root, delete=False) as handle:
            temporary_path = Path(handle.name)
        try:
            with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(temporary_path)) as target:
                source.backup(target)
            self._validate_database_file(temporary_path)
            temporary_path.chmod(0o600)
            os.replace(temporary_path, self.database_path)
            self._initialize()
        finally:
            temporary_path.unlink(missing_ok=True)

    def _validate_database_file(self, path: Path) -> None:
        self._validate_sqlite_header(path)
        try:
            with closing(self._connect(path)) as connection:
                version = int(connection.execute(_PRAGMA_USER_VERSION).fetchone()[0])
                row = connection.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise StateStoreCorruptionError(f"state database integrity check failed: {exc}") from exc
        result = str(row[0]) if row is not None else "missing quick_check result"
        if result.lower() != "ok":
            raise StateStoreCorruptionError(f"state database integrity check failed: {result}")
        if version > SCHEMA_VERSION:
            raise StateStoreSchemaError(
                f"state database uses newer schema version {version}; supported maximum is {SCHEMA_VERSION}"
            )


__all__ = [
    "DesignIdentity",
    "SCHEMA_VERSION",
    "SQLiteStateStore",
    "SessionRecord",
    "StateStoreCorruptionError",
    "StateStoreError",
    "StateStoreSchemaError",
]
