# Persistent versioned state

ZapTrace can persist committed design sessions to a local SQLite database. The feature is opt-in and is intended for a private workstation or a controlled team service. It does **not** turn ZapTrace into a safe arbitrary multi-tenant SaaS platform.

## Enable persistence

Set one private directory before starting the CLI, MCP server, or REST API:

```bash
export ZAPTRACE_SESSION_STORE_ROOT="$HOME/.local/share/zaptrace/state"
zaptrace-mcp
```

ZapTrace creates:

```text
$ZAPTRACE_SESSION_STORE_ROOT/zaptrace-state.sqlite3
```

The database file is created with owner-only permissions. User-supplied session IDs, design names, labels, and artifact names are stored as SQL values; they are never used as SQL identifiers or filesystem paths.

When `ZAPTRACE_SESSION_STORE_ROOT` is unset, ZapTrace retains its original process-local in-memory behavior.

## What survives restart

The durable backend records:

- current committed design heads;
- immutable design-version lineage and parent version IDs;
- content-addressed canonical design JSON identified by SHA-256;
- named snapshots and snapshot rollback targets;
- transaction preview, validation, rejection, commit, and rollback state;
- capability audit events and object-authorization decisions;
- session ownership, delegates, and parent-object relationships;
- ERC, DRC, validation, and release evidence identities;
- artifact metadata and active proof/release references.

A successful isolated MCP mutation is written only by the trusted parent process after the worker has exited successfully. A timed-out, cancelled, or failed worker cannot publish candidate state to SQLite.

## Design and evidence identity

Each canonical design payload receives a stable content ID:

```text
sha256:<digest>
```

Each committed mutation receives a distinct immutable version ID:

```text
version-<UUID>
```

Identical content may reuse the same content blob while still producing a new lineage record. Evidence generated while persistence is enabled includes `persistent_content_id` and `persistent_version_id`, in addition to the existing design-state hashes.

Two sessions may use the same design name without sharing a head, snapshot, transaction, audit stream, or ACL. Session ID and design name form the storage boundary.

## SQLite behavior

ZapTrace uses Python's standard-library `sqlite3` driver with:

- write-ahead logging (WAL);
- foreign-key enforcement;
- serialized write transactions;
- a bounded busy timeout;
- `PRAGMA quick_check` at startup;
- ordered checksum-verified schema migrations;
- fail-closed rejection of unknown newer schemas.

The first schema contains tables for migrations, sessions, content blobs, design versions and heads, typed session records, audit events, and object access records.

## Backup

Stop destructive maintenance while producing an operator backup. SQLite's online backup API can copy a live database consistently:

```python
from pathlib import Path
from zaptrace.core.state_store import SQLiteStateStore

store = SQLiteStateStore(Path("/srv/zaptrace/state"))
backup = store.backup_to(Path("/srv/zaptrace/backups/state-before-upgrade.sqlite3"))
print(backup)
```

`backup_to()` verifies the copied database before returning. Protect backup files with the same filesystem permissions and retention policy as the active state directory.

## Restore and corruption response

A malformed SQLite header, failed `quick_check`, invalid stored JSON, or migration-checksum mismatch stops state initialization. Do not delete the active database before preserving it for diagnosis.

Restore a validated backup:

```python
from pathlib import Path
from zaptrace.core.state_store import SQLiteStateStore

store = SQLiteStateStore(Path("/srv/zaptrace/state"))
store.restore_from_backup(Path("/srv/zaptrace/backups/state-before-upgrade.sqlite3"))
```

The backup is copied into a temporary database, integrity-checked, and then atomically replaces the active database. ZapTrace re-runs schema and integrity validation after replacement.

## Migration and rollback policy

Migrations are forward-only, ordered, transactional, and bound to committed SHA-256 checksums. Before applying a future schema migration:

1. create and validate an online backup;
2. deploy one ZapTrace version against the database;
3. confirm startup integrity and representative session reads;
4. retain the pre-migration backup for the operational rollback window.

ZapTrace does not perform destructive down-migrations in place. Rollback restores the pre-migration backup while running the matching earlier application version.

The previous filesystem-only session design layout is imported once with operation `legacy-filesystem-import`. Import is idempotent and does not delete legacy files. Remove legacy files only after independent backup and verification.

## Session destruction and retention

An authorized `session_destroy` removes the durable session, design heads and lineage, snapshots, transactions, audit rows, and unreferenced content blobs in one SQLite transaction. Object ACLs are removed separately through the same authorized lifecycle.

Artifact payloads remain in the opaque filesystem artifact store. Expiration cleanup skips an artifact while an active proof or release reference exists. Explicit deletion also fails closed for protected artifacts. After the last reference is released, ordinary retention cleanup may remove the payload and its metadata.

Historical design content remains referenced by immutable version lineage until the owning session is explicitly destroyed. ZapTrace does not silently prune committed design history.

## Deployment modes

### Local single-user

Use a directory owned by the local account, keep the service bound to loopback unless network authentication is configured, and include the SQLite database and artifact root in backups.

### Controlled team service

Use one authenticated ZapTrace service instance, or coordinated workers sharing one protected local volume. Enforce:

- server-controlled authentication and session allowlists;
- object ownership and delegation;
- private filesystem ownership and permissions;
- scheduled, tested backups;
- bounded artifact retention;
- one operational owner for schema upgrades and restore decisions.

SQLite WAL permits concurrent readers and serialized writers. It does not provide distributed consensus, cross-region replication, or protection from incorrectly configured independent service instances.

## Verification commands

```bash
pytest tests/test_state_store.py tests/test_session_store.py tests/test_transactions.py -q
pytest tests/test_agent_execution.py tests/test_mcp_server.py -q
pytest tests/test_object_authorization.py tests/test_api_hardening.py -q
```

The state-store suite includes schema and checksum checks, corruption handling, online backup/restore, restart hydration, same-name session isolation, legacy import, explicit deletion, and a bounded 100-version local regression fixture.

## Non-claims

Persistent state does not establish:

- arbitrary untrusted multi-tenant isolation;
- a hosted or managed service;
- distributed transaction guarantees across independent databases or filesystems;
- regulatory retention or deletion certification;
- hardware correctness, fabrication readiness, manufacturer approval, or qualified engineering sign-off.

Persistence improves durability, traceability, and recovery for controlled deployments. Existing authentication, capability, release-evidence, human-review, and physical-validation requirements still apply.
