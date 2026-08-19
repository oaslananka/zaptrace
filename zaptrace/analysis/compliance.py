"""Regulatory compliance pre-check.

Turns the structured requirements of a design (see
:mod:`zaptrace.synthesis.requirements`) into the list of regulatory regimes that
plausibly apply, so an agent can surface a compliance checklist *during* design
instead of discovering it at certification.

This is a **pre-check, not certification**: every item says what applies and
why, and that it needs human review / lab testing. It never claims conformity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from zaptrace.synthesis.requirements import Requirements

_WIRELESS_INTERFACES = {"ble", "wifi", "lora"}
# Low Voltage Directive applies from 50 V AC / 75 V DC upward; below that it does not.
_LVD_THRESHOLD_V = 50.0
_ROHS_STANDARD = "EU RoHS 2011/65/EU"
_REACH_STANDARD = "EU REACH (SVHC)"


@dataclass(frozen=True)
class ComplianceItem:
    standard: str
    category: str
    applies_because: str
    action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compliance_checklist(requirements: Requirements) -> list[ComplianceItem]:
    """Return the regulatory pre-check items that apply to *requirements*.

    Deterministic and order-stable. Items are added because a feature of the
    design triggers them; each carries a human-review/test action.
    """
    items: list[ComplianceItem] = [
        ComplianceItem(
            standard=_ROHS_STANDARD,
            category="materials",
            applies_because="all electrical/electronic equipment on the EU market",
            action="Collect supplier RoHS declarations; track exemptions in the BOM.",
        ),
        ComplianceItem(
            standard=_REACH_STANDARD,
            category="materials",
            applies_because="all articles placed on the EU market",
            action="Track SVHC content per BOM line via supplier declarations.",
        ),
        ComplianceItem(
            standard="EU EMC Directive 2014/30/EU",
            category="emc",
            applies_because="all electronic equipment (CE marking)",
            action="Plan EMC emissions/immunity pre-compliance and final testing.",
        ),
    ]

    is_wireless = bool(set(requirements.interfaces) & _WIRELESS_INTERFACES)
    if is_wireless:
        items.append(
            ComplianceItem(
                standard="EU RED 2014/53/EU",
                category="radio",
                applies_because="design includes a radio interface",
                action="Use a pre-certified radio module where possible; plan RED testing.",
            )
        )
        items.append(
            ComplianceItem(
                standard="FCC Part 15",
                category="radio",
                applies_because="design includes a radio interface (US market)",
                action="Plan FCC equipment authorization; check modular-approval reuse.",
            )
        )

    if requirements.battery:
        items.append(
            ComplianceItem(
                standard="EU Battery Regulation 2023/1542",
                category="battery",
                applies_because="design includes a battery",
                action="Plan labelling, safety, and the battery-passport data requirements.",
            )
        )

    if requirements.rails_v and max(requirements.rails_v) >= _LVD_THRESHOLD_V:
        items.append(
            ComplianceItem(
                standard="EU Low Voltage Directive 2014/35/EU",
                category="safety",
                applies_because=f"a rail is at or above {_LVD_THRESHOLD_V:g} V",
                action="Address creepage/clearance, insulation, and protective-earth requirements.",
            )
        )

    # UKCA (UK Conformity Assessed) — mirrors CE for post-Brexit UK market
    items.append(
        ComplianceItem(
            standard="UKCA 2023 (UK market)",
            category="market-access",
            applies_because="products placed on the Great Britain market require UKCA",
            action="Assess if CE + UKCA dual-marking is required; check UKAS-accredited lab.",
        )
    )

    # WEEE directive
    items.append(
        ComplianceItem(
            standard="EU WEEE Directive 2012/19/EU",
            category="recycling",
            applies_because="electronic equipment sold in the EU must carry WEEE symbol",
            action="Register with a national producer-compliance scheme; add WEEE symbol to PCB silkscreen.",
        )
    )

    # IEC 62368-1 AV/IT safety — applies to most consumer and industrial electronics
    items.append(
        ComplianceItem(
            standard="IEC 62368-1 (safety for AV/IT equipment)",
            category="safety",
            applies_because="replaces IEC 60950-1 / IEC 60065 for most electronics",
            action=(
                "Classify energy sources; verify touch-safe creepage/clearance "
                "per Table 7 and Table 8; confirm insulation coordination."
            ),
        )
    )

    # IEC 61000-4 EMC immunity (key sub-standard for industrial)
    _industrial_tokens = ("industrial", "factory", "automation", "automotive", "harsh environment")
    raw = requirements.raw_intent.lower()
    if any(tok in raw for tok in _industrial_tokens):
        items.append(
            ComplianceItem(
                standard="IEC 61000-4-x (EMC immunity)",
                category="emc",
                applies_because="industrial/automotive environment requires IEC 61000-4 immunity",
                action=(
                    "Test IEC 61000-4-2 (ESD), 4-3 (radiated), 4-4 (EFT), "
                    "4-5 (surge), 4-6 (conducted) per appropriate severity level."
                ),
            )
        )

    return items


@dataclass(frozen=True)
class ProductClassProfile:
    """Compliance profile for a product class."""

    product_class: str
    primary_markets: list[str]
    required_standards: list[str]
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PRODUCT_CLASS_PROFILES: dict[str, ProductClassProfile] = {
    "consumer": ProductClassProfile(
        product_class="consumer",
        primary_markets=["EU", "UK", "US", "global"],
        required_standards=[
            _ROHS_STANDARD,
            _REACH_STANDARD,
            "EU EMC 2014/30/EU",
            "EU LVD 2014/35/EU (if ≥50 V AC)",
            "UKCA (UK market)",
            "FCC Part 15 (US)",
            "IEC 62368-1 (safety)",
            "EU WEEE 2012/19/EU",
            "EU Battery Regulation (if battery)",
        ],
        notes="Consumer electronics: CE marking, UKCA, FCC authorization required before sale.",
    ),
    "industrial": ProductClassProfile(
        product_class="industrial",
        primary_markets=["EU", "UK", "US"],
        required_standards=[
            _ROHS_STANDARD,
            _REACH_STANDARD,
            "EU EMC 2014/30/EU (industry limits)",
            "IEC 61000-4-x immunity (harsh environment)",
            "EU Machinery Directive 2006/42/EC (if motion)",
            "IEC 62368-1 / IEC 61010-1",
        ],
        notes="Industrial: tighter immunity, often IEC 61010-1 safety, no WEEE registration for B2B.",
    ),
    "wireless": ProductClassProfile(
        product_class="wireless",
        primary_markets=["EU", "UK", "US"],
        required_standards=[
            "EU RED 2014/53/EU",
            "FCC Part 15 / Part 22 / Part 24 (US)",
            "ISED RSS (Canada)",
            "EU RoHS + REACH + EMC + LVD",
            "UK UKCA radio equipment",
        ],
        notes="Wireless: radio authorization mandatory; consider using pre-certified modules.",
    ),
    "battery": ProductClassProfile(
        product_class="battery",
        primary_markets=["EU", "global"],
        required_standards=[
            "EU Battery Regulation 2023/1542",
            "IEC 62133-2 (portable Li-ion safety)",
            "UN 38.3 (transport)",
            "EU RoHS + REACH",
        ],
        notes="Li-ion products: UN 38.3 required for air/sea shipping; EU Battery Passport from 2026.",
    ),
}


def product_class_profile(product_class: str) -> ProductClassProfile:
    """Return the compliance profile for a product class (case-insensitive).

    Supported classes: ``"consumer"``, ``"industrial"``, ``"wireless"``, ``"battery"``.
    """
    key = product_class.lower().strip()
    if key not in _PRODUCT_CLASS_PROFILES:
        raise ValueError(f"Unknown product class '{product_class}'. Known: {sorted(_PRODUCT_CLASS_PROFILES)}")
    return _PRODUCT_CLASS_PROFILES[key]
