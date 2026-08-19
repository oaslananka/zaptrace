from __future__ import annotations

from scripts.ci_dco_check import has_signoff, is_code_sensitive_path


def test_code_sensitive_paths_include_source_and_workflows() -> None:
    assert is_code_sensitive_path("zaptrace/core/model.py")
    assert is_code_sensitive_path("zaptrace_core/src/lib.rs")
    assert is_code_sensitive_path(".github/workflows/quality.yml")
    assert is_code_sensitive_path("pyproject.toml")
    assert is_code_sensitive_path("Dockerfile")


def test_code_sensitive_paths_exclude_plain_docs() -> None:
    assert not is_code_sensitive_path("README.md")
    assert not is_code_sensitive_path("docs/security/release-verification.md")


def test_signed_off_by_detection() -> None:
    assert has_signoff("feat: add check\n\nSigned-off-by: Ada Lovelace <ada@example.com>")
    assert has_signoff("signed-off-by: Grace Hopper <grace@example.org>")
    assert not has_signoff("feat: add check\n\nSigned off by Ada")
    assert not has_signoff("Signed-off-by: <missing-name@example.com>")
    assert not has_signoff("Signed-off-by: Ada Lovelace <missing-domain@>")


def test_signed_off_by_detection_handles_long_invalid_lines() -> None:
    assert not has_signoff("Signed-off-by: " + "A" * 100_000)


def test_revision_validation_accepts_expected_git_refs() -> None:
    from scripts.ci_dco_check import validate_revision

    assert validate_revision("HEAD", label="head") == "HEAD"
    assert validate_revision("origin/main", label="base") == "origin/main"
    assert validate_revision("a" * 40, label="head") == "a" * 40


def test_revision_validation_rejects_git_syntax_and_options() -> None:
    import pytest

    from scripts.ci_dco_check import validate_revision

    for value in ("--help", "HEAD~1", "main..feature", "main@{1}", "bad ref", "refs/heads/main.lock"):
        with pytest.raises(ValueError, match="invalid .* revision"):
            validate_revision(value, label="base")


def test_resolve_commit_uses_end_of_options(monkeypatch) -> None:
    from scripts import ci_dco_check

    calls: list[list[str]] = []

    def fake_run_git(args: list[str]) -> str:
        calls.append(args)
        return "b" * 40 + "\n"

    monkeypatch.setattr(ci_dco_check, "run_git", fake_run_git)

    assert ci_dco_check.resolve_commit("origin/main", label="base") == "b" * 40
    assert calls == [["rev-parse", "--verify", "--end-of-options", "origin/main^{commit}"]]
