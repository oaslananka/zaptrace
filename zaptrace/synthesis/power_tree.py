"""Block-level power-tree architecture planner.

From parsed :class:`~zaptrace.synthesis.requirements.Requirements`, plan the
board's power architecture — input sources, battery charging, power-path, and a
regulator per rail — with every choice justified and pointing at the calculator
that sizes it. This is the *architecture* layer of real schematic synthesis:
it decides which power stages a design needs and why, before any component
values or netlist are generated.

Deterministic and conservative: it plans only from what the requirements state
and never invents a rail or source that was not asked for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zaptrace.synthesis.requirements import Requirements

# A linear regulator dissipates (Vin - Vout) * Iout as heat; above this a small
# SOT-23/SOT-223 LDO needs a heatsink, so a switching regulator is preferred.
_LDO_MAX_DISSIPATION_W = 0.5
# Single Li-ion/Li-Po cell: 3.0 V (empty) – 4.2 V (full), ~3.7 V nominal.
_LI_ION_NOMINAL_V = 3.7
_USB_VBUS_V = 5.0
# When no current budget is stated, assume a light load for regulator sizing.
_DEFAULT_LOAD_A = 0.1


def _power_sources(requirements: Requirements) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if requirements.usb_c:
        sources.append(
            {
                "source": "usb_c_vbus",
                "voltage_v": _USB_VBUS_V,
                "rationale": "USB-C VBUS as a 5 V sink input; CC pins need Rd termination",
                "calculator": "usb_c_cc_termination",
            }
        )
    if requirements.battery:
        sources.append(
            {
                "source": "li_ion_battery",
                "voltage_v": _LI_ION_NOMINAL_V,
                "rationale": "single Li-ion/Li-Po cell, 3.0–4.2 V (3.7 V nominal)",
                "calculator": None,
            }
        )
    return sources


def _system_power_path(requirements: Requirements) -> tuple[list[dict[str, Any]], float | None, list[str]]:
    stages: list[dict[str, Any]] = []
    notes: list[str] = []
    if requirements.battery and requirements.usb_c:
        stages.extend(
            [
                {
                    "stage": "charger",
                    "from": "usb_c_vbus",
                    "to": "li_ion_battery",
                    "topology": "li-ion linear charger",
                    "rationale": "charge the cell from VBUS while USB is connected",
                    "calculator": "lipo_charge_resistor",
                },
                {
                    "stage": "power_path",
                    "rationale": "select VBUS when present, otherwise the battery, to feed VSYS",
                    "calculator": None,
                },
            ]
        )
        return stages, _USB_VBUS_V, notes
    if requirements.usb_c:
        return stages, _USB_VBUS_V, notes
    if requirements.battery:
        notes.append("battery present but no charging input stated; add a USB/DC charge source or confirm primary cell")
        return stages, _LI_ION_NOMINAL_V, notes
    system_v = max(requirements.rails_v) if requirements.rails_v else None
    if system_v is None:
        notes.append("no input source or rail stated; cannot plan a power tree")
    return stages, system_v, notes


def _regulator_stage(system_v: float, rail: float, load_a: float) -> dict[str, Any]:
    if rail >= system_v:
        return {
            "stage": "regulator",
            "from_v": system_v,
            "to_rail_v": rail,
            "topology": "boost",
            "rationale": f"{rail:g} V rail is above the {system_v:g} V system rail; needs a step-up",
            "calculator": None,
        }

    dissipation_w = (system_v - rail) * load_a
    if dissipation_w <= _LDO_MAX_DISSIPATION_W:
        topology, calculator = "ldo", None
        rationale = (
            f"drop {system_v:g}->{rail:g} V at {load_a:g} A dissipates {round(dissipation_w, 3):g} W "
            f"(<= {_LDO_MAX_DISSIPATION_W:g} W): an LDO is simplest"
        )
    else:
        topology, calculator = "buck", "buck_inductor_capacitor"
        rationale = (
            f"drop {system_v:g}->{rail:g} V at {load_a:g} A dissipates {round(dissipation_w, 3):g} W "
            f"(> {_LDO_MAX_DISSIPATION_W:g} W): a buck avoids the heat"
        )
    return {
        "stage": "regulator",
        "from_v": system_v,
        "to_rail_v": rail,
        "topology": topology,
        "dissipation_w": round(dissipation_w, 3),
        "rationale": rationale,
        "calculator": calculator,
    }


def plan_power_tree(requirements: Requirements) -> dict[str, Any]:
    """Plan a justified power tree (sources → charge/path → per-rail regulators)."""
    stages, system_v, notes = _system_power_path(requirements)
    load_a = requirements.max_current_a if requirements.max_current_a is not None else _DEFAULT_LOAD_A
    if system_v is not None:
        stages.extend(_regulator_stage(system_v, rail, load_a) for rail in sorted(requirements.rails_v))
    return {
        "sources": _power_sources(requirements),
        "stages": stages,
        "rails_v": sorted(requirements.rails_v),
        "notes": notes,
    }


# Assumed buck switching frequency when none is stated (a common small-buck value).
_DEFAULT_BUCK_FSW_HZ = 500_000.0


def _rail_net(rail_v: float) -> str:
    """Net name for a rail, e.g. 3.3 -> VDD_3V3, 5 -> VDD_5."""
    return "VDD_" + f"{rail_v:g}".replace(".", "V")


def build_power_tree_design(requirements: Requirements, *, name: str = "SynthesizedPowerTree") -> Any:
    """Emit a :class:`~zaptrace.core.models.Design` netlist from the power-tree plan.

    Turns the plan from :func:`plan_power_tree` into real components and nets via
    the parametric blocks: a USB-C CC termination, a regulator per rail (a
    computed-L/C buck or an LDO), and I2C pull-ups when an I2C bus is required.
    Boost stages are left unrealized (no block yet) — honest under-build, not a
    silent gap; the caller can read the plan's stages to see them.

    Returns the populated ``Design``.
    """
    from zaptrace.core.models import Design, DesignMeta
    from zaptrace.synthesis.blocks import (
        instantiate_i2c_pullups,
        instantiate_ldo,
        instantiate_sync_buck_tlv62569,
        instantiate_usb_c_ufp_cc,
    )
    from zaptrace.synthesis.calculators import buck_inductor_capacitor

    plan = plan_power_tree(requirements)
    design = Design(meta=DesignMeta(name=name, description=f"Power tree synthesized from: {requirements.raw_intent}"))

    if requirements.usb_c:
        input_net = "VBUS"
    elif requirements.battery:
        input_net = "VBAT"
    else:
        input_net = "VIN"
    if requirements.usb_c:
        instantiate_usb_c_ufp_cc(design, "PB_USB_C_CC")

    load_a = requirements.max_current_a if requirements.max_current_a is not None else _DEFAULT_LOAD_A
    for stage in plan["stages"]:
        if stage["stage"] != "regulator":
            continue
        rail = stage["to_rail_v"]
        rail_net = _rail_net(rail)
        if stage["topology"] == "buck":
            bc = buck_inductor_capacitor(stage["from_v"], rail, load_a, _DEFAULT_BUCK_FSW_HZ)
            instantiate_sync_buck_tlv62569(
                design,
                f"PB_BUCK_{rail_net}",
                vin_net=input_net,
                vout_net=rail_net,
                sw_net=f"SW_{rail_net}",
                en_net=f"EN_{rail_net}",
                fb_net=f"FB_{rail_net}",
                inductor_val=f"{bc.inductor_chosen_uh:g}uH",
                cout_val=f"{bc.output_cap_chosen_uf:g}uF",
            )
        elif stage["topology"] == "ldo":
            instantiate_ldo(design, f"PB_LDO_{rail_net}", vin_net=input_net, vout_net=rail_net, output_v=rail)

    if "i2c" in requirements.interfaces:
        supply_v = requirements.rails_v[0] if requirements.rails_v else 3.3
        instantiate_i2c_pullups(design, "PB_I2C_PU", vdd_net=_rail_net(supply_v), supply_v=supply_v)

    return design
