from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from zaptrace.evidence.identity import (
    EvidenceIdentity,
    EvidenceMode,
    capture_evidence_identity,
    hash_source_inputs,
    parse_name_value_pairs,
    verify_evidence_identity,
)


def _write_project(root: Path, *, version: str = "1.2.3") -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "zaptrace"\nversion = "{version}"\n', encoding="utf-8", newline="\n"
    )
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8", newline="\n")
    (root / "source.txt").write_text("alpha\n", encoding="utf-8", newline="\n")


def test_snapshot_identity_contains_required_reproducibility_fields(tmp_path: Path) -> None:
    _write_project(tmp_path)

    identity = capture_evidence_identity(
        root=tmp_path,
        mode=EvidenceMode.SNAPSHOT,
        source_inputs=["source.txt"],
        source_commit="a" * 40,
        source_ref="refs/heads/feature/evidence",
        dirty=False,
        generated_at="2026-07-22T18:00:00+00:00",
        toolchain={"python": "3.12.3", "kicad-cli": "9.0.2"},
    )

    assert identity.schema_version == "1.0"
    assert identity.mode == EvidenceMode.SNAPSHOT
    assert identity.package_version == "1.2.3"
    assert identity.source_commit == "a" * 40
    assert identity.source_ref == "refs/heads/feature/evidence"
    assert identity.dirty is False
    assert identity.lock_sha256 == hashlib.sha256(b"version = 1\n").hexdigest()
    assert identity.source_inputs == ["source.txt"]
    assert len(identity.source_inputs_sha256) == 64
    assert identity.generated_at == "2026-07-22T18:00:00+00:00"
    assert identity.toolchain["kicad-cli"] == "9.0.2"
    assert len(identity.identity_sha256) == 64


def test_identity_hash_excludes_only_generation_time(tmp_path: Path) -> None:
    _write_project(tmp_path)
    kwargs = {
        "root": tmp_path,
        "mode": EvidenceMode.SNAPSHOT,
        "source_inputs": ["source.txt"],
        "source_commit": "b" * 40,
        "source_ref": "refs/heads/main",
        "dirty": False,
        "toolchain": {"python": "3.12.3"},
    }

    first = capture_evidence_identity(generated_at="2026-07-22T18:00:00+00:00", **kwargs)
    second = capture_evidence_identity(generated_at="2026-07-22T19:00:00+00:00", **kwargs)

    assert first.generated_at != second.generated_at
    assert first.identity_sha256 == second.identity_sha256


def test_release_identity_rejects_dirty_tree_without_override(tmp_path: Path) -> None:
    _write_project(tmp_path)

    with pytest.raises(ValueError, match="dirty working tree"):
        capture_evidence_identity(
            root=tmp_path,
            mode=EvidenceMode.RELEASE,
            source_inputs=["source.txt"],
            source_commit="c" * 40,
            source_ref="refs/tags/v1.2.3",
            dirty=True,
        )


def test_release_identity_records_policy_approved_dirty_override(tmp_path: Path) -> None:
    _write_project(tmp_path)

    identity = capture_evidence_identity(
        root=tmp_path,
        mode=EvidenceMode.RELEASE,
        source_inputs=["source.txt"],
        source_commit="d" * 40,
        source_ref="refs/tags/v1.2.3",
        dirty=True,
        dirty_override_id="REL-DIRTY-OVERRIDE-1",
    )

    assert identity.dirty is True
    assert identity.dirty_override_id == "REL-DIRTY-OVERRIDE-1"


def test_release_identity_rejects_tag_version_mismatch(tmp_path: Path) -> None:
    _write_project(tmp_path, version="1.2.3")

    with pytest.raises(ValueError, match="tag/version mismatch"):
        capture_evidence_identity(
            root=tmp_path,
            mode=EvidenceMode.RELEASE,
            source_inputs=["source.txt"],
            source_commit="e" * 40,
            source_ref="refs/tags/v1.2.4",
            dirty=False,
        )


def test_release_identity_rejects_development_package_version(tmp_path: Path) -> None:
    _write_project(tmp_path, version="1.2.4.dev0")

    with pytest.raises(ValueError, match="development package version"):
        capture_evidence_identity(
            root=tmp_path,
            mode=EvidenceMode.RELEASE,
            source_inputs=["source.txt"],
            source_commit="3" * 40,
            source_ref="refs/tags/v1.2.4.dev0",
            dirty=False,
        )


