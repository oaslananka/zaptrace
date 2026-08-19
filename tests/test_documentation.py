"""Tests for product documentation completeness."""

from __future__ import annotations

from pathlib import Path

MANIFESTO = Path("docs/product/manifesto.md")
COMPETITOR_MATRIX = Path("docs/strategy/competitor-matrix.md")
README = Path("README.md")
CONTRIBUTING = Path("CONTRIBUTING.md")
STALE_ISSUE_DOCUMENTS = (
    Path("docs/openssf-gap-analysis.md"),
    Path("docs/repo-maturity-report.md"),
    Path("docs/quality/sonar-historical-debt.md"),
)


class TestPublicRepositoryState:
    def test_readme_uses_enabled_discussions_channel(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert "GitHub Discussions is currently disabled" not in text
        assert "https://github.com/oaslananka/zaptrace/discussions" in text

    def test_readme_describes_bounded_spice_evidence(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert "no analog simulation (yet)" not in text
        assert "bounded ngspice-backed" in text

    def test_review_process_matches_solo_maintainer_governance(self) -> None:
        text = CONTRIBUTING.read_text(encoding="utf-8")
        assert "At least one maintainer review required" not in text
        assert "independent approval is not yet enforced" in text

    def test_public_docs_do_not_reference_deleted_issue(self) -> None:
        for path in STALE_ISSUE_DOCUMENTS:
            text = path.read_text(encoding="utf-8")
            assert "/issues/302" not in text, f"{path} references deleted issue #302"


class TestManifesto:
    def test_manifesto_exists(self) -> None:
        assert MANIFESTO.exists(), "docs/product/manifesto.md must exist"

    def test_manifesto_required_sections(self) -> None:
        text = MANIFESTO.read_text(encoding="utf-8")
        for section in [
            "## The Problem",
            "## The Bet",
            "## What ZapTrace Is",
            "## Design Principles",
            "## What ZapTrace Is Not",
            "## The Vision",
            "## Roadmap Commitments",
        ]:
            assert section in text, f"Missing section: {section}"

    def test_manifesto_mentions_proof_system(self) -> None:
        text = MANIFESTO.read_text(encoding="utf-8")
        assert "proof" in text.lower()
        assert "agent" in text.lower()

    def test_manifesto_non_claims_present(self) -> None:
        text = MANIFESTO.read_text(encoding="utf-8")
        assert "not" in text.lower()  # "What ZapTrace Is Not"

    def test_manifesto_roadmap_table_has_priorities(self) -> None:
        text = MANIFESTO.read_text(encoding="utf-8")
        assert "P0" in text
        assert "P1" in text
        assert "P2" in text


class TestCompetitorMatrix:
    def test_competitor_matrix_exists(self) -> None:
        assert COMPETITOR_MATRIX.exists(), "docs/strategy/competitor-matrix.md must exist"

    def test_matrix_covers_key_competitors(self) -> None:
        text = COMPETITOR_MATRIX.read_text(encoding="utf-8")
        for competitor in ["KiCad", "Altium", "Flux", "Octopart"]:
            assert competitor in text, f"Competitor missing from matrix: {competitor}"

    def test_matrix_differentiators_present(self) -> None:
        text = COMPETITOR_MATRIX.read_text(encoding="utf-8")
        assert "Agent-native" in text or "agent-native" in text
        assert "Proof" in text or "proof" in text
        assert "MCP" in text

    def test_matrix_pricing_tiers(self) -> None:
        text = COMPETITOR_MATRIX.read_text(encoding="utf-8")
        assert "Enterprise" in text
        assert "Open" in text or "open source" in text.lower()

    def test_matrix_strategic_moat_section(self) -> None:
        text = COMPETITOR_MATRIX.read_text(encoding="utf-8")
        assert "Strategic Moat" in text or "moat" in text.lower()
