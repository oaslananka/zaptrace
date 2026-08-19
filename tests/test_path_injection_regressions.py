"""Regression coverage for CodeQL path-injection alert dispositions."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Generator
from pathlib import Path

import pytest

import zaptrace.api.storage as artifact_storage
import zaptrace.core.session_store as session_storage
from zaptrace.agent import _tool_impls
from zaptrace.api.storage import ArtifactStore
from zaptrace.core.models import Design, DesignMeta
from zaptrace.core.session_store import SessionDesignStore
from zaptrace.export.kicad import _artifact_path, export_kicad_schematic


@pytest.fixture(autouse=True)
def _restore_workspace() -> Generator[None, None, None]:
    old_env = os.environ.get("ZAPTRACE_WORKSPACE")
    old_cache = _tool_impls._WORKSPACE
    yield
    if old_env is None:
        os.environ.pop("ZAPTRACE_WORKSPACE", None)
    else:
        os.environ["ZAPTRACE_WORKSPACE"] = old_env
    _tool_impls._WORKSPACE = old_cache


def _set_workspace(path: Path) -> None:
    os.environ["ZAPTRACE_WORKSPACE"] = str(path)
    _tool_impls._WORKSPACE = None


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")


def test_artifact_storage_never_uses_request_values_as_path_components(tmp_path: Path) -> None:
    store = ArtifactStore(root=tmp_path)
    outside = tmp_path.parent / "artifact-path-escape.txt"

    record = store.store_text(
        "../../other-session",
        filename="../../artifact-path-escape.txt",
        kind="../proof",
        content="evidence",
    )
    payload_path = tmp_path / record.path

    assert record.artifact_id.startswith("artifact-")
    assert len(record.artifact_id) > 30
    assert payload_path.name == "payload.txt"
    assert payload_path.is_file()
    assert payload_path.resolve().is_relative_to(tmp_path.resolve())
    assert not outside.exists()

    assert store.delete_artifact("../../other-session", "../../artifact-path-escape.txt") is None
    assert payload_path.exists()


def test_session_store_uses_opaque_directories_for_session_and_design_names(tmp_path: Path) -> None:
    session_id = "../../shared/session"
    design_name = "../../shared/design"
    store = SessionDesignStore(tmp_path, session_id)
    design = Design(meta=DesignMeta(name=design_name))

    manifest = store.write_design(design_name, design)
    current_path = tmp_path / manifest["current_path"]
    version_path = tmp_path / manifest["version_path"]

    assert current_path.resolve().is_relative_to(tmp_path.resolve())
    assert version_path.resolve().is_relative_to(tmp_path.resolve())
    assert session_id not in manifest["current_path"]
    assert design_name not in manifest["current_path"]
    assert current_path.name == "current.json"
    assert version_path.name.startswith("version-")

    reopened = SessionDesignStore(tmp_path, session_id)
    assert reopened.load_designs()[design_name].meta.name == design_name


def test_workspace_validation_returns_canonical_path_before_symlink_swap(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    inside = workspace / "inside"
    outside = tmp_path / "outside"
    workspace.mkdir()
    inside.mkdir()
    outside.mkdir()
    link = workspace / "link"
    _symlink(link, inside)
    _set_workspace(workspace)

    validated = _tool_impls._validate_path(link / "result.txt")
    assert validated == inside.resolve() / "result.txt"

    link.unlink()
    _symlink(link, outside)
    validated.write_text("safe", encoding="utf-8")

    assert (inside / "result.txt").read_text(encoding="utf-8") == "safe"
    assert not (outside / "result.txt").exists()


def test_kicad_artifact_path_is_canonical_and_filename_is_contained(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    design = Design(meta=DesignMeta(name="../../escape.kicad_sch/board"))

    artifact = _artifact_path(output_dir, design, ".kicad_sch")

    assert artifact.parent == output_dir.resolve()
    assert artifact.name.endswith(".kicad_sch")
    assert artifact.resolve().is_relative_to(output_dir.resolve())

    exported = export_kicad_schematic(design, output_dir)
    assert all(path.resolve().is_relative_to(output_dir.resolve()) for path in exported.values())


def test_kicad_artifact_path_remains_safe_after_output_symlink_swap(tmp_path: Path) -> None:
    trusted_output = tmp_path / "trusted"
    outside = tmp_path / "outside"
    trusted_output.mkdir()
    outside.mkdir()
    output_link = tmp_path / "output-link"
    _symlink(output_link, trusted_output)
    design = Design(meta=DesignMeta(name="board"))

    artifact = _artifact_path(output_link, design, ".kicad_sch")
    output_link.unlink()
    _symlink(output_link, outside)
    artifact.write_text("safe", encoding="utf-8")

    assert (trusted_output / "board.kicad_sch").read_text(encoding="utf-8") == "safe"
    assert not (outside / "board.kicad_sch").exists()


def test_artifact_store_reads_and_deletes_legacy_fixed_root_layout(tmp_path: Path) -> None:
    session_id = "legacy/session"
    artifact_id = "legacy-artifact"
    legacy_dir = tmp_path / "legacy-session" / artifact_id
    legacy_dir.mkdir(parents=True)
    payload = b"legacy evidence"
    payload_path = legacy_dir / "report.md"
    payload_path.write_bytes(payload)
    manifest = {
        "session_id": session_id,
        "owner_principal": "legacy-owner",
        "artifact_id": artifact_id,
        "kind": "proof",
        "filename": "report.md",
        "path": str(payload_path.relative_to(tmp_path)),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "created_at": "2026-07-01T00:00:00+00:00",
        "retention_seconds": 86400,
    }
    (legacy_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    store = ArtifactStore(root=tmp_path)

    listed = store.list_artifacts(session_id)
    deleted = store.delete_artifact(session_id, artifact_id)

    assert [record.artifact_id for record in listed] == [artifact_id]
    assert deleted is not None
    assert deleted.artifact_id == artifact_id
    assert not legacy_dir.exists()


def test_session_store_hydrates_legacy_layout_without_request_derived_lookup(tmp_path: Path) -> None:
    session_id = "legacy/session"
    design_name = "legacy/design"
    legacy_design_dir = tmp_path / "legacy-session" / "designs" / "legacy-design"
    legacy_design_dir.mkdir(parents=True)
    design = Design(meta=DesignMeta(name=design_name))
    current_path = legacy_design_dir / "current.json"
    current_path.write_text(design.model_dump_json(), encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "session_id": session_id,
        "design_name": design_name,
        "state_hash": "legacy",
        "current_path": str(current_path.relative_to(tmp_path)),
        "version_path": str(current_path.relative_to(tmp_path)),
    }
    (legacy_design_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    store = SessionDesignStore(tmp_path, session_id)

    assert store.session_root == (tmp_path / "legacy-session").resolve()
    assert store.load_designs()[design_name].meta.name == design_name


def test_artifact_allocator_exhausts_collisions_without_reusing_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(root=tmp_path)
    collision = tmp_path / "objects" / "artifact-collision"
    collision.mkdir(parents=True)
    monkeypatch.setattr(artifact_storage, "token_urlsafe", lambda _size: "collision")

    with pytest.raises(RuntimeError, match="unique artifact identifier"):
        store._new_artifact_dir()


def test_artifact_manifest_enumeration_rejects_broken_symlink(tmp_path: Path) -> None:
    store = ArtifactStore(root=tmp_path)
    assert ArtifactStore(root=tmp_path / "missing").list_artifacts("session") == []
    candidate = tmp_path / "legacy" / "artifact" / "manifest.json"
    candidate.parent.mkdir(parents=True)
    try:
        candidate.symlink_to(tmp_path / "does-not-exist.json")
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    assert store._iter_manifests() == []


def test_session_store_private_enumerators_handle_absent_roots_and_invalid_json(tmp_path: Path) -> None:
    assert session_storage._read_json_object(tmp_path / "missing.json") is None
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    assert session_storage._read_json_object(invalid) is None

    store = object.__new__(SessionDesignStore)
    store.root = tmp_path / "absent"
    store.sessions_root = store.root / "sessions"
    store.session_dir = store.root / "designs"

    assert store._iter_session_manifests() == []
    assert store._iter_legacy_design_manifests() == []
    assert store._iter_design_manifests() == []


def test_session_and_design_allocators_fail_closed_after_repeated_collisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions_root = tmp_path / "sessions"
    (sessions_root / "session-collision").mkdir(parents=True)
    monkeypatch.setattr(session_storage, "token_urlsafe", lambda _size: "collision")

    with pytest.raises(RuntimeError, match="unique session storage directory"):
        SessionDesignStore(tmp_path, "new-session")

    monkeypatch.setattr(session_storage, "token_urlsafe", lambda _size: "initial")
    store = SessionDesignStore(tmp_path / "design-root", "session")
    (store.session_dir / "design-collision").mkdir(parents=True)
    monkeypatch.setattr(session_storage, "token_urlsafe", lambda _size: "collision")

    with pytest.raises(RuntimeError, match="unique design storage directory"):
        store._locate_or_create_design_dir("new-design")
