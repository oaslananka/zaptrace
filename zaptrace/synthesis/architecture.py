"""Board-level architecture synthesis by block composition.

This is the generalization of :mod:`zaptrace.synthesis.power_tree` from "what
power stages" to "what functional blocks the whole board needs, and how they
connect" — the first step away from template selection toward from-scratch
synthesis (see ``docs/design/autonomous-synthesis.md``).

The model is a typed **block graph**: every planned block declares what it
``provides`` (rails, interface support) and what it ``requires`` (a rail to run
from). The planner composes by satisfying requires-with-provides, so a bare
intent never invents a block it was not asked for, and an unsatisfiable
requirement is reported rather than silently emitted.

Deterministic: the same frozen :class:`~zaptrace.synthesis.requirements.Requirements`
always yields the same plan and the same netlist, so a result is reproducible
and a diff is meaningful. Honest: interfaces with no parametric block yet are
recorded as ``unrealized`` instead of being skipped silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from zaptrace.synthesis.mcu import has_mcu_part
from zaptrace.synthesis.peripherals import plan_sensors, plan_storage
from zaptrace.synthesis.power_tree import _rail_net, plan_power_tree

if TYPE_CHECKING:
    from zaptrace.core.models import Design
    from zaptrace.synthesis.explain import SynthesisDecisionLog
    from zaptrace.synthesis.requirements import Requirements

# Default logic rail when an intent states no rails but needs interface support.
_DEFAULT_LOGIC_RAIL_V = 3.3
_GROUND_NET_TOKEN = "net:GND"


@dataclass(frozen=True)
class BlockContract:
    """What a planned block offers to and needs from the rest of the board.

    Tokens are namespaced strings so composition is a simple set match:
    ``"rail:3V3"`` (a power rail), ``"net:GND"`` (a global net every block may
    assume), ``"iface:i2c"`` (interface support present).
    """

    provides: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannedBlock:
    """One node in the board's block graph: a unit of circuitry with provenance.

    ``realized`` is False for a block the planner knows is needed but has no
    parametric implementation for yet (e.g. an RS-485 transceiver) — it is kept
    in the plan, with a reason, so the gap is visible rather than dropped.
    """

    block_id: str
    kind: str
    rationale: str
    contract: BlockContract
    realized: bool
    calculator: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "kind": self.kind,
            "rationale": self.rationale,
            "provides": list(self.contract.provides),
            "requires": list(self.contract.requires),
            "realized": self.realized,
            "calculator": self.calculator,
        }


@dataclass(frozen=True)
class UnmetRequirement:
    """A block ``requires`` token that no other block ``provides``."""

    block_id: str
    token: str


@dataclass
class ArchitecturePlan:
    """The composed block graph plus what could not be satisfied or realized."""

    blocks: list[PlannedBlock] = field(default_factory=list)
    rails_v: list[float] = field(default_factory=list)
    unmet: list[UnmetRequirement] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def realized_blocks(self) -> list[PlannedBlock]:
        return [b for b in self.blocks if b.realized]

    @property
    def unrealized_blocks(self) -> list[PlannedBlock]:
        return [b for b in self.blocks if not b.realized]

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks": [b.to_dict() for b in self.blocks],
            "rails_v": self.rails_v,
            "unmet_requirements": [{"block_id": u.block_id, "token": u.token} for u in self.unmet],
            "notes": self.notes,
        }


# Interface → how the board supports it. ``realized`` blocks have a parametric
# implementation in ``synthesis.blocks``; others are honestly deferred.
#
# ``support`` semantics:
#   "rail-pullups"  needs the logic rail (e.g. I2C SDA/SCL pull-ups)
#   "gnd-only"      needs only GND (e.g. USB-C CC Rd termination)
#   "transceiver"   needs the logic rail + a transceiver IC (e.g. RS-485, CAN)
#   "none"          a digital bus needing no passive support block
#   "deferred"      needs a block (transceiver/PHY) not yet implemented
_INTERFACE_SUPPORT: dict[str, dict[str, Any]] = {
    "i2c": {
        "support": "rail-pullups",
        "realized": True,
        "rationale": "I2C bus needs SDA/SCL pull-ups to the logic rail",
    },
    "usb": {"support": "gnd-only", "realized": True, "rationale": "USB-C port needs CC pin Rd termination to GND"},
    "ethernet": {"support": "none", "realized": True, "rationale": "Ethernet is an SPI controller (W5500) + RJ45 jack"},
    "spi": {
        "support": "none",
        "realized": True,
        "rationale": "SPI is point-to-point; no passive support block required",
    },
    "uart": {
        "support": "none",
        "realized": True,
        "rationale": "UART is point-to-point; no passive support block required",
    },
    "rs485": {
        "support": "transceiver",
        "realized": True,
        "rationale": "RS-485 needs a transceiver + 120Ω bus termination",
    },
    "can": {
        "support": "transceiver",
        "realized": True,
        "rationale": "CAN needs a transceiver + 120Ω bus termination",
    },
    "ble": {
        "support": "deferred",
        "realized": False,
        "rationale": "BLE needs an RF front-end/antenna block (not yet implemented)",
    },
    "wifi": {
        "support": "deferred",
        "realized": False,
        "rationale": "Wi-Fi needs an RF front-end/antenna block (not yet implemented)",
    },
    "lora": {
        "support": "deferred",
        "realized": False,
        "rationale": "LoRa needs an RF front-end/antenna block (not yet implemented)",
    },
}


def _logic_rail_v(requirements: Requirements) -> float:
    """The rail interface support hangs off — the lowest stated rail, or a default."""
    return min(requirements.rails_v) if requirements.rails_v else _DEFAULT_LOGIC_RAIL_V


def _append_usb_input_blocks(plan: ArchitecturePlan) -> None:
    plan.blocks.extend(
        [
            PlannedBlock(
                block_id="PB_USB_C_CC",
                kind="power_input",
                rationale="USB-C VBUS input; CC pins need Rd termination",
                contract=BlockContract(provides=("net:VBUS",), requires=(_GROUND_NET_TOKEN,)),
                realized=True,
                calculator="usb_c_cc_termination",
            ),
            PlannedBlock(
                block_id="J_USB_C",
                kind="connector",
                rationale="USB-C receptacle: the board's physical power input",
                contract=BlockContract(provides=("net:VBUS",), requires=(_GROUND_NET_TOKEN,)),
                realized=True,
                params={"connector": "usb_c"},
            ),
        ]
    )


def _power_stage_block(
    stage: dict[str, Any],
    *,
    no_input: bool,
    system_v: float | None,
) -> PlannedBlock:
    rail_v = stage["to_rail_v"]
    rail_net = _rail_net(rail_v)
    topology = stage["topology"]
    if no_input and system_v is not None and rail_v == system_v and topology == "boost":
        return PlannedBlock(
            block_id=f"J_DC_{rail_net}",
            kind="connector",
            rationale=f"external DC power input at {rail_v:g} V (no on-board conversion stated)",
            contract=BlockContract(provides=(f"rail:{rail_net}",), requires=(_GROUND_NET_TOKEN,)),
            realized=True,
            params={"connector": "dc_input", "rail_net": rail_net},
        )
    realized = topology in ("buck", "ldo")
    return PlannedBlock(
        block_id=f"PB_REG_{rail_net}",
        kind="regulator",
        rationale=stage["rationale"],
        contract=BlockContract(provides=(f"rail:{rail_net}",), requires=(_GROUND_NET_TOKEN,)),
        realized=realized,
        calculator=stage.get("calculator"),
        params={"rail_v": rail_v, "topology": topology, "from_v": stage["from_v"]},
    )


def _append_power_blocks(
    plan: ArchitecturePlan,
    requirements: Requirements,
    power: dict[str, Any],
) -> None:
    if requirements.usb_c:
        _append_usb_input_blocks(plan)
    no_input = not requirements.usb_c and not requirements.battery
    system_v = max(requirements.rails_v) if requirements.rails_v else None
    for stage in power["stages"]:
        if stage["stage"] != "regulator":
            continue
        block = _power_stage_block(stage, no_input=no_input, system_v=system_v)
        plan.blocks.append(block)
        if block.kind == "regulator" and not block.realized:
            plan.notes.append(
                f"{block.params['topology']} stage for {_rail_net(block.params['rail_v'])} "
                "planned but has no parametric block yet"
            )


def _interface_block(
    iface: str,
    spec: dict[str, Any],
    logic_rail_v: float,
    logic_rail: str,
) -> PlannedBlock:
    support = spec["support"]
    requires: tuple[str, ...]
    if support == "none":
        requires = ()
    elif support == "gnd-only":
        requires = (_GROUND_NET_TOKEN,)
    else:
        requires = (f"rail:{logic_rail}", _GROUND_NET_TOKEN)
    params = {} if support == "none" else {"logic_rail_v": logic_rail_v, "support": support}
    return PlannedBlock(
        block_id=f"IF_{iface.upper()}",
        kind="interface",
        rationale=spec["rationale"],
        contract=BlockContract(provides=(f"iface:{iface}",), requires=requires),
        realized=bool(spec["realized"]),
        params=params,
    )


def _append_interface_blocks(
    plan: ArchitecturePlan,
    requirements: Requirements,
    logic_rail_v: float,
    logic_rail: str,
) -> None:
    for iface in sorted(requirements.interfaces):
        spec = _INTERFACE_SUPPORT.get(iface)
        if spec is None:
            plan.notes.append(f"interface '{iface}' recognized but has no support policy")
            continue
        plan.blocks.append(_interface_block(iface, spec, logic_rail_v, logic_rail))


def _append_core_block(plan: ArchitecturePlan, requirements: Requirements, logic_rail: str) -> None:
    if not requirements.mcu:
        return
    realized = has_mcu_part(requirements.mcu)
    plan.blocks.append(
        PlannedBlock(
            block_id="CORE_MCU",
            kind="mcu",
            rationale=f"{requirements.mcu} is the functional core; drives the board's interfaces",
            contract=BlockContract(provides=("core",), requires=(f"rail:{logic_rail}", _GROUND_NET_TOKEN)),
            realized=realized,
            params={"family": requirements.mcu},
        )
    )
    if not realized:
        plan.notes.append(f"MCU family '{requirements.mcu}' has no library part yet")


def _append_peripheral_blocks(plan: ArchitecturePlan, requirements: Requirements, logic_rail: str) -> None:
    for peripheral in [*plan_sensors(requirements), *plan_storage(requirements)]:
        plan.blocks.append(
            PlannedBlock(
                block_id=f"PERIPH_{peripheral.part_id.upper().replace('-', '_')}",
                kind="peripheral",
                rationale=f"{peripheral.function} ({peripheral.part_id}) on the {peripheral.bus.upper()} bus",
                contract=BlockContract(
                    provides=(f"peripheral:{peripheral.function}",),
                    requires=(f"rail:{logic_rail}", _GROUND_NET_TOKEN, f"iface:{peripheral.bus}"),
                ),
                realized=peripheral.realized,
                params={"part_id": peripheral.part_id, "bus": peripheral.bus},
            )
        )
        if not peripheral.realized:
            plan.notes.append(f"peripheral '{peripheral.part_id}' ({peripheral.function}) has no library part")


def _append_ethernet_block(plan: ArchitecturePlan, requirements: Requirements, logic_rail: str) -> None:
    if "ethernet" not in requirements.interfaces:
        return
    plan.blocks.append(
        PlannedBlock(
            block_id="PERIPH_ETHERNET",
            kind="peripheral",
            rationale="W5500 SPI Ethernet controller + RJ45 jack",
            contract=BlockContract(
                provides=("peripheral:ethernet",),
                requires=(f"rail:{logic_rail}", _GROUND_NET_TOKEN, "iface:ethernet"),
            ),
            realized=True,
            params={"part_id": "w5500", "bus": "ethernet"},
        )
    )


def plan_architecture(requirements: Requirements) -> ArchitecturePlan:
    """Compose the board's block graph from requirements, with provenance."""
    plan = ArchitecturePlan(rails_v=sorted(requirements.rails_v))
    plan.notes.extend(plan_power_tree(requirements).get("notes", []))
    logic_rail_v = _logic_rail_v(requirements)
    logic_rail = _rail_net(logic_rail_v)
    _append_power_blocks(plan, requirements, plan_power_tree(requirements))
    _append_interface_blocks(plan, requirements, logic_rail_v, logic_rail)
    _append_core_block(plan, requirements, logic_rail)
    _append_peripheral_blocks(plan, requirements, logic_rail)
    _append_ethernet_block(plan, requirements, logic_rail)
    _check_composition(plan)
    return plan


