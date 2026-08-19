"""Tests for the fabrication profile system — FabProfile, DFMChecker, and loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from zaptrace.core.models import (
    BoardDefinition,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    Net,
    Pad,
    PadShape,
    RouteResult,
    TraceSegment,
)
from zaptrace.fab.dfm import (
    DFMChecker,
    DFMCheckResult,
    DFMViolation,
    _drill_violations,
    _trace_clearance_violations,
    _trace_width_violation,
)
from zaptrace.fab.profile import (
    FabProfile,
    ProfileRegistry,
    get_builtin_profile_names,
    load_builtin_profile,
    load_profile,
    load_profile_from_yaml,
)

# ======================================================================
# Sample data
# ======================================================================

_SAMPLE_PROFILE_YAML = """\
name: test-profile
manufacturer: TestFab
description: "Test profile for unit tests"
min_board_width_mm: 10.0
min_board_height_mm: 10.0
max_board_width_mm: 200.0
max_board_height_mm: 200.0
min_board_thickness_mm: 0.4
max_board_thickness_mm: 2.0
min_trace_mm: 0.15
min_space_mm: 0.15
min_trace_power_mm: 0.3
min_drill_mm: 0.2
max_drill_mm: 6.5
min_annular_ring_mm: 0.13
min_via_diameter_mm: 0.3
min_via_hole_mm: 0.15
max_via_hole_mm: 0.5
min_solder_mask_sliver_mm: 0.1
min_solder_mask_clearance_mm: 0.05
min_silkscreen_width_mm: 0.15
min_silkscreen_clearance_mm: 0.15
"""

_EMPTY_DESIGN = Design(meta=DesignMeta(name="empty"))


def _make_design(**kw: object) -> Design:
    d = Design(meta=DesignMeta(name="test"))
    d.board_def = BoardDefinition(width=50.0, height=40.0, layers=2)
    for k, v in kw.items():
        setattr(d, k, v)
    return d


# ======================================================================
# FabProfile model tests
# ======================================================================


class TestFabProfile:
    def test_minimal_profile(self) -> None:
        p = FabProfile(name="test", manufacturer="Test")
        assert p.name == "test"
        assert p.min_trace_mm == 0.15
        assert p.min_space_mm == 0.15

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            FabProfile(name="", manufacturer="Test")

    def test_to_simple_dict(self) -> None:
        p = FabProfile(name="test", manufacturer="Test")
        d = p.to_simple_dict()
        assert d["name"] == "test"
        assert d["manufacturer"] == "Test"
        assert "min_trace_mm" in d

    def test_custom_values(self) -> None:
        p = FabProfile(
            name="advanced",
            manufacturer="ProFab",
            min_trace_mm=0.08,
            min_space_mm=0.08,
            min_drill_mm=0.1,
            max_drill_mm=10.0,
        )
        assert p.min_trace_mm == 0.08
        assert p.min_space_mm == 0.08
        assert p.min_drill_mm == 0.1
        assert p.max_drill_mm == 10.0


# ======================================================================
# Profile loading tests
# ======================================================================


class TestProfileLoading:
    def test_load_from_yaml(self, tmp_path: Path) -> None:
        yml = tmp_path / "profile.yaml"
        yml.write_text(_SAMPLE_PROFILE_YAML, encoding="utf-8")
        p = load_profile_from_yaml(yml)
        assert p.name == "test-profile"
        assert p.manufacturer == "TestFab"
        assert p.min_trace_mm == 0.15

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        yml = tmp_path / "bad.yaml"
        yml.write_text("not: a: valid: profile: {{{{", encoding="utf-8")
        with pytest.raises(ValueError):
            load_profile_from_yaml(yml)

    def test_load_nonexistent(self) -> None:
        with pytest.raises(ValueError):
            load_profile("/nonexistent/profile.yaml")

    def test_load_by_name(self) -> None:
        p = load_profile("jlcpcb-2layer")
        assert p.manufacturer == "JLCPCB"
        assert p.min_trace_mm == 0.15

    def test_load_by_name_case_insensitive(self) -> None:
        p = load_profile("JLCPCB-2LAYER")
        assert p.manufacturer == "JLCPCB"

    def test_builtin_loader_rejects_yaml_paths(self, tmp_path: Path) -> None:
        yml = tmp_path / "profile.yaml"
        yml.write_text(_SAMPLE_PROFILE_YAML, encoding="utf-8")
        profile_path = str(yml)

        with pytest.raises(ValueError, match="Built-in profile not found"):
            load_builtin_profile(profile_path)

    def test_builtin_names(self) -> None:
        names = get_builtin_profile_names()
        assert "jlcpcb-2layer" in names
        assert "jlcpcb-4layer" in names
        assert "pcbway-standard" in names
        assert "oshpark" in names

    def test_registry_custom_register(self) -> None:
        registry = ProfileRegistry()
        p = FabProfile(name="custom", manufacturer="Custom")
        registry.register(p)
        assert registry.get("custom") is p
        assert registry.get("CUSTOM") is p

    def test_registry_unknown(self) -> None:
        registry = ProfileRegistry()
        assert registry.get("nonexistent") is None


# ======================================================================
# DFMChecker tests
# ======================================================================


class TestDFMChecker:
    def test_empty_design_passes(self) -> None:
        profile = FabProfile(name="test", manufacturer="Test")
        checker = DFMChecker(profile)
        result = checker.check(_EMPTY_DESIGN)
        assert result.passed
        assert result.total_violations == 0

    def test_board_too_wide(self) -> None:
        profile = FabProfile(name="test", manufacturer="Test", max_board_width_mm=30.0)
        d = _make_design()
        d.board_def = BoardDefinition(width=50.0, height=40.0)  # type: ignore[assignment]
        checker = DFMChecker(profile)
        result = checker.check(d)
        assert not result.passed
        assert any(v.rule_id == "board-width-max" for v in result.violations)

    def test_board_too_tall(self) -> None:
        profile = FabProfile(name="test", manufacturer="Test", max_board_height_mm=20.0)
        d = _make_design()
        d.board_def = BoardDefinition(width=10.0, height=50.0)  # type: ignore[assignment]
        checker = DFMChecker(profile)
        result = checker.check(d)
        assert not result.passed
        assert any(v.rule_id == "board-height-max" for v in result.violations)

    def test_trace_width_below_minimum(self) -> None:
        profile = FabProfile(name="test", manufacturer="Test", min_trace_mm=0.2)
        d = _make_design(
            routing=RouteResult(
                traces=[
                    TraceSegment(
                        layer="F.Cu",
                        start=(0, 0),
                        end=(10, 0),
                        width=0.1,
                        net_id="sig",
                    )
                ]
            )
        )
        d.nets["sig"] = Net(id="sig", name="SIG")
        checker = DFMChecker(profile)
        result = checker.check(d)
        # Signal trace below minimum → warning, not error → still passes
        assert result.passed
        assert any(v.rule_id == "trace-width" for v in result.violations)

    def test_power_trace_below_minimum(self) -> None:
        profile = FabProfile(name="test", manufacturer="Test", min_trace_power_mm=0.5)
        d = _make_design(
            routing=RouteResult(
                traces=[
                    TraceSegment(
                        layer="F.Cu",
                        start=(0, 0),
                        end=(10, 0),
                        width=0.3,
                        net_id="vcc",
                    )
                ]
            )
        )
        d.nets["vcc"] = Net(id="vcc", name="VCC", type="power")
        checker = DFMChecker(profile)
        result = checker.check(d)
        assert not result.passed
        assert any(v.rule_id == "trace-width" for v in result.violations)

    def test_clearance_violation(self) -> None:
        profile = FabProfile(name="test", manufacturer="Test", min_space_mm=1.0)
        d = _make_design(
            routing=RouteResult(
                traces=[
                    TraceSegment(layer="F.Cu", start=(0, 0), end=(0, 10), width=0.2, net_id="net1"),
                    TraceSegment(layer="F.Cu", start=(0.5, 0), end=(0.5, 10), width=0.2, net_id="net2"),
                ]
            )
        )
        d.nets["net1"] = Net(id="net1", name="NET1")
        d.nets["net2"] = Net(id="net2", name="NET2")
        checker = DFMChecker(profile)
        result = checker.check(d)
        assert not result.passed
        assert any(v.rule_id == "clearance" for v in result.violations)

    def test_drill_hole_below_minimum(self) -> None:
        profile = FabProfile(name="test", manufacturer="Test", min_drill_mm=0.5)
        fp = FootprintDef(
            name="test",
            pads=[Pad(id="1", shape="circle", position=(0.0, 0.0), size=(1.0, 1.0), drill=0.3)],
        )
        comp = Component(id="u1", ref="U1", type="ic", footprint="test")
        comp.footprint_def = fp
        d = _make_design()
        d.components["u1"] = comp
        checker = DFMChecker(profile)
        result = checker.check(d)
        assert not result.passed
        assert any(v.rule_id == "drill-min" for v in result.violations)

    def test_via_hole_below_minimum(self) -> None:
        profile = FabProfile(name="test", manufacturer="Test", min_via_hole_mm=0.2)
        d = _make_design(
            routing=RouteResult(
                traces=[
                    TraceSegment(
                        layer="F.Cu",
                        start=(0, 0),
                        end=(10, 0),
                        width=0.2,
                        net_id="sig",
                        via=True,
                        via_diameter=0.5,
                        via_hole=0.1,
                    )
                ]
            )
        )
        d.nets["sig"] = Net(id="sig", name="SIG")
        checker = DFMChecker(profile)
        result = checker.check(d)
        assert not result.passed
        assert any(v.rule_id == "via-hole-min" for v in result.violations)

    def test_annular_ring_below_minimum(self) -> None:
        profile = FabProfile(name="test", manufacturer="Test", min_annular_ring_mm=0.2)
        d = _make_design(
            routing=RouteResult(
                traces=[
                    TraceSegment(
                        layer="F.Cu",
                        start=(0, 0),
                        end=(10, 0),
                        width=0.2,
                        net_id="sig",
                        via=True,
                        via_diameter=0.4,
                        via_hole=0.25,
                    )
                ]
            )
        )
        d.nets["sig"] = Net(id="sig", name="SIG")
        checker = DFMChecker(profile)
        result = checker.check(d)
        assert not result.passed
        assert any(v.rule_id == "annular-ring" for v in result.violations)

    def test_layer_count_unsupported(self) -> None:
        profile = FabProfile(
            name="test",
            manufacturer="Test",
            capabilities__layer_counts=[2],  # type: ignore[arg-type]
        )
        profile.capabilities.layer_counts = [2]
        d = _make_design()
        d.board_def = BoardDefinition(width=10, height=10, layers=4)  # type: ignore[assignment]
        checker = DFMChecker(profile)
        result = checker.check(d)
        assert not result.passed
        assert any(v.rule_id == "layer-count" for v in result.violations)

    def test_special_features_detected(self) -> None:
        features = DFMChecker._detect_special_features(_EMPTY_DESIGN)
        assert isinstance(features, dict)

    def test_to_dict(self) -> None:
        profile = FabProfile(name="test", manufacturer="Test", min_trace_mm=10.0)
        d = _make_design(
            routing=RouteResult(traces=[TraceSegment(layer="F.Cu", start=(0, 0), end=(10, 0), width=0.1, net_id="sig")])
        )
        d.nets["sig"] = Net(id="sig", name="SIG")
        checker = DFMChecker(profile)
        result = checker.check(d)
        d = result.to_dict()
        assert "passed" in d
        assert "violations" in d
        assert "profile" in d

    def test_dfm_violation_dataclass(self) -> None:
        v = DFMViolation(
            rule_id="test-rule",
            severity="error",
            message="test",
            location="x",
            actual="y",
            expected="z",
        )
        assert v.rule_id == "test-rule"
        assert v.severity == "error"

    def test_dfm_result_properties(self) -> None:
        r = DFMCheckResult(profile_name="test")
        assert r.passed
        assert r.total_violations == 0
        assert r.errors == 0
        assert r.warnings == 0
        r.violations.append(DFMViolation(rule_id="e1", severity="error", message="err"))
        r.violations.append(DFMViolation(rule_id="w1", severity="warning", message="warn"))
        assert not r.passed
        assert r.total_violations == 2
        assert r.errors == 1
        assert r.warnings == 1

    def test_trace_same_net_skip_clearance(self) -> None:
        profile = FabProfile(name="test", manufacturer="Test", min_space_mm=10.0)
        d = _make_design(
            routing=RouteResult(
                traces=[
                    TraceSegment(layer="F.Cu", start=(0, 0), end=(0, 10), width=0.2, net_id="same"),
                    TraceSegment(layer="F.Cu", start=(0.5, 0), end=(0.5, 10), width=0.2, net_id="same"),
                ]
            )
        )
        d.nets["same"] = Net(id="same", name="SAME")
        checker = DFMChecker(profile)
        result = checker.check(d)
        # Same net traces should skip clearance check
        assert all(v.rule_id != "clearance" or "same" not in v.location for v in result.violations)


def test_clearance_helper_skips_same_net_and_reports_other_net() -> None:
    traces = [
        TraceSegment(layer="F.Cu", start=(0, 0), end=(0, 10), width=0.2, net_id="same"),
        TraceSegment(layer="F.Cu", start=(0.5, 0), end=(0.5, 10), width=0.2, net_id="same"),
        TraceSegment(layer="F.Cu", start=(0.25, 0), end=(0.25, 10), width=0.2, net_id="other"),
    ]
    violations = _trace_clearance_violations(traces, 1.0, DFMChecker._segment_distance)
    assert violations
    assert all(violation.location != "same / same" for violation in violations)
    assert any("other" in violation.location for violation in violations)


def test_drill_helper_reports_bounds_and_skips_smd() -> None:
    below = Pad(id="1", shape=PadShape.CIRCLE, position=(0.0, 0.0), size=(1.0, 1.0), drill=0.2)
    above = Pad(id="2", shape=PadShape.CIRCLE, position=(0.0, 0.0), size=(1.0, 1.0), drill=7.0)
    smd = Pad(id="3", shape=PadShape.RECT, position=(0.0, 0.0), size=(1.0, 1.0), drill=0.0)
    assert [item.rule_id for item in _drill_violations("U1", below, 0.3, 6.5)] == ["drill-min"]
    assert [item.rule_id for item in _drill_violations("U1", above, 0.3, 6.5)] == ["drill-max"]
    assert _drill_violations("U1", smd, 0.3, 6.5) == []


def test_clearance_prefilter_uses_current_pair_bbox() -> None:
    profile = FabProfile(name="test", manufacturer="Test", min_space_mm=1.0)
    d = _make_design(
        routing=RouteResult(
            traces=[
                TraceSegment(layer="F.Cu", start=(0, 0), end=(0, 10), width=0.2, net_id="net1"),
                TraceSegment(layer="F.Cu", start=(20, 0), end=(20, 10), width=0.2, net_id="net_far"),
                TraceSegment(layer="F.Cu", start=(0.5, 0), end=(0.5, 10), width=0.2, net_id="net2"),
            ]
        )
    )
    d.nets["net1"] = Net(id="net1", name="NET1")
    d.nets["net_far"] = Net(id="net_far", name="FAR")
    d.nets["net2"] = Net(id="net2", name="NET2")
    result = DFMChecker(profile).check(d)
    assert any(v.rule_id == "clearance" and "net1 / net2" in v.location for v in result.violations)


def test_route_result_vias_are_checked() -> None:
    profile = FabProfile(name="test", manufacturer="Test", min_via_diameter_mm=0.5, min_via_hole_mm=0.25)
    d = _make_design(routing=RouteResult(vias=[(1.0, 1.0, 0.4, 0.2, "net1")]))
    d.nets["net1"] = Net(id="net1", name="NET1")
    result = DFMChecker(profile).check(d)
    assert any(v.rule_id == "via-diameter-min" for v in result.violations)
    assert any(v.rule_id == "via-hole-min" for v in result.violations)


def test_solder_mask_sliver_between_traces_is_reported() -> None:
    profile = FabProfile(name="test", manufacturer="Test", min_solder_mask_sliver_mm=0.1)
    d = _make_design(
        routing=RouteResult(
            traces=[
                TraceSegment(layer="F.Cu", start=(0, 0), end=(5, 0), width=0.2, net_id="net1"),
                TraceSegment(layer="F.Cu", start=(0, 0.25), end=(5, 0.25), width=0.2, net_id="net2"),
            ]
        )
    )
    d.nets["net1"] = Net(id="net1", name="NET1")
    d.nets["net2"] = Net(id="net2", name="NET2")
    result = DFMChecker(profile).check(d)
    assert any(v.rule_id == "solder-mask-sliver" for v in result.violations)


def test_fab_profile_freshness_metadata_and_warnings() -> None:
    profile = FabProfile(
        name="old-profile",
        manufacturer="OldFab",
        source_urls=["https://example.invalid/capabilities"],
        last_verified="2020-01-01",
        stale_after_days=30,
    )
    assert profile.is_stale()
    assert profile.freshness_warnings()
    result = DFMChecker(profile).check(_EMPTY_DESIGN)
    assert any(v.rule_id == "fab-profile-stale" for v in result.violations)


def test_builtin_profiles_have_source_and_freshness_metadata() -> None:
    for name in get_builtin_profile_names():
        profile = load_profile(name)
        assert profile.source_urls or profile.url
        assert profile.last_verified
        assert profile.stale_after_days > 0


def test_trace_width_helper_distinguishes_signal_and_power() -> None:
    design = _make_design()
    design.nets["sig"] = Net(id="sig", name="SIG")
    design.nets["vcc"] = Net(id="vcc", name="VCC", type="power")

    signal = TraceSegment(layer="F.Cu", start=(0, 0), end=(1, 0), width=0.1, net_id="sig")
    signal_violation = _trace_width_violation(design, signal, 2, 0.15, 0.3)
    assert signal_violation is not None
    assert signal_violation.severity == "warning"
    assert signal_violation.location == "sig seg#2"

    power = TraceSegment(layer="F.Cu", start=(0, 0), end=(1, 0), width=0.2, net_id="vcc")
    power_violation = _trace_width_violation(design, power, 3, 0.15, 0.3)
    assert power_violation is not None
    assert power_violation.severity == "error"
    assert "power minimum" in power_violation.message

    compliant = TraceSegment(layer="F.Cu", start=(0, 0), end=(1, 0), width=0.3, net_id="vcc")
    assert _trace_width_violation(design, compliant, 4, 0.15, 0.3) is None
