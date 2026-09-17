from __future__ import annotations

from zaptrace.evidence.physical import (
    MeasurementEvidence,
    PhysicalUnitRegistration,
    PhysicalVerificationRecord,
    TestCondition,
    TestEquipmentRecord,
    TestResultStatus,
)


def test_physical_verification_record_hash_computation() -> None:
    unit = PhysicalUnitRegistration(
        unit_serial_number="BOARD-001-A",
        pcb_batch_id="LOT-2026-001",
        fab_house="JLCPCB",
        assembly_house="JLCPCB",
        fab_date="2026-09-01",
        assembly_date="2026-09-05",
        target_design_sha256="a" * 64,
    )
    equipment = TestEquipmentRecord(
        equipment_id="SCOPE-01",
        equipment_type="Oscilloscope",
        manufacturer="Keysight",
        model_number="DSOX1204G",
        serial_number="MY12345678",
        calibration_date="2026-01-15",
    )
    conditions = TestCondition(
        ambient_temperature_c=25.0,
        relative_humidity_pct=45.0,
        input_voltage_v=5.0,
        load_current_a=0.25,
    )
    measurement = MeasurementEvidence(
        parameter_name="V3V3_RAIL_VOLTAGE",
        test_point_id="TP1",
        expected_value=3.30,
        measured_value=3.31,
        unit="V",
        tolerance_min=3.20,
        tolerance_max=3.40,
        status=TestResultStatus.PASS,
        raw_artifact_sha256="b" * 64,
    )
    record = PhysicalVerificationRecord(
        unit=unit,
        operator_id="ENG-101",
        equipment=[equipment],
        conditions=conditions,
        measurements=[measurement],
        overall_status=TestResultStatus.PASS,
        proof_pack_sha256="c" * 64,
    )

    digest = record.calculate_evidence_hash()
    assert isinstance(digest, str)
    assert len(digest) == 64
    assert record.unit.unit_serial_number == "BOARD-001-A"
    assert record.measurements[0].status == TestResultStatus.PASS
