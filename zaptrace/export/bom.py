from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Any

from zaptrace.core.models import Component, Design
from zaptrace.supply.client import SupplyClient

_BASIC_PART_LABELS: dict[bool | None, str] = {True: "Basic", False: "Extended", None: ""}


def _component_supply_fields(comp: Component, client: SupplyClient) -> tuple[str | None, str, str, list[str]]:
    lcsc_id = comp.lcsc_id
    basic_part = comp.basic_part
    stock = comp.stock

    if comp.mpn and not lcsc_id:
        result = client.resolve_mpn(comp.mpn)
        if result:
            lcsc_id = result.lcsc_id
            basic_part = result.basic_part
            stock = result.stock

    dnp_val = "DNP" if comp.dnp else "Populate"
    flags: list[str] = []
    if not comp.dnp and not lcsc_id:
        flags.append("Missing LCSC#")
    if not comp.dnp and stock == 0:
        flags.append("Out of Stock")

    return lcsc_id, _BASIC_PART_LABELS[basic_part], dnp_val, flags


def generate_bom_csv(design: Design) -> str:
    """Generate Bill of Materials as CSV string."""
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "Ref",
            "Type",
            "Value",
            "Footprint",
            "MPN",
            "Manufacturer",
            "Lifecycle",
            "Datasheet",
            "LCSC#",
            "Basic/Extended",
            "Populate/DNP",
            "Flags",
        ],
    )
    writer.writeheader()
    client = SupplyClient()
    for comp in sorted(design.components.values(), key=lambda c: c.ref):
        lcsc_id, basic_val, dnp_val, flags = _component_supply_fields(comp, client)

        writer.writerow(
            {
                "Ref": comp.ref,
                "Type": comp.type,
                "Value": comp.value or "",
                "Footprint": comp.footprint,
                "MPN": comp.mpn or "",
                "Manufacturer": comp.manufacturer or "",
                "Lifecycle": comp.lifecycle.value,
                "Datasheet": comp.datasheet_url or "",
                "LCSC#": lcsc_id or "",
                "Basic/Extended": basic_val,
                "Populate/DNP": dnp_val,
                "Flags": ", ".join(flags),
            }
        )
    return output.getvalue()


def generate_bom_json(design: Design) -> str:
    """Generate BOM as JSON string."""
    items: list[dict[str, str | None]] = []
    client = SupplyClient()
    for comp in sorted(design.components.values(), key=lambda c: c.ref):
        lcsc_id, basic_val, dnp_val, flags = _component_supply_fields(comp, client)

        items.append(
            {
                "ref": comp.ref,
                "type": comp.type,
                "value": comp.value,
                "footprint": comp.footprint,
                "mpn": comp.mpn,
                "manufacturer": comp.manufacturer,
                "lifecycle": comp.lifecycle.value,
                "datasheet_url": comp.datasheet_url,
                "lcsc_id": lcsc_id,
                "basic_extended": basic_val,
                "populate_dnp": dnp_val,
                "flags": ", ".join(flags),
            }
        )
    return json.dumps(
        {"design": design.meta.name, "items": items, "count": len(items)},
        indent=2,
        ensure_ascii=False,
    )


HbomGroupKey = tuple[str, str, str, str]


def _hbom_groups(design: Design) -> dict[HbomGroupKey, list[Component]]:
    groups: dict[HbomGroupKey, list[Component]] = {}
    for component in design.components.values():
        if component.dnp:
            continue
        key = (component.type, component.value or "", component.mpn or "", component.footprint or "")
        groups.setdefault(key, []).append(component)
    return groups


def _hbom_component(key: HbomGroupKey, components: list[Component]) -> dict[str, Any]:
    component_type, value, mpn, footprint = key
    head = components[0]
    properties: list[dict[str, str]] = [
        {"name": "zaptrace:reference-designators", "value": ",".join(sorted(item.ref for item in components))},
        {"name": "zaptrace:quantity", "value": str(len(components))},
        {"name": "zaptrace:type", "value": component_type},
        {"name": "zaptrace:lifecycle", "value": head.lifecycle.value},
    ]
    optional_properties = (
        ("zaptrace:footprint", footprint),
        ("zaptrace:mpn", mpn),
        ("zaptrace:lcsc-id", head.lcsc_id or ""),
    )
    properties.extend({"name": name, "value": item} for name, item in optional_properties if item)
    result: dict[str, Any] = {"type": "device", "name": value or component_type, "properties": properties}
    if head.manufacturer:
        result["manufacturer"] = {"name": head.manufacturer}
    return result


def generate_hbom_cyclonedx(design: Design, *, timestamp: str | None = None) -> str:
    """Generate a CycloneDX 1.6 hardware BOM (HBOM) as a JSON string.

    Populated components are grouped by part identity (type, value, MPN,
    footprint) into one CycloneDX component each, carrying the reference
    designators, quantity, lifecycle and sourcing metadata as properties.

    The output is deterministic — no ``metadata.timestamp`` is emitted unless
    one is supplied — so it can be hashed for the proof pack and diffed in CI.
    """
    groups = _hbom_groups(design)
    components = [_hbom_component(key, grouped) for key, grouped in sorted(groups.items())]

    bom: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"component": {"type": "device", "name": design.meta.name}},
        "components": components,
    }
    if timestamp:
        bom["metadata"]["timestamp"] = timestamp
    return json.dumps(bom, indent=2, ensure_ascii=False)
