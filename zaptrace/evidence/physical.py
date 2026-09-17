"""Pydantic schemas and tooling for physical hardware validation evidence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TestResultStatus(StrEnum):
    __test__ = False
    PASS = "pass"
    FAIL = "fail"
    NOT_TESTED = "not_tested"
    WARNING = "warning"


class PhysicalUnitRegistration(BaseModel):
    """Registration record for a physical fabricated/assembled board unit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_serial_number: str = Field(..., description="Unique hardware unit serial number")
    pcb_batch_id: str = Field(..., description="PCB fabrication lot/batch identifier")
    fab_house: str = Field(..., description="PCB manufacturer name")
    assembly_house: str = Field(..., description="PCBA assembly provider name")
    fab_date: str = Field(..., description="ISO-8601 date of PCB fabrication")
    assembly_date: str = Field(..., description="ISO-8601 date of PCBA assembly")
    target_design_sha256: str = Field(..., description="SHA-256 hash of design state frozen for fab")


class TestEquipmentRecord(BaseModel):
    """Metadata for test equipment used in physical measurements."""

    __test__ = False
    model_config = ConfigDict(extra="forbid", frozen=True)

    equipment_id: str = Field(..., description="Internal asset tag or identifier")
    equipment_type: str = Field(..., description="Type (e.g. Oscilloscope, DMM, Thermal Camera)")
    manufacturer: str = Field(..., description="Equipment manufacturer")
    model_number: str = Field(..., description="Equipment model")
    serial_number: str = Field(..., description="Equipment serial number")
    calibration_date: str = Field(..., description="ISO-8601 date of last calibration")
    calibration_status: str = Field(default="calibrated", description="Calibration status")


class TestCondition(BaseModel):
    """Environmental and electrical test setup parameters."""

    __test__ = False
    model_config = ConfigDict(extra="forbid", frozen=True)

    ambient_temperature_c: float = Field(default=25.0, description="Ambient temperature in degrees C")
    relative_humidity_pct: float = Field(default=50.0, description="Relative humidity percentage")
    input_voltage_v: float = Field(..., description="Nominal supply voltage applied during test")
    load_current_a: float = Field(default=0.0, description="Load current drawn during test")


class MeasurementEvidence(BaseModel):
    """Individual hardware measurement result with traceability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_name: str = Field(..., description="Name of tested electrical/physical parameter")
    test_point_id: str = Field(..., description="Schematic/PCB test point reference")
    expected_value: float = Field(..., description="Nominal/expected parameter value")
    measured_value: float = Field(..., description="Actual measured physical value")
    unit: str = Field(..., description="Measurement unit (e.g. V, A, degC, Hz)")
    tolerance_min: float = Field(..., description="Minimum acceptable threshold")
    tolerance_max: float = Field(..., description="Maximum acceptable threshold")
    status: TestResultStatus = Field(..., description="Evaluation result status")
    raw_artifact_sha256: str | None = Field(default=None, description="SHA-256 digest of raw waveform/log file")


class PhysicalVerificationRecord(BaseModel):
    """Complete physical evidence record for a hardware test session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    unit: PhysicalUnitRegistration = Field(..., description="Physical board unit under test")
    operator_id: str = Field(..., description="Identified technician or engineer operator")
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(), description="ISO-8601 test timestamp")
    equipment: list[TestEquipmentRecord] = Field(default_factory=list, description="Test equipment utilized")
    conditions: TestCondition = Field(..., description="Test environmental/electrical conditions")
    measurements: list[MeasurementEvidence] = Field(default_factory=list, description="Measured parameter results")
    overall_status: TestResultStatus = Field(..., description="Summary status across all mandatory tests")
    proof_pack_sha256: str | None = Field(default=None, description="SHA-256 hash of associated Proof Pack")

    def calculate_evidence_hash(self) -> str:
        """Compute deterministic canonical SHA-256 hash of the evidence record."""
        raw = self.model_dump_json(by_alias=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
