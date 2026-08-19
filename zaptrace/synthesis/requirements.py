"""Requirements → constraints extraction.

Turns a natural-language / keyword design intent into a structured, machine-
readable :class:`Requirements` object — voltage rails, current budget, buses,
MCU family, and USB-C / battery flags — so every later synthesis decision can
be traced back to an explicit requirement instead of a guess.

This is deliberately deterministic pattern extraction, not an LLM: the same
intent always yields the same requirements, which is what verification-first
synthesis needs. It captures what was clearly stated; it does not invent
defaults (a missing field stays empty/None for the caller to resolve).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Requirements schema v1 — explicit pre-synthesis contract
# ---------------------------------------------------------------------------


class EnvironmentRequirements(BaseModel):
    """Environmental operating requirements for a design contract."""

    model_config = ConfigDict(extra="forbid")

    temperature_c: tuple[float, float] = Field(description="Operating temperature range as (min_c, max_c)")
    ingress_rating: str | None = Field(default=None, description="Ingress protection target, e.g. IP67")
    enclosure: str | None = Field(default=None, description="Expected enclosure/material context")

    @model_validator(mode="after")
    def _temperature_range_must_be_ordered(self) -> EnvironmentRequirements:
        if self.temperature_c[0] >= self.temperature_c[1]:
            raise ValueError("environment.temperature_c must be ordered as min < max")
        return self


class PowerRequirements(BaseModel):
    """Power-source and rail requirements for a design contract."""

    model_config = ConfigDict(extra="forbid")

    inputs: list[str] = Field(min_length=1, description="Input power sources, e.g. usb_c_5v or battery_lipo")
    rails_v: list[float] = Field(min_length=1, description="Required regulated/supplied voltage rails")
    max_current_a: float = Field(gt=0, description="Maximum board current budget in amperes")


class SafetyRequirements(BaseModel):
    """Safety-domain requirements for a design contract."""

    model_config = ConfigDict(extra="forbid")

    mains: bool = Field(description="Whether the design touches mains/hazardous line voltage")
    battery: bool = Field(description="Whether the design includes or charges a battery")
    isolation_required: bool = Field(default=False, description="Whether reinforced/basic isolation is required")
    safety_critical: bool = Field(default=False, description="Whether functional-safety/life-safety constraints apply")


class ManufacturingRequirements(BaseModel):
    """Manufacturing constraints for a design contract."""

    model_config = ConfigDict(extra="forbid")

    fab_profile: str = Field(description="Target fabrication profile, e.g. jlcpcb-2layer")
    layers: int = Field(ge=1, le=32, description="Expected PCB layer count")
    min_trace_width_mm: float = Field(gt=0, description="Minimum trace width allowed by the fab profile")
    min_clearance_mm: float = Field(gt=0, description="Minimum clearance allowed by the fab profile")
    assembly: str | None = Field(default=None, description="Assembly target, e.g. smt, hand, mixed")


class RequirementsSchemaV1(BaseModel):
    """Machine-readable requirements contract consumed before synthesis."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = Field(default="1.0", description="Requirements schema version")
    product_class: str = Field(min_length=1, description="Board/product family, e.g. iot_sensor_node")
    environment: EnvironmentRequirements
    power: PowerRequirements
    interfaces: list[str] = Field(description="Required external/internal interfaces")
    safety: SafetyRequirements
    manufacturing: ManufacturingRequirements
    compliance_targets: list[str] = Field(description="Regulatory/compliance targets, can be empty if explicitly none")


def validate_requirements_schema_v1(data: Mapping[str, Any]) -> RequirementsSchemaV1:
    """Validate a mapping as a requirements schema v1 contract."""
    return RequirementsSchemaV1.model_validate(data)


def load_requirements_schema_v1(path: str | Path) -> RequirementsSchemaV1:
    """Load and validate a requirements schema v1 JSON/YAML file."""
    import json

    import yaml

    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw) if p.suffix.lower() == ".json" else yaml.safe_load(raw)
    if not isinstance(data, Mapping):
        raise ValueError("requirements schema file must contain a mapping/object")
    return validate_requirements_schema_v1(data)