# Global nets every block may assume exist without a provider declaring them.
_GLOBAL_NETS = (_GROUND_NET_TOKEN,)


def _check_composition(plan: ArchitecturePlan) -> None:
    """Flag any ``requires`` token not satisfied by some block's ``provides``."""
    provided: set[str] = set(_GLOBAL_NETS)
    for block in plan.blocks:
        provided.update(block.contract.provides)
    for block in plan.blocks:
        for token in block.contract.requires:
            if token not in provided:
                plan.unmet.append(UnmetRequirement(block_id=block.block_id, token=token))


@dataclass
class _ArchitectureEmissionContext:
    requirements: Requirements
    design: Design
    log: SynthesisDecisionLog
    input_net: str
    load_a: float
    logic_rail: str


def _architecture_input_net(requirements: Requirements) -> str:
    if requirements.usb_c:
        return "VBUS"
    if requirements.battery:
        return "VBAT"
    if requirements.rails_v:
        return _rail_net(max(requirements.rails_v))
    return "VIN"


def _build_emission_context(requirements: Requirements, name: str) -> _ArchitectureEmissionContext:
    from zaptrace.core.models import Design, DesignMeta
    from zaptrace.synthesis.explain import SynthesisDecisionLog
    from zaptrace.synthesis.power_tree import _DEFAULT_LOAD_A

    return _ArchitectureEmissionContext(
        requirements=requirements,
        design=Design(meta=DesignMeta(name=name, description=f"Board synthesized from: {requirements.raw_intent}")),
        log=SynthesisDecisionLog(),
        input_net=_architecture_input_net(requirements),
        load_a=requirements.max_current_a if requirements.max_current_a is not None else _DEFAULT_LOAD_A,
        logic_rail=_rail_net(_logic_rail_v(requirements)),
    )


