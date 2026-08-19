"""Tests for CycloneDX hardware BOM (HBOM) export."""

from __future__ import annotations

import json

from zaptrace.core.models import Component, Design, DesignMeta
from zaptrace.export.bom import _hbom_component, _hbom_groups, generate_hbom_cyclonedx


def _design() -> Design:
    d = Design(meta=DesignMeta(name="HBOMTest"))
    d.components["r1"] = Component(id="r1", ref="R1", type="resistor", value="10k", footprint="0402")
    d.components["r2"] = Component(id="r2", ref="R2", type="resistor", value="10k", footprint="0402")
    d.components["c1"] = Component(id="c1", ref="C1", type="capacitor", value="100nF", dnp=True)  # excluded
    d.components["u1"] = Component(
        id="u1",
        ref="U1",
        type="ic",
        value="ESP32",
        mpn="ESP32-X",
        manufacturer="Espressif",
        lcsc_id="C123",
    )
    return d


def test_hbom_structure() -> None:
    bom = json.loads(generate_hbom_cyclonedx(_design()))
    assert bom["bomFormat"] == "CycloneDX"
    assert bom["specVersion"] == "1.6"
    assert bom["version"] == 1
    assert bom["metadata"]["component"]["name"] == "HBOMTest"
    assert "timestamp" not in bom["metadata"]


def test_hbom_groups_identical_parts() -> None:
    comps = json.loads(generate_hbom_cyclonedx(_design()))["components"]
    # resistor group (R1+R2) and the IC; the DNP cap is excluded
    assert len(comps) == 2
    resistor = next(c for c in comps if c["name"] == "10k")
    props = {p["name"]: p["value"] for p in resistor["properties"]}
    assert props["zaptrace:reference-designators"] == "R1,R2"
    assert props["zaptrace:quantity"] == "2"


def test_hbom_excludes_dnp() -> None:
    bom = json.loads(generate_hbom_cyclonedx(_design()))
    refs = ",".join(
        p["value"] for c in bom["components"] for p in c["properties"] if p["name"] == "zaptrace:reference-designators"
    )
    assert "C1" not in refs


def test_hbom_sourcing_properties() -> None:
    bom = json.loads(generate_hbom_cyclonedx(_design()))
    ic = next(c for c in bom["components"] if c["name"] == "ESP32")
    assert ic["manufacturer"]["name"] == "Espressif"
    props = {p["name"]: p["value"] for p in ic["properties"]}
    assert props["zaptrace:mpn"] == "ESP32-X"
    assert props["zaptrace:lcsc-id"] == "C123"
    assert props["zaptrace:lifecycle"] == "active"


def test_hbom_is_deterministic() -> None:
    design = _design()
    first = generate_hbom_cyclonedx(design)
    second = generate_hbom_cyclonedx(design.model_copy(deep=True))
    assert first == second


def test_hbom_timestamp_injection() -> None:
    bom = json.loads(generate_hbom_cyclonedx(_design(), timestamp="2026-06-25T00:00:00Z"))
    assert bom["metadata"]["timestamp"] == "2026-06-25T00:00:00Z"


def test_hbom_empty_design() -> None:
    bom = json.loads(generate_hbom_cyclonedx(Design(meta=DesignMeta(name="empty"))))
    assert bom["components"] == []
    assert bom["bomFormat"] == "CycloneDX"


def test_hbom_helpers_group_and_render_optional_properties() -> None:
    design = _design()
    groups = _hbom_groups(design)
    assert len(groups) == 2
    resistor_key = next(key for key in groups if key[1] == "10k")
    resistor = _hbom_component(resistor_key, groups[resistor_key])
    properties = {item["name"]: item["value"] for item in resistor["properties"]}
    assert properties["zaptrace:reference-designators"] == "R1,R2"
    assert properties["zaptrace:footprint"] == "0402"

    ic_key = next(key for key in groups if key[1] == "ESP32")
    ic = _hbom_component(ic_key, groups[ic_key])
    assert ic["manufacturer"] == {"name": "Espressif"}
    assert {item["name"] for item in ic["properties"]} >= {"zaptrace:mpn", "zaptrace:lcsc-id"}