def minimal_requirements_schema_v1_example() -> dict[str, Any]:
    """Return a minimal valid requirements schema v1 example."""
    return {
        "schema_version": "1.0",
        "product_class": "iot_sensor_node",
        "environment": {
            "temperature_c": [0.0, 50.0],
            "ingress_rating": None,
            "enclosure": "plastic",
        },
        "power": {
            "inputs": ["usb_c_5v"],
            "rails_v": [3.3],
            "max_current_a": 0.5,
        },
        "interfaces": ["usb", "i2c"],
        "safety": {
            "mains": False,
            "battery": False,
            "isolation_required": False,
            "safety_critical": False,
        },
        "manufacturing": {
            "fab_profile": "jlcpcb-2layer",
            "layers": 2,
            "min_trace_width_mm": 0.15,
            "min_clearance_mm": 0.15,
            "assembly": "smt",
        },
        "compliance_targets": ["RoHS"],
    }


# Canonical interface -> the tokens that imply it.
_INTERFACES: dict[str, tuple[str, ...]] = {
    "i2c": ("i2c", "i²c", "iic"),
    "spi": ("spi",),
    "uart": ("uart",),
    "usb": ("usb", "usb-c", "type-c", "typec"),
    "can": ("can", "canbus", "can-bus"),
    "rs485": ("rs485", "rs-485", "modbus"),
    "ethernet": ("ethernet", "rj45", "rmii"),
    "ble": ("ble", "bluetooth"),
    "wifi": ("wifi", "wi-fi", "wlan"),
    "lora": ("lora", "lorawan"),
}

# Canonical MCU family -> tokens.
_MCU_FAMILIES: dict[str, tuple[str, ...]] = {
    "esp32": ("esp32", "esp32-s3", "esp32-c3", "esp32-c6"),
    "stm32": ("stm32",),
    "rp2040": ("rp2040", "pico"),
    "nrf52": ("nrf52", "nrf5"),
    "atmega": ("atmega",),
    "samd": ("samd21", "samd51", "samd"),
    "ch32": ("ch32",),
}

_USB_C_TOKENS = ("usb-c", "usb c", "type-c", "typec", "usbc")
_BATTERY_TOKENS = ("battery", "li-ion", "lithium", "lipo", "li-po", "lifepo4", "18650", "coin cell")

# Risk-classification token sets (matched against the raw intent, whole-token).
_WIRELESS_INTERFACES = frozenset({"ble", "wifi", "lora"})
_WIRELESS_TOKENS = (
    "rf",
    "antenna",
    "2.4ghz",
    "sub-ghz",
    "subghz",
    "zigbee",
    "nfc",
    "rfid",
    "gps",
    "gnss",
    "cellular",
    "lte",
    "nb-iot",
    "433mhz",
    "915mhz",
)
_MAINS_TOKENS = (
    "mains",
    "ac line",
    "ac-line",
    "line voltage",
    "110vac",
    "120vac",
    "220vac",
    "230vac",
    "240vac",
    "high voltage",
    "high-voltage",
    "offline smps",
)
_SAFETY_CRITICAL_TOKENS = (
    "medical",
    "automotive",
    "aerospace",
    "avionics",
    "iso 26262",
    "iso26262",
    "iec 62304",
    "do-178",
    "safety-critical",
    "safety critical",
    "life support",
    "implant",
    "defibrillator",
    "infusion pump",
    "functional safety",
)
# Below this rail voltage a design is SELV (Safety Extra-Low Voltage); at or
# above it the board carries a hazardous-voltage / high-voltage risk.
_HV_RAIL_THRESHOLD_V = 60.0

# Canonical regulatory target -> tokens. Only unambiguous forms are listed
# (no bare "ce"/"ul"/"reach", which collide with ordinary English) so the
# extractor keeps the module's "invents nothing" precision.
_REGULATORY: dict[str, tuple[str, ...]] = {
    "CE": ("ce mark", "ce-mark", "ce marking", "ce marked", "ce-marked"),
    "FCC": ("fcc",),
    "UL": ("ul listed", "ul-listed", "ul94", "ul 94"),
    "RoHS": ("rohs",),
    "REACH": ("reach svhc", "reach compliance"),
    "CISPR": ("cispr",),
    "ATEX": ("atex",),
    "EN55032": ("en 55032", "en55032"),
    "IEC61000": ("iec 61000", "iec61000"),
}


def _has_token(text: str, token: str) -> bool:
    """Whole-token match (non-alphanumeric boundaries, so 'can' != 'scanner')."""
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None


