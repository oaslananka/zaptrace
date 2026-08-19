#!/usr/bin/env python3
"""Verify synchronized package/runtime versions and exact release-tag identity."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.evidence.identity import EvidenceMode, capture_evidence_identity  # noqa: E402
from zaptrace.versioning import (  # noqa: E402
    VersionStage,
    parse_python_version,
    python_to_cargo_version,
    read_project_version,
)

_VERSION_POLICY_PATH = "config/version-policy.json"
POLICY_PATH = ROOT / _VERSION_POLICY_PATH
_PYPROJECT_PATH = "pyproject.toml"
_UV_LOCK_PATH = "uv.lock"
_CARGO_MANIFEST_PATH = "zaptrace_core/Cargo.toml"
_CARGO_LOCK_PATH = "zaptrace_core/Cargo.lock"
_RELEASE_TAG_SURFACE = "release-tag"
_TAG_REF_PREFIX = "refs/tags/"
_VERSION_SOURCE_INPUTS = (
    _PYPROJECT_PATH,
    _UV_LOCK_PATH,
    _CARGO_MANIFEST_PATH,
    _CARGO_LOCK_PATH,
    _VERSION_POLICY_PATH,
    "scripts/ci_version_consistency.py",
)


class VersionContext(StrEnum):
    """Lifecycle context for version-consistency evidence."""

    DEVELOPMENT = "development"
    RELEASE_PREPARATION = "release-preparation"
    RELEASE = "release"


class VersionPolicy(BaseModel):
    """Committed release-version and tag policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    development_branch: str = Field(min_length=1)
    tag_prefix: str = Field(min_length=1)
    require_annotated_release_tags: bool = True
    require_cryptographic_tag_verification: bool = False
    post_release_bump: Literal["next-patch-dev0"] = "next-patch-dev0"


class VersionViolation(BaseModel):
    """One deterministic synchronization or tag-policy violation."""

    model_config = ConfigDict(frozen=True)

    code: str
    surface: str
    message: str


class VersionAudit(BaseModel):
    """Complete version consistency result."""

    model_config = ConfigDict(frozen=True)

    passed: bool
    context: VersionContext
    distribution_state: str
    published: bool
    python_version: str
    rust_version: str
    uv_lock_version: str
    cargo_lock_version: str
    runtime_version: str
    api_version: str
    mcp_version: str
    version_stage: VersionStage
    source_ref: str
    source_commit: str
    release_tag: str | None = None
    tag_object_type: str | None = None
    tag_target_commit: str | None = None
    tag_signature_required: bool
    tag_signature_verified: bool | None = None
    violations: list[VersionViolation]


def _violation(code: str, surface: str, message: str) -> VersionViolation:
    return VersionViolation(code=code, surface=surface, message=message)


