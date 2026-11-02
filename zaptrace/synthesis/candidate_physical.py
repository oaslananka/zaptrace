"""Narrow, source-backed STM32F103C8T6 and GCT USB4105 pilot qualification.

The two selected devices are not promoted to production trust: only the
pin-number table and the exact SHA-pinned USB land-pattern identity are checked.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from zaptrace.core.models import Design
from zaptrace.kicad.verified_vendor import resolve_verified_footprint, verified_footprint_bytes
from zaptrace.library.loader import LibraryLoader
from zaptrace.synthesis.requirements import Requirements

_ST_DATASHEET = "https://www.st.com/resource/en/datasheet/stm32f103c8.pdf"
_ST_I2C_REF = "ST RM0008 Rev 21, Table 55 I2C1_REMAP=0 (PB6 SCL / PB7 SDA)"
_USB_DRAWING = "https://gct.co/files/drawings/usb4105.pdf"

# GCT USB4105 manufacturer drawing Rev B contact identity. The independent
# contract prevents a tampered library's own maps from self-validating.
_USB4105_CONTACTS = {
    "A1": "GND",
    "A4": "VBUS",
    "A5": "CC1",
    "A6": "D+",
    "A7": "D-",
    "A8": "SBU1",
    "A9": "VBUS",
    "A12": "GND",
    "B1": "GND",
    "B4": "VBUS",
    "B5": "CC2",
    "B6": "D+",
    "B7": "D-",
    "B8": "SBU2",
    "B9": "VBUS",
    "B12": "GND",
    "S1": "SHIELD",
}

# ST DS5319 Rev 20 Figure 8, exact 48-lead LQFP48 order (pad = index+1).
_ST_LQFP48: tuple[str, ...] = (
    "VBAT",
    "PC13",
    "PC14",
    "PC15",
    "PD0",
    "PD1",
    "NRST",
    "VSSA",
    "VDDA",
    "PA0",
    "PA1",
    "PA2",
    "PA3",
    "PA4",
    "PA5",
    "PA6",
    "PA7",
    "PB0",
    "PB1",
    "PB2",
    "PB10",
    "PB11",
    "GND",
    "VDD",
    "PB12",
    "PB13",
    "PB14",
    "PB15",
    "PA8",
    "PA9",
    "PA10",
    "PA11",
    "PA12",
    "PA13",
    "GND",
    "VDD",
    "PA14",
    "PA15",
    "PB3",
    "PB4",
    "PB5",
    "PB6",
    "PB7",
    "BOOT0",
    "PB8",
    "PB9",
    "GND",
    "VDD",
)


def qualify_pilot_physical_pins(design: Design, requirements: Requirements) -> dict[str, Any]:
    """Modify only exact known source designs; report any malformed input as blocker."""
    result: dict[str, Any] = {"qualified": [], "blockers": []}
    if requirements.mcu != "stm32" or "i2c" not in requirements.interfaces:
        return result

    mcu = [c for c in design.components.values() if c.type == "mcu" and c.mpn == "STM32F103C8T6"]
    if len(mcu) != 1:
        result["blockers"].append({"code": "exact_stm32_device_unavailable", "subject": "stm32"})
        return result
    comp = mcu[0]
    spec = LibraryLoader().get("stm32f103c8t6")
    mapping = {str(index + 1): name for index, name in enumerate(_ST_LQFP48)}
    if (
        comp.footprint != "STM32F103C8T6-LQFP48"
        or spec.mpn != "STM32F103C8T6"
        or spec.datasheet != _ST_DATASHEET
        or spec.package_pin_map
        or comp.package_pin_map
        or set(comp.pins) - set(_ST_LQFP48)
        or len(mapping) != 48
    ):
        result["blockers"].append({"code": "stm32_source_and_package_contract_not_proven", "subject": comp.ref})
        return result
    bus = {"SDA": ("PA0", "PB7"), "SCL": ("PA1", "PB6")}
    for net_name, (old_pin, new_pin) in bus.items():
        net = design.nets.get(net_name)
        if (
            net is None
            or sum(n.component_ref == comp.ref for n in net.nodes) != 1
            or any(n.component_ref == comp.ref and n.pin_name != old_pin for n in net.nodes)
            or new_pin not in comp.pins
            or any(
                n.component_ref == comp.ref and n.pin_name == new_pin
                for other in design.nets.values()
                for n in other.nodes
            )
        ):
            result["blockers"].append({"code": "stm32_i2c_assignment_not_exact", "subject": net_name})
            return result
    for net_name, (old_pin, new_pin) in bus.items():
        for node in design.nets[net_name].nodes:
            if node.component_ref == comp.ref and node.pin_name == old_pin:
                node.pin_name = new_pin
    comp.package_pin_map = mapping
    result["qualified"].append(
        {
            "ref": comp.ref,
            "mpn": comp.mpn,
            "pin_map_source": _ST_DATASHEET + " Figure 8 / DS5319 Rev 20",
            "i2c_function_source": _ST_I2C_REF,
            "physical_pad_count": 48,
            "i2c_sda_pad": "43",
            "i2c_scl_pad": "42",
            "review_status": "source_documented_not_independent_electrical_qualification",
        }
    )

    if not requirements.usb_c:
        return result
    usb = [c for c in design.components.values() if c.type == "connector" and c.mpn == "USB4105-15-A-120"]
    if len(usb) != 1:
        result["blockers"].append({"code": "exact_usb4105_device_unavailable", "subject": "usb_c"})
        return result
    connector = usb[0]
    info = LibraryLoader().get("usb-c-16p")
    try:
        filename, content = verified_footprint_bytes("usb4105-16p")
        geometry = resolve_verified_footprint("usb4105-16p")
    except (ValueError, OSError) as exc:
        result["blockers"].append({"code": "usb4105_vendor_footprint_integrity_failure", "subject": str(exc)})
        return result
    ids = Counter(p.id for p in geometry.pads)
    expected = set(info.package_pin_map) | {""}
    if (
        connector.footprint != info.footprint
        or connector.package_pin_map != _USB4105_CONTACTS
        or info.package_pin_map != _USB4105_CONTACTS
        or connector.mpn != info.mpn
        or info.datasheet != _USB_DRAWING
        or set(ids) != expected
        or ids[""] != 2
        or ids["S1"] != 4
        or any(ids[pin] != 1 for pin in info.package_pin_map if pin != "S1")
        or any(p.id == "" and (p.plated or (p.drill is None and p.drill_slot is None)) for p in geometry.pads)
        or filename != "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.kicad_mod"
        or len(content) < 1000
    ):
        result["blockers"].append({"code": "usb4105_pad_map_or_geometry_mismatch", "subject": connector.ref})
        return result
    connector.footprint_def = geometry
    result["qualified"].append(
        {
            "ref": connector.ref,
            "mpn": connector.mpn,
            "pin_map_source": _USB_DRAWING,
            "physical_source": "sha256-pinned official KiCad USB4105 footprint",
            "vendor_geometry_hash_verified": True,
            "physical_contact_ids": sorted(info.package_pin_map),
            "repeated_shield_pads": 4,
            "anonymous_mechanical_holes": 2,
            "review_status": "source_documented_starter_library_heuristic_no_manufacturing_approval",
        }
    )
    return result
