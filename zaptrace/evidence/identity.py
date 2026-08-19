"""Shared source and toolchain identity for release-critical evidence."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from zaptrace.versioning import VersionStage, parse_python_version

_IDENTITY_SCHEMA_VERSION = "1.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_UV_LOCK_PATH = "uv.lock"


class EvidenceMode(StrEnum):
    """Whether evidence describes an unreleased snapshot or a tagged release."""

    SNAPSHOT = "snapshot"
    RELEASE = "release"


class EvidenceIdentity(BaseModel):
    """Immutable identity attached to release-critical evidence."""

    model_config = ConfigDict(frozen=True, strict=False)

    schema_version: Literal["1.0"] = _IDENTITY_SCHEMA_VERSION
    mode: EvidenceMode
    package_version: str = Field(min_length=1)
    source_commit: str = Field(pattern=_COMMIT_RE.pattern)
    source_ref: str = Field(min_length=1)
    dirty: bool
    dirty_override_id: str = ""
    lock_sha256: str = Field(pattern=_SHA256_RE.pattern)
    source_inputs: list[str] = Field(min_length=1)
    source_inputs_sha256: str = Field(pattern=_SHA256_RE.pattern)
    generated_at: str = Field(min_length=1)
    toolchain: dict[str, str] = Field(min_length=1)
    identity_sha256: str = Field(pattern=_SHA256_RE.pattern)

    @model_validator(mode="after")
    def validate_embedded_identity(self) -> Self:
        """Reject incomplete or tampered identities loaded from JSON."""
        if self.source_inputs != sorted(set(self.source_inputs)) or any(
            not item.strip() for item in self.source_inputs
        ):
            raise ValueError("source_inputs must be non-empty, unique, and sorted")
        if any(not name.strip() or not value.strip() for name, value in self.toolchain.items()):
            raise ValueError("toolchain names and values must be non-empty")
        expected = _identity_sha256(self.model_dump(mode="json"))
        if self.identity_sha256 != expected:
            raise ValueError("identity_sha256 does not match identity fields")
        return self


def parse_name_value_pairs(values: Iterable[str], *, option: str) -> dict[str, str]:
    """Parse repeatable ``name=value`` CLI values without silent overwrites."""
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option} must use name=value format: {value!r}")
        name, raw = value.split("=", 1)
        name = name.strip()
        raw = raw.strip()
        if not name or not raw:
            raise ValueError(f"{option} must include non-empty name and value: {value!r}")
        if name in parsed:
            raise ValueError(f"{option} contains duplicate name: {name!r}")
        parsed[name] = raw
    return parsed


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _normalize_source_inputs(root: Path, paths: Iterable[str | Path]) -> list[str]:
    normalized: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(root.resolve())
            except ValueError as exc:
                raise ValueError(f"source input is outside repository root: {raw_path}") from exc
        normalized.append(path.as_posix())
    return sorted(set(normalized))


def hash_source_inputs(root: Path, paths: Iterable[str | Path]) -> str:
    """Hash source-input paths and exact bytes in stable path order."""
    normalized = _normalize_source_inputs(root, paths)
    payload: list[dict[str, str]] = []
    for relative in normalized:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"source input does not exist: {relative}")
        payload.append({"path": relative, "sha256": _sha256_file(path)})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return _sha256_bytes(encoded)


def _package_version(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = str(data.get("project", {}).get("version", "")).strip()
    if not version:
        raise ValueError("pyproject.toml does not define project.version")
    return version


def _git_output(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail or proc.returncode}")
    return proc.stdout.strip()


def _capture_source_commit(root: Path) -> str:
    with contextlib.suppress(ValueError):
        return _git_output(root, "rev-parse", "HEAD").strip().lower()
    github_sha = os.environ.get("GITHUB_SHA", "").strip().lower()
    if github_sha:
        return github_sha
    raise ValueError("source commit is unavailable from Git HEAD and GITHUB_SHA")


def _capture_source_ref(root: Path) -> str:
    github_ref = os.environ.get("GITHUB_REF", "").strip()
    if github_ref:
        return github_ref
    branch = _git_output(root, "symbolic-ref", "--quiet", "HEAD")
    return branch or "detached"


def _capture_dirty(root: Path) -> bool:
    return bool(_git_output(root, "status", "--porcelain", "--untracked-files=normal"))


def _capture_toolchain(root: Path) -> dict[str, str]:
    tools = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    with contextlib.suppress(ValueError):
        tools["git"] = _git_output(root, "--version")
    return tools


def _identity_payload(values: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in values.items() if key not in {"generated_at", "identity_sha256"}}


def _identity_sha256(values: Mapping[str, object]) -> str:
    encoded = json.dumps(_identity_payload(values), sort_keys=True, separators=(",", ":"), default=str).encode()
    return _sha256_bytes(encoded)


def _validate_release_policy(
    *,
    mode: EvidenceMode,
    package_version: str,
    source_ref: str,
    dirty: bool,
    dirty_override_id: str,
) -> None:
    if mode != EvidenceMode.RELEASE:
        return
    if parse_python_version(package_version).stage == VersionStage.DEVELOPMENT:
        raise ValueError(f"development package version cannot produce release evidence: {package_version!r}")
    if dirty and not dirty_override_id:
        raise ValueError("dirty working tree cannot produce release evidence without an approved override")
    tag = source_ref.removeprefix("refs/tags/")
    expected_tag = f"v{package_version}"
    if not source_ref.startswith("refs/tags/") or tag != expected_tag:
        raise ValueError(f"tag/version mismatch: expected refs/tags/{expected_tag}, got {source_ref!r}")


def capture_evidence_identity(
    *,
    root: str | Path,
    mode: EvidenceMode | str = EvidenceMode.SNAPSHOT,
    source_inputs: Iterable[str | Path] = ("pyproject.toml", _UV_LOCK_PATH),
    source_commit: str | None = None,
    source_ref: str | None = None,
    dirty: bool | None = None,
    dirty_override_id: str = "",
    generated_at: str | None = None,
    toolchain: Mapping[str, str] | None = None,
) -> EvidenceIdentity:
    """Capture one canonical identity for a report or proof artifact."""
    root_path = Path(root).resolve()
    evidence_mode = EvidenceMode(mode)
    normalized_inputs = _normalize_source_inputs(root_path, source_inputs)
    package_version = _package_version(root_path)
    commit = (source_commit or _capture_source_commit(root_path)).strip().lower()
    ref = (source_ref or _capture_source_ref(root_path)).strip()
    is_dirty = _capture_dirty(root_path) if dirty is None else dirty
    override_id = dirty_override_id.strip()
    if not _COMMIT_RE.fullmatch(commit):
        raise ValueError(f"source_commit must be a full 40-character hexadecimal Git commit: {commit!r}")
    if not ref:
        raise ValueError("source_ref must be non-empty")
    _validate_release_policy(
        mode=evidence_mode,
        package_version=package_version,
        source_ref=ref,
        dirty=is_dirty,
        dirty_override_id=override_id,
    )
    lock_path = root_path / _UV_LOCK_PATH
    if not lock_path.is_file():
        raise ValueError("uv.lock is required for evidence identity")
    lock_sha256 = _sha256_file(lock_path)
    source_inputs_sha256 = hash_source_inputs(root_path, normalized_inputs)
    values: dict[str, object] = {
        "schema_version": _IDENTITY_SCHEMA_VERSION,
        "mode": evidence_mode.value,
        "package_version": package_version,
        "source_commit": commit,
        "source_ref": ref,
        "dirty": is_dirty,
        "dirty_override_id": override_id,
        "lock_sha256": lock_sha256,
        "source_inputs": normalized_inputs,
        "source_inputs_sha256": source_inputs_sha256,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "toolchain": dict(sorted((toolchain or _capture_toolchain(root_path)).items())),
    }
    values["identity_sha256"] = _identity_sha256(values)
    return EvidenceIdentity.model_validate(values)


def verify_evidence_identity(identity: EvidenceIdentity, *, root: str | Path) -> list[str]:
    """Return stale or internally inconsistent identity diagnostics."""
    root_path = Path(root).resolve()
    errors: list[str] = []
    if identity.schema_version != _IDENTITY_SCHEMA_VERSION:
        errors.append(f"unsupported evidence identity schema: {identity.schema_version}")
    if not _SHA256_RE.fullmatch(identity.lock_sha256):
        errors.append("lock_sha256 is malformed")
    if not _SHA256_RE.fullmatch(identity.source_inputs_sha256):
        errors.append("source_inputs_sha256 is malformed")
    if not _SHA256_RE.fullmatch(identity.identity_sha256):
        errors.append("identity_sha256 is malformed")
    if _identity_sha256(identity.model_dump(mode="json")) != identity.identity_sha256:
        errors.append("identity_sha256 does not match identity fields")
    try:
        if _package_version(root_path) != identity.package_version:
            errors.append("package_version is stale")
        if _sha256_file(root_path / _UV_LOCK_PATH) != identity.lock_sha256:
            errors.append("lock_sha256 is stale")
        if hash_source_inputs(root_path, identity.source_inputs) != identity.source_inputs_sha256:
            errors.append("source_inputs_sha256 is stale")
        _validate_release_policy(
            mode=identity.mode,
            package_version=identity.package_version,
            source_ref=identity.source_ref,
            dirty=identity.dirty,
            dirty_override_id=identity.dirty_override_id,
        )
    except ValueError as exc:
        errors.append(str(exc))
    return errors
