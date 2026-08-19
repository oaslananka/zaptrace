from __future__ import annotations

import json
from pathlib import Path

from zaptrace.analysis import (
    build_analysis_proof_artifacts,
    generate_electrical_analysis_report,
    render_analysis_markdown,
    run_analysis,
)
from zaptrace.core.parser import parse_file

FIXTURES = [
    Path("examples/analysis-fixtures/usb_diff_pair.yaml"),
    Path("examples/analysis-fixtures/ble_feed.yaml"),
    Path("examples/analysis-fixtures/switching_regulator.yaml"),
    Path("examples/analysis-fixtures/mcu_power_rail.yaml"),
]


def test_analysis_api_produces_machine_readable_and_markdown_reports() -> None:
    design = parse_file(FIXTURES[0])
    report = generate_electrical_analysis_report(design)
    markdown = render_analysis_markdown(report)
    payload = json.loads(report.model_dump_json())

    assert payload["schema_version"] == "1.0"
    assert payload["findings"]
    assert "# Electrical analysis report" in markdown
    assert "heuristic estimate, not signoff-grade simulation" in markdown


def test_impedance_diff_pair_and_length_reports_consume_net_constraints() -> None:
    report = generate_electrical_analysis_report(parse_file(FIXTURES[0]))
    categories = report.by_category()

    assert "controlled_impedance" in categories
    assert "differential_pair_length_match" in categories
    assert "length_constraints" in categories
    impedance = categories["controlled_impedance"][0]
    assert impedance.metrics["target_ohms"] == 90.0
    length = categories["differential_pair_length_match"][0]
    assert length.metrics["lengths_mm"]["USB_D+"] == 20.0


def test_pdn_and_thermal_reports_state_assumptions_and_limitations() -> None:
    report = generate_electrical_analysis_report(parse_file(FIXTURES[0]))
    categories = report.by_category()

    assert "pdn_ir_drop_current_density" in categories
    assert "thermal_hotspot" in categories
    assert any("PDN estimates" in item for item in report.assumptions)
    assert any("does not replace" in item for item in report.limitations)
    assert categories["pdn_ir_drop_current_density"][0].limitations
    assert categories["thermal_hotspot"][0].assumptions


def test_proof_pack_artifacts_include_json_and_markdown_reports(tmp_path: Path) -> None:
    report = generate_electrical_analysis_report(parse_file(FIXTURES[0]))

    artifacts = build_analysis_proof_artifacts(report, tmp_path)

    assert {artifact["kind"] for artifact in artifacts} == {"analysis-json", "analysis-markdown"}
    assert all(len(artifact["sha256"]) == 64 for artifact in artifacts)
    assert (tmp_path / "electrical-analysis-report.json").exists()
    assert (tmp_path / "electrical-analysis-report.md").exists()


def test_four_high_risk_analysis_fixtures_exist_and_generate_findings() -> None:
    assert len(FIXTURES) == 4
    for fixture in FIXTURES:
        report = generate_electrical_analysis_report(parse_file(fixture))
        assert report.findings, fixture


def test_run_analysis_adapter_matches_proof_checker_shape() -> None:
    legacy = run_analysis(parse_file(FIXTURES[0]))

    assert legacy.impedance
    assert legacy.impedance[0].net_name == "USB_D+"
    assert legacy.impedance[0].tolerance_pct is not None
    assert legacy.length_match
    assert legacy.length_match[0].group_name == "USB"
    assert isinstance(legacy.length_match[0].within_tolerance, bool)
    assert legacy.thermal
    assert legacy.thermal[0].component_ref == "U1"


# ---------------------------------------------------------------------------
# EMC pre-compliance tests
# ---------------------------------------------------------------------------

from zaptrace.analysis.reports import (  # noqa: E402
    _check_external_cable_filtering,
    _detect_fast_edges,
    _emc_loop_area_scores,
    _is_switching_component,
    _loop_area_risk,
)
from zaptrace.core.models import (  # noqa: E402
    Component,
    Design,
    DesignMeta,
    Net,
    NetConstraints,
    NetNode,
    NetType,
)