def _emit_power_input(context: _ArchitectureEmissionContext, block: PlannedBlock) -> None:
    from zaptrace.synthesis.blocks import instantiate_usb_c_ufp_cc

    instantiate_usb_c_ufp_cc(context.design, block.block_id)
    context.log.record(
        "topology",
        block.block_id,
        "USB-C CC Rd",
        rationale=block.rationale,
        calculator="usb_c_cc_termination",
    )


def _emit_connector(context: _ArchitectureEmissionContext, block: PlannedBlock) -> None:
    from zaptrace.synthesis.connectors import instantiate_dc_input, instantiate_usb_c_connector

    if block.params.get("connector") == "dc_input":
        ref = instantiate_dc_input(context.design, vin_net=block.params["rail_net"])
        context.log.record("topology", block.block_id, f"DC power input {ref}", rationale=block.rationale)
        return
    ref = instantiate_usb_c_connector(context.design, vbus_net=context.input_net)
    context.log.record("topology", block.block_id, f"USB-C receptacle {ref}", rationale=block.rationale)


def _emit_regulator(context: _ArchitectureEmissionContext, block: PlannedBlock) -> None:
    from zaptrace.synthesis.blocks import instantiate_ldo, instantiate_sync_buck_tlv62569
    from zaptrace.synthesis.calculators import buck_inductor_capacitor
    from zaptrace.synthesis.power_tree import _DEFAULT_BUCK_FSW_HZ

    rail_v = block.params["rail_v"]
    rail_net = _rail_net(rail_v)
    if block.params["topology"] != "buck":
        instantiate_ldo(context.design, block.block_id, vin_net=context.input_net, vout_net=rail_net, output_v=rail_v)
        context.log.record("topology", block.block_id, f"LDO {rail_v:g}V", rationale=block.rationale)
        return
    buck = buck_inductor_capacitor(block.params["from_v"], rail_v, context.load_a, _DEFAULT_BUCK_FSW_HZ)
    instantiate_sync_buck_tlv62569(
        context.design,
        block.block_id,
        vin_net=context.input_net,
        vout_net=rail_net,
        sw_net=f"SW_{rail_net}",
        en_net=f"EN_{rail_net}",
        fb_net=f"FB_{rail_net}",
        inductor_val=f"{buck.inductor_chosen_uh:g}uH",
        cout_val=f"{buck.output_cap_chosen_uf:g}uF",
    )
    context.log.record(
        "value",
        block.block_id,
        f"buck {rail_v:g}V (L={buck.inductor_chosen_uh:g}uH, Cout={buck.output_cap_chosen_uf:g}uF)",
        rationale=block.rationale,
        calculator="buck_inductor_capacitor",
    )


