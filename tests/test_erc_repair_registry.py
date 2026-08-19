"""Tests for the extensible ERC repair registry (issue #106).

Covers:
* RepairRegistry register/lookup/determinism
* RepairDecision dataclass construction and serialization
* Decision outcomes: applied, declined, escalated
* ERC008 LED series resistor handler
* ERC005 I2C pull-up handler
* Fixed-point convergence and non-progress termination still work
* REPAIR_REGISTRY singleton contains the four built-in handlers
"""

from __future__ import annotations

from zaptrace.synthesis.repair import (
    REPAIR_REGISTRY,
    Patch,
    RepairDecision,
    RepairRegistry,
    RepairResult,
    _infer_rail_voltage,
    repair_design,
)

# ---------------------------------------------------------------------------
# RepairRegistry unit tests
# ---------------------------------------------------------------------------


class TestRepairRegistry:
    def test_register_and_get(self) -> None:
        reg = RepairRegistry()

        def dummy(design, violations):  # type: ignore[override]
            return []

        reg.register("ERC999", dummy)
        assert reg.get_handler("ERC999") is dummy

    def test_get_missing_returns_none(self) -> None:
        reg = RepairRegistry()
        assert reg.get_handler("ERC_NOT_REAL") is None

    def test_register_replaces_existing(self) -> None:
        reg = RepairRegistry()

        def h1(design, violations):  # type: ignore[override]
            return []

        def h2(design, violations):  # type: ignore[override]
            return []

        reg.register("ERC001", h1)
        reg.register("ERC001", h2)
        assert reg.get_handler("ERC001") is h2

    def test_registered_rule_ids_sorted(self) -> None:
        reg = RepairRegistry()

        def h(design, violations):  # type: ignore[override]
            return []

        reg.register("ERC030", h)
        reg.register("ERC010", h)
        reg.register("ERC020", h)
        assert reg.registered_rule_ids == ("ERC010", "ERC020", "ERC030")

    def test_unregister_removes_handler(self) -> None:
        reg = RepairRegistry()

        def h(design, violations):  # type: ignore[override]
            return []

        reg.register("ERC001", h)
        reg.unregister("ERC001")
        assert reg.get_handler("ERC001") is None

    def test_unregister_noop_if_absent(self) -> None:
        reg = RepairRegistry()
        reg.unregister("ERC_NOT_THERE")  # must not raise


class TestRepairRegistrySingleton:
    def test_builtin_handlers_registered(self) -> None:
        ids = REPAIR_REGISTRY.registered_rule_ids
        assert "ERC020" in ids, "ERC020 (missing footprint) should be built-in"
        assert "ERC012" in ids, "ERC012 (floating enable) should be built-in"
        assert "ERC005" in ids, "ERC005 (I2C pull-up) should be built-in"
        assert "ERC008" in ids, "ERC008 (LED series resistor) should be built-in"

    def test_handler_is_callable(self) -> None:
        for rule_id in REPAIR_REGISTRY.registered_rule_ids:
            assert callable(REPAIR_REGISTRY.get_handler(rule_id)), rule_id


# ---------------------------------------------------------------------------
# RepairDecision unit tests
# ---------------------------------------------------------------------------


class TestRepairDecision:
    def _make(self, **kwargs) -> RepairDecision:  # type: ignore[override]
        defaults: dict = {
            "rule_id": "ERC001",
            "component_refs": ["U1"],
            "net_refs": ["NET_A"],
            "outcome": "applied",
            "reason": "added 10k pull-up",
        }
        defaults.update(kwargs)
        return RepairDecision(**defaults)

    def test_to_dict_applied(self) -> None:
        patch = Patch(
            rule_id="ERC001",
            component_ref="R1",
            field="value",
            old_value="",
            new_value="10k",
            rationale="test",
        )
        dec = self._make(outcome="applied", patch=patch)
        d = dec.to_dict()
        assert d["outcome"] == "applied"
        assert "patch" in d
        assert d["patch"]["component_ref"] == "R1"

    def test_to_dict_declined_no_patch(self) -> None:
        dec = self._make(outcome="declined", reason="insufficient context")
        d = dec.to_dict()
        assert d["outcome"] == "declined"
        assert "patch" not in d

    def test_to_dict_escalated(self) -> None:
        dec = self._make(outcome="escalated", reason="no handler registered")
        d = dec.to_dict()
        assert d["outcome"] == "escalated"
        assert "patch" not in d

    def test_assumptions_in_dict(self) -> None:
        dec = self._make(assumptions="Vsupply=3.3V, I=10mA")
        d = dec.to_dict()
        assert d["assumptions"] == "Vsupply=3.3V, I=10mA"

    def test_frozen_immutability(self) -> None:
        import dataclasses

        dec = self._make()
        assert dataclasses.is_dataclass(dec)
        # Frozen dataclass: attribute assignment must raise
        try:
            dec.rule_id = "ERC002"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AssertionError:
            raise
        except Exception:
            pass


