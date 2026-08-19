"""Board generation intent schema for bounded generated KiCad projects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from zaptrace.benchmark.families import get_board_family

_NOT_FABRICATION_READY = "not fabrication-ready"


class RequirementRef(BaseModel):
    """Traceable requirement reference consumed by board generation."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="Stable requirement identifier")
    text: str = Field(min_length=1, description="Human-readable requirement text")
    source: str = Field(default="user", description="Requirement source, e.g. user, benchmark, imported-contract")
    release_blocking: bool = Field(default=True, description="Whether missing evidence should block release/sign-off")


class PowerConstraint(BaseModel):
    """Power constraint declared before Design IR compilation."""

    model_config = ConfigDict(extra="forbid")

    net_name: str = Field(min_length=1, description="Power net or rail name, e.g. VBUS or VDD_3V3")
    voltage_v: float | None = Field(default=None, gt=0, description="Nominal voltage in volts when known")
    max_current_a: float | None = Field(default=None, gt=0, description="Maximum expected current draw in amperes")
    source: str = Field(default="intent", description="Constraint source")
    release_blocking: bool = Field(default=True, description="Whether missing power evidence blocks sign-off")


class InterfaceConstraint(BaseModel):
    """Interface constraint declared before Design IR compilation."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Interface name, e.g. usb, i2c, can, rs485")
    role: str = Field(default="unspecified", description="Interface role such as device, host, sensor-bus, debug")
    nets: list[str] = Field(default_factory=list, description="Expected net names associated with the interface")
    controlled_impedance: bool = Field(default=False, description="Whether impedance/return-path evidence is expected")
    release_blocking: bool = Field(default=True, description="Whether missing interface evidence blocks sign-off")

    @field_validator("nets")
    @classmethod
    def _nets_must_be_unique(cls, nets: list[str]) -> list[str]:
        if len(nets) != len(set(nets)):
            raise ValueError("interface nets must be unique")
        return nets


class ArtifactPolicy(BaseModel):
    """Generated artifact policy and fabrication-claim guard."""

    model_config = ConfigDict(extra="forbid")

    generate_kicad_project: bool = Field(default=True, description="Generate KiCad project artifacts")
    generate_proof_pack: bool = Field(default=True, description="Generate proof-pack evidence")
    generate_review_bundle: bool = Field(default=True, description="Generate Review Studio handoff artifacts")
    generate_manufacturing_exports: bool = Field(
        default=True, description="Generate manufacturing export manifest/bundle"
    )
    fabrication_claim_allowed: bool = Field(default=False, description="Must remain false for pre-1.0 generated boards")

    @model_validator(mode="after")
    def _fabrication_claims_are_blocked(self) -> ArtifactPolicy:
        if self.fabrication_claim_allowed:
            raise ValueError("board generation intents may not allow fabrication-ready claims")
        return self


class EvidenceExpectation(BaseModel):
    """Evidence categories expected from the generated board workflow."""

    model_config = ConfigDict(extra="forbid")

    requirements_coverage: bool = True
    kicad_project_presence: bool = True
    kicad_oracle: bool = True
    proof_pack: bool = True
    fixture_integrity: bool = True
    manufacturing_export_manifest: bool = True
    review_bundle: bool = True
    autonomous_status_allowed: list[str] = Field(default_factory=lambda: ["human-review-required", "autonomous-pass"])

    @field_validator("autonomous_status_allowed")
    @classmethod
    def _allowed_statuses_must_be_non_empty(cls, statuses: list[str]) -> list[str]:
        if not statuses:
            raise ValueError("at least one autonomous status must be allowed")
        return statuses


class BoardGenerationIntent(BaseModel):
    """Machine-readable intent contract for generating a reviewable board project."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = Field(default="1.0")
    family_id: str = Field(min_length=1, description="Supported benchmark board family ID")
    design_name: str = Field(min_length=1, description="Stable generated design name")
    description: str = Field(default="", description="Human-readable design summary")
    requirements: list[RequirementRef] = Field(
        min_length=1, description="Traceable requirements consumed by generation"
    )
    power: list[PowerConstraint] = Field(default_factory=list, description="Power rails/sources expected by generation")
    interfaces: list[InterfaceConstraint] = Field(default_factory=list, description="Interfaces expected by generation")
    artifact_policy: ArtifactPolicy = Field(default_factory=ArtifactPolicy)
    evidence: EvidenceExpectation = Field(default_factory=EvidenceExpectation)
    target_output_dir: str = Field(default="generated", description="Relative output directory for generated artifacts")
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "generated board project is for engineering review only",
            _NOT_FABRICATION_READY,
            "not manufacturer-approved",
            "not production-ready",
        ],
        min_length=1,
        description="Explicit non-claims displayed with generated artifacts",
    )

    @field_validator("family_id")
    @classmethod
    def _family_must_be_supported(cls, family_id: str) -> str:
        try:
            get_board_family(family_id)
        except ValueError as exc:
            raise ValueError(f"unknown board family: {family_id}") from exc
        return family_id

    @field_validator("target_output_dir")
    @classmethod
    def _target_output_dir_must_be_relative(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("target_output_dir must be a safe relative path")
        return value

    @field_validator("non_claims")
    @classmethod
    def _non_claims_must_block_fabrication_ready_language(cls, claims: list[str]) -> list[str]:
        joined = " ".join(claims).lower()
        if _NOT_FABRICATION_READY not in joined:
            raise ValueError(f"non_claims must include '{_NOT_FABRICATION_READY}'")
        return claims

    @model_validator(mode="after")
    def _require_traceable_generation_inputs(self) -> BoardGenerationIntent:
        if not any(req.release_blocking for req in self.requirements):
            raise ValueError("at least one release-blocking requirement is required")
        if self.artifact_policy.generate_kicad_project and not self.evidence.kicad_project_presence:
            raise ValueError("kicad_project_presence evidence is required when KiCad project generation is enabled")
        return self

    def family_title(self) -> str:
        """Return the built-in board-family title."""
        return get_board_family(self.family_id).title

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return self.model_dump(mode="json")


def validate_board_generation_intent(data: dict[str, Any]) -> BoardGenerationIntent:
    """Validate a mapping as a board generation intent."""
    return BoardGenerationIntent.model_validate(data)


def load_board_generation_intent(path: str | Path) -> BoardGenerationIntent:
    """Load a board generation intent from JSON."""
    return validate_board_generation_intent(json.loads(Path(path).read_text(encoding="utf-8")))


def board_generation_intent_json(intent: BoardGenerationIntent) -> str:
    """Serialize a board generation intent as stable JSON."""
    return json.dumps(intent.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def minimal_board_generation_intent_example() -> dict[str, Any]:
    """Return a minimal ESP32 USB sensor intent example."""
    return {
        "schema_version": "1.0",
        "family_id": "esp32_usb_sensor",
        "design_name": "esp32_usb_sensor_generated_v1",
        "description": "Reviewable ESP32-C3 USB-C I2C sensor board generation intent.",
        "requirements": [
            {
                "id": "REQ-USBC-POWER",
                "text": "Provide USB-C 5 V input and a 3.3 V logic rail for ESP32 and sensor loads.",
                "source": "benchmark",
                "release_blocking": True,
            },
            {
                "id": "REQ-I2C-SENSOR",
                "text": "Connect an I2C temperature sensor with pull-up evidence.",
                "source": "benchmark",
                "release_blocking": True,
            },
        ],
        "power": [
            {"net_name": "VBUS", "voltage_v": 5.0, "max_current_a": 0.5, "source": "benchmark"},
            {"net_name": "VDD_3V3", "voltage_v": 3.3, "max_current_a": 0.25, "source": "benchmark"},
        ],
        "interfaces": [
            {"name": "usb", "role": "device", "nets": ["USB_D_P", "USB_D_N"], "controlled_impedance": True},
            {"name": "i2c", "role": "sensor-bus", "nets": ["I2C_SDA", "I2C_SCL"]},
        ],
        "artifact_policy": ArtifactPolicy().model_dump(mode="json"),
        "evidence": EvidenceExpectation().model_dump(mode="json"),
        "target_output_dir": "generated/esp32_usb_sensor",
        "non_claims": [
            "generated board project is for engineering review only",
            _NOT_FABRICATION_READY,
            "not manufacturer-approved",
            "not production-ready",
        ],
    }
