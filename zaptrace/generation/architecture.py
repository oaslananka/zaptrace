"""Requirements-to-architecture compiler for bounded electronics intents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from zaptrace.generation.intent import BoardGenerationIntent

_NOT_FABRICATION_READY = "not fabrication-ready"


class ArchitectureCompileStatus(StrEnum):
    """Status emitted by the requirements-to-architecture compiler."""

    READY = "ready"
    NEEDS_CLARIFICATION = "needs-clarification"
    UNSAFE_BLOCKED = "unsafe-blocked"


class RequirementCategory(StrEnum):
    """Requirement categories used by the architecture artifact."""

    FUNCTIONAL = "functional"
    POWER = "power"
    INTERFACE = "interface"
    MECHANICAL = "mechanical"
    MANUFACTURING = "manufacturing"
    SAFETY = "safety"


class ArchitectureRequirement(BaseModel):
    """Traceable requirement derived from an electronics intent."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    category: RequirementCategory
    source: str = Field(default="user-intent")
    release_blocking: bool = True


class ArchitectureAssumption(BaseModel):
    """Assumption that must be carried into proof packs and review."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high"] = "medium"
    requires_confirmation: bool = True
    related_requirement_ids: list[str] = Field(default_factory=list)


class ArchitectureConflict(BaseModel):
    """Explicit contradiction that prevents a ready architecture decision."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    requirement_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)
    resolution_required: str = Field(min_length=1)


class ArchitectureSubsystem(BaseModel):
    """Planned design subsystem."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["mcu", "power", "sensor", "interface", "protection", "mechanical", "generic"] = "generic"
    requirement_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)


class PowerRailPlan(BaseModel):
    """Planned rail or supply domain."""

    model_config = ConfigDict(extra="forbid")

    net_name: str = Field(min_length=1)
    nominal_voltage_v: float | None = Field(default=None, gt=0)
    max_current_a: float | None = Field(default=None, gt=0)
    source: str = Field(default="architecture-compiler")
    load_subsystems: list[str] = Field(default_factory=list)
    margin_target_pct: float = Field(default=20.0, ge=0)
    requirement_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)


class InterfacePlan(BaseModel):
    """Planned interface and associated nets."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    protocol: str = Field(min_length=1)
    role: str = Field(default="unspecified")
    nets: list[str] = Field(default_factory=list)
    controlled_impedance: bool = False
    requirement_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)

    @field_validator("nets")
    @classmethod
    def _nets_must_be_unique(cls, nets: list[str]) -> list[str]:
        if len(nets) != len(set(nets)):
            raise ValueError("interface nets must be unique")
        return nets


class ArchitectureConstraint(BaseModel):
    """Machine-checkable constraint derived from the architecture."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    domain: Literal["erc", "drc", "dfm", "layout", "simulation", "supply-chain", "review"]
    text: str = Field(min_length=1)
    evidence_required: bool = True
    release_blocking: bool = True
    requirement_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)


class ArchitectureRisk(BaseModel):
    """Risk-register entry for architecture review."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    description: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    mitigation: str = Field(min_length=1)
    evidence_required: bool = True
    human_review_required: bool = True
    requirement_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)


type AcceptanceMethod = Literal["erc", "drc", "simulation", "kicad-oracle", "dfm", "human-review"]


