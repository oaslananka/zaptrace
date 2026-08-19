"""Tests for attaching real footprint geometry to synthesized components."""

from __future__ import annotations

from zaptrace.core.models import Component, Design, DesignMeta
from zaptrace.synthesis.footprint_resolver import (
    FootprintResolution,
    _generated_footprint,
    _resolve_component,
    _unresolved_component,
    resolve_footprints,
)
from zaptrace.synthesis.repair import synthesize_and_repair


def _design_with(*components: Component) -> Design:
    design = Design(meta=DesignMeta(name="fp_test"))
    for comp in components:
        design.components[comp.ref] = comp
    return design


class TestResolution:
    def test_known_package_gets_real_pads(self) -> None:
        design = _design_with(Component(id="R1", ref="R1", type="resistor", value="10k", footprint="0402"))
        result = resolve_footprints(design)
        comp = design.components["R1"]
        assert comp.footprint_def is not None
        assert len(comp.footprint_def.pads) == 2
        assert "R1" in result.resolved

    def test_sot23_3_resolves(self) -> None:
        # Regression: SOT-23-3 (the synthesized LDO package) must generate pads.
        design = _design_with(Component(id="U1", ref="U1", type="ldo", value="LDO_3.3V", footprint="SOT-23-3"))
        resolve_footprints(design)
        assert design.components["U1"].footprint_def is not None
        assert len(design.components["U1"].footprint_def.pads) == 3

    def test_lqfp_resolves_via_package_fallback(self) -> None:
        # STM32F103 has a custom footprint name but a standard LQFP-48 package.
        design = _design_with(
            Component(
                id="U1", ref="U1", type="mcu", value="STM32", footprint="STM32F103C8T6-LQFP48", mpn="STM32F103C8T6"
            )
        )
        resolve_footprints(design)
        assert design.components["U1"].footprint_def is not None
        assert len(design.components["U1"].footprint_def.pads) == 48

    def test_bare_mcu_board_is_fully_manufacturable(self) -> None:
        out = synthesize_and_repair("STM32 3.3V board, RS485 modbus node")
        assert out["footprints"].fully_resolved

    def test_unknown_module_package_is_unresolved_not_faked(self) -> None:
        # A package with neither a parametric generator nor a vendored land
        # pattern stays an honest gap — pads are never invented.
        design = _design_with(
            Component(id="U1", ref="U1", type="mcu", value="MysteryMCU", footprint="NO-SUCH-MODULE-QFNX")
        )
        result = resolve_footprints(design)
        assert design.components["U1"].footprint_def is None  # no invented pads
        assert any(u["ref"] == "U1" for u in result.unresolved)
        assert not result.fully_resolved

    def test_known_module_resolves_via_vendored_geometry(self) -> None:
        # A module with a verified vendored land pattern resolves with real pads.
        design = _design_with(Component(id="U1", ref="U1", type="mcu", value="ESP32", footprint="ESP32-C3-MINI-1"))
        result = resolve_footprints(design)
        fp = design.components["U1"].footprint_def
        assert fp is not None
        assert fp.pads  # verified geometry, not invented
        assert result.fully_resolved

    def test_missing_name_is_reported(self) -> None:
        design = _design_with(Component(id="R1", ref="R1", type="resistor", value="10k"))  # no footprint
        result = resolve_footprints(design)
        assert any(u["ref"] == "R1" and u["footprint"] == "" for u in result.unresolved)

    def test_already_resolved_is_left_alone(self) -> None:
        design = _design_with(Component(id="R1", ref="R1", type="resistor", value="10k", footprint="0402"))
        resolve_footprints(design)
        pads_first = design.components["R1"].footprint_def
        resolve_footprints(design)  # second pass
        assert design.components["R1"].footprint_def is pads_first  # unchanged object


class TestEndToEnd:
    def test_synthesized_board_gets_full_geometry(self) -> None:
        # The MCU module now resolves from a vendored verified land pattern, so
        # every part — passives, the RS485 IC, and the ESP32 module — has pads.
        out = synthesize_and_repair("ESP32-C3 USB-C 3.3V board, RS485 modbus")
        design, footprints = out["design"], out["footprints"]
        with_geometry = [c for c in design.components.values() if c.footprint_def and c.footprint_def.pads]
        assert len(with_geometry) == len(design.components)
        assert footprints.fully_resolved

    def test_resolution_to_dict_shape(self) -> None:
        out = synthesize_and_repair("USB-C powered board, 3.3V rail, I2C sensor")
        data = out["footprints"].to_dict()
        assert set(data) == {"fully_resolved", "resolved_count", "unresolved_count", "resolved", "unresolved"}
        assert data["resolved_count"] == len(data["resolved"])


def test_resolution_helpers_preserve_component_outcomes() -> None:
    missing = Component(id="R1", ref="R1", type="resistor")
    assert _unresolved_component(missing, "missing")["footprint"] == ""
    assert _generated_footprint(missing, {}) is None

    known = Component(id="R2", ref="R2", type="resistor", footprint="0402")
    generated = _generated_footprint(known, {})
    assert generated is not None
    assert len(generated.pads) == 2

    result = FootprintResolution()
    _resolve_component(known, {}, result)
    assert result.resolved == ["R2"]
    assert known.footprint_def is not None

    unresolved = Component(id="U1", ref="U1", type="mcu", footprint="UNKNOWN-PACKAGE")
    _resolve_component(unresolved, {}, result)
    assert result.unresolved[-1]["ref"] == "U1"
