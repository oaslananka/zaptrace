from __future__ import annotations

import re
from pathlib import Path


def test_docker_python_version_is_covered_by_ci_matrix() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    image_versions = set(re.findall(r"Base identity: python:(\d+\.\d+)-alpine", dockerfile))
    assert image_versions
    assert len(image_versions) == 1
    matrix_versions = set(re.findall(r'"(3\.\d+)"', workflow))
    assert image_versions <= matrix_versions


def test_docker_runtime_bundles_ngspice_for_simulation_gate() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "ngspice" in dockerfile


def test_docker_uses_pinned_alpine_base_without_apt() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("FROM python@sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a") == 2
    assert "apk add --no-cache" in dockerfile
    assert "apk add --no-cache build-base cargo patchelf rust" in dockerfile
    assert "apt-get" not in dockerfile


def test_docker_installs_committed_runtime_lock_without_resolution() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "COPY requirements/container-runtime.txt" in dockerfile
    assert "pip install --no-cache-dir --require-hashes --only-binary=:all:" in dockerfile
    assert "--find-links=/app/dist -r /app/requirements/zaptrace-wheel.txt" in dockerfile
    assert '"${WHEEL}[mcp,server]"' not in dockerfile
    assert "container-build-provenance.json" in dockerfile
    assert "zaptrace-wheel-requirement.txt" in dockerfile
    assert "--no-index" in dockerfile
    assert "maturin build --release --locked" in dockerfile
    assert "printf 'zaptrace-eda==%s --hash=sha256:%s\\n'" in dockerfile
    assert "printf 'zaptrace==%s" not in dockerfile


def test_container_manifest_is_committed_and_hash_complete() -> None:
    manifest = Path("requirements/container-runtime.txt").read_text(encoding="utf-8")

    assert "click==" in manifest
    assert "fastmcp==" in manifest
    assert "fastapi==" in manifest
    assert "--hash=sha256:" in manifest


def test_docker_manifest_digest_defaults_match_committed_files() -> None:
    import hashlib

    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    python_manifest = Path("requirements/container-runtime.txt").read_bytes()
    apk_manifest = Path("requirements/container-apk.txt").read_bytes()
    python_digest = hashlib.sha256(python_manifest).hexdigest()
    apk_digest = hashlib.sha256(apk_manifest).hexdigest()

    assert dockerfile.count(f"ARG CONTAINER_LOCK_SHA256={python_digest}") == 2
    assert dockerfile.count(f"ARG CONTAINER_APK_LOCK_SHA256={apk_digest}") == 2


def test_docker_builder_tools_use_hash_locked_manifest() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    manifest_path = Path("requirements/container-builder.txt")
    manifest = manifest_path.read_text(encoding="utf-8")

    assert "maturin==1.13.3" in manifest
    assert "uv==0.11.29" in manifest
    assert manifest.count("--hash=sha256:") >= 2
    assert "COPY requirements/container-builder.txt /build/requirements/container-builder.txt" in dockerfile
    assert "pip install --no-cache-dir --require-hashes --only-binary=:all:" in dockerfile
    assert "-r /build/requirements/container-builder.txt" in dockerfile
    assert "pip install --no-cache-dir maturin==1.13.3 uv==0.11.29" not in dockerfile


def test_docker_builder_manifest_digest_defaults_match_committed_file() -> None:
    import hashlib

    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    builder_manifest = Path("requirements/container-builder.txt").read_bytes()
    digest = hashlib.sha256(builder_manifest).hexdigest()

    assert dockerfile.count(f"ARG CONTAINER_BUILDER_LOCK_SHA256={digest}") == 2
    assert 'io.zaptrace.dependencies.builder-python.sha256="$CONTAINER_BUILDER_LOCK_SHA256"' in dockerfile