def _emit_interface(context: _ArchitectureEmissionContext, block: PlannedBlock) -> None:
    from zaptrace.synthesis.blocks import (
        instantiate_can_transceiver,
        instantiate_i2c_pullups,
        instantiate_rs485_transceiver,
    )

    support = block.params.get("support")
    if support == "rail-pullups":
        instantiate_i2c_pullups(
            context.design, block.block_id, vdd_net=context.logic_rail, supply_v=block.params["logic_rail_v"]
        )
        context.log.record("value", block.block_id, "I2C pull-ups", rationale=block.rationale, calculator="i2c_pullup")
    elif support == "gnd-only" and block.block_id == "IF_USB":
        context.log.record("topology", block.block_id, "covered by USB-C input", rationale=block.rationale)
    elif support == "transceiver" and block.block_id == "IF_RS485":
        instantiate_rs485_transceiver(context.design, block.block_id, rail_net=context.logic_rail)
        context.log.record("topology", block.block_id, "RS-485 transceiver (MAX3485)", rationale=block.rationale)
    elif support == "transceiver" and block.block_id == "IF_CAN":
        instantiate_can_transceiver(context.design, block.block_id, rail_net=context.logic_rail)
        context.log.record("topology", block.block_id, "CAN transceiver (SN65HVD230)", rationale=block.rationale)
    else:
        context.log.record("note", block.block_id, "no support block required", rationale=block.rationale)


