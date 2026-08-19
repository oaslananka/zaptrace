"""Regression coverage for stable review-panel titles."""

from zaptrace.core.models import Design, DesignMeta
from zaptrace.review.panels import collect_panels


def test_benchmark_and_semantic_diff_panels_retain_public_titles() -> None:
    design = Design(meta=DesignMeta(name="Candidate"))
    baseline = Design(meta=DesignMeta(name="Baseline"))

    panels = collect_panels(design, baseline=baseline, panel_ids=["benchmark", "semantic_diff"])

    assert panels["benchmark"].title == "Benchmark Readiness"
    assert panels["semantic_diff"].title == "Semantic Diff"


def test_semantic_diff_without_baseline_retains_public_title() -> None:
    design = Design(meta=DesignMeta(name="Candidate"))

    panel = collect_panels(design, panel_ids=["semantic_diff"])["semantic_diff"]

    assert panel.title == "Semantic Diff"
