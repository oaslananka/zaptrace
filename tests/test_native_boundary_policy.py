"""Repository contracts for mandatory Rust/PyO3 security evidence."""

from __future__ import annotations

from pathlib import Path


def test_quality_rust_job_installs_and_requires_native_wheel() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    rust_job = workflow[workflow.index("  rust:") : workflow.index("\n  benchmark-001:")]

    assert 'ZAPTRACE_REQUIRE_NATIVE: "1"' in rust_job
    assert "Install built Rust wheel" in rust_job
    assert "scripts/ci_native_boundary.py" in rust_job
    assert "native-boundary-evidence.json" in rust_job
    assert "if-no-files-found: error" in rust_job
    assert "UV_PROJECT_ENVIRONMENT=" in rust_job
    assert "uv sync --locked" in rust_job
    assert "--no-install-project" in rust_job
    assert "--no-deps" in rust_job
    assert "--require-hashes" in rust_job
    assert "sha256sum" in rust_job
    assert "native-wheel.requirements.txt" in rust_job
    assert "-i .venv/bin/python" in rust_job


def test_security_workflow_emits_pinned_cargo_audit_evidence() -> None:
    workflow = Path(".github/workflows/security-scan.yml").read_text(encoding="utf-8")

    assert 'CARGO_AUDIT_VERSION: "0.22.2"' in workflow
    assert "cargo audit --file zaptrace_core/Cargo.lock --json" in workflow
    assert "cargo-audit.json" in workflow
    assert "cargo-audit-evidence.json" in workflow
    assert "if: always()" in workflow


def test_quality_native_evidence_records_explicit_target_and_all_target_clippy() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    rust_job = workflow[workflow.index("  rust:") : workflow.index("\n  benchmark-001:")]

    assert "cargo clippy --manifest-path zaptrace_core/Cargo.toml --all-targets -- -D warnings" in rust_job
    assert "--target x86_64-unknown-linux-gnu" in rust_job