def _emit_mcu(context: _ArchitectureEmissionContext, block: PlannedBlock) -> None:
    from zaptrace.synthesis.mcu import instantiate_mcu

    result = instantiate_mcu(
        context.design,
        block.params["family"],
        context.requirements.interfaces,
        rail_net=context.logic_rail,
    )
    context.log.record(
        "topology",
        block.block_id,
        f"{result.part_id} core, {len(result.assignments)} pins wired",
        rationale=block.rationale,
    )
    for iface in result.unconnected_interfaces:
        context.log.record(
            "note",
            block.block_id,
            f"{iface} not wired (no support net / no spare GPIO)",
            confidence=0.0,
        )


def _emit_peripheral(context: _ArchitectureEmissionContext, block: PlannedBlock) -> None:
    from zaptrace.synthesis.peripherals import instantiate_ethernet, instantiate_sensor, instantiate_spi_flash

    part_id = block.params["part_id"]
    bus = block.params["bus"]
    if bus == "ethernet":
        ref = instantiate_ethernet(context.design, rail_net=context.logic_rail)
    elif bus == "spi":
        ref = instantiate_spi_flash(context.design, part_id, rail_net=context.logic_rail)
    else:
        ref = instantiate_sensor(context.design, part_id, rail_net=context.logic_rail)
    if ref is not None:
        context.log.record("topology", block.block_id, f"{part_id} on {bus.upper()} bus", rationale=block.rationale)
    else:
        context.log.record("note", block.block_id, f"{part_id} not wired as {bus.upper()}", confidence=0.0)


def _emit_realized_block(context: _ArchitectureEmissionContext, block: PlannedBlock) -> None:
    emitters = {
        "power_input": _emit_power_input,
        "connector": _emit_connector,
        "regulator": _emit_regulator,
        "interface": _emit_interface,
        "mcu": _emit_mcu,
        "peripheral": _emit_peripheral,
    }
    emitter = emitters.get(block.kind)
    if emitter is not None:
        emitter(context, block)


def _emit_architecture_blocks(context: _ArchitectureEmissionContext, plan: ArchitecturePlan) -> None:
    for block in plan.blocks:
        if not block.realized:
            context.log.record("gap", block.block_id, "unrealized", rationale=block.rationale, confidence=0.0)
            continue
        _emit_realized_block(context, block)


def build_architecture_design(
    requirements: Requirements,
    *,
    name: str = "SynthesizedBoard",
) -> tuple[Design, ArchitecturePlan, SynthesisDecisionLog]:
    """Emit a Design from the composed block graph and return its decision log."""
    from zaptrace.ee.classifier import assign_net_types

    plan = plan_architecture(requirements)
    context = _build_emission_context(requirements, name)
    _emit_architecture_blocks(context, plan)
    assign_net_types(context.design)
    return context.design, plan, context.log