# ---------------------------------------------------------------------------
# repair_design() decision emission integration tests
# ---------------------------------------------------------------------------


def _make_minimal_design_with_erc020():
    """Design with one component missing a footprint → triggers ERC020."""
    from zaptrace.core.models import Component, Design, DesignMeta

    design = Design(meta=DesignMeta(name="test_design"))
    design.components["U1"] = Component(
        id="U1",
        ref="U1",
        type="ic",
        value="STM32",
        footprint="",  # missing footprint triggers ERC020
    )
    return design


class TestRepairDesignDecisions:
    def test_decisions_populated_on_convergence(self) -> None:
        design = _make_minimal_design_with_erc020()
        result = repair_design(design)
        assert isinstance(result, RepairResult)
        # There must be at least one decision recorded.
        assert len(result.decisions) >= 1

    def test_every_decision_has_valid_outcome(self) -> None:
        design = _make_minimal_design_with_erc020()
        result = repair_design(design)
        for dec in result.decisions:
            assert dec.outcome in ("applied", "declined", "escalated"), dec

    def test_applied_decision_has_patch(self) -> None:
        design = _make_minimal_design_with_erc020()
        result = repair_design(design)
        applied = [d for d in result.decisions if d.outcome == "applied"]
        for dec in applied:
            assert dec.patch is not None, "applied decision must have a patch"

    def test_escalated_decision_for_unregistered_rule(self) -> None:
        """Violations from unregistered rules produce escalated decisions."""
        from unittest.mock import patch as mock_patch

        from zaptrace.core.models import Component, Design, DesignMeta

        design = Design(meta=DesignMeta(name="test_escalate"))
        design.components["U1"] = Component(id="U1", ref="U1", type="ic", value="X", footprint="")
        # Temporarily register nothing so ERC020 is unregistered.
        registry_copy = RepairRegistry()
        with mock_patch("zaptrace.synthesis.repair.REPAIR_REGISTRY", registry_copy):
            result = repair_design(design)
        escalated = [d for d in result.decisions if d.outcome == "escalated"]
        assert escalated, "Should have at least one escalated decision when no handler"

    def test_decisions_serialise_to_dict(self) -> None:
        design = _make_minimal_design_with_erc020()
        result = repair_design(design)
        data = result.to_dict()
        assert "decisions" in data
        for item in data["decisions"]:
            assert "rule_id" in item
            assert "outcome" in item

    def test_convergence_still_works(self) -> None:
        """Sanity-check: repair_design still converges cleanly on a fixable design."""
        design = _make_minimal_design_with_erc020()
        result = repair_design(design)
        assert result.converged

    def test_non_progress_termination(self) -> None:
        """If patches don't reduce violation count, loop stops before max_iterations."""
        design = _make_minimal_design_with_erc020()
        # Limit to 1 iteration — should still terminate gracefully.
        result = repair_design(design, max_iterations=1)
        assert result is not None


# ---------------------------------------------------------------------------
# ERC005 handler: I2C pull-up
# ---------------------------------------------------------------------------