def _minimal_design() -> Design:
    """Design with no EMC risks (no fast edges, no switchers, no connectors)."""
    return Design(meta=DesignMeta(name="emc_test"))


def test_emc_no_issues_reports_info() -> None:
    report = generate_electrical_analysis_report(_minimal_design())
    emc = [f for f in report.findings if f.category == "emc_pre_compliance"]
    assert len(emc) == 1
    assert "No EMC pre-compliance issues" in emc[0].message


def test_emc_fast_edge_spi_net_detected() -> None:
    """SPI nets are fast (2 ns rise) and should be flagged."""
    d = Design(meta=DesignMeta(name="emc_spi"))
    d.components["u1"] = Component(id="u1", ref="U1", type="mcu", value="STM32")
    d.components["u2"] = Component(id="u2", ref="U2", type="spi_flash", value="W25Q")
    d.nets["sck"] = Net(
        id="sck",
        name="SPI_SCK",
        type=NetType.SIGNAL,
        nodes=[NetNode(component_ref="U1", pin_name="SCK"), NetNode(component_ref="U2", pin_name="SCK")],
    )
    d.nets["mosi"] = Net(
        id="mosi",
        name="SPI_MOSI",
        type=NetType.SIGNAL,
        nodes=[NetNode(component_ref="U1", pin_name="MOSI"), NetNode(component_ref="U2", pin_name="MOSI")],
    )

    report = generate_electrical_analysis_report(d)
    emc = [f for f in report.findings if f.category == "emc_fast_edge_rate"]
    assert len(emc) == 1
    assert "potential emi sources" in emc[0].message.lower()
    assert "SPI_SCK" in str(emc[0].metrics)


def test_emc_fast_edge_controlled_impedance_flagged() -> None:
    """A net with an impedance constraint but no interface match is still flagged."""
    d = Design(meta=DesignMeta(name="emc_ctrl_imp"))
    d.components["u1"] = Component(id="u1", ref="U1", type="ic", value="FPGA")
    d.nets["hs"] = Net(
        id="hs",
        name="HS_DATA",
        type=NetType.SIGNAL,
        constraints=NetConstraints(impedance_target=50.0),
        nodes=[NetNode(component_ref="U1", pin_name="IO")],
    )

    report = generate_electrical_analysis_report(d)
    emc = [f for f in report.findings if f.category == "emc_fast_edge_rate"]
    assert len(emc) == 1
    assert "HS_DATA" in str(emc[0].metrics)


def test_emc_switcher_loop_area_scored() -> None:
    """Switching-regulator components get a loop-area score."""
    d = Design(meta=DesignMeta(name="emc_switcher"))
    d.components["u1"] = Component(
        id="u1",
        ref="U1",
        type="buck",
        value="3.3V",
        footprint="SOT23-6",
        properties={"power_w": 2.0},
    )
    d.components["u2"] = Component(
        id="u2",
        ref="U2",
        type="boost",
        value="5V",
        footprint="QFN-12",
        properties={"power_w": 3.0},
    )
    d.components["u3"] = Component(
        id="u3",
        ref="U3",
        type="resistor",
        value="10k",
    )

    scores = _emc_loop_area_scores(d)
    assert len(scores) == 2
    u1_score = next(s for s in scores if s["ref"] == "U1")
    u2_score = next(s for s in scores if s["ref"] == "U2")
    assert u1_score["score"] == 2  # SOT23 → score 2
    assert u2_score["score"] == 1  # QFN → score 1

    report = generate_electrical_analysis_report(d)
    emc = [f for f in report.findings if f.category == "emc_switcher_loop_area"]
    assert len(emc) == 1
    assert "loop area" in emc[0].message.lower()


