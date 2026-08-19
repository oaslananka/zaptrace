"""Tests for the requirements -> constraints parser."""

from __future__ import annotations

from pathlib import Path

from zaptrace.synthesis.requirements import (
    Requirements,
    classify_risk,
    diff_requirements,
    freeze_requirements,
    parse_requirements,
    requirements_assumption_report,
    requirements_assumptions,
    requirements_conflicts,
    requirements_coverage,
    requirements_coverage_report,
    requirements_to_constraints,
    review_assumptions,
    write_requirements_artifacts,
)


def test_iot_node_intent() -> None:
    req = parse_requirements("ESP32-S3 IoT node, 3.3V rail, USB-C powered, Li-ion battery, I2C sensor, BLE")
    assert req.rails_v == [3.3]
    assert req.mcu == "esp32"
    assert set(req.interfaces) >= {"i2c", "ble", "usb"}
    assert req.usb_c is True
    assert req.battery is True
    assert req.max_current_a is None  # no current stated


def test_power_supply_intent() -> None:
    req = parse_requirements("5V 2A power supply with a buck converter to 3.3V")
    assert req.rails_v == [3.3, 5.0]
    assert req.max_current_a == 2.0
    assert req.mcu is None
    assert req.interfaces == []


def test_industrial_intent() -> None:
    req = parse_requirements("STM32 RS485 Modbus node, 12V input, 500mA")
    assert req.rails_v == [12.0]
    assert req.max_current_a == 0.5  # 500 mA
    assert req.mcu == "stm32"
    assert req.interfaces == ["rs485"]


def test_european_rail_notation() -> None:
    req = parse_requirements("3V3 and 1V8 rails for the sensor")
    assert req.rails_v == [1.8, 3.3]


def test_can_word_boundary_no_false_positive() -> None:
    # "scanner" contains "can" but must not be read as a CAN bus
    assert "can" not in parse_requirements("a barcode scanner board").interfaces
    assert "can" in parse_requirements("CAN bus gateway").interfaces


def test_minimal_intent_invents_nothing() -> None:
    req = parse_requirements("a simple LED blinker")
    assert req.rails_v == []
    assert req.mcu is None
    assert req.interfaces == []
    assert req.max_current_a is None
    assert req.usb_c is False
    assert req.battery is False


def test_to_dict_is_serializable() -> None:
    req = parse_requirements("RP2040 USB HID keyboard, 5V")
    data = req.to_dict()
    assert data["mcu"] == "rp2040"
    assert data["rails_v"] == [5.0]
    assert "usb" in data["interfaces"]
    assert isinstance(req, Requirements)


def test_requirements_to_constraints_maps_rails_and_buses() -> None:
    req = parse_requirements("esp32 usb-c 3.3v 1.8v i2c sensor")
    cs = requirements_to_constraints(req)
    ids = {d.id for d in cs.voltage_domains}
    assert ids == {"VDD_3V3", "VDD_1V8"}
    # USB-C implies a 90-ohm differential pair and an edge-placed connector.
    usb = next(r for r in cs.routing if r.net == "USB_D*")
    assert usb.differential_pair is True
    assert usb.impedance_ohm == 90.0
    assert any(p.component == "J*" and p.edge for p in cs.placement)


def test_constraints_are_traceable() -> None:
    cs = requirements_to_constraints(parse_requirements("rp2040 usb 5v"))
    # Every routing/placement constraint records why it exists (requirement trace).
    assert all(r.reason for r in cs.routing)
    assert all(p.reason for p in cs.placement)


def test_constraints_invent_nothing_for_bare_intent() -> None:
    cs = requirements_to_constraints(parse_requirements("a simple LED blinker"))
    assert cs.voltage_domains == []
    assert cs.routing == []
    assert cs.placement == []


def test_write_requirements_artifacts(tmp_path: Path) -> None:
    import json

    import yaml

    paths = write_requirements_artifacts("esp32 usb-c 3.3v i2c sensor", tmp_path)
    req_path = Path(paths["requirements"])
    con_path = Path(paths["constraints"])
    assert req_path.name == "requirements.json"
    assert con_path.name == "constraints.yaml"

    req = json.loads(req_path.read_text(encoding="utf-8"))
    assert req["mcu"] == "esp32"
    assert req["rails_v"] == [3.3]

    con = yaml.safe_load(con_path.read_text(encoding="utf-8"))
    assert any(d["id"] == "VDD_3V3" for d in con["voltage_domains"])
    assert any(r["differential_pair"] for r in con["routing"])


