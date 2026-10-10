from __future__ import annotations

import re
import tomllib
from pathlib import Path

from zaptrace.versioning import python_to_cargo_version


def _pyproject_version() -> str:
    return tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _cargo_manifest_version(path: str) -> str:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return data["package"]["version"]


def _cargo_lock_package_version(package_name: str) -> str:
    data = tomllib.loads(Path("zaptrace_core/Cargo.lock").read_text(encoding="utf-8"))
    for package in data["package"]:
        if package["name"] == package_name:
            return package["version"]
    raise AssertionError(f"package not found in Cargo.lock: {package_name}")


def test_rust_extension_version_matches_python_package() -> None:
    assert _cargo_manifest_version("zaptrace_core/Cargo.toml") == python_to_cargo_version(_pyproject_version())


def test_rust_lock_version_matches_cargo_manifest() -> None:
    assert _cargo_lock_package_version("zaptrace-core") == _cargo_manifest_version("zaptrace_core/Cargo.toml")


def _supported_rust_toolchain(channel: str) -> bool:
    """Only accept stable, exactly pinned Rust versions above the CI minimum."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", channel):
        return False
    return tuple(int(part) for part in channel.split(".")) >= (1, 98, 0)


def test_rust_toolchain_policy_rejects_unpinned_or_too_old_versions() -> None:
    for supported in ("1.98.0", "1.99.0", "1.100.0"):
        assert _supported_rust_toolchain(supported)
    for invalid in ("1.97.9", "stable", "nightly", "1.99", "1.99.0-beta.1"):
        assert not _supported_rust_toolchain(invalid)


def test_rust_toolchain_file_declares_pinned_channel_and_components() -> None:
    toolchain_path = Path("rust-toolchain.toml")
    assert toolchain_path.is_file(), "rust-toolchain.toml must exist at repository root"
    data = tomllib.loads(toolchain_path.read_text(encoding="utf-8"))
    toolchain = data["toolchain"]
    assert _supported_rust_toolchain(toolchain["channel"])
    assert toolchain["components"] == ["rustfmt", "clippy"]
    assert toolchain["profile"] == "minimal"


def test_workflows_do_not_override_repo_rust_toolchain_contract() -> None:
    for workflow_path in (
        Path(".github/workflows/quality.yml"),
        Path(".github/workflows/quality-native.yml"),
        Path(".github/workflows/release.yml"),
        Path(".github/workflows/security-scan.yml"),
    ):
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "dtolnay/rust-toolchain@" not in workflow, (
            f"{workflow_path} must use the repository rust-toolchain.toml contract instead of a second toolchain source"
        )
        assert "RUSTUP_TOOLCHAIN" not in workflow, (
            f"{workflow_path} must not override the repository rust-toolchain.toml contract"
        )


def test_ci_validation_environment_requires_rust_toolchain_parity() -> None:
    from scripts import ci_validation_environment

    assert "rust-toolchain.toml" in ci_validation_environment.EVIDENCE_SOURCE_INPUTS
    reqs = {req.name: req for req in ci_validation_environment.TOOL_REQUIREMENTS}
    assert (reqs["Rust compiler"].min_major, reqs["Rust compiler"].min_minor) == (1, 98)
    assert (reqs["Cargo"].min_major, reqs["Cargo"].min_minor) == (1, 98)


def test_quality_rust_job_native_evidence_upload_only_runs_on_success() -> None:
    workflow = Path(".github/workflows/quality-native.yml").read_text(encoding="utf-8")
    rust_job = workflow[workflow.index("  verify:") :]
    upload_block = rust_job[rust_job.index("- name: Upload native boundary evidence") :]

    assert "if: inputs.heavy_ci == 'true'" in upload_block
    assert "always()" not in upload_block
