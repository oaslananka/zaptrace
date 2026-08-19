"""Optional filesystem-backed session design persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from secrets import token_urlsafe
from typing import Any

from zaptrace.core.models import Design
from zaptrace.core.state import design_state_hash

_SESSIONS_DIR = "sessions"
_SESSION_MANIFEST = "session.json"
_DESIGNS_DIR = "designs"
_DESIGN_MANIFEST = "manifest.json"
_CURRENT_FILE = "current.json"
_VERSIONS_DIR = "versions"


def session_store_root() -> Path | None:
    raw = os.environ.get("ZAPTRACE_SESSION_STORE_ROOT", "").strip()
    return Path(raw).resolve() if raw else None


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


class SessionDesignStore:
    """Filesystem store using opaque server-generated path components only."""

    def __init__(self, root: Path, session_id: str) -> None:
        self.root = root.resolve()
        self.session_id = session_id
        self.sessions_root = self.root / _SESSIONS_DIR
        self.session_root = self._locate_or_create_session_root()
        self.session_dir = self.session_root / _DESIGNS_DIR

    def _iter_session_manifests(self) -> list[Path]:
        if not self.sessions_root.is_dir():
            return []
        canonical_root = self.sessions_root.resolve()
        manifests: list[Path] = []
        for candidate in sorted(self.sessions_root.glob(f"*/{_SESSION_MANIFEST}")):
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(canonical_root)
            except (FileNotFoundError, RuntimeError, ValueError):
                continue
            if resolved.parent.parent != canonical_root:
                continue
            manifests.append(resolved)
        return manifests

    def _iter_legacy_design_manifests(self) -> list[Path]:
        """Discover manifests from the pre-opaque session/design layout."""
        if not self.root.is_dir():
            return []
        canonical_root = self.root.resolve()
        manifests: list[Path] = []
        for candidate in sorted(self.root.glob(f"*/{_DESIGNS_DIR}/*/{_DESIGN_MANIFEST}")):
            try:
                resolved = candidate.resolve(strict=True)
                relative = resolved.relative_to(canonical_root)
            except (FileNotFoundError, RuntimeError, ValueError):
                continue
            if len(relative.parts) != 4 or relative.parts[1] != _DESIGNS_DIR:
                continue
            manifests.append(resolved)
        return manifests

    def _locate_or_create_session_root(self) -> Path:
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        for manifest_path in self._iter_session_manifests():
            manifest = _read_json_object(manifest_path)
            if manifest is not None and manifest.get("session_id") == self.session_id:
                return manifest_path.parent

        for manifest_path in self._iter_legacy_design_manifests():
            manifest = _read_json_object(manifest_path)
            if manifest is not None and manifest.get("session_id") == self.session_id:
                return manifest_path.parents[2]

        for _attempt in range(8):
            storage_id = f"session-{token_urlsafe(24)}"
            session_root = self.sessions_root / storage_id
            try:
                session_root.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            (session_root / _SESSION_MANIFEST).write_text(
                json.dumps({"schema_version": "1.0", "session_id": self.session_id}, indent=2) + "\n",
                encoding="utf-8",
            )
            return session_root
        raise RuntimeError("could not allocate a unique session storage directory")

    def _iter_design_manifests(self) -> list[Path]:
        if not self.session_dir.is_dir():
            return []
        canonical_root = self.session_dir.resolve()
        manifests: list[Path] = []
        for candidate in sorted(self.session_dir.glob(f"*/{_DESIGN_MANIFEST}")):
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(canonical_root)
            except (FileNotFoundError, RuntimeError, ValueError):
                continue
            if resolved.parent.parent != canonical_root:
                continue
            manifests.append(resolved)
        return manifests

    def _locate_or_create_design_dir(self, design_name: str) -> Path:
        for manifest_path in self._iter_design_manifests():
            manifest = _read_json_object(manifest_path)
            if manifest is not None and manifest.get("design_name") == design_name:
                return manifest_path.parent

        self.session_dir.mkdir(parents=True, exist_ok=True)
        for _attempt in range(8):
            storage_id = f"design-{token_urlsafe(24)}"
            design_dir = self.session_dir / storage_id
            try:
                design_dir.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            return design_dir
        raise RuntimeError("could not allocate a unique design storage directory")

    def load_designs(self) -> dict[str, Design]:
        designs: dict[str, Design] = {}
        for manifest_path in self._iter_design_manifests():
            manifest = _read_json_object(manifest_path)
            if manifest is None:
                continue
            design_name = manifest.get("design_name")
            if not isinstance(design_name, str) or not design_name:
                continue
            current_path = manifest_path.parent / _CURRENT_FILE
            try:
                design = Design.model_validate_json(current_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            designs[design_name] = design
        return designs

    def write_design(self, design_name: str, design: Design) -> dict[str, Any]:
        design_dir = self._locate_or_create_design_dir(design_name)
        versions_dir = design_dir / _VERSIONS_DIR
        versions_dir.mkdir(parents=True, exist_ok=True)
        payload = design.model_dump_json(indent=2) + "\n"
        state_hash = design_state_hash(design)
        version_path = versions_dir / f"version-{token_urlsafe(24)}.json"
        version_path.write_text(payload, encoding="utf-8")
        current_path = design_dir / _CURRENT_FILE
        current_path.write_text(payload, encoding="utf-8")
        manifest = {
            "schema_version": "1.0",
            "session_id": self.session_id,
            "design_name": design_name,
            "state_hash": state_hash,
            "current_path": str(current_path.relative_to(self.root)),
            "version_path": str(version_path.relative_to(self.root)),
        }
        (design_dir / _DESIGN_MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest


class PersistentDesignDict(dict[str, Design]):
    """Dictionary that persists committed design assignments into SQLite."""

    def __init__(
        self,
        store: Any,
        initial: dict[str, Design] | None = None,
        *,
        session_id: str | None = None,
    ) -> None:
        super().__init__(initial or {})
        self.store = store
        self.session_id = session_id or str(getattr(store, "session_id", ""))

    def _write(self, key: str, value: Design, *, operation: str) -> None:
        store_design = getattr(self.store, "store_design", None)
        if callable(store_design):
            store_design(self.session_id, key, value, operation=operation)
        else:
            self.store.write_design(key, value)

    def __setitem__(self, key: str, value: Design) -> None:
        super().__setitem__(key, value)
        self._write(key, value, operation="mapping-assignment")

    def persist(self, key: str, *, operation: str = "in-place-persist") -> None:
        if key in self:
            self._write(key, self[key], operation=operation)

    def commit_design(self, key: str, value: Design, *, operation: str) -> None:
        """Persist one design with an explicit lineage operation."""
        self.store.store_design(self.session_id, key, value, operation=operation)
        dict.__setitem__(self, key, value)

    def current_identity(self, key: str) -> Any | None:
        current = getattr(self.store, "current_design_identity", None)
        return current(self.session_id, key) if callable(current) else None

    def replace_all(self, designs: dict[str, Design], *, operation: str) -> None:
        """Atomically replace durable heads, then refresh the in-memory mapping."""
        replace_session_designs = getattr(self.store, "replace_session_designs", None)
        if not callable(replace_session_designs):
            raise TypeError("persistent design store does not support atomic session replacement")
        replace_session_designs(self.session_id, designs, operation=operation)
        dict.clear(self)
        for key, value in designs.items():
            dict.__setitem__(self, key, value)


def make_design_mapping(session_id: str) -> dict[str, Design]:
    root = session_store_root()
    if root is None or os.environ.get("ZAPTRACE_PERSISTENCE_DISABLED") == "1":
        return {}
    from zaptrace.core.state_store import SQLiteStateStore

    store = SQLiteStateStore(root)
    return PersistentDesignDict(store, store.load_designs(session_id), session_id=session_id)