class ArchitectureAcceptanceTest(BaseModel):
    """Acceptance test planned from requirements."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    requirement_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)
    method: AcceptanceMethod
    expected_result: str = Field(min_length=1)


class ElectronicsArchitectureArtifact(BaseModel):
    """Structured architecture artifact produced before schematic and PCB synthesis."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    status: ArchitectureCompileStatus
    design_name: str = Field(min_length=1)
    source_intent: str = Field(min_length=1)
    requirements: list[ArchitectureRequirement] = Field(min_length=1)
    assumptions: list[ArchitectureAssumption] = Field(default_factory=list)
    subsystems: list[ArchitectureSubsystem] = Field(default_factory=list)
    power_tree: list[PowerRailPlan] = Field(default_factory=list)
    interfaces: list[InterfacePlan] = Field(default_factory=list)
    constraints: list[ArchitectureConstraint] = Field(default_factory=list)
    risks: list[ArchitectureRisk] = Field(default_factory=list)
    acceptance_tests: list[ArchitectureAcceptanceTest] = Field(default_factory=list)
    conflicts: list[ArchitectureConflict] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    human_review_required: bool = True
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "architecture artifact is for engineering review only",
            _NOT_FABRICATION_READY,
            "not manufacturer-approved",
            "not production-ready",
        ],
        min_length=1,
    )

    @field_validator("non_claims")
    @classmethod
    def _must_keep_fabrication_non_claim(cls, claims: list[str]) -> list[str]:
        joined = " ".join(claims).lower()
        if _NOT_FABRICATION_READY not in joined:
            raise ValueError(f"non_claims must include '{_NOT_FABRICATION_READY}'")
        return claims

    @model_validator(mode="after")
    def _validate_gate_semantics(self) -> ElectronicsArchitectureArtifact:
        self._validate_status_requirements()
        self._validate_reference_integrity()
        if self.status == ArchitectureCompileStatus.READY:
            self._validate_ready_gate_semantics()
        return self

    def _validate_status_requirements(self) -> None:
        if not any(req.release_blocking for req in self.requirements):
            raise ValueError("at least one release-blocking requirement is required")
        if self.status != ArchitectureCompileStatus.READY and not self.blocking_reasons:
            raise ValueError("non-ready architecture artifacts must include blocking_reasons")

    def _validate_reference_integrity(self) -> None:
        known_requirement_ids = self.requirement_ids
        known_assumption_ids = {item.id for item in self.assumptions}
        for assumption in self.assumptions:
            self._validate_requirement_references(
                f"assumption {assumption.id}", assumption.related_requirement_ids, known_requirement_ids
            )
        for kind, element_id, requirement_ids, assumption_ids in self._trace_references():
            label = f"{kind} {element_id}"
            self._validate_requirement_references(label, requirement_ids, known_requirement_ids)
            self._validate_assumption_references(label, assumption_ids, known_assumption_ids)
            if self.status == ArchitectureCompileStatus.READY and not requirement_ids and not assumption_ids:
                raise ValueError(f"{label} must include at least one trace reference")
        for conflict in self.conflicts:
            label = f"conflict {conflict.id}"
            self._validate_requirement_references(label, conflict.requirement_ids, known_requirement_ids)
            self._validate_assumption_references(label, conflict.assumption_ids, known_assumption_ids)

    def _validate_ready_gate_semantics(self) -> None:
        if self.conflicts:
            raise ValueError(f"ready architecture contains unresolved conflict {self.conflicts[0].id}")
        unconfirmed = next((item.id for item in self.assumptions if item.requires_confirmation), None)
        if unconfirmed is not None:
            raise ValueError(f"ready architecture contains unconfirmed assumption {unconfirmed}")
        coverage = self.requirement_coverage_matrix()
        uncovered = next(
            (req_id for req_id in sorted(self.release_blocking_requirement_ids) if not coverage.get(req_id)),
            None,
        )
        if uncovered is not None:
            raise ValueError(f"uncovered release-blocking requirement {uncovered}")

    @staticmethod
    def _validate_requirement_references(label: str, references: list[str], known: set[str]) -> None:
        unknown = next((item for item in references if item not in known), None)
        if unknown is not None:
            raise ValueError(f"{label} references unknown requirement ID {unknown}")

    @staticmethod
    def _validate_assumption_references(label: str, references: list[str], known: set[str]) -> None:
        unknown = next((item for item in references if item not in known), None)
        if unknown is not None:
            raise ValueError(f"{label} references unknown assumption ID {unknown}")

    def _trace_references(self) -> list[tuple[str, str, list[str], list[str]]]:
        rows: list[tuple[str, str, list[str], list[str]]] = []
        rows.extend(("subsystem", item.id, item.requirement_ids, item.assumption_ids) for item in self.subsystems)
        rows.extend(
            ("power rail", item.net_name, item.requirement_ids, item.assumption_ids) for item in self.power_tree
        )
        rows.extend(("interface", item.name, item.requirement_ids, item.assumption_ids) for item in self.interfaces)
        rows.extend(("constraint", item.id, item.requirement_ids, item.assumption_ids) for item in self.constraints)
        rows.extend(("risk", item.id, item.requirement_ids, item.assumption_ids) for item in self.risks)
        rows.extend(
            ("acceptance test", item.id, item.requirement_ids, item.assumption_ids) for item in self.acceptance_tests
        )
        return rows

    @property
    def requirement_ids(self) -> set[str]:
        """Return all declared requirement IDs."""
        return {req.id for req in self.requirements}

    @property
    def release_blocking_requirement_ids(self) -> set[str]:
        """Return release-blocking requirement IDs."""
        return {req.id for req in self.requirements if req.release_blocking}

    def requirement_coverage_matrix(self) -> dict[str, list[str]]:
        """Return artifact classes that reference each requirement ID."""
        matrix: dict[str, list[str]] = {req.id: [] for req in self.requirements}
        for evidence_id, requirement_ids in self._requirement_coverage_references():
            for req_id in requirement_ids:
                matrix.setdefault(req_id, []).append(evidence_id)
        return {key: sorted(set(values)) for key, values in sorted(matrix.items())}

    def _requirement_coverage_references(self) -> list[tuple[str, list[str]]]:
        rows: list[tuple[str, list[str]]] = []
        rows.extend((f"assumption:{item.id}", item.related_requirement_ids) for item in self.assumptions)
        rows.extend((f"subsystem:{item.id}", item.requirement_ids) for item in self.subsystems)
        rows.extend((f"power:{item.net_name}", item.requirement_ids) for item in self.power_tree)
        rows.extend((f"interface:{item.name}", item.requirement_ids) for item in self.interfaces)
        rows.extend((f"constraint:{item.id}", item.requirement_ids) for item in self.constraints)
        rows.extend((f"risk:{item.id}", item.requirement_ids) for item in self.risks)
        rows.extend((f"test:{item.id}", item.requirement_ids) for item in self.acceptance_tests)
        return rows

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return self.model_dump(mode="json")


_KEYWORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _words(intent: str) -> set[str]:
    return {word.lower() for word in _KEYWORD_RE.findall(intent)}


def _slug(text: str) -> str:
    words = _KEYWORD_RE.findall(text.lower())[:8]
    return "_".join(words) or "generated_architecture"


def _has_any(words: set[str], *candidates: str) -> bool:
    return any(candidate in words for candidate in candidates)


def _requirement(
    index: int,
    category: RequirementCategory,
    text: str,
    *,
    release_blocking: bool = True,
) -> ArchitectureRequirement:
    return ArchitectureRequirement(
        id=f"REQ-{category.value.upper()}-{index:03d}",
        text=text,
        category=category,
        release_blocking=release_blocking,
    )


def _acceptance_test(
    index: int,
    req_id: str,
    method: AcceptanceMethod,
    expected: str,
) -> ArchitectureAcceptanceTest:
    return ArchitectureAcceptanceTest(
        id=f"AT-{index:03d}",
        requirement_ids=[req_id],
        method=method,
        expected_result=expected,
    )


def _base_non_claims() -> list[str]:
    return [
        "architecture artifact is for engineering review only",
        _NOT_FABRICATION_READY,
        "not manufacturer-approved",
        "not production-ready",
    ]


def _explicit_conflict_artifact(
    normalized: str,
    design_name: str,
    tokens: set[str],
) -> ElectronicsArchitectureArtifact | None:
    lowered = normalized.casefold()
    requirements: list[ArchitectureRequirement] = []
    conflicts: list[ArchitectureConflict] = []

    def add_conflict(
        *,
        code: str,
        category: RequirementCategory,
        required_text: str,
        prohibited_text: str,
        description: str,
        resolution_required: str,
    ) -> None:
        first = _requirement(len(requirements) + 1, category, required_text)
        second = _requirement(len(requirements) + 2, category, prohibited_text)
        requirements.extend([first, second])
        conflicts.append(
            ArchitectureConflict(
                id=f"CONFLICT-{len(conflicts) + 1:03d}",
                code=code,
                description=description,
                requirement_ids=[first.id, second.id],
                resolution_required=resolution_required,
            )
        )

    if _has_any(tokens, "battery", "lipo", "charger") and re.search(r"\b(?:no|without)\s+batter(?:y|ies)\b", lowered):
        add_conflict(
            code="battery-presence-conflict",
            category=RequirementCategory.POWER,
            required_text="Provide battery-powered operation.",
            prohibited_text="Exclude all batteries from the design.",
            description="The intent both requires and prohibits a battery power source.",
            resolution_required="Confirm whether battery operation is required or prohibited.",
        )

    if _has_any(tokens, "wireless", "radio", "lora", "wifi", "bluetooth") and re.search(
        r"\b(?:no|without)\s+(?:wireless|radio)\b", lowered
    ):
        add_conflict(
            code="wireless-presence-conflict",
            category=RequirementCategory.INTERFACE,
            required_text="Provide a wireless or radio interface.",
            prohibited_text="Exclude wireless and radio interfaces.",
            description="The intent both requires and prohibits wireless communication.",
            resolution_required="Confirm whether a wireless interface is required or prohibited.",
        )
    if (
        "usb host" in lowered
        and "usb device" in lowered
        and re.search(r"\b(?:same|single)\s+(?:usb\s+)?connector\b", lowered)
    ):
        add_conflict(
            code="usb-role-conflict",
            category=RequirementCategory.INTERFACE,
            required_text="Use the single USB connector exclusively as a host.",
            prohibited_text="Use the single USB connector exclusively as a device.",
            description="One explicitly single USB connector is assigned mutually exclusive fixed roles.",
            resolution_required="Choose host, device, or an explicitly reviewed dual-role architecture.",
        )
    if re.search(r"\b1(?:\.8)?\s*v\s+only\b", lowered) and re.search(r"\b3(?:\.3)?\s*v\s+only\b", lowered):
        add_conflict(
            code="logic-voltage-conflict",
            category=RequirementCategory.POWER,
            required_text="Use only a 1.8 V logic domain.",
            prohibited_text="Use only a 3.3 V logic domain.",
            description="The same logic architecture is constrained to two exclusive voltage-only requirements.",
            resolution_required="Choose one logic voltage or define separate level-shifted domains.",
        )

    if not conflicts:
        return None
    return ElectronicsArchitectureArtifact(
        status=ArchitectureCompileStatus.NEEDS_CLARIFICATION,
        design_name=design_name,
        source_intent=normalized,
        requirements=requirements,
        conflicts=conflicts,
        blocking_reasons=[f"resolve architecture conflict: {item.code}" for item in conflicts],
        non_claims=_base_non_claims(),
    )