def test_write_requirements_artifacts_creates_missing_dir(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "out"
    paths = write_requirements_artifacts("rp2040 usb 5v", target)
    assert Path(paths["requirements"]).exists()
    assert Path(paths["constraints"]).exists()


def test_requirements_coverage_traces_and_flags_gaps() -> None:
    cov = requirements_coverage(parse_requirements("esp32 usb-c li-ion 3.3v i2c can 0.5a"))
    covered = {row["aspect"] for row in cov["covered"]}
    uncovered = {row["aspect"] for row in cov["uncovered"]}
    assert "rails_v" in covered
    assert "usb" in covered
    assert "interface:i2c" in covered
    # Stated-but-unmapped requirements are honestly flagged, not silently passed.
    assert "battery" in uncovered
    assert "max_current_a" in uncovered
    assert "interface:can" in uncovered
    assert cov["fully_covered"] is False


def test_requirements_coverage_fully_covered_when_no_gaps() -> None:
    cov = requirements_coverage(parse_requirements("3.3v i2c sensor"))
    assert cov["uncovered"] == []
    assert cov["fully_covered"] is True


def test_requirements_assumptions_registers_unstated_facts() -> None:
    fields = {a["field"] for a in requirements_assumptions(parse_requirements("a simple LED blinker"))}
    # Nothing stated -> rail, current, and MCU are all unspecified assumptions.
    assert {"rails_v", "max_current_a", "mcu"} <= fields


def test_requirements_assumptions_minimal_for_complete_intent() -> None:
    # A stated rail + current + MCU removes those assumptions; no battery/usb-c here.
    assumptions = requirements_assumptions(parse_requirements("esp32 3.3v 0.5a i2c sensor"))
    assert assumptions == []


def test_freeze_is_stable_and_ignores_prose() -> None:
    # Same extracted contract via different wording -> same freeze hash.
    a = freeze_requirements(parse_requirements("esp32 3.3v i2c sensor"))
    b = freeze_requirements(parse_requirements("an ESP32 board with a 3.3V rail and an I2C sensor"))
    assert a["hash"] == b["hash"]
    assert "raw_intent" not in a["frozen"]
    assert a["frozen"]["rails_v"] == [3.3]


def test_freeze_hash_changes_on_real_requirement_change() -> None:
    base = freeze_requirements(parse_requirements("esp32 3.3v i2c sensor"))
    changed = freeze_requirements(parse_requirements("esp32 3.3v 5v i2c sensor"))
    assert base["hash"] != changed["hash"]


def test_diff_requirements_reports_changed_fields() -> None:
    old = parse_requirements("esp32 3.3v i2c sensor")
    new = parse_requirements("esp32 3.3v 5v i2c sensor")
    diff = diff_requirements(old, new)
    assert diff["unchanged"] is False
    rails = next(c for c in diff["changed"] if c["field"] == "rails_v")
    assert rails["from"] == [3.3]
    assert rails["to"] == [3.3, 5.0]
    assert diff["from_hash"] == freeze_requirements(old)["hash"]
    assert diff["to_hash"] == freeze_requirements(new)["hash"]


def test_diff_requirements_unchanged_for_equivalent_intent() -> None:
    diff = diff_requirements(
        parse_requirements("rp2040 usb 5v"),
        parse_requirements("an RP2040 board, USB, 5V"),
    )
    assert diff["changed"] == []
    assert diff["unchanged"] is True
    assert diff["from_hash"] == diff["to_hash"]


def test_review_assumptions_gate_blocks_until_all_approved() -> None:
    req = parse_requirements("a simple LED blinker")  # rails_v, max_current_a, mcu unstated
    review = review_assumptions(req)
    assert review["approved"] is False
    pending = {p["field"] for p in review["pending"]}
    assert {"rails_v", "max_current_a", "mcu"} <= pending
    assert review["reviewed"] == []
    # The gate is bound to the freeze hash of this requirements version.
    assert review["freeze_hash"] == freeze_requirements(req)["hash"]


def test_review_assumptions_partial_then_full_approval() -> None:
    req = parse_requirements("a simple LED blinker")
    partial = review_assumptions(req, {"rails_v": "3.3V"})
    assert partial["approved"] is False
    approved_fields = {r["field"] for r in partial["reviewed"]}
    assert approved_fields == {"rails_v"}
    assert partial["reviewed"][0]["decision"] == "3.3V"

    full = review_assumptions(req, {"rails_v": "3.3V", "max_current_a": "0.2A", "mcu": "atmega328p"})
    assert full["approved"] is True
    assert full["pending"] == []


def test_review_assumptions_approved_when_nothing_to_assume() -> None:
    # A fully-specified intent has no open assumptions -> gate is already approved.
    review = review_assumptions(parse_requirements("esp32 3.3v 0.5a i2c sensor"))
    assert review["approved"] is True
    assert review["pending"] == []


def test_classify_risk_battery_and_wireless() -> None:
    risk = classify_risk(parse_requirements("esp32 ble li-ion sensor node, 3.3v"))
    assert set(risk["risk_classes"]) == {"battery", "wireless"}
    wireless = next(c for c in risk["classifications"] if c["class"] == "wireless")
    assert "ble" in wireless["evidence"]


def test_classify_risk_high_voltage_from_rail_and_mains() -> None:
    # A >=60V rail is hazardous voltage even without the word "mains".
    by_rail = classify_risk(parse_requirements("48v to 230v boost stage"))
    assert "high_voltage" in by_rail["risk_classes"]
    hv = next(c for c in by_rail["classifications"] if c["class"] == "high_voltage")
    assert "230V rail" in hv["evidence"]
    # And the mains token triggers it independent of any extracted rail.
    by_token = classify_risk(parse_requirements("offline smps controller board"))
    assert "high_voltage" in by_token["risk_classes"]


def test_classify_risk_safety_critical_domain() -> None:
    risk = classify_risk(parse_requirements("automotive ECU, ISO 26262 ASIL-B, 12v"))
    assert "safety_critical" in risk["risk_classes"]
    sc = next(c for c in risk["classifications"] if c["class"] == "safety_critical")
    assert "automotive" in sc["evidence"]


def test_classify_risk_infers_nothing_for_low_risk_intent() -> None:
    # A 3.3V wired LED blinker is none of the risk classes.
    risk = classify_risk(parse_requirements("a simple 3.3v LED blinker on i2c"))
    assert risk["risk_classes"] == []
    assert risk["classifications"] == []


def test_extract_temperature_range() -> None:
    assert parse_requirements("industrial sensor, -40 to 85C").temp_range_c == [-40.0, 85.0]
    assert parse_requirements("0-70°C commercial range").temp_range_c == [0.0, 70.0]
    # A voltage range must NOT be misread as a temperature.
    assert parse_requirements("48v to 230v boost stage").temp_range_c is None


def test_extract_ingress_cost_dimensions_regulatory() -> None:
    req = parse_requirements("IP67 outdoor node, 50x30mm, under $8, CE marked and FCC, RoHS")
    assert req.ingress_rating == "IP67"
    assert req.dimensions_mm == [50.0, 30.0]
    assert req.cost_target_usd == 8.0
    assert req.regulatory == ["CE", "FCC", "RoHS"]


def test_cost_target_takes_tightest_amount() -> None:
    # Multiple amounts -> the tightest (minimum) target is kept.
    assert parse_requirements("BOM under $12, stretch goal $7 per board").cost_target_usd == 7.0


def test_regulatory_avoids_ambiguous_bare_words() -> None:
    # Bare "reach" (a common verb) must not be read as the REACH regulation.
    assert parse_requirements("cables that reach across the board").regulatory == []
    assert parse_requirements("REACH SVHC compliance required").regulatory == ["REACH"]


def test_breadth_fields_default_empty_and_serialize() -> None:
    req = parse_requirements("a simple LED blinker")
    assert req.temp_range_c is None
    assert req.ingress_rating is None
    assert req.dimensions_mm is None
    assert req.cost_target_usd is None
    assert req.regulatory == []
    data = req.to_dict()
    assert data["regulatory"] == []
    assert "temp_range_c" in data


def test_conflicts_usb_c_current_over_budget() -> None:
    conflicts = requirements_conflicts(parse_requirements("usb-c powered board, 5v 4a"))
    ids = {c["conflict"] for c in conflicts}
    assert "usb_c_current_over_budget" in ids
    # At or below the 3A non-PD ceiling there is no conflict.
    assert requirements_conflicts(parse_requirements("usb-c powered board, 5v 2a")) == []


def test_conflicts_battery_vs_high_voltage() -> None:
    conflicts = requirements_conflicts(parse_requirements("li-ion handheld with a 100v rail"))
    assert "battery_vs_high_voltage" in {c["conflict"] for c in conflicts}


def test_conflicts_battery_vs_subzero_temperature() -> None:
    conflicts = requirements_conflicts(parse_requirements("li-ion outdoor logger, -20 to 60C"))
    conflict = next(c for c in conflicts if c["conflict"] == "battery_vs_subzero_temperature")
    assert "battery" in conflict["between"]
    # A battery design rated to a non-negative low temp has no charging conflict.
    assert requirements_conflicts(parse_requirements("li-ion logger, 0 to 60C")) == []


def test_conflicts_none_for_consistent_intent() -> None:
    assert requirements_conflicts(parse_requirements("esp32 3.3v 0.2a i2c sensor")) == []


def test_requirements_coverage_report_traces_design_checks_and_exports() -> None:
    from zaptrace.core.models import Component, Design, DesignMeta, Net, NetType

    req = parse_requirements("esp32 usb-c 3.3v i2c sensor")
    design = Design(
        meta=DesignMeta(name="CoverageFixture"),
        components={
            "U1": Component(id="U1", ref="U1", type="mcu", value="ESP32-C3", footprint="QFN", voltage_supply="3.3V"),
            "J1": Component(id="J1", ref="J1", type="connector", value="USB-C", footprint="USB_C"),
        },
        nets={
            "VDD_3V3": Net(id="VDD_3V3", name="VDD_3V3", type=NetType.POWER),
            "USB_D_P": Net(id="USB_D_P", name="USB_D+"),
            "SDA": Net(id="SDA", name="I2C_SDA"),
        },
    )
    report = requirements_coverage_report(
        req,
        design=design,
        checks=[type("Check", (), {"name": "erc", "category": "erc", "description": "electrical rules"})()],
        exports=["design.yaml"],
    )

    assert report["schema_version"] == "1.0"
    assert {row["id"] for row in report["requirements"]} >= {"REQ-POWER-RAILS", "REQ-USB-C", "REQ-IFACE-I2C"}
    assert any(row["kind"] == "component" and row["id"] == "U1" for row in report["traceability"])
    assert any(row["kind"] == "net" and row["id"] == "SDA" and row["requirement_ids"] for row in report["traceability"])
    assert any(row["kind"] == "export" and row["id"] == "design.yaml" for row in report["traceability"])
    assert isinstance(report["untraced_artifacts"], list)


def test_requirements_coverage_report_reports_untraced_artifacts() -> None:
    from zaptrace.core.models import Component, Design, DesignMeta

    req = parse_requirements("3.3v sensor")
    design = Design(
        meta=DesignMeta(name="CoverageGap"),
        components={"X1": Component(id="X1", ref="X1", type="mystery", value="unknown", footprint="unknown")},
    )
    report = requirements_coverage_report(req, design=design)

    assert report["fully_traced"] is False
    assert {row["id"] for row in report["untraced_artifacts"]} == {"X1"}


def test_requirements_assumption_report_includes_risk_and_confirmation_state() -> None:
    report = requirements_assumption_report(parse_requirements("usb-c sensor"))

    assert report["schema_version"] == "1.0"
    assert report["approved"] is False
    fields = {item["field"]: item for item in report["assumptions"]}
    assert fields["rails_v"]["risk"] == "high"
    assert fields["rails_v"]["requires_confirmation"] is True
    assert fields["rails_v"]["confirmed"] is False
    assert report["unconfirmed_high_risk_count"] >= 1


def test_requirements_assumption_report_marks_approved_assumptions_confirmed() -> None:
    req = parse_requirements("a simple LED blinker")
    report = requirements_assumption_report(req, {"rails_v": "3.3V", "max_current_a": "0.1A", "mcu": "attiny"})

    assert report["approved"] is True
    assert report["unconfirmed_high_risk"] == []
    assert all(item["confirmed"] for item in report["assumptions"])
