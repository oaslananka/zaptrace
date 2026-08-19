from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path

import pytest

from zaptrace.core.models import Design, DesignMeta
from zaptrace.core.session_store import SessionDesignStore, make_design_mapping
from zaptrace.core.state_store import (
    SCHEMA_VERSION,
    SQLiteStateStore,
    StateStoreCorruptionError,
    StateStoreSchemaError,
)


def test_store_creates_schema_and_passes_integrity_check(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)

    assert store.database_path == tmp_path.resolve() / "zaptrace-state.sqlite3"
    assert store.schema_version() == SCHEMA_VERSION == 1
    assert store.integrity_check() == "ok"

    with closing(sqlite3.connect(store.database_path)) as connection:
        tables = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    assert {
        "schema_migrations",
        "sessions",
        "content_blobs",
        "design_versions",
        "design_heads",
        "session_records",
        "audit_events",
        "object_access",
    } <= tables


def test_store_rejects_unknown_newer_schema(tmp_path: Path) -> None:
    database = tmp_path / "zaptrace-state.sqlite3"
    tmp_path.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA user_version = 999")
        connection.commit()

    with pytest.raises(StateStoreSchemaError, match="newer schema version 999"):
        SQLiteStateStore(tmp_path)


def test_store_detects_migration_checksum_drift(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("UPDATE schema_migrations SET checksum = 'tampered' WHERE version = 1")
        connection.commit()

    with pytest.raises(StateStoreSchemaError, match="migration checksum mismatch"):
        SQLiteStateStore(tmp_path)


def test_online_backup_and_restore_recover_state(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path / "primary")
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO sessions(session_id, created_at, updated_at) VALUES (?, ?, ?)",
            ("session-a", "2026-07-28T00:00:00+00:00", "2026-07-28T00:00:00+00:00"),
        )

    backup = store.backup_to(tmp_path / "backups" / "state.sqlite3")
    with store.transaction() as connection:
        connection.execute("DELETE FROM sessions WHERE session_id = ?", ("session-a",))
    assert store.session_exists("session-a") is False

    store.restore_from_backup(backup)

    assert store.session_exists("session-a") is True
    assert store.integrity_check() == "ok"