def load_policy(path: str | Path = POLICY_PATH) -> VersionPolicy:
    """Load and validate the committed version policy."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return VersionPolicy.model_validate(payload)


def _python_distribution_name(root: Path) -> str:
    data = tomllib.loads((root / _PYPROJECT_PATH).read_text(encoding="utf-8"))
    value = str(data.get("project", {}).get("name", "")).strip()
    if not value:
        raise ValueError("pyproject.toml does not define project.name")
    return value


def _package_version_from_lock(path: Path, package_name: str) -> str:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for package in data.get("package", []):
        if package.get("name") == package_name:
            value = str(package.get("version", "")).strip()
            if value:
                return value
    raise ValueError(f"package {package_name!r} is missing from {path.name}")


def _cargo_manifest_version(root: Path) -> str:
    data = tomllib.loads((root / _CARGO_MANIFEST_PATH).read_text(encoding="utf-8"))
    value = str(data.get("package", {}).get("version", "")).strip()
    if not value:
        raise ValueError("zaptrace_core/Cargo.toml does not define package.version")
    return value


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail or result.returncode}")
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_ref_exists(root: Path, ref: str) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref],
        cwd=root,
        capture_output=True,
        timeout=15,
        check=False,
    )
    return result.returncode == 0


def _runtime_surfaces() -> tuple[str, str, str]:
    from zaptrace import __version__
    from zaptrace.api.server import API_VERSION
    from zaptrace.mcp.server import SERVER_VERSION

    return __version__, API_VERSION, SERVER_VERSION


def _default_source_ref(root: Path) -> str:
    return os.environ.get("GITHUB_REF", "").strip() or _git(root, "symbolic-ref", "--quiet", "HEAD") or "detached"


def _default_source_commit(root: Path) -> str:
    return (os.environ.get("GITHUB_SHA", "").strip() or _git(root, "rev-parse", "HEAD")).lower()


def _distribution_state(context: VersionContext, stage: VersionStage) -> tuple[str, bool]:
    if context == VersionContext.DEVELOPMENT:
        return "unreleased-development", False
    if context == VersionContext.RELEASE_PREPARATION:
        return "release-preparation", False
    if stage == VersionStage.RELEASE_CANDIDATE:
        return "tagged-release-candidate", True
    return "tagged-final-release", True


def _surface_violations(expected: str, values: dict[str, str]) -> list[VersionViolation]:
    code_by_surface = {
        "uv-lock": "uv-lock-version-mismatch",
        "runtime": "runtime-version-mismatch",
        "api": "api-version-mismatch",
        "mcp": "mcp-version-mismatch",
    }
    return [
        _violation(
            code_by_surface[surface],
            surface,
            f"{surface} reports {actual!r}; expected authoritative Python version {expected!r}",
        )
        for surface, actual in values.items()
        if actual != expected
    ]


def _release_tag_audit(
    *,
    root: Path,
    policy: VersionPolicy,
    python_version: str,
    source_ref: str,
    source_commit: str,
) -> tuple[str | None, str | None, str | None, bool | None, list[VersionViolation]]:
    violations: list[VersionViolation] = []
    expected_tag = f"{policy.tag_prefix}{python_version}"
    actual_tag = source_ref.removeprefix(_TAG_REF_PREFIX) if source_ref.startswith(_TAG_REF_PREFIX) else None
    if actual_tag != expected_tag:
        violations.append(
            _violation(
                "tag-package-version-mismatch",
                _RELEASE_TAG_SURFACE,
                f"release ref must be {_TAG_REF_PREFIX}{expected_tag}; got {source_ref!r}",
            )
        )
    tag_ref = f"{_TAG_REF_PREFIX}{actual_tag}" if actual_tag else ""
    if not tag_ref or not _git_ref_exists(root, tag_ref):
        violations.append(
            _violation(
                "release-tag-missing",
                _RELEASE_TAG_SURFACE,
                f"tag object is unavailable: {actual_tag!r}",
            )
        )
        return actual_tag, None, None, None, violations

    object_type = _git(root, "cat-file", "-t", tag_ref)
    if policy.require_annotated_release_tags and object_type != "tag":
        violations.append(
            _violation(
                "release-tag-not-annotated",
                _RELEASE_TAG_SURFACE,
                f"release tag {actual_tag!r} is a {object_type} object; annotated tag required",
            )
        )
    target_commit = _git(root, "rev-parse", f"{tag_ref}^{{}}").lower()
    if target_commit != source_commit.lower():
        violations.append(
            _violation(
                "tag-source-commit-mismatch",
                _RELEASE_TAG_SURFACE,
                f"tag resolves to {target_commit}; workflow source commit is {source_commit.lower()}",
            )
        )
    signature_verified: bool | None = None
    if policy.require_cryptographic_tag_verification:
        verification = subprocess.run(
            ["git", "tag", "-v", actual_tag or ""],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        signature_verified = verification.returncode == 0
        if not signature_verified:
            violations.append(
                _violation(
                    "release-tag-signature-unverified",
                    _RELEASE_TAG_SURFACE,
                    (verification.stderr or verification.stdout).strip() or "cryptographic tag verification failed",
                )
            )
    return actual_tag, object_type, target_commit, signature_verified, violations


def _resolve_runtime_surface_versions(
    runtime_version: str | None,
    api_version: str | None,
    mcp_version: str | None,
) -> tuple[str, str, str]:
    if runtime_version is not None and api_version is not None and mcp_version is not None:
        return runtime_version, api_version, mcp_version
    detected_runtime, detected_api, detected_mcp = _runtime_surfaces()
    return (
        runtime_version or detected_runtime,
        api_version or detected_api,
        mcp_version or detected_mcp,
    )


def _rust_version_violations(
    *,
    python_version: str,
    parsed: Any,
    rust_version: str,
    cargo_lock_version: str,
) -> list[VersionViolation]:
    violations: list[VersionViolation] = []
    expected_rust = python_to_cargo_version(parsed)
    if rust_version != expected_rust:
        violations.append(
            _violation(
                "python-rust-version-mismatch",
                _CARGO_MANIFEST_PATH,
                f"Rust version {rust_version!r}; expected {expected_rust!r} from Python {python_version!r}",
            )
        )
    if cargo_lock_version != rust_version:
        violations.append(
            _violation(
                "cargo-lock-version-mismatch",
                _CARGO_LOCK_PATH,
                f"Cargo.lock reports {cargo_lock_version!r}; Cargo.toml reports {rust_version!r}",
            )
        )
    return violations


def _development_context_violations(
    *,
    root: Path,
    policy: VersionPolicy,
    python_version: str,
    parsed: Any,
) -> list[VersionViolation]:
    violations: list[VersionViolation] = []
    if parsed.stage != VersionStage.DEVELOPMENT:
        violations.append(
            _violation(
                "development-version-not-unreleased",
                _PYPROJECT_PATH,
                f"development context requires a .devN version; got {python_version!r}",
            )
        )
    final_tag = f"{_TAG_REF_PREFIX}{policy.tag_prefix}{parsed.base_version}"
    if _git_ref_exists(root, final_tag):
        violations.append(
            _violation(
                "development-line-already-released",
                "git-tag",
                (
                    f"development version {python_version!r} reuses released line "
                    f"{final_tag.removeprefix(_TAG_REF_PREFIX)!r}"
                ),
            )
        )
    return violations


def _release_preparation_violations(
    *,
    root: Path,
    policy: VersionPolicy,
    python_version: str,
    parsed: Any,
    source_ref: str,
) -> list[VersionViolation]:
    violations: list[VersionViolation] = []
    if parsed.stage == VersionStage.DEVELOPMENT:
        violations.append(
            _violation(
                "release-preparation-version-is-development",
                _PYPROJECT_PATH,
                f"release preparation requires an RC or final version; got {python_version!r}",
            )
        )
    release_ref = f"refs/heads/release/{policy.tag_prefix}{python_version}"
    transition_ref = f"refs/heads/{policy.development_branch}"
    allowed_refs = {release_ref, transition_ref}
    if source_ref not in allowed_refs:
        violations.append(
            _violation(
                "release-preparation-branch-mismatch",
                "git-ref",
                "release preparation ref must be the exact release branch "
                f"{release_ref!r} or its merge transition on {transition_ref!r}; got {source_ref!r}",
            )
        )
    candidate_tags = {
        f"{_TAG_REF_PREFIX}{policy.tag_prefix}{python_version}",
        f"{_TAG_REF_PREFIX}{policy.tag_prefix}{parsed.base_version}",
    }
    existing_tags = sorted(tag for tag in candidate_tags if _git_ref_exists(root, tag))
    if existing_tags:
        violations.append(
            _violation(
                "release-preparation-tag-already-exists",
                _RELEASE_TAG_SURFACE,
                "release preparation cannot reuse existing tag(s): "
                + ", ".join(repr(tag.removeprefix(_TAG_REF_PREFIX)) for tag in existing_tags),
            )
        )
    return violations


def _release_context_result(
    *,
    root: Path,
    policy: VersionPolicy,
    python_version: str,
    parsed: Any,
    source_ref: str,
    source_commit: str,
) -> tuple[str | None, str | None, str | None, bool | None, list[VersionViolation]]:
    violations: list[VersionViolation] = []
    if parsed.stage == VersionStage.DEVELOPMENT:
        violations.append(
            _violation(
                "release-version-is-development",
                _PYPROJECT_PATH,
                f"release context cannot publish development version {python_version!r}",
            )
        )
    release_tag, object_type, target_commit, signature_verified, tag_violations = _release_tag_audit(
        root=root,
        policy=policy,
        python_version=python_version,
        source_ref=source_ref,
        source_commit=source_commit,
    )
    violations.extend(tag_violations)
    return release_tag, object_type, target_commit, signature_verified, violations


def audit_version_consistency(
    *,
    root: str | Path,
    context: VersionContext | str,
    runtime_version: str | None = None,
    api_version: str | None = None,
    mcp_version: str | None = None,
    source_ref: str | None = None,
    source_commit: str | None = None,
    policy_path: str | Path | None = None,
) -> VersionAudit:
    """Audit all package/runtime surfaces and release tag identity."""
    root_path = Path(root).resolve()
    selected_context = VersionContext(context)
    policy = load_policy(policy_path or root_path / _VERSION_POLICY_PATH)
    python_version = read_project_version(root_path)
    parsed = parse_python_version(python_version)
    rust_version = _cargo_manifest_version(root_path)
    uv_lock_version = _package_version_from_lock(root_path / _UV_LOCK_PATH, _python_distribution_name(root_path))
    cargo_lock_version = _package_version_from_lock(root_path / _CARGO_LOCK_PATH, "zaptrace-core")
    runtime_version, api_version, mcp_version = _resolve_runtime_surface_versions(
        runtime_version, api_version, mcp_version
    )
    ref = (source_ref or _default_source_ref(root_path)).strip()
    commit = (source_commit or _default_source_commit(root_path)).strip().lower()
    violations = _surface_violations(
        python_version,
        {
            "uv-lock": uv_lock_version,
            "runtime": runtime_version,
            "api": api_version,
            "mcp": mcp_version,
        },
    )
    violations.extend(
        _rust_version_violations(
            python_version=python_version,
            parsed=parsed,
            rust_version=rust_version,
            cargo_lock_version=cargo_lock_version,
        )
    )

    release_tag: str | None = None
    tag_object_type: str | None = None
    tag_target_commit: str | None = None
    tag_signature_verified: bool | None = None
    if selected_context == VersionContext.DEVELOPMENT:
        violations.extend(
            _development_context_violations(
                root=root_path,
                policy=policy,
                python_version=python_version,
                parsed=parsed,
            )
        )
    elif selected_context == VersionContext.RELEASE_PREPARATION:
        violations.extend(
            _release_preparation_violations(
                root=root_path,
                policy=policy,
                python_version=python_version,
                parsed=parsed,
                source_ref=ref,
            )
        )
    else:
        (
            release_tag,
            tag_object_type,
            tag_target_commit,
            tag_signature_verified,
            release_violations,
        ) = _release_context_result(
            root=root_path,
            policy=policy,
            python_version=python_version,
            parsed=parsed,
            source_ref=ref,
            source_commit=commit,
        )
        violations.extend(release_violations)

    state, published = _distribution_state(selected_context, parsed.stage)
    return VersionAudit(
        passed=not violations,
        context=selected_context,
        distribution_state=state,
        published=published,
        python_version=python_version,
        rust_version=rust_version,
        uv_lock_version=uv_lock_version,
        cargo_lock_version=cargo_lock_version,
        runtime_version=runtime_version,
        api_version=api_version,
        mcp_version=mcp_version,
        version_stage=parsed.stage,
        source_ref=ref,
        source_commit=commit,
        release_tag=release_tag,
        tag_object_type=tag_object_type,
        tag_target_commit=tag_target_commit,
        tag_signature_required=policy.require_cryptographic_tag_verification,
        tag_signature_verified=tag_signature_verified,
        violations=violations,
    )


def build_report(
    *,
    root: str | Path,
    context: VersionContext | str,
    runtime_version: str | None = None,
    api_version: str | None = None,
    mcp_version: str | None = None,
    source_ref: str | None = None,
    source_commit: str | None = None,
) -> dict[str, Any]:
    """Build identity-bound version consistency evidence."""
    root_path = Path(root).resolve()
    selected_context = VersionContext(context)
    audit = audit_version_consistency(
        root=root_path,
        context=selected_context,
        runtime_version=runtime_version,
        api_version=api_version,
        mcp_version=mcp_version,
        source_ref=source_ref,
        source_commit=source_commit,
    )
    identity = capture_evidence_identity(
        root=root_path,
        mode=EvidenceMode.RELEASE if selected_context == VersionContext.RELEASE else EvidenceMode.SNAPSHOT,
        source_inputs=[path for path in _VERSION_SOURCE_INPUTS if (root_path / path).is_file()],
        source_ref=audit.source_ref,
        source_commit=audit.source_commit,
    )
    return {
        "schema_version": "1.0",
        "generated_at": identity.generated_at,
        "evidence_identity": identity.model_dump(mode="json"),
        **audit.model_dump(mode="json"),
        "non_claims": [
            "version consistency does not prove package correctness or release quality",
            "cryptographic tag verification is not claimed unless tag_signature_required is true and verified",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Render a compact human-readable version consistency report."""
    lines = [
        "# Version Consistency",
        "",
        f"- Passed: `{'yes' if report['passed'] else 'no'}`",
        f"- Distribution state: `{report['distribution_state']}`",
        f"- Published: `{str(report['published']).lower()}`",
        f"- Python/runtime version: `{report['python_version']}`",
        f"- Rust crate version: `{report['rust_version']}`",
        f"- Source ref: `{report['source_ref']}`",
        f"- Source commit: `{report['source_commit']}`",
        "",
        "## Violations",
        "",
    ]
    if report["violations"]:
        lines.extend(f"- `{item['code']}` `{item['surface']}` — {item['message']}" for item in report["violations"])
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--context", choices=tuple(VersionContext), default=VersionContext.DEVELOPMENT.value)
    parser.add_argument("--source-ref")
    parser.add_argument("--source-commit")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report(
            root=args.root,
            context=args.context,
            source_ref=args.source_ref,
            source_commit=args.source_commit,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    if report["violations"]:
        for item in report["violations"]:
            print(f"{item['code']}: {item['surface']}: {item['message']}", file=sys.stderr)
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