def test_emc_switcher_large_package_high_score() -> None:
    """DIP/through-hole packages get score 4."""
    d = Design(meta=DesignMeta(name="emc_sw_dip"))
    d.components["u1"] = Component(
        id="u1",
        ref="U1",
        type="dc-dc",
        value="12V",
        footprint="DIP-8",
    )
    scores = _emc_loop_area_scores(d)
    assert scores[0]["score"] == 4


def test_emc_no_switchers_no_loop_finding() -> None:
    d = Design(meta=DesignMeta(name="no_switchers"))
    d.components["r1"] = Component(id="r1", ref="R1", type="resistor", value="10k")
    scores = _emc_loop_area_scores(d)
    assert scores == []


def test_emc_external_connector_without_ferrite_flagged() -> None:
    """USB connector without a ferrite should be flagged."""
    d = Design(meta=DesignMeta(name="emc_conn"))
    d.components["j1"] = Component(id="j1", ref="J1", type="USB-C", value="connector")
    d.components["r1"] = Component(id="r1", ref="R1", type="resistor", value="10k")

    unfiltered = _check_external_cable_filtering(d)
    assert unfiltered == ["J1"]


def test_emc_connector_with_ferrite_clean() -> None:
    """Connector with a ferrite on the same design is not flagged."""
    d = Design(meta=DesignMeta(name="emc_conn_ok"))
    d.components["j1"] = Component(id="j1", ref="J1", type="USB-C", value="connector")
    d.components["fb1"] = Component(id="fb1", ref="FB1", type="ferrite_bead", value="BLM18")

    unfiltered = _check_external_cable_filtering(d)
    assert unfiltered == []


def test_emc_fast_edge_detection_for_usb() -> None:
    """USB DP/DM nets should be flagged as fast-edge."""
    d = Design(meta=DesignMeta(name="emc_usb"))
    d.components["u1"] = Component(id="u1", ref="U1", type="usb_controller", value="FT232")
    d.components["j1"] = Component(id="j1", ref="J1", type="USB-B", value="connector")
    d.nets["dp"] = Net(
        id="dp",
        name="USB_D+",
        type=NetType.DIFFERENTIAL,
        nodes=[NetNode(component_ref="U1", pin_name="DP"), NetNode(component_ref="J1", pin_name="DP")],
    )

    fast = _detect_fast_edges(d)
    assert "USB_D+" in fast


def test_emc_report_includes_emc_category() -> None:
    """The full analysis report includes the emc_fast_edge_rate category
    when a fast-edge net is present."""
    d = Design(meta=DesignMeta(name="emc_full"))
    d.components["u1"] = Component(id="u1", ref="U1", type="mcu", value="STM32")
    d.components["u2"] = Component(id="u2", ref="U2", type="spi_flash", value="W25Q")
    d.nets["sck"] = Net(
        id="sck",
        name="SPI_SCK",
        type=NetType.SIGNAL,
        nodes=[NetNode(component_ref="U1", pin_name="SCK"), NetNode(component_ref="U2", pin_name="SCK")],
    )

    report = generate_electrical_analysis_report(d)
    cats = report.by_category()
    assert "emc_fast_edge_rate" in cats
    assert "emc_cable_filtering" not in cats  # no connectors


def test_emc_detect_fast_edges_empty_design() -> None:
    """An empty design should produce no fast-edge nets."""
    assert _detect_fast_edges(_minimal_design()) == []


def test_emc_loop_area_helpers_cover_explicit_and_unknown_packages() -> None:
    explicit = Component(
        id="u1",
        ref="U1",
        type="regulator",
        properties={"switching_regulator": True, "power_w": 2.0},
    )
    assert _is_switching_component(explicit) is True
    assert _loop_area_risk(explicit) == (3, "package unknown but > 1 W, treat as moderate risk")

    low_power = Component(id="u2", ref="U2", type="buck", properties={"power_w": 0.5})
    assert _is_switching_component(low_power) is True
    assert _loop_area_risk(low_power) == (2, "package unknown, assume moderate loop area")

    passive = Component(id="r1", ref="R1", type="resistor")
    assert _is_switching_component(passive) is False
