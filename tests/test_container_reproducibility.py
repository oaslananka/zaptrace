"""Tests for locked container dependency and image provenance evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import ci_container_reproducibility as policy


def _hashed_manifest() -> bytes:
    return (
        b"click==8.4.1 \\\n"
        b"    --hash=sha256:482be17c6991b8c19c5429a1e995d9b0efdbb63172824c41f99965dc0ade8ec2\n"
        b"rich==15.0.0 ; python_version >= '3.12' \\\n"
        b"    --hash=sha256:33bd4ef74232fb73fe9279a257718407f169c09b78a87ad3d296f548e27de0bb\n"
    )


def _toolchain() -> policy.ToolchainIdentity:
    return policy.ToolchainIdentity(
        python=policy.ToolIdentity("Python 3.13.11", "a" * 64),
        maturin=policy.ToolIdentity("maturin 1.13.3", "b" * 64),
        uv=policy.ToolIdentity("uv 0.11.29", "c" * 64),
    )


def _runtime_files(tmp_path: Path, *, apk_pin: str = "ngspice=42-r0") -> tuple[Path, Path, Path]:
    manifest = tmp_path / "container-runtime.txt"
    manifest.write_bytes(_hashed_manifest())
    apk_manifest = tmp_path / "container-apk.txt"
    apk_manifest.write_text(f"{apk_pin}\n", encoding="utf-8")
    wheel = tmp_path / "zaptrace.whl"
    wheel.write_bytes(b"wheel")
    return manifest, apk_manifest, wheel


def _builder_provenance_inputs(tmp_path: Path) -> tuple[dict[str, Any], Path, Path, Path]:
    manifest, apk_manifest, wheel = _runtime_files(tmp_path)
    builder_manifest = tmp_path / "container-builder.txt"
    builder_manifest.write_bytes(_hashed_manifest())
    arguments: dict[str, Any] = {
        "source_commit": "1" * 40,
        "base_digest": "sha256:" + "2" * 64,
        "manifest": manifest,
        "expected_manifest_sha256": hashlib.sha256(_hashed_manifest()).hexdigest(),
        "wheel": wheel,
        "toolchain": _toolchain(),
        "apk_manifest": apk_manifest,
        "expected_apk_manifest_sha256": hashlib.sha256(apk_manifest.read_bytes()).hexdigest(),
        "builder_dependency_manifest": builder_manifest,
        "expected_builder_dependency_manifest_sha256": hashlib.sha256(builder_manifest.read_bytes()).hexdigest(),
    }
    return arguments, manifest, apk_manifest, builder_manifest


def _builder_image_report(tmp_path: Path, *, tamper_manifest: bool = False) -> tuple[dict[str, Any], Path]:
    arguments, manifest, apk_manifest, builder_manifest = _builder_provenance_inputs(tmp_path)
    provenance = policy.build_provenance(**arguments)
    provenance_path = tmp_path / "provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    if tamper_manifest:
        builder_manifest.write_bytes(_hashed_manifest() + b"idna==3.18 --hash=sha256:" + b"d" * 64 + b"\n")
    report = policy.build_image_report(
        provenance_path=provenance_path,
        manifest=manifest,
        expected_source_commit="1" * 40,
        expected_base_digest="sha256:" + "2" * 64,
        image_digest="sha256:" + "4" * 64,
        apk_manifest=apk_manifest,
        builder_dependency_manifest=builder_manifest,
    )
    return report, builder_manifest


def _bound_provenance(tmp_path: Path) -> tuple[Path, Path, Path]:
    manifest, apk_manifest, wheel = _runtime_files(tmp_path)
    provenance = policy.build_provenance(
        source_commit="1" * 40,
        base_digest="sha256:" + "2" * 64,
        manifest=manifest,
        expected_manifest_sha256=hashlib.sha256(_hashed_manifest()).hexdigest(),
        wheel=wheel,
        toolchain=_toolchain(),
        apk_manifest=apk_manifest,
        expected_apk_manifest_sha256=hashlib.sha256(apk_manifest.read_bytes()).hexdigest(),
    )
    provenance_path = tmp_path / "provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    return manifest, apk_manifest, provenance_path


def test_committed_builder_manifest_is_hash_locked() -> None:
    manifest = Path("requirements/container-builder.txt")

    assert policy.parse_hashed_manifest(manifest) == ["maturin==1.13.3", "uv==0.11.29"]


def test_committed_alpine_runtime_manifest_matches_pinned_base_repository() -> None:
    manifest = Path("requirements/container-apk.txt")

    assert manifest.read_text(encoding="utf-8").splitlines() == [
        "libcrypto3=3.5.8-r0",
        "libssl3=3.5.8-r0",
        "musl=1.2.6-r2",
        "musl-utils=1.2.6-r2",
        "ngspice=46-r0",
        "zlib=1.3.2-r0",
    ]


def test_lock_report_records_upgraded_runtime_os_packages(tmp_path: Path) -> None:
    manifest = tmp_path / "container-runtime.txt"
    manifest.write_bytes(_hashed_manifest())
    apk_manifest = tmp_path / "container-apk.txt"
    apk_manifest.write_text(
        "\n".join(
            [
                "libcrypto3=3.5.8-r0",
                "libssl3=3.5.8-r0",
                "musl=1.2.6-r2",
                "musl-utils=1.2.6-r2",
                "ngspice=46-r0",
                "zlib=1.3.2-r0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = policy.build_lock_report(manifest, _hashed_manifest(), "uv 0.11.29", apk_manifest)

    assert report["status"] == "pass"
    assert report["checks"]["apk_manifest_is_exactly_pinned"] is True
    assert report["apk_manifest"]["packages"] == [
        "libcrypto3=3.5.8-r0",
        "libssl3=3.5.8-r0",
        "musl=1.2.6-r2",
        "musl-utils=1.2.6-r2",
        "ngspice=46-r0",
        "zlib=1.3.2-r0",
    ]
    assert len(report["apk_manifest"]["sha256"]) == 64


def test_manifest_requires_exact_pins_and_hashes(tmp_path: Path) -> None:
    manifest = tmp_path / "container-runtime.txt"
    manifest.write_bytes(_hashed_manifest())

    requirements = policy.parse_hashed_manifest(manifest)

    assert requirements == ["click==8.4.1", "rich==15.0.0 ; python_version >= '3.12'"]


@pytest.mark.parametrize(
    "content, message",
    [
        (b"click>=8.4.1 --hash=sha256:" + b"a" * 64 + b"\n", "exactly pinned"),
        (b"click==8.4.1\n", "missing SHA-256"),
        (b"-e .\n", "editable or local"),
        (b"click @ https://example.invalid/click.whl --hash=sha256:" + b"a" * 64 + b"\n", "direct URL"),
    ],
)
def test_manifest_rejects_unconstrained_entries(tmp_path: Path, content: bytes, message: str) -> None:
    manifest = tmp_path / "container-runtime.txt"
    manifest.write_bytes(content)

    with pytest.raises(policy.ContainerReproducibilityError, match=message):
        policy.parse_hashed_manifest(manifest)


def test_lock_report_detects_regeneration_drift(tmp_path: Path) -> None:
    manifest = tmp_path / "container-runtime.txt"
    manifest.write_bytes(_hashed_manifest())

    passed = policy.build_lock_report(manifest, _hashed_manifest(), "uv 0.11.29")
    drifted = policy.build_lock_report(
        manifest, _hashed_manifest() + b"idna==3.18 --hash=sha256:" + b"b" * 64 + b"\n", "uv 0.11.29"
    )

    assert passed["status"] == "pass"
    assert passed["manifest"]["sha256"] == hashlib.sha256(_hashed_manifest()).hexdigest()
    assert passed["requirement_count"] == 2
    assert drifted["status"] == "fail"
    assert drifted["checks"]["regenerated_manifest_matches"] is False


def test_lock_report_records_exact_alpine_runtime_manifest(tmp_path: Path) -> None:
    manifest, apk_manifest, _wheel = _runtime_files(tmp_path)

    report = policy.build_lock_report(manifest, _hashed_manifest(), "uv 0.11.29", apk_manifest)

    assert report["status"] == "pass"
    assert report["checks"]["apk_manifest_is_exactly_pinned"] is True
    assert report["apk_manifest"]["packages"] == ["ngspice=42-r0"]
    assert len(report["apk_manifest"]["sha256"]) == 64


def test_lock_report_rejects_unpinned_alpine_package(tmp_path: Path) -> None:
    manifest, apk_manifest, _wheel = _runtime_files(tmp_path, apk_pin="ngspice")

    report = policy.build_lock_report(manifest, _hashed_manifest(), "uv 0.11.29", apk_manifest)

    assert report["status"] == "fail"
    assert report["checks"]["apk_manifest_is_exactly_pinned"] is False


def test_build_provenance_binds_source_base_wheel_and_manifest(tmp_path: Path) -> None:
    manifest, _apk_manifest, wheel = _runtime_files(tmp_path)
    source_commit = "1" * 40
    base_digest = "sha256:" + "2" * 64
    manifest_sha256 = hashlib.sha256(_hashed_manifest()).hexdigest()

    report = policy.build_provenance(
        source_commit=source_commit,
        base_digest=base_digest,
        manifest=manifest,
        expected_manifest_sha256=manifest_sha256,
        wheel=wheel,
        toolchain=_toolchain(),
    )

    assert report["status"] == "pass"
    assert report["source_commit"] == source_commit
    assert report["base_image_digest"] == base_digest
    assert report["dependency_manifest"]["sha256"] == manifest_sha256
    assert report["wheel"]["sha256"] == hashlib.sha256(b"wheel").hexdigest()
    assert report["toolchain"]["python"]["version"] == "Python 3.13.11"
    assert report["toolchain"]["python"]["sha256"] == "a" * 64
    assert len(report["evidence_digest"]) == 64


def test_build_provenance_binds_builder_dependency_manifest(tmp_path: Path) -> None:
    arguments, _manifest, _apk_manifest, builder_manifest = _builder_provenance_inputs(tmp_path)

    report = policy.build_provenance(**arguments)

    builder_digest = hashlib.sha256(builder_manifest.read_bytes()).hexdigest()
    assert report["builder_dependency_manifest"] == {
        "filename": "container-builder.txt",
        "sha256": builder_digest,
        "size_bytes": len(_hashed_manifest()),
        "requirements": ["click==8.4.1", "rich==15.0.0 ; python_version >= '3.12'"],
    }


def test_build_provenance_rejects_builder_dependency_digest_mismatch(tmp_path: Path) -> None:
    arguments, _manifest, _apk_manifest, _builder_manifest = _builder_provenance_inputs(tmp_path)
    arguments["expected_builder_dependency_manifest_sha256"] = "9" * 64

    with pytest.raises(policy.ContainerReproducibilityError, match="builder dependency manifest digest"):
        policy.build_provenance(**arguments)


def test_build_provenance_rejects_builder_digest_without_manifest(tmp_path: Path) -> None:
    arguments, _manifest, _apk_manifest, _builder_manifest = _builder_provenance_inputs(tmp_path)
    arguments.pop("builder_dependency_manifest")

    with pytest.raises(policy.ContainerReproducibilityError, match="builder dependency manifest is required"):
        policy.build_provenance(**arguments)


def test_image_report_verifies_builder_dependency_manifest(tmp_path: Path) -> None:
    report, builder_manifest = _builder_image_report(tmp_path)

    assert report["status"] == "pass"
    assert report["checks"]["builder_dependency_manifest_digest_matches"] is True
    assert report["builder_dependency_manifest_sha256"] == hashlib.sha256(builder_manifest.read_bytes()).hexdigest()


def test_image_report_fails_on_builder_dependency_manifest_mismatch(tmp_path: Path) -> None:
    report, _builder_manifest = _builder_image_report(tmp_path, tamper_manifest=True)

    assert report["status"] == "fail"
    assert report["checks"]["builder_dependency_manifest_digest_matches"] is False


def test_build_provenance_marks_default_source_placeholder_unbound(tmp_path: Path) -> None:
    manifest, _apk_manifest, wheel = _runtime_files(tmp_path)

    report = policy.build_provenance(
        source_commit="0" * 40,
        base_digest="sha256:" + "2" * 64,
        manifest=manifest,
        expected_manifest_sha256=hashlib.sha256(_hashed_manifest()).hexdigest(),
        wheel=wheel,
        toolchain=_toolchain(),
    )

    assert report["status"] == "unbound"
    assert report["source_bound"] is False


def test_build_provenance_rejects_unverified_build_arguments(tmp_path: Path) -> None:
    manifest, _apk_manifest, wheel = _runtime_files(tmp_path)
    arguments = {
        "source_commit": "1" * 40,
        "base_digest": "sha256:" + "2" * 64,
        "manifest": manifest,
        "expected_manifest_sha256": "3" * 64,
        "wheel": wheel,
        "toolchain": _toolchain(),
    }

    with pytest.raises(policy.ContainerReproducibilityError, match="manifest digest"):
        policy.build_provenance(**arguments)


def test_image_report_verifies_provenance_and_exact_image_digest(tmp_path: Path) -> None:
    manifest, apk_manifest, provenance_path = _bound_provenance(tmp_path)

    report = policy.build_image_report(
        provenance_path=provenance_path,
        manifest=manifest,
        expected_source_commit="1" * 40,
        expected_base_digest="sha256:" + "2" * 64,
        image_digest="sha256:" + "4" * 64,
        apk_manifest=apk_manifest,
    )

    assert report["status"] == "pass"
    assert report["image_digest"] == "sha256:" + "4" * 64
    assert report["checks"] == {
        "apk_manifest_digest_matches": True,
        "base_digest_matches": True,
        "manifest_digest_matches": True,
        "provenance_passed": True,
        "source_commit_matches": True,
        "wheel_digest_is_valid": True,
    }


def test_image_report_fails_on_source_mismatch(tmp_path: Path) -> None:
    manifest = tmp_path / "container-runtime.txt"
    manifest.write_bytes(_hashed_manifest())
    provenance = {
        "schema_version": 1,
        "status": "pass",
        "source_commit": "1" * 40,
        "base_image_digest": "sha256:" + "2" * 64,
        "dependency_manifest": {"sha256": hashlib.sha256(_hashed_manifest()).hexdigest()},
        "wheel": {"sha256": "3" * 64},
        "toolchain": {},
    }
    provenance["evidence_digest"] = policy._evidence_digest(provenance)
    provenance_path = tmp_path / "provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

    report = policy.build_image_report(
        provenance_path=provenance_path,
        manifest=manifest,
        expected_source_commit="9" * 40,
        expected_base_digest="sha256:" + "2" * 64,
        image_digest="sha256:" + "5" * 64,
    )

    assert report["status"] == "fail"
    assert report["checks"]["source_commit_matches"] is False


def test_image_report_fails_on_alpine_manifest_mismatch(tmp_path: Path) -> None:
    manifest, apk_manifest, provenance_path = _bound_provenance(tmp_path)
    apk_manifest.write_text("ngspice=47-r0\n", encoding="utf-8")

    report = policy.build_image_report(
        provenance_path=provenance_path,
        manifest=manifest,
        expected_source_commit="1" * 40,
        expected_base_digest="sha256:" + "2" * 64,
        image_digest="sha256:" + "4" * 64,
        apk_manifest=apk_manifest,
    )

    assert report["status"] == "fail"
    assert report["checks"]["apk_manifest_digest_matches"] is False
