from __future__ import annotations

from scripts.ci_change_policy import classify_paths


def test_agent_instruction_markdown_is_docs_only_even_below_high_risk_prefixes() -> None:
    policy = classify_paths(
        [
            "AGENTS.md",
            ".github/AGENTS.md",
            "data/AGENTS.md",
            "zaptrace_core/AGENTS.md",
        ],
        event_name="pull_request",
    )

    assert policy.test_mode == "docs"
    assert policy.docs_only is True
    assert policy.full_ci is False
    assert policy.full_matrix is False
    assert policy.heavy_ci is False


def test_explicit_high_risk_markdown_policy_remains_high_risk() -> None:
    policy = classify_paths(["docs/development/version-policy.md"], event_name="pull_request")

    assert policy.test_mode == "full-matrix"
    assert policy.full_ci is True
    assert policy.full_matrix is True
    assert policy.heavy_ci is True


def test_native_source_change_still_selects_full_matrix() -> None:
    policy = classify_paths(["zaptrace_core/src/lib.rs"], event_name="pull_request")

    assert policy.test_mode == "full-matrix"
    assert policy.full_ci is True
    assert policy.full_matrix is True
    assert policy.heavy_ci is True