def _extract_rails(text: str) -> list[float]:
    rails: set[float] = set()
    # "3.3V", "5V", "12V" (a digit/decimal before V, not followed by a digit so
    # the European "3V3" form is left to the next pattern, not read as "3V").
    for match in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)\s*v(?![a-z0-9])", text):
        rails.add(float(match.group(1)))
    # "3V3", "1V8" European notation
    for match in re.finditer(r"(?<![\w])(\d+)v(\d+)(?![\w])", text):
        rails.add(float(f"{match.group(1)}.{match.group(2)}"))
    return sorted(rails)


def _extract_max_current_a(text: str) -> float | None:
    currents: list[float] = []
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(ma|a)\b", text):
        amount = float(match.group(1))
        currents.append(amount / 1000.0 if match.group(2) == "ma" else amount)
    return max(currents) if currents else None


def _extract_temp_range_c(text: str) -> list[float] | None:
    """Operating temperature range, e.g. "-40 to 85C" / "0-70°C" -> [min, max].

    Anchored on a trailing Celsius marker so a voltage range ("48v to 230v")
    cannot be misread as a temperature.
    """
    pattern = (
        r"(-?\d{1,4})\s{0,32}°?\s{0,32}c?\s{0,32}"
        r"(?:to|–|—|\.\.|-)\s{0,32}\+?(-?\d{1,4})\s{0,32}°?\s{0,32}c\b"
    )
    match = re.search(pattern, text)
    if not match:
        return None
    lo, hi = float(match.group(1)), float(match.group(2))
    return [min(lo, hi), max(lo, hi)]


def _extract_ingress_rating(text: str) -> str | None:
    """IP ingress-protection code, e.g. "IP67" -> "IP67"."""
    match = re.search(r"\bip\s?(\d{2})\b", text)
    return f"IP{match.group(1)}" if match else None


def _extract_cost_target_usd(text: str) -> float | None:
    """Tightest stated BOM/unit cost target in USD ("under $5", "10 usd" -> min)."""
    amounts: list[float] = []
    for match in re.finditer(r"\$\s*(\d+(?:\.\d+)?)", text):
        amounts.append(float(match.group(1)))
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*usd\b", text):
        amounts.append(float(match.group(1)))
    return min(amounts) if amounts else None


def _extract_dimensions_mm(text: str) -> list[float] | None:
    """Board dimensions in mm, e.g. "50x30mm" / "50 mm x 30 mm" -> [50.0, 30.0]."""
    pattern = (
        r"(\d{1,8}(?:\.\d{1,8})?)\s{0,32}(?:mm)?\s{0,32}[x×]\s{0,32}"
        r"(\d{1,8}(?:\.\d{1,8})?)\s{0,32}mm\b"
    )
    match = re.search(pattern, text)
    if not match:
        return None
    return [float(match.group(1)), float(match.group(2))]


def _extract_regulatory(text: str) -> list[str]:
    """Stated regulatory / compliance targets (CE, FCC, UL, RoHS, ...)."""
    return sorted(name for name, tokens in _REGULATORY.items() if any(_has_token(text, t) for t in tokens))


@dataclass
class Requirements:
    """Structured, machine-readable requirements extracted from a design intent."""

    raw_intent: str
    rails_v: list[float] = field(default_factory=list)
    max_current_a: float | None = None
    interfaces: list[str] = field(default_factory=list)
    mcu: str | None = None
    usb_c: bool = False
    battery: bool = False
    # Environmental / mechanical / cost / regulatory targets.
    temp_range_c: list[float] | None = None
    ingress_rating: str | None = None
    dimensions_mm: list[float] | None = None
    cost_target_usd: float | None = None
    regulatory: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_requirements(intent: str) -> Requirements:
    """Extract structured :class:`Requirements` from a design *intent* string."""
    text = intent.lower()
    interfaces = sorted(name for name, tokens in _INTERFACES.items() if any(_has_token(text, t) for t in tokens))
    mcu = next(
        (family for family, tokens in _MCU_FAMILIES.items() if any(_has_token(text, t) for t in tokens)),
        None,
    )
    return Requirements(
        raw_intent=intent,
        rails_v=_extract_rails(text),
        max_current_a=_extract_max_current_a(text),
        interfaces=interfaces,
        mcu=mcu,
        usb_c=any(t in text for t in _USB_C_TOKENS),
        battery=any(t in text for t in _BATTERY_TOKENS),
        temp_range_c=_extract_temp_range_c(text),
        ingress_rating=_extract_ingress_rating(text),
        dimensions_mm=_extract_dimensions_mm(text),
        cost_target_usd=_extract_cost_target_usd(text),
        regulatory=_extract_regulatory(text),
    )


