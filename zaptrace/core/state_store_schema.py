"""Schema and checksum-verified migrations for persistent ZapTrace state."""

from __future__ import annotations

import hashlib

SCHEMA_VERSION = 1
_DATABASE_NAME = "zaptrace-state.sqlite3"
_BUSY_TIMEOUT_MS = 5_000

_MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS content_blobs (
    content_id TEXT PRIMARY KEY,
    media_type TEXT NOT NULL,
    payload BLOB NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS design_versions (
    version_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    design_name TEXT NOT NULL,
    content_id TEXT NOT NULL,
    parent_version_id TEXT,
    operation TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY(content_id) REFERENCES content_blobs(content_id),
    FOREIGN KEY(parent_version_id) REFERENCES design_versions(version_id)
);
CREATE INDEX IF NOT EXISTS idx_design_versions_session_name
    ON design_versions(session_id, design_name, created_at);
CREATE TABLE IF NOT EXISTS design_heads (
    session_id TEXT NOT NULL,
    design_name TEXT NOT NULL,
    version_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(session_id, design_name),
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY(version_id) REFERENCES design_versions(version_id)
);
CREATE TABLE IF NOT EXISTS session_records (
    session_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    design_name TEXT NOT NULL DEFAULT '',
    content_id TEXT,
    metadata_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    protected INTEGER NOT NULL DEFAULT 0 CHECK(protected IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(session_id, record_type, record_id),
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY(content_id) REFERENCES content_blobs(content_id)
);
CREATE INDEX IF NOT EXISTS idx_session_records_lookup
    ON session_records(session_id, record_type, design_name, active);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    principal_id TEXT NOT NULL DEFAULT '',
    surface TEXT NOT NULL,
    object_type TEXT NOT NULL DEFAULT '',
    object_id TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL DEFAULT '',
    design_name TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_audit_events_session_created
    ON audit_events(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_object
    ON audit_events(object_type, object_id, created_at);
CREATE TABLE IF NOT EXISTS object_access (
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    owner_principal TEXT NOT NULL,
    delegates_json TEXT NOT NULL,
    parent_object_type TEXT NOT NULL DEFAULT '',
    parent_object_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(object_type, object_id)
);
""".strip()

_MIGRATIONS = {1: _MIGRATION_1}
_MIGRATION_CHECKSUMS = {
    version: hashlib.sha256(sql.encode("utf-8")).hexdigest() for version, sql in _MIGRATIONS.items()
}
