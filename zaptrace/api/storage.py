"""Configurable REST artifact storage and lifecycle helpers."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_urlsafe
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_OBJECTS_DIR = "objects"
_PAYLOAD_FILE = "payload.txt"
_MANIFEST_FILE = "manifest.json"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_segment(value: str, *, fallback: str) -> str:
    """Normalize user-facing metadata; the result is never used as a path selector."""
    cleaned = _SAFE_SEGMENT_RE.sub("-", value.strip()).strip(".-_")
    return cleaned[:128] or fallback


def _artifact_root() -> Path:
    return Path(os.environ.get("ZAPTRACE_API_ARTIFACT_ROOT", ".zaptrace/api-artifacts")).resolve()


def _retention_seconds() -> int:
    raw = os.environ.get("ZAPTRACE_API_ARTIFACT_RETENTION_SECONDS", "86400")
    try:
        return max(0, int(raw))
    except ValueError:
        return 86400


def _persistent_state_store() -> Any | None:
    if os.environ.get("ZAPTRACE_PERSISTENCE_DISABLED") == "1":
        return None
    from zaptrace.core.session_store import session_store_root

    root = session_store_root()
    if root is None:
        return None
    from zaptrace.core.state_store import SQLiteStateStore

    return SQLiteStateStore(root)


def _max_artifact_bytes() -> int:
    raw = os.environ.get("ZAPTRACE_API_MAX_ARTIFACT_BYTES", str(5 * 1024 * 1024))
    try:
        return max(1, int(raw))
    except ValueError:
        return 5 * 1024 * 1024


class ArtifactRecord(BaseModel):
    """Stored REST artifact metadata with opaque filesystem identity."""

    model_config = ConfigDict(strict=False)

    session_id: str
    owner_principal: str = ""
    artifact_id: str
    kind: str
    filename: str
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    created_at: str
    retention_seconds: int = Field(ge=0)


class ArtifactCreateRequest(BaseModel):
    """Request body for registering a REST artifact."""

    filename: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="generic", min_length=1, max_length=64)
    content: str = Field(default="", description="UTF-8 artifact content for deterministic REST storage tests")


class ArtifactStore:
    """Filesystem-backed artifact store that never derives paths from request values."""

    def __init__(
        self, *, root: Path | None = None, retention_seconds: int | None = None, max_bytes: int | None = None
    ) -> None:
        self.root = (root or _artifact_root()).resolve()
        self.objects_root = self.root / _OBJECTS_DIR
        self.retention_seconds = _retention_seconds() if retention_seconds is None else retention_seconds
        self.max_bytes = _max_artifact_bytes() if max_bytes is None else max_bytes
        self.last_cleanup_protected: list[ArtifactRecord] = []

    def _new_artifact_dir(self) -> tuple[str, Path]:
        """Allocate an opaque server-generated artifact directory."""
        self.objects_root.mkdir(parents=True, exist_ok=True)
        for _attempt in range(8):
            artifact_id = f"artifact-{token_urlsafe(24)}"
            artifact_dir = self.objects_root / artifact_id
            try:
                artifact_dir.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            return artifact_id, artifact_dir
        raise RuntimeError("could not allocate a unique artifact identifier")

    def _iter_manifests(self) -> list[Path]:
        """Return canonical manifests from current and legacy fixed-root layouts."""
        if not self.root.is_dir():
            return []
        canonical_root = self.root.resolve()
        manifests: list[Path] = []
        for candidate in sorted(self.root.glob(f"*/*/{_MANIFEST_FILE}")):
            try:
                resolved = candidate.resolve(strict=True)
                relative = resolved.relative_to(canonical_root)
            except (FileNotFoundError, RuntimeError, ValueError):
                continue
            if len(relative.parts) != 3 or relative.name != _MANIFEST_FILE:
                continue
            manifests.append(resolved)
        return manifests

    def store_text(
        self,
        session_id: str,
        *,
        filename: str,
        kind: str,
        content: str,
        owner_principal: str = "",
    ) -> ArtifactRecord:
        payload = content.encode("utf-8")
        if len(payload) > self.max_bytes:
            raise ValueError(f"artifact exceeds {self.max_bytes} byte limit")
        safe_filename = _safe_segment(filename, fallback="artifact.txt")
        safe_kind = _safe_segment(kind, fallback="generic")
        digest = hashlib.sha256(payload).hexdigest()
        artifact_id, artifact_dir = self._new_artifact_dir()
        artifact_path = artifact_dir / _PAYLOAD_FILE
        artifact_path.write_bytes(payload)
        record = ArtifactRecord(
            session_id=session_id,
            owner_principal=owner_principal,
            artifact_id=artifact_id,
            kind=safe_kind,
            filename=safe_filename,
            path=str(artifact_path.relative_to(self.root)),
            sha256=digest,
            size_bytes=len(payload),
            created_at=_utc_now().isoformat(),
            retention_seconds=self.retention_seconds,
        )
        (artifact_dir / _MANIFEST_FILE).write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
        state_store = _persistent_state_store()
        if state_store is not None:
            state_store.upsert_session_record(
                session_id,
                "artifact",
                artifact_id,
                record.model_dump(mode="json"),
            )
        return record

    def _read_manifest(self, manifest_path: Path) -> ArtifactRecord | None:
        try:
            return ArtifactRecord.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def list_artifacts(self, session_id: str) -> list[ArtifactRecord]:
        records: list[ArtifactRecord] = []
        for manifest_path in self._iter_manifests():
            record = self._read_manifest(manifest_path)
            if record is not None and record.session_id == session_id:
                records.append(record)
        return records

    def protect_artifact(
        self,
        session_id: str,
        artifact_id: str,
        *,
        reference_id: str,
        reference_kind: str,
    ) -> None:
        """Bind an artifact to active proof/release evidence."""
        if not any(record.artifact_id == artifact_id for record in self.list_artifacts(session_id)):
            raise KeyError(f"artifact not found: {artifact_id}")
        state_store = _persistent_state_store()
        if state_store is None:
            raise RuntimeError("persistent state is required to protect artifact evidence")
        state_store.register_artifact_reference(
            session_id,
            artifact_id,
            reference_id,
            reference_kind=reference_kind,
        )

    def release_artifact_reference(self, session_id: str, artifact_id: str, reference_id: str) -> bool:
        state_store = _persistent_state_store()
        if state_store is None:
            return False
        return state_store.release_artifact_reference(session_id, artifact_id, reference_id)

    @staticmethod
    def _is_protected(session_id: str, artifact_id: str) -> bool:
        state_store = _persistent_state_store()
        return bool(state_store and state_store.artifact_is_referenced(session_id, artifact_id))

    @staticmethod
    def _created_at(record: ArtifactRecord, *, fallback: datetime) -> datetime:
        try:
            return datetime.fromisoformat(record.created_at)
        except ValueError:
            return fallback

    @classmethod
    def _is_expired(cls, record: ArtifactRecord, *, current: datetime) -> bool:
        created = cls._created_at(record, fallback=current)
        return (current - created).total_seconds() >= record.retention_seconds

    @staticmethod
    def _remove_artifact_payload(
        record: ArtifactRecord,
        manifest_path: Path,
        *,
        ignore_errors: bool = False,
    ) -> None:
        shutil.rmtree(manifest_path.parent, ignore_errors=ignore_errors)
        state_store = _persistent_state_store()
        if state_store is not None:
            state_store.delete_session_record(record.session_id, "artifact", record.artifact_id)

    def delete_artifact(self, session_id: str, artifact_id: str) -> ArtifactRecord | None:
        if self._is_protected(session_id, artifact_id):
            return None
        for manifest_path in self._iter_manifests():
            record = self._read_manifest(manifest_path)
            if record is None or record.session_id != session_id or record.artifact_id != artifact_id:
                continue
            self._remove_artifact_payload(record, manifest_path)
            return record
        return None

    def cleanup_expired(self, *, session_id: str | None = None, now: datetime | None = None) -> list[ArtifactRecord]:
        current = now or _utc_now()
        deleted: list[ArtifactRecord] = []
        self.last_cleanup_protected = []
        for manifest_path in self._iter_manifests():
            record = self._read_manifest(manifest_path)
            if record is None or (session_id is not None and record.session_id != session_id):
                continue
            if not self._is_expired(record, current=current):
                continue
            if self._is_protected(record.session_id, record.artifact_id):
                self.last_cleanup_protected.append(record)
                continue
            self._remove_artifact_payload(record, manifest_path, ignore_errors=True)
            deleted.append(record)
        return deleted

    def config(self) -> dict[str, Any]:
        return {
            "artifact_root": str(self.root),
            "retention_seconds": self.retention_seconds,
            "max_artifact_bytes": self.max_bytes,
        }