def _rail_id(rail_v: float) -> str:
    """Stable voltage-domain id, e.g. 3.3 -> VDD_3V3, 5.0 -> VDD_5."""
    return "VDD_" + f"{rail_v:g}".replace(".", "V")


def requirements_to_constraints(requirements: Requirements) -> Any:
    """Derive a constraint-DSL :class:`ConstraintSet` from parsed requirements.

    Each emitted constraint is traceable to the requirement that produced it
    (recorded in the constraint's ``reason``), satisfying the requirement →
    constraint half of the engine that this module's name promises. Only what
    the requirements actually state is emitted — nothing is invented.
    """
    from zaptrace.core.models import (
        ConstraintSet,
        PlacementIntent,
        RoutingIntent,
        VoltageDomainConstraint,
    )

    constraints = ConstraintSet()

    for rail in requirements.rails_v:
        constraints.voltage_domains.append(VoltageDomainConstraint(id=_rail_id(rail), nominal=f"{rail:g}V"))

    if requirements.usb_c or "usb" in requirements.interfaces:
        constraints.routing.append(
            RoutingIntent(
                net="USB_D*",
                differential_pair=True,
                impedance_ohm=90.0,
                length_match_mm=0.15,
                reason="USB high-speed differential pair (from usb_c/usb interface requirement)",
            )
        )
        constraints.placement.append(
            PlacementIntent(
                component="J*",
                edge="bottom",
                reason="USB connector on a board edge (from usb_c requirement)",
            )
        )

    if "i2c" in requirements.interfaces:
        constraints.routing.append(RoutingIntent(net="*SDA*", reason="I2C bus net (from i2c interface requirement)"))

    return constraints


_ASSUMPTION_RISK: dict[str, str] = {
    "rails_v": "high",
    "max_current_a": "high",
    "mcu": "medium",
    "usb_c": "medium",
    "battery": "high",
}


def _assumption_record(field: str, assumption: str) -> dict[str, Any]:
    return {
        "field": field,
        "assumption": assumption,
        "risk": _ASSUMPTION_RISK.get(field, "medium"),
        "requires_confirmation": True,
    }


def requirements_assumptions(requirements: Requirements) -> list[dict[str, Any]]:
    """Register information a design needs that the intent did not state.

    Distinct from coverage (which maps *stated* requirements to constraints):
    this lists the *unstated* facts a downstream step would otherwise have to
    assume, so every assumption is explicit and reviewable instead of silently
    baked in. (unspecified-assumption register.)
    """
    assumptions: list[dict[str, Any]] = []

    if not requirements.rails_v:
        assumptions.append(
            _assumption_record(
                "rails_v",
                "no supply voltage stated; downstream must choose a rail (commonly 3.3V)",
            )
        )
    if requirements.max_current_a is None:
        assumptions.append(
            _assumption_record(
                "max_current_a",
                "no current budget stated; regulator/thermal sizing cannot be verified",
            )
        )
    if requirements.mcu is None:
        assumptions.append(_assumption_record("mcu", "no controller/MCU stated"))
    if requirements.usb_c:
        assumptions.append(
            _assumption_record("usb_c", "USB-C power role (UFP sink vs DFP source) not stated; assuming sink")
        )
    if requirements.battery:
        assumptions.append(_assumption_record("battery", "battery chemistry/voltage and charge current not stated"))
    return assumptions


