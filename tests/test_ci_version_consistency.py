"""Version policy, synchronization, and release-tag verification tests."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from scripts.ci_version_consistency import (
    VersionContext,
    audit_version_consistency,
    build_report,
    load_policy,
)
from zaptrace.versioning import VersionStage, parse_python_version, python_to_cargo_version, read_project_version

ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _write_repo(
    root: Path,
    *,
    python_version: str = "1.2.4.dev0",
    cargo_version: str = "1.2.4-dev.0",
    runtime_version: str | None = None,
) -> Path:
    (root / "config").mkdir(parents=True)
    (root / "zaptrace_core").mkdir()
    (root / "zaptrace").mkdir()
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "zaptrace"\nversion = "{python_version}"\n', encoding="utf-8"
    )
    (root / "uv.lock").write_text(
        f'version = 1\n\n[[package]]\nname = "zaptrace"\nversion = "{python_version}"\n', encoding="utf-8"
    )
    (root / "zaptrace_core/Cargo.toml").write_text(
        f'[package]\nname = "zaptrace-core"\nversion = "{cargo_version}"\n', encoding="utf-8"
    )
    (root / "zaptrace_core/Cargo.lock").write_text(
        f'version = 4\n\n[[package]]\nname = "zaptrace-core"\nversion = "{cargo_version}"\n', encoding="utf-8"
    )
    (root / "config/version-policy.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "development_branch": "main",
                "tag_prefix": "v",
                "require_annotated_release_tags": True,
                "require_cryptographic_tag_verification": False,
                "post_release_bump": "next-patch-dev0",
            }
        ),
        encoding="utf-8",
    )
    (root / "zaptrace/__init__.py").write_text(
        f'__version__ = "{runtime_version or python_version}"\n', encoding="utf-8"
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.com")
    _git(root, "config", "user.name", "Version Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "initial")
    return root


def _audit(
    root: Path,
    *,
    context: VersionContext = VersionContext.DEVELOPMENT,
    runtime_version: str | None = None,
    api_version: str | None = None,
    mcp_version: str | None = None,
    source_ref: str | None = None,
    source_commit: str | None = None,
):
    python_version = runtime_version or "1.2.4.dev0"
    return audit_version_consistency(
        root=root,
        context=context,
        runtime_version=python_version,
        api_version=api_version or python_version,
        mcp_version=mcp_version or python_version,
        source_ref=source_ref or "refs/heads/main",
        source_commit=source_commit or _git(root, "rev-parse", "HEAD"),
    )


def _committed_repository_context(
    *,
    development_branch: str,
    tag_prefix: str,
    python_version: str,
    stage: VersionStage,
    workflow_ref: str,
) -> tuple[VersionContext, str]:
    development_ref = f"refs/heads/{development_branch}"
    if stage == VersionStage.DEVELOPMENT:
        return VersionContext.DEVELOPMENT, development_ref
    if workflow_ref.startswith("refs/tags/"):
        return VersionContext.RELEASE, workflow_ref
    if workflow_ref == development_ref:
        return VersionContext.RELEASE_PREPARATION, development_ref
    return VersionContext.RELEASE_PREPARATION, f"refs/heads/release/{tag_prefix}{python_version}"


def test_python_version_model_maps_development_rc_and_final() -> None:
    development = parse_python_version("0.3.1.dev0")
    candidate = parse_python_version("0.3.1rc2")
    final = parse_python_version("0.3.1")

    assert development.stage == VersionStage.DEVELOPMENT
    assert candidate.stage == VersionStage.RELEASE_CANDIDATE
    assert final.stage == VersionStage.FINAL
    assert python_to_cargo_version(development) == "0.3.1-dev.0"
    assert python_to_cargo_version(candidate) == "0.3.1-rc.2"
    assert python_to_cargo_version(final) == "0.3.1"


def test_committed_repository_context_uses_release_for_tagged_final() -> None:
    context, source_ref = _committed_repository_context(
        development_branch="main",
        tag_prefix="v",
        python_version="0.3.1",
        stage=VersionStage.FINAL,
        workflow_ref="refs/tags/v0.3.1",
    )

    assert context == VersionContext.RELEASE
    assert source_ref == "refs/tags/v0.3.1"


def test_committed_policy_and_repository_are_consistent() -> None:
    policy = load_policy(ROOT / "config/version-policy.json")
    python_version = read_project_version(ROOT)
    parsed = parse_python_version(python_version)
    context, source_ref = _committed_repository_context(
        development_branch=policy.development_branch,
        tag_prefix=policy.tag_prefix,
        python_version=python_version,
        stage=parsed.stage,
        workflow_ref=os.environ.get("GITHUB_REF", "").strip(),
    )
    report = audit_version_consistency(root=ROOT, context=context, source_ref=source_ref)

    assert policy.require_annotated_release_tags is True
    assert policy.require_cryptographic_tag_verification is False
    assert report.passed is True, [item.model_dump(mode="json") for item in report.violations]
    assert report.python_version == python_version
    assert report.rust_version == python_to_cargo_version(parsed)
    assert report.version_stage == parsed.stage


def test_development_context_rejects_stale_final_version(tmp_path: Path) -> None:
    root = _write_repo(tmp_path, python_version="1.2.3", cargo_version="1.2.3")
    result = _audit(root, runtime_version="1.2.3")

    assert result.passed is False
    assert any(item.code == "development-version-not-unreleased" for item in result.violations)


def test_development_context_rejects_already_released_line(tmp_path: Path) -> None:
    root = _write_repo(tmp_path)
    _git(root, "tag", "-a", "v1.2.4", "-m", "released")
    result = _audit(root)

    assert result.passed is False
    assert any(item.code == "development-line-already-released" for item in result.violations)


def test_release_preparation_accepts_matching_final_release_branch(tmp_path: Path) -> None:
    root = _write_repo(tmp_path, python_version="1.2.4", cargo_version="1.2.4")
    commit = _git(root, "rev-parse", "HEAD")
    report = build_report(
        root=root,
        context=VersionContext.RELEASE_PREPARATION,
        runtime_version="1.2.4",
        api_version="1.2.4",
        mcp_version="1.2.4",
        source_ref="refs/heads/release/v1.2.4",
        source_commit=commit,
    )

    assert report["passed"] is True
    assert report["distribution_state"] == "release-preparation"
    assert report["published"] is False
    assert report["evidence_identity"]["mode"] == "snapshot"


def test_release_preparation_accepts_final_identity_on_development_branch_transition(tmp_path: Path) -> None:
    root = _write_repo(tmp_path, python_version="1.2.4", cargo_version="1.2.4")
    result = _audit(
        root,
        context=VersionContext.RELEASE_PREPARATION,
        runtime_version="1.2.4",
        source_ref="refs/heads/main",
    )

    assert result.passed is True
    assert result.distribution_state == "release-preparation"
    assert result.published is False


def test_release_preparation_rejects_development_version(tmp_path: Path) -> None:
    root = _write_repo(tmp_path)
    result = _audit(
        root,
        context=VersionContext.RELEASE_PREPARATION,
        source_ref="refs/heads/release/v1.2.4.dev0",
    )

    assert result.passed is False
    assert any(item.code == "release-preparation-version-is-development" for item in result.violations)


def test_release_preparation_rejects_mismatched_branch_and_existing_tag(tmp_path: Path) -> None:
    root = _write_repo(tmp_path, python_version="1.2.4", cargo_version="1.2.4")
    commit = _git(root, "rev-parse", "HEAD")
    mismatch = _audit(
        root,
        context=VersionContext.RELEASE_PREPARATION,
        runtime_version="1.2.4",
        source_ref="refs/heads/release/v1.2.5",
        source_commit=commit,
    )
    _git(root, "tag", "-a", "v1.2.4", "-m", "already released")
    tagged = _audit(
        root,
        context=VersionContext.RELEASE_PREPARATION,
        runtime_version="1.2.4",
        source_ref="refs/heads/release/v1.2.4",
        source_commit=commit,
    )

    assert any(item.code == "release-preparation-branch-mismatch" for item in mismatch.violations)
    assert any(item.code == "release-preparation-tag-already-exists" for item in tagged.violations)


def test_release_preparation_rejects_existing_candidate_tag(tmp_path: Path) -> None:
    root = _write_repo(tmp_path, python_version="1.2.4rc1", cargo_version="1.2.4-rc.1")
    commit = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", "-a", "v1.2.4rc1", "-m", "existing candidate")
    result = _audit(
        root,
        context=VersionContext.RELEASE_PREPARATION,
        runtime_version="1.2.4rc1",
        source_ref="refs/heads/release/v1.2.4rc1",
        source_commit=commit,
    )

    assert result.passed is False
    assert any(item.code == "release-preparation-tag-already-exists" for item in result.violations)


def test_audit_rejects_rust_lock_runtime_api_and_mcp_drift(tmp_path: Path) -> None:
    root = _write_repo(tmp_path, cargo_version="1.2.4-dev.9")
    (root / "zaptrace_core/Cargo.lock").write_text(
        'version = 4\n\n[[package]]\nname = "zaptrace-core"\nversion = "1.2.4-dev.8"\n', encoding="utf-8"
    )
    result = audit_version_consistency(
        root=root,
        context=VersionContext.DEVELOPMENT,
        runtime_version="1.2.4.dev7",
        api_version="1.2.4.dev6",
        mcp_version="1.2.4.dev5",
        source_ref="refs/heads/main",
        source_commit=_git(root, "rev-parse", "HEAD"),
    )

    codes = {item.code for item in result.violations}
    assert "python-rust-version-mismatch" in codes
    assert "cargo-lock-version-mismatch" in codes
    assert "runtime-version-mismatch" in codes
    assert "api-version-mismatch" in codes
    assert "mcp-version-mismatch" in codes


def test_release_rejects_tag_package_and_commit_mismatch(tmp_path: Path) -> None:
    root = _write_repo(tmp_path, python_version="1.2.4", cargo_version="1.2.4")
    first_commit = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", "-a", "v1.2.4", "-m", "release")
    (root / "extra.txt").write_text("later\n", encoding="utf-8")
    _git(root, "add", "extra.txt")
    _git(root, "commit", "-qm", "later")
    later_commit = _git(root, "rev-parse", "HEAD")

    mismatch = _audit(
        root,
        context=VersionContext.RELEASE,
        runtime_version="1.2.4",
        source_ref="refs/tags/v1.2.5",
        source_commit=later_commit,
    )
    wrong_commit = _audit(
        root,
        context=VersionContext.RELEASE,
        runtime_version="1.2.4",
        source_ref="refs/tags/v1.2.4",
        source_commit=later_commit,
    )

    assert any(item.code == "tag-package-version-mismatch" for item in mismatch.violations)
    assert any(item.code == "tag-source-commit-mismatch" for item in wrong_commit.violations)
    assert first_commit != later_commit


def test_release_rejects_lightweight_tag_and_accepts_annotated_exact_tag(tmp_path: Path) -> None:
    root = _write_repo(tmp_path, python_version="1.2.4", cargo_version="1.2.4")
    commit = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", "v1.2.4")
    lightweight = _audit(
        root,
        context=VersionContext.RELEASE,
        runtime_version="1.2.4",
        source_ref="refs/tags/v1.2.4",
        source_commit=commit,
    )
    _git(root, "tag", "-d", "v1.2.4")
    _git(root, "tag", "-a", "v1.2.4", "-m", "release")
    annotated = _audit(
        root,
        context=VersionContext.RELEASE,
        runtime_version="1.2.4",
        source_ref="refs/tags/v1.2.4",
        source_commit=commit,
    )

    assert any(item.code == "release-tag-not-annotated" for item in lightweight.violations)
    assert annotated.passed is True, [item.model_dump(mode="json") for item in annotated.violations]


def test_reports_distinguish_unreleased_and_tagged_release_evidence(tmp_path: Path) -> None:
    development_root = _write_repo(tmp_path / "development")
    development = build_report(
        root=development_root,
        context=VersionContext.DEVELOPMENT,
        runtime_version="1.2.4.dev0",
        api_version="1.2.4.dev0",
        mcp_version="1.2.4.dev0",
        source_ref="refs/heads/main",
        source_commit=_git(development_root, "rev-parse", "HEAD"),
    )

    release_root = _write_repo(tmp_path / "release", python_version="1.2.4", cargo_version="1.2.4")
    release_commit = _git(release_root, "rev-parse", "HEAD")
    _git(release_root, "tag", "-a", "v1.2.4", "-m", "release")
    release = build_report(
        root=release_root,
        context=VersionContext.RELEASE,
        runtime_version="1.2.4",
        api_version="1.2.4",
        mcp_version="1.2.4",
        source_ref="refs/tags/v1.2.4",
        source_commit=release_commit,
    )

    assert development["distribution_state"] == "unreleased-development"
    assert development["published"] is False
    assert development["evidence_identity"]["mode"] == "snapshot"
    assert release["distribution_state"] == "tagged-final-release"
    assert release["published"] is True
    assert release["release_tag"] == "v1.2.4"
    assert release["tag_object_type"] == "tag"
    assert release["tag_target_commit"] == release_commit
    assert release["tag_signature_required"] is False
    assert release["tag_signature_verified"] is None
    assert release["evidence_identity"]["mode"] == "release"


def test_public_version_policy_documents_active_line_and_tag_trust() -> None:
    policy = Path("docs/development/version-policy.md").read_text(encoding="utf-8")
    release_process = Path("docs/development/release-process.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    faq = Path("docs/FAQ.md").read_text(encoding="utf-8")

    python_version = read_project_version(ROOT)
    cargo_version = python_to_cargo_version(parse_python_version(python_version))
    assert python_version in policy
    assert cargo_version in policy
    assert "next patch's `.dev0`" in policy
    assert "release-preparation" in policy
    assert "annotated" in policy
    assert "cryptographic tag verification is not currently required" in policy
    assert "historical `v0.3.0` lightweight tag" in policy
    assert "post-release development bump" in release_process
    assert python_version in changelog
    assert python_version in faq


def test_release_candidate_report_uses_tagged_rc_state(tmp_path: Path) -> None:
    root = _write_repo(tmp_path, python_version="1.2.4rc2", cargo_version="1.2.4-rc.2")
    commit = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", "-a", "v1.2.4rc2", "-m", "candidate")

    report = build_report(
        root=root,
        context=VersionContext.RELEASE,
        runtime_version="1.2.4rc2",
        api_version="1.2.4rc2",
        mcp_version="1.2.4rc2",
        source_ref="refs/tags/v1.2.4rc2",
        source_commit=commit,
    )

    assert report["passed"] is True
    assert report["distribution_state"] == "tagged-release-candidate"
    assert report["version_stage"] == "release-candidate"


def test_release_context_rejects_development_version(tmp_path: Path) -> None:
    root = _write_repo(tmp_path)
    result = audit_version_consistency(
        root=root,
        context=VersionContext.RELEASE,
        runtime_version="1.2.4.dev0",
        api_version="1.2.4.dev0",
        mcp_version="1.2.4.dev0",
        source_ref="refs/tags/v1.2.4.dev0",
        source_commit=_git(root, "rev-parse", "HEAD"),
    )

    assert any(item.code == "release-version-is-development" for item in result.violations)


def test_release_signature_policy_reports_unsigned_annotated_tag(tmp_path: Path) -> None:
    root = _write_repo(tmp_path, python_version="1.2.4", cargo_version="1.2.4")
    policy_path = root / "config/version-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["require_cryptographic_tag_verification"] = True
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    _git(root, "add", "config/version-policy.json")
    _git(root, "commit", "-qm", "require signatures")
    commit = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", "-a", "v1.2.4", "-m", "unsigned release")

    result = audit_version_consistency(
        root=root,
        context=VersionContext.RELEASE,
        runtime_version="1.2.4",
        api_version="1.2.4",
        mcp_version="1.2.4",
        source_ref="refs/tags/v1.2.4",
        source_commit=commit,
    )

    assert result.tag_signature_required is True
    assert result.tag_signature_verified is False
    assert any(item.code == "release-tag-signature-unverified" for item in result.violations)


def test_audit_rejects_missing_lock_package_and_manifest_version(tmp_path: Path) -> None:
    import pytest

    missing_lock = _write_repo(tmp_path / "missing-lock")
    (missing_lock / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="package 'zaptrace' is missing"):
        _audit(missing_lock)

    missing_manifest = _write_repo(tmp_path / "missing-manifest")
    (missing_manifest / "zaptrace_core/Cargo.toml").write_text('[package]\nname = "zaptrace-core"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="does not define package.version"):
        _audit(missing_manifest)


def test_git_failure_is_reported_deterministically(tmp_path: Path) -> None:
    import pytest

    from scripts.ci_version_consistency import _git

    with pytest.raises(ValueError, match="git rev-parse HEAD failed"):
        _git(tmp_path, "rev-parse", "HEAD")


def test_cli_writes_reports_and_returns_strict_failure_codes(tmp_path: Path, capsys, monkeypatch) -> None:
    import scripts.ci_version_consistency as version_ci

    monkeypatch.setattr(version_ci, "_runtime_surfaces", lambda: ("1.2.4.dev0",) * 3)
    main = version_ci.main

    root = _write_repo(tmp_path / "passing")
    output = tmp_path / "version.json"
    markdown = tmp_path / "version.md"
    code = main(
        [
            "--root",
            str(root),
            "--context",
            "development",
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--strict",
        ]
    )
    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is True
    assert "Version Consistency" in markdown.read_text(encoding="utf-8")

    failing = _write_repo(tmp_path / "failing", python_version="1.2.3", cargo_version="1.2.3")
    code = main(["--root", str(failing), "--context", "development", "--strict"])
    captured = capsys.readouterr()
    assert code == 1
    assert '"passed": false' in captured.out
    assert "development-version-not-unreleased" in captured.err

    malformed = _write_repo(tmp_path / "malformed")
    (malformed / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    assert main(["--root", str(malformed), "--strict"]) == 2
    assert "ERROR:" in capsys.readouterr().err


def test_runtime_resolver_uses_metadata_or_explicit_unknown_fallback(tmp_path: Path, monkeypatch) -> None:
    from importlib.metadata import PackageNotFoundError

    import zaptrace._version as runtime_version

    requested: list[str] = []

    def installed_version(name: str) -> str:
        requested.append(name)
        return "9.8.7"

    monkeypatch.setattr(runtime_version, "version", installed_version)
    assert runtime_version.resolve_runtime_version(tmp_path) == "9.8.7"
    assert requested == ["zaptrace-eda"]

    def missing(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(runtime_version, "version", missing)
    assert runtime_version.resolve_runtime_version(tmp_path) == "0.0.0.dev0"


def test_version_parser_and_project_reader_fail_closed(tmp_path: Path) -> None:
    import pytest

    from zaptrace.versioning import read_project_version

    with pytest.raises(ValueError, match="must use"):
        parse_python_version("1.2")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "zaptrace"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="does not define project.version"):
        read_project_version(tmp_path)


def test_version_audit_uses_distribution_name_declared_by_pyproject(tmp_path: Path) -> None:
    root = _write_repo(tmp_path)
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('name = "zaptrace"', 'name = "zaptrace-eda"'), encoding="utf-8"
    )
    lock = root / "uv.lock"
    lock.write_text(
        lock.read_text(encoding="utf-8").replace('name = "zaptrace"', 'name = "zaptrace-eda"'), encoding="utf-8"
    )

    audit = _audit(root)

    assert audit.passed is True
    assert audit.uv_lock_version == "1.2.4.dev0"