def test_verify_identity_detects_stale_lock_and_source_inputs(tmp_path: Path) -> None:
    _write_project(tmp_path)
    identity = capture_evidence_identity(
        root=tmp_path,
        mode=EvidenceMode.SNAPSHOT,
        source_inputs=["source.txt"],
        source_commit="f" * 40,
        source_ref="refs/heads/main",
        dirty=False,
    )

    (tmp_path / "uv.lock").write_text("version = 2\n", encoding="utf-8")
    (tmp_path / "source.txt").write_text("beta\n", encoding="utf-8")

    errors = verify_evidence_identity(identity, root=tmp_path)

    assert "lock_sha256 is stale" in errors
    assert "source_inputs_sha256 is stale" in errors


def test_hash_source_inputs_is_path_and_content_stable(tmp_path: Path) -> None:
    _write_project(tmp_path)
    (tmp_path / "other.txt").write_text("omega\n", encoding="utf-8", newline="\n")

    first = hash_source_inputs(tmp_path, ["other.txt", "source.txt"])
    second = hash_source_inputs(tmp_path, ["source.txt", "other.txt"])

    assert first == second
    expected_payload = [
        {"path": "other.txt", "sha256": hashlib.sha256(b"omega\n").hexdigest()},
        {"path": "source.txt", "sha256": hashlib.sha256(b"alpha\n").hexdigest()},
    ]
    expected = hashlib.sha256(json.dumps(expected_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert first == expected


def test_parse_name_value_pairs_rejects_ambiguous_values() -> None:
    assert parse_name_value_pairs(["python=3.12.3", "kicad-cli=9.0.2"], option="--tool-version") == {
        "python": "3.12.3",
        "kicad-cli": "9.0.2",
    }
    with pytest.raises(ValueError, match="name=value"):
        parse_name_value_pairs(["python"], option="--tool-version")


def test_embedded_identity_rejects_missing_toolchain(tmp_path: Path) -> None:
    _write_project(tmp_path)
    identity = capture_evidence_identity(
        root=tmp_path,
        source_inputs=["source.txt"],
        source_commit="1" * 40,
        source_ref="refs/heads/main",
        dirty=False,
        toolchain={"python": "3.12.3"},
    )
    payload = identity.model_dump(mode="json")
    payload["toolchain"] = {}

    with pytest.raises(ValidationError, match="toolchain"):
        EvidenceIdentity.model_validate(payload)


def test_embedded_identity_rejects_hash_tampering(tmp_path: Path) -> None:
    _write_project(tmp_path)
    identity = capture_evidence_identity(
        root=tmp_path,
        source_inputs=["source.txt"],
        source_commit="2" * 40,
        source_ref="refs/heads/main",
        dirty=False,
        toolchain={"python": "3.12.3"},
    )
    payload = identity.model_dump(mode="json")
    payload["package_version"] = "9.9.9"

    with pytest.raises(ValidationError, match="identity_sha256"):
        EvidenceIdentity.model_validate(payload)


def test_identity_uses_github_sha_when_git_head_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    _write_project(tmp_path)
    github_sha = "8" * 40
    monkeypatch.setenv("GITHUB_SHA", github_sha)

    identity = capture_evidence_identity(
        root=tmp_path,
        source_inputs=["source.txt"],
        source_ref="refs/heads/main",
        dirty=False,
    )

    assert identity.source_commit == github_sha


def test_identity_rejects_missing_git_head_and_github_sha(tmp_path: Path, monkeypatch) -> None:
    _write_project(tmp_path)
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    with pytest.raises(ValueError, match="source commit is unavailable"):
        capture_evidence_identity(
            root=tmp_path,
            source_inputs=["source.txt"],
            source_ref="refs/heads/main",
            dirty=False,
        )


def test_identity_prefers_checked_out_head_over_ambient_github_sha(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    _write_project(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Evidence Tests"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=tmp_path, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    monkeypatch.setenv("GITHUB_SHA", "9" * 40)

    identity = capture_evidence_identity(
        root=tmp_path,
        source_inputs=["source.txt"],
        source_ref="refs/heads/main",
        dirty=False,
    )

    assert identity.source_commit == head