def requirements_assumption_report(
    requirements: Requirements,
    approvals: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the proof-pack assumptions artifact for a requirements version.

    Each assumption has a stable ID, risk class, and confirmation state. The
    report exposes unconfirmed high-risk assumptions so sign-off policy can
    block autonomous-pass instead of silently accepting design guesses.
    """
    approvals = approvals or {}
    freeze_hash = freeze_requirements(requirements)["hash"]
    assumptions: list[dict[str, Any]] = []
    for index, item in enumerate(requirements_assumptions(requirements), start=1):
        field = item["field"]
        decision = approvals.get(field)
        assumptions.append(
            {
                "id": f"ASM-{index:03d}",
                "field": field,
                "assumption": item["assumption"],
                "risk": item["risk"],
                "requires_confirmation": item["requires_confirmation"],
                "confirmed": bool(decision),
                "decision": decision or "",
            }
        )
    unconfirmed_high_risk = [
        item
        for item in assumptions
        if item["risk"] == "high" and item["requires_confirmation"] and not item["confirmed"]
    ]
    return {
        "schema_version": "1.0",
        "requirements_hash": freeze_hash,
        "approved": not [item for item in assumptions if item["requires_confirmation"] and not item["confirmed"]],
        "assumptions": assumptions,
        "unconfirmed_high_risk": unconfirmed_high_risk,
        "unconfirmed_high_risk_count": len(unconfirmed_high_risk),
    }


def _contract_fields(requirements: Requirements) -> dict[str, Any]:
    """The design-contract fields used for freezing/diffing.

    Excludes ``raw_intent`` deliberately: the freeze gate tracks the *extracted*
    contract (rails, current, interfaces, ...), so reworded-but-equivalent prose
    does not break the freeze, and a genuine requirement change always does.
    """
    data = requirements.to_dict()
    data.pop("raw_intent", None)
    return data


def freeze_requirements(requirements: Requirements) -> dict[str, Any]:
    """Freeze parsed requirements into a content-addressed snapshot.

    Returns ``{"hash": "<sha256>", "frozen": {<contract fields>}}``. The hash is
    a stable digest over the contract fields (not the raw prose), so downstream
    synthesis can record which requirements version it was built against and
    detect drift — the freeze gate of the requirements engine.
    """
    import hashlib
    import json

    payload = _contract_fields(requirements)
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {"hash": hashlib.sha256(blob).hexdigest(), "frozen": payload}


def diff_requirements(old: Requirements, new: Requirements) -> dict[str, Any]:
    """Diff two requirement versions field-by-field for review and freeze gating.

    Returns ``{"changed": [{"field", "from", "to"}], "unchanged": bool,
    "from_hash", "to_hash"}``. A non-empty ``changed`` list means the frozen
    contract moved and any downstream artifacts built on the old freeze must be
    re-verified — the versioning/diff half of the freeze gate.
    """
    old_fields = _contract_fields(old)
    new_fields = _contract_fields(new)
    changed = [
        {"field": key, "from": old_fields[key], "to": new_fields[key]}
        for key in old_fields
        if old_fields[key] != new_fields[key]
    ]
    return {
        "changed": changed,
        "unchanged": not changed,
        "from_hash": freeze_requirements(old)["hash"],
        "to_hash": freeze_requirements(new)["hash"],
    }


def review_assumptions(requirements: Requirements, approvals: dict[str, str] | None = None) -> dict[str, Any]:
    """Approval gate over the unspecified-assumption register.

    Every registered assumption must be explicitly resolved before the
    requirements are review-complete. ``approvals`` maps an assumption ``field``
    to the decision the reviewer recorded for it (e.g. ``{"rails_v": "3.3V"}``);
    a missing field stays *pending*. Approvals are bound to ``freeze_hash`` so a
    later requirement change (which moves the hash, see :func:`freeze_requirements`)
    invalidates them and the gate re-opens.

    Returns ``{"freeze_hash", "approved": bool, "reviewed": [...], "pending": [...]}``;
    ``approved`` is True only when no assumption is still pending. (assumption approval workflow.)
    """
    approvals = approvals or {}
    freeze_hash = freeze_requirements(requirements)["hash"]
    reviewed: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for item in requirements_assumptions(requirements):
        decision = approvals.get(item["field"])
        if decision:
            reviewed.append({**item, "decision": decision, "status": "approved"})
        else:
            pending.append({**item, "status": "pending"})
    return {
        "freeze_hash": freeze_hash,
        "approved": not pending,
        "reviewed": reviewed,
        "pending": pending,
    }


def classify_risk(requirements: Requirements) -> dict[str, Any]:
    """Classify a design's product use-case / risk profile from its requirements.

    Deterministic, evidence-bearing classification into the risk classes that
    drive downstream rule-pack and standards selection: ``battery``,
    ``wireless``, ``high_voltage``, and ``safety_critical``. Each hit records the
    evidence that triggered it (a flag, a wireless interface, a hazardous rail, or
    an intent token) so the classification is auditable, never a black box. A
    class is emitted only when there is concrete evidence — nothing is inferred.

    Returns ``{"risk_classes": [<names>], "classifications": [{"class",
    "rationale", "evidence"}]}``. (product use-case & risk classifier.)
    """
    text = requirements.raw_intent.lower()
    classifications: list[dict[str, str]] = []

    if requirements.battery:
        classifications.append(
            {
                "class": "battery",
                "rationale": "battery-powered: needs charge/protection, fuel-gauging, and low-power review",
                "evidence": "battery requirement",
            }
        )

    wireless_ifaces = sorted(_WIRELESS_INTERFACES.intersection(requirements.interfaces))
    wireless_tokens = [t for t in _WIRELESS_TOKENS if _has_token(text, t)]
    if wireless_ifaces or wireless_tokens:
        classifications.append(
            {
                "class": "wireless",
                "rationale": "radio present: antenna matching, keep-outs, and RF/EMC certification apply",
                "evidence": ", ".join(wireless_ifaces + wireless_tokens),
            }
        )

    hv_rails = [r for r in requirements.rails_v if r >= _HV_RAIL_THRESHOLD_V]
    hv_tokens = [t for t in _MAINS_TOKENS if _has_token(text, t)]
    if hv_rails or hv_tokens:
        evidence = [f"{r:g}V rail" for r in hv_rails] + hv_tokens
        classifications.append(
            {
                "class": "high_voltage",
                "rationale": (
                    f"hazardous voltage (>= {_HV_RAIL_THRESHOLD_V:g}V): creepage/clearance and isolation apply"
                ),
                "evidence": ", ".join(evidence),
            }
        )

    safety_tokens = [t for t in _SAFETY_CRITICAL_TOKENS if _has_token(text, t)]
    if safety_tokens:
        classifications.append(
            {
                "class": "safety_critical",
                "rationale": "safety-critical domain: redundancy, traceability, and domain standards apply",
                "evidence": ", ".join(safety_tokens),
            }
        )

    return {
        "risk_classes": [c["class"] for c in classifications],
        "classifications": classifications,
    }


# USB-C without Power Delivery negotiation supplies at most 3 A at 5 V (the
# default/BC1.2 ceiling); above this a design must negotiate USB-PD or use
# another supply.
_USB_C_NON_PD_MAX_A = 3.0


def requirements_conflicts(requirements: Requirements) -> list[dict[str, Any]]:
    """Detect contradictions between stated requirements.

    Distinct from the assumption register (*unstated* facts) and the coverage
    matrix (*unmapped* facts): this flags stated requirements that are mutually
    inconsistent and cannot all hold as written, so the contradiction is caught
    before any drawing happens. Each conflict cites the two sides and explains
    the physical/spec reason. Deterministic and conservative — only genuine,
    explainable contradictions are emitted. (requirement conflict detector.)
    """
    conflicts: list[dict[str, Any]] = []

    hv_rails = [r for r in requirements.rails_v if r >= _HV_RAIL_THRESHOLD_V]
    if requirements.battery and hv_rails:
        conflicts.append(
            {
                "conflict": "battery_vs_high_voltage",
                "between": ["battery", f"rail {hv_rails[0]:g}V"],
                "detail": (
                    "battery-powered design also specifies a hazardous-voltage rail "
                    f"(>= {_HV_RAIL_THRESHOLD_V:g}V); confirm an isolated boost/charger "
                    "stage rather than a contradictory power source"
                ),
            }
        )

    current_a = requirements.max_current_a
    if requirements.usb_c and current_a is not None and current_a > _USB_C_NON_PD_MAX_A:
        conflicts.append(
            {
                "conflict": "usb_c_current_over_budget",
                "between": ["usb_c", f"max_current_a {current_a:g}A"],
                "detail": (
                    f"current budget {current_a:g}A exceeds the USB-C default (non-PD) "
                    f"{_USB_C_NON_PD_MAX_A:g}A limit; requires USB-PD negotiation or an "
                    "alternate supply"
                ),
            }
        )

    if requirements.battery and requirements.temp_range_c and requirements.temp_range_c[0] < 0:
        conflicts.append(
            {
                "conflict": "battery_vs_subzero_temperature",
                "between": ["battery", f"temp_range_c min {requirements.temp_range_c[0]:g}C"],
                "detail": (
                    "Li-ion/Li-Po charging is unsafe below 0 C; the stated low operating "
                    "temperature conflicts with battery charging without a heater or charge "
                    "inhibit"
                ),
            }
        )

    return conflicts


def requirements_coverage(requirements: Requirements) -> dict[str, Any]:
    """Trace which requirements produced constraints and which are not yet covered.

    Returns ``{"covered": [...], "uncovered": [...], "fully_covered": bool}``.
    The ``uncovered`` list is the honest record of stated requirements that the
    constraint derivation does not yet handle (e.g. battery charge/protection,
    current budget) — a coverage matrix, not a silent pass.
    """
    constraints = requirements_to_constraints(requirements)
    covered: list[dict[str, Any]] = []
    uncovered: list[dict[str, str]] = []

    if requirements.rails_v:
        covered.append(
            {
                "aspect": "rails_v",
                "detail": f"{len(requirements.rails_v)} voltage rail(s)",
                "constraints": [d.id for d in constraints.voltage_domains],
            }
        )
    if requirements.usb_c or "usb" in requirements.interfaces:
        covered.append(
            {
                "aspect": "usb",
                "detail": "USB differential-pair routing + edge-placed connector",
                "constraints": [r.net for r in constraints.routing if "usb" in r.reason.lower()]
                + [p.component for p in constraints.placement],
            }
        )
    if "i2c" in requirements.interfaces:
        covered.append(
            {
                "aspect": "interface:i2c",
                "detail": "I2C bus routing intent",
                "constraints": [r.net for r in constraints.routing if "i2c" in r.reason.lower()],
            }
        )

    # Stated requirements with no constraint mapping yet — the coverage gaps.
    if requirements.battery:
        uncovered.append({"aspect": "battery", "reason": "charge/protection constraints not yet derived"})
    if requirements.max_current_a is not None:
        uncovered.append({"aspect": "max_current_a", "reason": "current-budget constraint not yet derived"})
    for iface in requirements.interfaces:
        if iface not in {"usb", "i2c"}:
            uncovered.append({"aspect": f"interface:{iface}", "reason": "no constraint mapping yet"})

    return {"covered": covered, "uncovered": uncovered, "fully_covered": not uncovered}


def requirement_ids(requirements: Requirements) -> list[dict[str, Any]]:
    """Return stable requirement IDs for the extracted contract.

    The IDs are intentionally coarse at this stage. They provide a stable trace
    vocabulary for generated components, nets, checks, and export artifacts, and
    will become the bridge to full schema-v1 authored requirement IDs later.
    """
    ids: list[dict[str, Any]] = []
    if requirements.rails_v:
        ids.append({"id": "REQ-POWER-RAILS", "field": "rails_v", "value": requirements.rails_v})
    if requirements.max_current_a is not None:
        ids.append({"id": "REQ-POWER-CURRENT", "field": "max_current_a", "value": requirements.max_current_a})
    for iface in requirements.interfaces:
        ids.append({"id": f"REQ-IFACE-{iface.upper()}", "field": "interfaces", "value": iface})
    if requirements.mcu:
        ids.append({"id": "REQ-MCU", "field": "mcu", "value": requirements.mcu})
    if requirements.usb_c:
        ids.append({"id": "REQ-USB-C", "field": "usb_c", "value": True})
    if requirements.battery:
        ids.append({"id": "REQ-BATTERY", "field": "battery", "value": True})
    if requirements.temp_range_c:
        ids.append({"id": "REQ-ENV-TEMP", "field": "temp_range_c", "value": requirements.temp_range_c})
    if requirements.ingress_rating:
        ids.append({"id": "REQ-ENV-INGRESS", "field": "ingress_rating", "value": requirements.ingress_rating})
    if requirements.dimensions_mm:
        ids.append({"id": "REQ-MECH-DIMENSIONS", "field": "dimensions_mm", "value": requirements.dimensions_mm})
    if requirements.cost_target_usd is not None:
        ids.append({"id": "REQ-COST", "field": "cost_target_usd", "value": requirements.cost_target_usd})
    for target in requirements.regulatory:
        ids.append({"id": f"REQ-COMPLIANCE-{target.upper()}", "field": "regulatory", "value": target})
    return ids


def _trace_ids_for_text(text: str, requirements: Requirements) -> list[str]:
    """Best-effort deterministic trace IDs from object names/values."""
    haystack = text.lower()
    traces: set[str] = set()
    for rail in requirements.rails_v:
        rail_text = f"{rail:g}".replace(".", "v")
        if f"{rail:g}" in haystack or rail_text in haystack:
            traces.add("REQ-POWER-RAILS")
    for iface in requirements.interfaces:
        if iface.lower() in haystack:
            traces.add(f"REQ-IFACE-{iface.upper()}")
    if requirements.usb_c and ("usb" in haystack or "type-c" in haystack or "typec" in haystack):
        traces.add("REQ-USB-C")
    if requirements.mcu and requirements.mcu.lower() in haystack:
        traces.add("REQ-MCU")
    if requirements.battery and any(tok in haystack for tok in ("bat", "lipo", "li-ion", "charger")):
        traces.add("REQ-BATTERY")
    return sorted(traces)


def _component_trace_rows(design: Any, requirements: Requirements) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for component in getattr(design, "components", {}).values():
        cid = str(getattr(component, "id", getattr(component, "ref", "")))
        text = " ".join(
            str(value or "")
            for value in (
                getattr(component, "id", ""),
                getattr(component, "ref", ""),
                getattr(component, "type", ""),
                getattr(component, "value", ""),
                getattr(component, "footprint", ""),
                getattr(component, "voltage_supply", ""),
            )
        )
        rows.append({"kind": "component", "id": cid, "requirement_ids": _trace_ids_for_text(text, requirements)})
    return rows


def _net_trace_rows(design: Any, requirements: Requirements) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for net in getattr(design, "nets", {}).values():
        nid = str(getattr(net, "id", getattr(net, "name", "")))
        text = f"{getattr(net, 'id', '')} {getattr(net, 'name', '')} {getattr(net, 'type', '')}"
        rows.append({"kind": "net", "id": nid, "requirement_ids": _trace_ids_for_text(text, requirements)})
    return rows


def _check_trace_rows(checks: list[Any], requirements: Requirements) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for check in checks:
        name = str(getattr(check, "name", ""))
        category = str(getattr(getattr(check, "category", ""), "value", getattr(check, "category", "")))
        traces = _trace_ids_for_text(f"{name} {category} {getattr(check, 'description', '')}", requirements)
        requirement_rows = requirement_ids(requirements)
        if name in {"erc", "drc", "footprints"} and requirement_rows:
            if requirements.rails_v:
                default_trace = "REQ-POWER-RAILS"
            elif requirements.mcu:
                default_trace = "REQ-MCU"
            elif "usb" in requirements.interfaces:
                default_trace = "REQ-IFACE-USB"
            else:
                default_trace = requirement_rows[0]["id"]
            traces = sorted(set(traces) | {default_trace})
        rows.append({"kind": "check", "id": name, "requirement_ids": traces})
    return rows


def _export_trace_rows(exports: list[str], requirements: Requirements) -> list[dict[str, Any]]:
    ids = [r["id"] for r in requirement_ids(requirements)]
    return [{"kind": "export", "id": export, "requirement_ids": ids.copy()} for export in exports]


def requirements_coverage_report(
    requirements: Requirements,
    *,
    design: Any | None = None,
    checks: list[Any] | None = None,
    exports: list[str] | None = None,
) -> dict[str, Any]:
    """Build a synthesis coverage report with requirement IDs and trace gaps.

    The report extends the existing requirements coverage matrix with concrete
    trace rows for generated components, nets, checks, and exports. Any row with
    no requirement ID is reported in ``untraced_artifacts`` instead of being
    silently accepted.
    """
    checks = checks or []
    exports = exports or []
    trace_rows: list[dict[str, Any]] = []
    if design is not None:
        trace_rows.extend(_component_trace_rows(design, requirements))
        trace_rows.extend(_net_trace_rows(design, requirements))
    trace_rows.extend(_check_trace_rows(checks, requirements))
    trace_rows.extend(_export_trace_rows(exports, requirements))
    untraced = [row for row in trace_rows if not row["requirement_ids"]]
    base = requirements_coverage(requirements)
    return {
        "schema_version": "1.0",
        "requirements_hash": freeze_requirements(requirements)["hash"],
        "requirements": requirement_ids(requirements),
        "coverage": base,
        "traceability": trace_rows,
        "untraced_artifacts": untraced,
        "fully_traced": not untraced,
        "fully_covered": bool(base["fully_covered"] and not untraced),
    }


def write_requirements_artifacts(intent: str, output_dir: str | Path) -> dict[str, str]:
    """Emit machine-readable ``requirements.json`` and ``constraints.yaml``.

    Turns a design intent into the two reviewable, version-controllable design-
    contract artifacts the requirements engine promises, and returns the written
    paths. JSON/YAML are deterministic (stable key order) so they diff cleanly in
    review and CI.
    """
    import json

    import yaml

    requirements = parse_requirements(intent)
    constraints = requirements_to_constraints(requirements)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    req_path = out / "requirements.json"
    con_path = out / "constraints.yaml"

    req_path.write_text(json.dumps(requirements.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    con_path.write_text(
        yaml.safe_dump(constraints.model_dump(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return {"requirements": str(req_path), "constraints": str(con_path)}