def test_integrity_check_fails_closed_for_corrupt_database(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    store.database_path.write_bytes(b"not a sqlite database")

    with pytest.raises(StateStoreCorruptionError, match="integrity check failed"):
        SQLiteStateStore(tmp_path)


def test_design_versions_use_stable_content_identity_and_immutable_lineage(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    initial = Design(meta=DesignMeta(name="board"))

    first = store.store_design("session-a", "board", initial, operation="parse")
    changed = initial.model_copy(deep=True)
    changed.board.width_mm = 125
    second = store.store_design("session-a", "board", changed, operation="board-update")
    duplicate = store.store_design("session-a", "board", changed, operation="explicit-commit")

    assert first.content_id.startswith("sha256:")
    assert first.version_id.startswith("version-")
    assert second.parent_version_id == first.version_id
    assert duplicate.parent_version_id == second.version_id
    assert second.content_id == duplicate.content_id
    assert second.version_id != duplicate.version_id
    assert store.current_design_identity("session-a", "board") == duplicate
    assert [item.operation for item in store.list_design_versions("session-a", "board")] == [
        "parse",
        "board-update",
        "explicit-commit",
    ]
    assert store.load_designs("session-a")["board"].board.width_mm == 125


def test_same_design_name_is_isolated_between_sessions(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    first = Design(meta=DesignMeta(name="shared"))
    second = Design(meta=DesignMeta(name="shared"))
    first.board.width_mm = 40
    second.board.width_mm = 90

    store.store_design("session-a", "shared", first, operation="parse")
    store.store_design("session-b", "shared", second, operation="parse")

    assert store.load_designs("session-a")["shared"].board.width_mm == 40
    assert store.load_designs("session-b")["shared"].board.width_mm == 90
    assert store.current_design_identity("session-a", "shared") != store.current_design_identity("session-b", "shared")


def test_legacy_filesystem_designs_import_once_without_deleting_source(tmp_path: Path) -> None:
    legacy = SessionDesignStore(tmp_path, "legacy-session")
    design = Design(meta=DesignMeta(name="legacy-board"))
    design.board.height_mm = 73
    manifest = legacy.write_design("legacy-board", design)
    legacy_current = tmp_path / manifest["current_path"]

    first_open = SQLiteStateStore(tmp_path)
    first_identity = first_open.current_design_identity("legacy-session", "legacy-board")
    second_open = SQLiteStateStore(tmp_path)
    second_identity = second_open.current_design_identity("legacy-session", "legacy-board")

    assert first_identity is not None
    assert first_identity.operation == "legacy-filesystem-import"
    assert second_identity == first_identity
    assert len(second_open.list_design_versions("legacy-session", "legacy-board")) == 1
    assert second_open.load_designs("legacy-session")["legacy-board"].board.height_mm == 73
    assert legacy_current.exists()


def test_make_design_mapping_hydrates_from_sqlite_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path))
    mapping = make_design_mapping("session-a")
    mapping["persisted"] = Design(meta=DesignMeta(name="persisted"))

    hydrated = make_design_mapping("session-a")

    assert hydrated["persisted"].meta.name == "persisted"
    database = tmp_path / "zaptrace-state.sqlite3"
    assert database.is_file()


def test_persistent_mapping_replaces_session_heads_atomically(tmp_path: Path) -> None:
    from zaptrace.core.session_store import PersistentDesignDict

    store = SQLiteStateStore(tmp_path)
    first = Design(meta=DesignMeta(name="first"))
    obsolete = Design(meta=DesignMeta(name="obsolete"))
    mapping = PersistentDesignDict(store, {}, session_id="session-a")
    mapping["first"] = first
    mapping["obsolete"] = obsolete

    replacement = Design(meta=DesignMeta(name="first"))
    replacement.board.width_mm = 88
    mapping.replace_all({"first": replacement}, operation="worker-commit")

    assert set(mapping) == {"first"}
    assert set(store.load_designs("session-a")) == {"first"}
    identity = store.current_design_identity("session-a", "first")
    assert identity is not None
    assert identity.operation == "worker-commit"
    assert store.current_design_identity("session-a", "obsolete") is None


def test_hundred_version_local_baseline_is_bounded(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    design = Design(meta=DesignMeta(name="baseline"))
    started = time.monotonic()

    for index in range(100):
        design.board.width_mm = 100 + index
        store.store_design("performance-session", "baseline", design, operation=f"baseline-{index}")

    elapsed = time.monotonic() - started
    versions = store.list_design_versions("performance-session", "baseline")
    loaded = store.load_designs("performance-session")["baseline"]

    assert len(versions) == 100
    assert loaded.board.width_mm == 199
    sqlite_files = list(tmp_path.glob("zaptrace-state.sqlite3*"))
    total_sqlite_bytes = sum(path.stat().st_size for path in sqlite_files)
    assert elapsed < 10.0
    assert total_sqlite_bytes < 10 * 1024 * 1024


def test_session_record_bulk_delete_respects_design_scope(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    for record_id, design_name in (("one", "board-a"), ("two", "board-b"), ("three", "board-a")):
        store.upsert_session_record(
            "record-session",
            "snapshot",
            record_id,
            {"record_id": record_id},
            design_name=design_name,
        )

    assert store.delete_session_records("record-session", "snapshot", design_name="board-a") == 2
    remaining = store.list_session_records("record-session", record_type="snapshot")
    assert [record.record_id for record in remaining] == ["two"]
    assert store.delete_session_records("record-session", "snapshot") == 1
    assert store.list_session_records("record-session", record_type="snapshot") == []


def test_object_authorization_event_routing_and_filters(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    child_event = {
        "event_id": "event-child",
        "timestamp": "2026-07-28T00:00:00+00:00",
        "surface": "object-authorization",
        "principal_id": "principal-a",
        "object_type": "artifact",
        "object_id": "artifact-a",
        "parent_object_type": "session",
        "parent_object_id": "session-a",
        "decision": "allow",
    }
    standalone_event = {
        "event_id": "event-standalone",
        "timestamp": "2026-07-28T00:00:01+00:00",
        "surface": "object-authorization",
        "principal_id": "principal-a",
        "object_type": "artifact",
        "object_id": "artifact-b",
        "decision": "deny",
    }
    store.append_object_authorization_event(child_event)
    store.append_object_authorization_event(standalone_event)

    filtered = store.load_object_authorization_events(
        object_type="artifact",
        principal_id="principal-a",
        parent_object_type="session",
        parent_object_id="session-a",
    )
    assert filtered == [{**child_event, "session_id": "session-a"}]
    assert store.session_exists("session-a") is True
    assert store.session_exists("object:artifact:artifact-b") is True


def test_corrupt_authorization_event_payload_fails_closed(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    event = {
        "event_id": "event-corrupt",
        "timestamp": "2026-07-28T00:00:00+00:00",
        "surface": "object-authorization",
        "principal_id": "principal-a",
        "object_type": "session",
        "object_id": "session-a",
    }
    store.append_object_authorization_event(event)
    with store.transaction() as connection:
        connection.execute(
            "UPDATE audit_events SET payload_json = ? WHERE event_id = ?",
            ("not-json", "event-corrupt"),
        )
    with pytest.raises(StateStoreCorruptionError, match="authorization event is invalid"):
        store.load_object_authorization_events(object_id="session-a")

    with store.transaction() as connection:
        connection.execute(
            "UPDATE audit_events SET payload_json = ? WHERE event_id = ?",
            ("[]", "event-corrupt"),
        )
    assert store.load_object_authorization_events(object_id="session-a") == []


def test_audit_validation_limit_and_corruption_paths(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    with pytest.raises(ValueError, match="requires session_id and event_id"):
        store.append_audit_event({})

    for index in range(2):
        store.append_audit_event(
            {
                "event_id": f"audit-{index}",
                "session_id": "audit-session",
                "timestamp": f"2026-07-28T00:00:0{index}+00:00",
                "surface": "test",
                "metadata": {"request_id": f"request-{index}"},
            }
        )
    assert [event["event_id"] for event in store.load_audit_events("audit-session", limit=1)] == ["audit-0"]

    with store.transaction() as connection:
        connection.execute(
            "UPDATE audit_events SET payload_json = ? WHERE event_id = ?",
            ("not-json", "audit-0"),
        )
    with pytest.raises(StateStoreCorruptionError, match="audit event payload is invalid"):
        store.load_audit_events("audit-session")

    with store.transaction() as connection:
        connection.execute(
            "UPDATE audit_events SET payload_json = ? WHERE event_id = ?",
            ("[]", "audit-0"),
        )
    with pytest.raises(StateStoreCorruptionError, match="payload is not an object"):
        store.load_audit_events("audit-session")


def test_design_identity_exports_json_safe_dictionary(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    identity = store.store_design(
        "identity-session",
        "identity-board",
        Design(meta=DesignMeta(name="identity-board")),
        operation="identity-test",
    )

    assert identity.to_dict() == {
        "session_id": "identity-session",
        "design_name": "identity-board",
        "content_id": identity.content_id,
        "version_id": identity.version_id,
        "parent_version_id": None,
        "operation": "identity-test",
        "created_at": identity.created_at,
    }