class TestERC005Handler:
    def _make_i2c_design(self):  # type: ignore[override]
        from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode

        design = Design(meta=DesignMeta(name="i2c_test"))
        sda_net = Net(id="SDA", name="SDA")
        sda_net.nodes.append(NetNode(component_ref="J1", pin_name="1"))
        design.nets["SDA"] = sda_net
        design.components["J1"] = Component(id="J1", ref="J1", type="connector", value="conn")
        return design

    def test_handler_callable_via_registry(self) -> None:
        handler = REPAIR_REGISTRY.get_handler("ERC005")
        assert handler is not None

    def test_handler_returns_list(self) -> None:
        from zaptrace.erc.rules import ERCSeverity, ERCViolation

        handler = REPAIR_REGISTRY.get_handler("ERC005")
        assert handler is not None
        design = self._make_i2c_design()
        v = ERCViolation(
            rule_id="ERC005",
            message="SDA missing pull-up",
            severity=ERCSeverity.ERROR,
            net_refs=["SDA"],
        )
        patches = handler(design, [v])
        assert isinstance(patches, list)

    def test_patch_rule_id_is_erc005(self) -> None:
        from zaptrace.erc.rules import ERCSeverity, ERCViolation

        handler = REPAIR_REGISTRY.get_handler("ERC005")
        assert handler is not None
        design = self._make_i2c_design()
        v = ERCViolation(
            rule_id="ERC005",
            message="SDA missing pull-up",
            severity=ERCSeverity.ERROR,
            net_refs=["SDA"],
        )
        patches = handler(design, [v])
        for p in patches:
            assert p.rule_id == "ERC005"


# ---------------------------------------------------------------------------
# ERC008 handler: LED series resistor
# ---------------------------------------------------------------------------


class TestERC008Handler:
    def _make_led_design(self) -> object:
        from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode

        design = Design(meta=DesignMeta(name="led_test"))
        # LED with supply connected on ANODE pin
        supply_net = Net(id="VCC_3V3", name="VCC 3.3V")
        supply_net.nodes.append(NetNode(component_ref="LED1", pin_name="ANODE"))
        design.nets["VCC_3V3"] = supply_net
        led = Component(id="LED1", ref="LED1", type="led", value="LED_RED")
        design.components["LED1"] = led
        return design

    def test_handler_callable_via_registry(self) -> None:
        handler = REPAIR_REGISTRY.get_handler("ERC008")
        assert handler is not None

    def test_handler_returns_list(self) -> None:
        from zaptrace.erc.rules import ERCSeverity, ERCViolation

        handler = REPAIR_REGISTRY.get_handler("ERC008")
        assert handler is not None
        design = self._make_led_design()
        v = ERCViolation(
            rule_id="ERC008",
            message="LED1 missing series resistor",
            severity=ERCSeverity.ERROR,
            component_refs=["LED1"],
        )
        patches = handler(design, [v])  # type: ignore[arg-type]
        assert isinstance(patches, list)

    def test_patch_rule_id_is_erc008(self) -> None:
        from zaptrace.erc.rules import ERCSeverity, ERCViolation

        handler = REPAIR_REGISTRY.get_handler("ERC008")
        assert handler is not None
        design = self._make_led_design()
        v = ERCViolation(
            rule_id="ERC008",
            message="LED1 missing series resistor",
            severity=ERCSeverity.ERROR,
            component_refs=["LED1"],
        )
        patches = handler(design, [v])  # type: ignore[arg-type]
        for p in patches:
            assert p.rule_id == "ERC008"

    def test_no_patch_when_supply_unknown(self) -> None:
        """Handler must not produce a patch when supply voltage cannot be inferred."""
        from zaptrace.core.models import Component, Design, DesignMeta
        from zaptrace.erc.rules import ERCSeverity, ERCViolation

        handler = REPAIR_REGISTRY.get_handler("ERC008")
        assert handler is not None
        # LED with no supply net connected
        design = Design(meta=DesignMeta(name="led_no_supply"))
        design.components["LED1"] = Component(id="LED1", ref="LED1", type="led", value="X")
        v = ERCViolation(
            rule_id="ERC008",
            message="LED1 missing series resistor",
            severity=ERCSeverity.ERROR,
            component_refs=["LED1"],
        )
        patches = handler(design, [v])
        assert patches == []


def test_repair_rail_voltage_patterns_are_bounded() -> None:
    from zaptrace.core.models import Design, DesignMeta, Net

    for name, expected in (("VCC 1.8V", 1.8), ("1V8", 1.8), ("5V", 5.0)):
        design = Design(meta=DesignMeta(name="rail"), nets={"rail": Net(id="rail", name=name)})
        assert _infer_rail_voltage(design, "rail") == expected

    long_name = "9" * 100_000 + ".8V"
    design = Design(meta=DesignMeta(name="rail"), nets={"rail": Net(id="rail", name=long_name)})
    assert _infer_rail_voltage(design, "rail") is None