@dataclass
class _ArchitectureDraft:
    requirements: list[ArchitectureRequirement] = field(default_factory=list)
    assumptions: list[ArchitectureAssumption] = field(default_factory=list)
    subsystems: list[ArchitectureSubsystem] = field(default_factory=list)
    power_tree: list[PowerRailPlan] = field(default_factory=list)
    interfaces: list[InterfacePlan] = field(default_factory=list)
    constraints: list[ArchitectureConstraint] = field(default_factory=list)
    risks: list[ArchitectureRisk] = field(default_factory=list)
    acceptance_tests: list[ArchitectureAcceptanceTest] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    req_index: int = 1
    test_index: int = 1


def _populate_detected_features(tokens: set[str], normalized: str, draft: _ArchitectureDraft) -> None:
    """Populate feature-derived architecture elements in stable public order."""
    requirements = draft.requirements
    subsystems = draft.subsystems
    power_tree = draft.power_tree
    interfaces = draft.interfaces
    constraints = draft.constraints
    risks = draft.risks
    acceptance_tests = draft.acceptance_tests
    req_index = draft.req_index
    test_index = draft.test_index

    if _has_any(tokens, "esp32", "stm32", "rp2040", "nrf52", "mcu", "microcontroller"):
        req = _requirement(
            req_index,
            RequirementCategory.FUNCTIONAL,
            "Provide a microcontroller subsystem with reset, boot, programming, and required support circuits.",
        )
        req_index += 1
        requirements.append(req)
        subsystems.append(
            ArchitectureSubsystem(id="SUBSYS-MCU", name="Microcontroller", kind="mcu", requirement_ids=[req.id])
        )
        acceptance_tests.append(
            _acceptance_test(
                test_index, req.id, "erc", "MCU power, reset, boot, and programming nets pass ERC coverage."
            )
        )
        test_index += 1

    if _has_any(tokens, "usb", "usbc") or "usb-c" in normalized.lower():
        req = _requirement(
            req_index,
            RequirementCategory.POWER,
            "Provide USB-C 5 V input with protection and downstream regulation assumptions.",
        )
        req_index += 1
        requirements.append(req)
        subsystems.append(
            ArchitectureSubsystem(
                id="SUBSYS-USB", name="USB-C input and data", kind="interface", requirement_ids=[req.id]
            )
        )
        power_tree.append(
            PowerRailPlan(
                net_name="VBUS",
                nominal_voltage_v=5.0,
                max_current_a=0.5,
                load_subsystems=["SUBSYS-MCU"],
                requirement_ids=[req.id],
            )
        )
        interfaces.append(
            InterfacePlan(
                name="usb",
                protocol="usb2",
                role="device",
                nets=["USB_D_P", "USB_D_N"],
                controlled_impedance=True,
                requirement_ids=[req.id],
            )
        )
        constraints.append(
            ArchitectureConstraint(
                id="CONSTRAINT-USB-001",
                domain="layout",
                text="USB D+/D- require short matched routing, continuous return path, and connector-side ESD review.",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(
                test_index, req.id, "kicad-oracle", "USB nets are present and pass KiCad/ERC parity checks."
            )
        )
        test_index += 1

    if _has_any(tokens, "3v3", "3", "esp32", "sensor", "i2c"):
        req = _requirement(
            req_index, RequirementCategory.POWER, "Provide a 3.3 V logic rail with load margin for digital devices."
        )
        req_index += 1
        requirements.append(req)
        power_tree.append(
            PowerRailPlan(
                net_name="VDD_3V3",
                nominal_voltage_v=3.3,
                max_current_a=0.25,
                load_subsystems=["SUBSYS-MCU", "SUBSYS-SENSOR"],
                requirement_ids=[req.id],
            )
        )
        constraints.append(
            ArchitectureConstraint(
                id="CONSTRAINT-PWR-001",
                domain="simulation",
                text="3.3 V rail margin and startup assumptions require analytical or simulation evidence.",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(
                test_index,
                req.id,
                "simulation",
                "3.3 V rail margin evidence is present or explicitly skipped with human review.",
            )
        )
        test_index += 1

    if _has_any(tokens, "battery", "lipo", "charger"):
        req = _requirement(
            req_index,
            RequirementCategory.POWER,
            "Provide battery input or charging subsystem with current, thermal, and safety review evidence.",
        )
        req_index += 1
        requirements.append(req)
        subsystems.append(
            ArchitectureSubsystem(
                id="SUBSYS-BATTERY", name="Battery and charging", kind="power", requirement_ids=[req.id]
            )
        )
        power_tree.append(
            PowerRailPlan(
                net_name="VBAT",
                nominal_voltage_v=3.7,
                max_current_a=1.0,
                load_subsystems=["SUBSYS-MCU"],
                requirement_ids=[req.id],
            )
        )
        risks.append(
            ArchitectureRisk(
                id="RISK-BATTERY-001",
                domain="power",
                description="Battery charging and protection choices require datasheet-backed safety review.",
                severity="high",
                mitigation="Require charger IC datasheet evidence, protection constraints, and thermal/current review.",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(
                test_index,
                req.id,
                "human-review",
                "Battery safety choices are reviewed with datasheet and layout evidence.",
            )
        )
        test_index += 1

    if _has_any(tokens, "sensor", "temperature", "humidity", "imu"):
        req = _requirement(
            req_index,
            RequirementCategory.FUNCTIONAL,
            "Provide a sensor subsystem with power, decoupling, interface, and placement assumptions.",
        )
        req_index += 1
        requirements.append(req)
        subsystems.append(
            ArchitectureSubsystem(id="SUBSYS-SENSOR", name="Sensor", kind="sensor", requirement_ids=[req.id])
        )
        acceptance_tests.append(
            _acceptance_test(test_index, req.id, "erc", "Sensor power and interface nets are connected and traceable.")
        )
        test_index += 1

    if _has_any(tokens, "i2c"):
        req = _requirement(
            req_index,
            RequirementCategory.INTERFACE,
            "Provide I2C bus with SDA/SCL nets, pull-up evidence, and address-conflict review.",
        )
        req_index += 1
        requirements.append(req)
        interfaces.append(
            InterfacePlan(
                name="i2c", protocol="i2c", role="sensor-bus", nets=["I2C_SDA", "I2C_SCL"], requirement_ids=[req.id]
            )
        )
        constraints.append(
            ArchitectureConstraint(
                id="CONSTRAINT-I2C-001",
                domain="erc",
                text="I2C SDA/SCL require pull-up evidence and address-conflict review.",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(test_index, req.id, "erc", "I2C pull-up and net connectivity evidence is present.")
        )
        test_index += 1

    if _has_any(tokens, "spi"):
        req = _requirement(
            req_index,
            RequirementCategory.INTERFACE,
            "Provide SPI bus with chip-select ownership and signal routing review.",
        )
        req_index += 1
        requirements.append(req)
        interfaces.append(
            InterfacePlan(
                name="spi",
                protocol="spi",
                role="peripheral-bus",
                nets=["SPI_MOSI", "SPI_MISO", "SPI_SCK", "SPI_CS"],
                requirement_ids=[req.id],
            )
        )
        constraints.append(
            ArchitectureConstraint(
                id="CONSTRAINT-SPI-001",
                domain="layout",
                text="SPI nets require length, return-path, and chip-select ownership review.",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(test_index, req.id, "erc", "SPI ownership and net connectivity evidence is present.")
        )
        test_index += 1

    if "rs-485" in normalized.casefold() or _has_any(tokens, "rs485", "modbus"):
        req = _requirement(
            req_index,
            RequirementCategory.INTERFACE,
            "Provide an RS-485 fieldbus interface with transceiver, protection, termination, and direction control.",
        )
        req_index += 1
        requirements.append(req)
        subsystems.append(
            ArchitectureSubsystem(
                id="SUBSYS-RS485",
                name="RS-485 fieldbus",
                kind="interface",
                requirement_ids=[req.id],
            )
        )
        interfaces.append(
            InterfacePlan(
                name="rs485",
                protocol="rs485",
                role="fieldbus",
                nets=["UART_TX", "UART_RX", "RS485_DE", "RS485_A", "RS485_B"],
                requirement_ids=[req.id],
            )
        )
        constraints.append(
            ArchitectureConstraint(
                id="CONSTRAINT-RS485-001",
                domain="layout",
                text="RS-485 A/B routing requires termination, protection, and return-path review.",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(test_index, req.id, "erc", "RS-485 transceiver and direction-control nets are traceable.")
        )
        test_index += 1

    if _has_any(tokens, "can"):
        req = _requirement(
            req_index,
            RequirementCategory.INTERFACE,
            "Provide a CAN bus interface with transceiver, termination, and connector-side protection.",
        )
        req_index += 1
        requirements.append(req)
        subsystems.append(
            ArchitectureSubsystem(id="SUBSYS-CAN", name="CAN fieldbus", kind="interface", requirement_ids=[req.id])
        )
        interfaces.append(
            InterfacePlan(
                name="can",
                protocol="can",
                role="fieldbus",
                nets=["CAN_TX", "CAN_RX", "CAN_H", "CAN_L"],
                requirement_ids=[req.id],
            )
        )
        constraints.append(
            ArchitectureConstraint(
                id="CONSTRAINT-CAN-001",
                domain="layout",
                text="CAN_H/CAN_L require differential routing, termination, and protection review.",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(test_index, req.id, "erc", "CAN transceiver and bus nets are connected and traceable.")
        )
        test_index += 1

    if _has_any(tokens, "storage", "datalogger", "flash", "sd", "microsd"):
        req = _requirement(
            req_index,
            RequirementCategory.FUNCTIONAL,
            "Provide nonvolatile storage with interface ownership, power, and data-integrity review.",
        )
        req_index += 1
        requirements.append(req)
        subsystems.append(
            ArchitectureSubsystem(
                id="SUBSYS-STORAGE",
                name="Nonvolatile storage",
                kind="generic",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(test_index, req.id, "erc", "Storage power and interface ownership are traceable.")
        )
        test_index += 1

    if _has_any(tokens, "lora", "radio", "wireless"):
        req = _requirement(
            req_index,
            RequirementCategory.INTERFACE,
            "Provide a LoRa or radio subsystem with controlled RF path and antenna-interface review.",
        )
        req_index += 1
        requirements.append(req)
        subsystems.append(
            ArchitectureSubsystem(id="SUBSYS-RADIO", name="LoRa radio", kind="interface", requirement_ids=[req.id])
        )
        interfaces.append(
            InterfacePlan(
                name="lora",
                protocol="lora",
                role="radio",
                nets=["RF_ANT"],
                controlled_impedance=True,
                requirement_ids=[req.id],
            )
        )
        constraints.append(
            ArchitectureConstraint(
                id="CONSTRAINT-RF-001",
                domain="layout",
                text="The RF path requires impedance, return-path, keepout, and antenna review.",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(test_index, req.id, "human-review", "RF path and antenna assumptions are reviewed.")
        )
        test_index += 1

    draft.req_index = req_index
    draft.test_index = test_index


def compile_electronics_intent_to_architecture(
    intent: str,
    *,
    design_name: str | None = None,
) -> ElectronicsArchitectureArtifact:
    """Compile natural-language electronics intent into a structured architecture artifact.

    The compiler is intentionally deterministic and conservative. It extracts common
    electronics requirements and emits human-review gates when the prompt is vague,
    unsafe, or outside the bounded first implementation.
    """
    normalized = " ".join(intent.strip().split())
    if not normalized:
        raise ValueError("intent must not be empty")

    tokens = _words(normalized)
    inferred_design_name = design_name or _slug(normalized)
    draft = _ArchitectureDraft()
    requirements = draft.requirements
    assumptions = draft.assumptions
    subsystems = draft.subsystems
    power_tree = draft.power_tree
    interfaces = draft.interfaces
    constraints = draft.constraints
    risks = draft.risks
    acceptance_tests = draft.acceptance_tests
    blocking_reasons = draft.blocking_reasons

    unsafe = _has_any(tokens, "mains", "230v", "220v", "110v", "medical", "automotive", "airbag", "defibrillator")
    if unsafe:
        req = _requirement(
            1,
            RequirementCategory.SAFETY,
            "High-risk or regulated design intent requires qualified engineering review before generation.",
        )
        requirements.append(req)
        risks.append(
            ArchitectureRisk(
                id="RISK-SAFETY-001",
                domain="safety",
                description=(
                    "Intent includes high-risk voltage, regulated, medical, or automotive "
                    "language outside bounded autonomous generation scope."
                ),
                severity="critical",
                mitigation=(
                    "Block autonomous-pass and require a qualified engineer to define safety, "
                    "isolation, compliance, and validation requirements."
                ),
                requirement_ids=[req.id],
            )
        )
        blocking_reasons.append(
            "intent includes high-risk or regulated terms outside bounded autonomous generation scope"
        )
        return ElectronicsArchitectureArtifact(
            status=ArchitectureCompileStatus.UNSAFE_BLOCKED,
            design_name=inferred_design_name,
            source_intent=normalized,
            requirements=requirements,
            risks=risks,
            blocking_reasons=blocking_reasons,
            non_claims=_base_non_claims(),
        )

    conflict_artifact = _explicit_conflict_artifact(normalized, inferred_design_name, tokens)
    if conflict_artifact is not None:
        return conflict_artifact

    feature_count = sum(
        [
            _has_any(tokens, "usb", "usb-c", "usbc"),
            _has_any(tokens, "esp32", "stm32", "rp2040", "nrf52", "mcu", "microcontroller"),
            _has_any(tokens, "sensor", "temperature", "humidity", "imu"),
            _has_any(tokens, "i2c", "spi", "uart", "can", "rs485", "modbus", "lora", "radio", "wireless"),
            _has_any(tokens, "battery", "lipo", "charger"),
            _has_any(tokens, "regulator", "buck", "ldo", "storage", "datalogger", "flash", "microsd"),
        ]
    )
    if feature_count == 0:
        req = _requirement(
            1,
            RequirementCategory.FUNCTIONAL,
            (
                "Clarify the target circuit function, power source, core components, "
                "interfaces, and manufacturing assumptions."
            ),
        )
        requirements.append(req)
        assumptions.append(
            ArchitectureAssumption(
                id="ASM-CLARIFY-001",
                text=(
                    "The prompt does not contain enough electronics-specific information to derive a safe architecture."
                ),
                confidence="low",
                related_requirement_ids=[req.id],
            )
        )
        blocking_reasons.append("intent is too vague to derive electronics architecture")
        return ElectronicsArchitectureArtifact(
            status=ArchitectureCompileStatus.NEEDS_CLARIFICATION,
            design_name=inferred_design_name,
            source_intent=normalized,
            requirements=requirements,
            assumptions=assumptions,
            blocking_reasons=blocking_reasons,
            non_claims=_base_non_claims(),
        )

    _populate_detected_features(tokens, normalized, draft)

    if not power_tree:
        assumptions.append(
            ArchitectureAssumption(
                id="ASM-POWER-001",
                text=(
                    "Power source and voltage rails were not explicit enough; downstream "
                    "generation must request confirmation."
                ),
                confidence="low",
            )
        )
        blocking_reasons.append("power source or voltage rails are underspecified")

    if not interfaces:
        assumptions.append(
            ArchitectureAssumption(
                id="ASM-INTERFACE-001",
                text=(
                    "External communication interfaces were not explicit enough; downstream "
                    "generation must request confirmation."
                ),
                confidence="low",
            )
        )
        blocking_reasons.append("external communication interfaces are underspecified")

    for req in requirements:
        constraints.append(
            ArchitectureConstraint(
                id=f"CONSTRAINT-TRACE-{req.id}",
                domain="review",
                text=(
                    f"Requirement {req.id} must remain traceable through schematic, PCB, "
                    "verification, and proof-pack artifacts."
                ),
                requirement_ids=[req.id],
            )
        )

    risks.append(
        ArchitectureRisk(
            id="RISK-REVIEW-001",
            domain="signoff",
            description="Generated architecture is a candidate plan and not a fabrication approval.",
            severity="medium",
            mitigation=(
                "Require proof-pack evidence and qualified human engineering review before fabrication decisions."
            ),
            requirement_ids=[requirements[0].id],
        )
    )

    status = ArchitectureCompileStatus.NEEDS_CLARIFICATION if blocking_reasons else ArchitectureCompileStatus.READY
    return ElectronicsArchitectureArtifact(
        status=status,
        design_name=inferred_design_name,
        source_intent=normalized,
        requirements=requirements,
        assumptions=assumptions,
        subsystems=subsystems,
        power_tree=power_tree,
        interfaces=interfaces,
        constraints=constraints,
        risks=risks,
        acceptance_tests=acceptance_tests,
        blocking_reasons=blocking_reasons,
        non_claims=_base_non_claims(),
    )


def electronics_architecture_artifact_json(artifact: ElectronicsArchitectureArtifact) -> str:
    """Serialize an architecture artifact as stable JSON."""
    return json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def electronics_architecture_schema_json() -> str:
    """Return the architecture artifact JSON schema."""
    return json.dumps(ElectronicsArchitectureArtifact.model_json_schema(), indent=2, sort_keys=True) + "\n"


def minimal_electronics_architecture_example() -> dict[str, Any]:
    """Return a minimal ready architecture example for fixture tests and docs."""
    artifact = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail",
        design_name="esp32_usb_temperature_sensor_architecture_v1",
    )
    return artifact.model_dump(mode="json")


class ArchitectureIntentBridgeStatus(StrEnum):
    """Status for architecture-to-generation-intent conversion."""

    CONVERTED = "converted"
    NOT_READY = "not-ready"
    UNSUPPORTED_ARCHITECTURE = "unsupported-architecture"


class ArchitectureIntentBridgeReport(BaseModel):
    """Machine-readable report for architecture-to-intent conversion."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    status: ArchitectureIntentBridgeStatus
    architecture_status: ArchitectureCompileStatus
    design_name: str = Field(min_length=1)
    family_id: str | None = None
    requirement_ids: list[str] = Field(default_factory=list)
    power_rails: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    assumptions_carried: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)

    @property
    def converted(self) -> bool:
        """Return whether conversion succeeded."""
        return self.status == ArchitectureIntentBridgeStatus.CONVERTED

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return self.model_dump(mode="json")


def _architecture_tokens(artifact: ElectronicsArchitectureArtifact) -> set[str]:
    haystack = " ".join(
        [
            artifact.source_intent,
            artifact.design_name,
            *(subsystem.name for subsystem in artifact.subsystems),
            *(interface.name for interface in artifact.interfaces),
            *(interface.protocol for interface in artifact.interfaces),
        ]
    )
    return _words(haystack)


def infer_board_generation_family(artifact: ElectronicsArchitectureArtifact) -> str | None:
    """Infer the supported board generation family for an architecture artifact."""
    tokens = _architecture_tokens(artifact)
    protocols = {interface.protocol.lower() for interface in artifact.interfaces}
    names = {interface.name.lower() for interface in artifact.interfaces}
    subsystem_kinds = {subsystem.kind for subsystem in artifact.subsystems}

    has_mcu = "mcu" in subsystem_kinds or _has_any(tokens, "esp32", "mcu", "microcontroller")
    has_sensor = "sensor" in subsystem_kinds or _has_any(tokens, "sensor", "temperature", "humidity", "imu")
    has_usb = bool({"usb", "usb2", "usb-c", "usbc"} & (protocols | names | tokens))
    has_i2c = "i2c" in protocols or "i2c" in names or "i2c" in tokens

    if has_mcu and has_sensor and has_usb and has_i2c:
        return "esp32_usb_sensor"
    return None


def architecture_intent_bridge_report_json(report: ArchitectureIntentBridgeReport) -> str:
    """Serialize an architecture-to-intent bridge report as stable JSON."""
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def _architecture_intent_bridge_report(
    artifact: ElectronicsArchitectureArtifact,
    *,
    status: ArchitectureIntentBridgeStatus,
    family_id: str | None,
    blocking_reasons: list[str] | None = None,
) -> ArchitectureIntentBridgeReport:
    return ArchitectureIntentBridgeReport(
        status=status,
        architecture_status=artifact.status,
        design_name=artifact.design_name,
        family_id=family_id,
        requirement_ids=sorted(artifact.requirement_ids),
        power_rails=[rail.net_name for rail in artifact.power_tree],
        interfaces=[interface.name for interface in artifact.interfaces],
        assumptions_carried=[assumption.id for assumption in artifact.assumptions],
        blocking_reasons=blocking_reasons or [],
    )


def convert_architecture_to_board_generation_intent_report(
    artifact: ElectronicsArchitectureArtifact,
    *,
    family_id: str | None = None,
) -> ArchitectureIntentBridgeReport:
    """Return the bridge report that would accompany architecture conversion."""
    resolved_family_id = family_id or infer_board_generation_family(artifact)
    if artifact.status != ArchitectureCompileStatus.READY:
        return _architecture_intent_bridge_report(
            artifact,
            status=ArchitectureIntentBridgeStatus.NOT_READY,
            family_id=resolved_family_id,
            blocking_reasons=artifact.blocking_reasons or [f"architecture status is {artifact.status.value}"],
        )
    if resolved_family_id is None:
        return _architecture_intent_bridge_report(
            artifact,
            status=ArchitectureIntentBridgeStatus.UNSUPPORTED_ARCHITECTURE,
            family_id=None,
            blocking_reasons=["no supported board generation family could be inferred"],
        )
    return _architecture_intent_bridge_report(
        artifact,
        status=ArchitectureIntentBridgeStatus.CONVERTED,
        family_id=resolved_family_id,
    )


def convert_architecture_to_board_generation_intent(
    artifact: ElectronicsArchitectureArtifact,
    *,
    family_id: str | None = None,
    target_output_dir: str | None = None,
) -> BoardGenerationIntent:
    """Convert a ready architecture artifact into a board generation intent."""
    from zaptrace.generation.intent import (
        ArtifactPolicy,
        BoardGenerationIntent,
        EvidenceExpectation,
        InterfaceConstraint,
        PowerConstraint,
        RequirementRef,
    )

    report = convert_architecture_to_board_generation_intent_report(artifact, family_id=family_id)
    if not report.converted:
        raise ValueError(architecture_intent_bridge_report_json(report))

    return BoardGenerationIntent(
        family_id=report.family_id or "",
        design_name=artifact.design_name,
        description=(f"Architecture-derived board generation intent. Source intent: {artifact.source_intent}"),
        requirements=[
            RequirementRef(
                id=requirement.id,
                text=requirement.text,
                source=f"architecture:{requirement.source}",
                release_blocking=requirement.release_blocking,
            )
            for requirement in artifact.requirements
        ],
        power=[
            PowerConstraint(
                net_name=rail.net_name,
                voltage_v=rail.nominal_voltage_v,
                max_current_a=rail.max_current_a,
                source=rail.source,
                release_blocking=bool(rail.requirement_ids),
            )
            for rail in artifact.power_tree
        ],
        interfaces=[
            InterfaceConstraint(
                name=interface.name,
                role=interface.role,
                nets=interface.nets,
                controlled_impedance=interface.controlled_impedance,
                release_blocking=bool(interface.requirement_ids),
            )
            for interface in artifact.interfaces
        ],
        artifact_policy=ArtifactPolicy(),
        evidence=EvidenceExpectation(),
        target_output_dir=target_output_dir or f"generated/{artifact.design_name}",
        non_claims=sorted(
            {
                *artifact.non_claims,
                "board generation intent is derived from a requirements architecture artifact",
                _NOT_FABRICATION_READY,
            }
        ),
    )
