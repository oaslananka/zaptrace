from __future__ import annotations

from pathlib import Path

SPEC = Path("docs/product/review-studio.md")


def test_review_studio_spec_contains_required_contract_sections() -> None:
    text = SPEC.read_text(encoding="utf-8")

    required_sections = [
        "## Target Users",
        "## Non-Goals for v0.1/v0.2",
        "## Core Screens",
        "## UI Data Contract",
        "## Static Viewer Mode for CI Artifacts",
        "## Local-First and Hosted Security Requirements",
        "## End-to-End Demo Scenario",
        "## First Implementation Slice",
    ]
    for section in required_sections:
        assert section in text


def test_review_studio_spec_maps_required_artifact_domains() -> None:
    text = SPEC.read_text(encoding="utf-8")

    required_domains = [
        "proof-pack",
        "transaction",
        "Semantic diff",
        "BOM risk",
        "manufacturing evidence",
        "release gate summary",
        "benchmark summary",
        "known-failure",
        "approval id",
    ]
    for domain in required_domains:
        assert domain in text


def test_review_studio_spec_separates_from_full_eda_editor() -> None:
    text = SPEC.read_text(encoding="utf-8")

    assert "full interactive PCB editor" in text
    assert "manual routing environment" in text
    assert "full schematic capture replacement" in text
