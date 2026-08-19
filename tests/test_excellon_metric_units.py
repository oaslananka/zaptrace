"""Regression coverage for the shared Excellon metric-units header."""

from zaptrace.core.models import Design, DesignMeta
from zaptrace.export.excellon import _ToolManager, generate_composite_drill


def test_excellon_outputs_share_the_metric_trailing_zero_header() -> None:
    design = Design(meta=DesignMeta(name="MetricHeader"))

    content = generate_composite_drill(design)

    assert _ToolManager().format_string() == "METRIC,TZ\n"
    assert isinstance(content, str)
    assert content.count("METRIC,TZ\n") == 1
