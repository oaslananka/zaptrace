from __future__ import annotations

import pytest

from zaptrace.ee.footprint_proof import (
    FootprintPadProof,
    FootprintPin1Evidence,
    FootprintProof,
    FootprintSourceProvenance,
    FootprintSourceType,
)
from zaptrace.library.datasheet import (
    DatasheetFact,
    DatasheetFactReport,
    DatasheetFactScope,
    DatasheetSourceRef,
)
from zaptrace.library.loader import ComponentSpec
from zaptrace.library.schema import (
    ComponentField,
    ComponentTrustTier,
    FieldProvenance,
    ProvenanceConfidence,
    ProvenanceSourceType,
)
from zaptrace.library.selection import (
    ComponentCandidateAssessment,
    ComponentSelectionEvidence,
    ComponentSelectionRequirement,
    assess_component_candidate,
    select_component,
)
from zaptrace.supply.contracts import (
    BomProviderResult,
    CacheMetadata,
    CacheStatus,
    LifecycleStatus,
    RiskLevel,
)


def _provenance() -> dict[ComponentField, FieldProvenance]:
    return {
        field: FieldProvenance(
            source_type=ProvenanceSourceType.INTERNAL_MANIFEST,
            source_locator="fixture",
            source_identity=f"fixture:{field.value}",
            source_version="1",
            extraction_method="test-fixture",
            confidence=ProvenanceConfidence.LOW,
        )
        for field in ComponentField
    }


def _spec(part_id: str, *, category: str = "power", package: str = "SOT-23-5") -> ComponentSpec:
    return ComponentSpec(
        id=part_id,
        name=part_id,
        category=category,
        manufacturer="Acme",
        mpn=f"{part_id}-MPN",
        description="fixture component",
        datasheet="https://manufacturer.example/part.pdf",
        package=package,
        footprint=f"Package:{package}",
        lifecycle="active",
        pins={"1": {"function": "VIN"}, "2": {"function": "GND"}, "3": {"function": "VOUT"}},
        electrical_limits={"max_voltage_v": 6.0, "current_rating_a": 1.0, "max_power_w": 1.5},
        sourcing={"status": "active"},
        compliance={"rohs": True},
        provenance={"source": "fixture"},
        trust_tier=ComponentTrustTier.HEURISTIC,
        field_provenance=_provenance(),
    )


def test_select_component_filters_category_and_returns_machine_readable_rationale() -> None:
    requirement = ComponentSelectionRequirement(
        requirement_id="rail-3v3",
        position="U1",
        category="power",
    )

    decision = select_component(
        requirement,
        [_spec("sensor", category="sensor"), _spec("ldo-b"), _spec("ldo-a")],
    )

    assert decision.blocked is False
    assert decision.selected_component_id == "ldo-a"
    assert [item.component_id for item in decision.assessments] == ["ldo-a", "ldo-b", "sensor"]
    assert decision.assessments[0].eligible is True
    assert decision.assessments[-1].eligible is False
    assert decision.assessments[-1].diagnostics[0].code == "category-mismatch"
    assert decision.rationale.startswith("selected ldo-a")
    assert len(decision.decision_hash) == 64


def test_select_component_uses_component_id_as_deterministic_tie_breaker() -> None:
    requirement = ComponentSelectionRequirement(requirement_id="tie", position="U2", category="power")

    first = select_component(requirement, [_spec("zeta"), _spec("alpha")])
    second = select_component(requirement, [_spec("alpha"), _spec("zeta")])

    assert first.selected_component_id == "alpha"
    assert second.selected_component_id == "alpha"
    assert first.decision_hash == second.decision_hash


def test_select_component_blocks_when_no_candidate_passes_hard_gates() -> None:
    requirement = ComponentSelectionRequirement(requirement_id="mcu", position="U3", category="mcu")

    decision = select_component(requirement, [_spec("ldo", category="power")])

    assert decision.blocked is True
    assert decision.selected_component_id == ""
    assert decision.human_review_required is True
    assert decision.rationale == "no candidate passed the pre-layout component-selection gate"
    assert decision.proof_evidence()["blocked"] is True


def _fact(
    component_id: str,
    field: str,
    value: float | str,
    scope: DatasheetFactScope,
    *,
    digest: str = "a" * 64,
    confidence: float = 0.95,
) -> DatasheetFact:
    return DatasheetFact(
        component_id=component_id,
        field=field,
        value=value,
        unit="V" if "voltage" in field else "",
        scope=scope,
        confidence=confidence,
        source=DatasheetSourceRef(
            datasheet_url="https://manufacturer.example/part.pdf",
            datasheet_sha256=digest,
            section=scope.value,
        ),
    )


def _datasheet_report(part_id: str, *, missing_hash: bool = False) -> DatasheetFactReport:
    digest = "" if missing_hash else "a" * 64
    return DatasheetFactReport(
        component_id=part_id,
        datasheet_url="https://manufacturer.example/part.pdf",
        datasheet_sha256=digest,
        absolute_maximum=[
            _fact(part_id, "supply_voltage_max_v", 6.0, DatasheetFactScope.ABSOLUTE_MAXIMUM, digest=digest)
        ],
        recommended_operating=[
            _fact(part_id, "supply_voltage_max_v", 5.0, DatasheetFactScope.RECOMMENDED_OPERATING, digest=digest)
        ],
        other_facts=[
            _fact(part_id, "output_current_max_a", 1.0, DatasheetFactScope.ELECTRICAL_CHARACTERISTIC, digest=digest)
        ],
    )


def _footprint_proof(*, missing_pad: bool = False) -> FootprintProof:
    pads = [
        FootprintPadProof(
            pad_id=pad_id,
            layer="F.Cu",
            shape="rect",
            position_mm=(float(index), 0.0),
            size_mm=(1.0, 1.0),
        )
        for index, pad_id in enumerate(("1", "2", "3"), start=1)
    ]
    return FootprintProof(
        package_id="SOT-23-5",
        footprint_name="Package:SOT-23-5",
        source=FootprintSourceProvenance(
            source_type=FootprintSourceType.VENDORED,
            source_name="fixture",
            source_sha256="b" * 64,
        ),
        pad_count=3,
        pin_count=3,
        pin_map={"1": "1", "2": "2", "3": "99" if missing_pad else "3"},
        pads=pads,
        courtyard_mm=(3.0, 3.0),
        paste_enabled_pad_count=3,
        paste_disabled_pad_count=0,
        pin1=FootprintPin1Evidence(present=True, pad_id="1", method="fixture"),
    )


def _thermal_footprint_proof() -> FootprintProof:
    proof = _footprint_proof()
    proof.pads.append(
        FootprintPadProof(
            pad_id="EP",
            layer="F.Cu",
            shape="rect",
            position_mm=(0.0, 1.0),
            size_mm=(1.5, 1.5),
        )
    )
    proof.pad_count = 4
    proof.paste_enabled_pad_count = 4
    proof.thermal_pads = ["EP"]
    return proof


def _evidence(
    part_id: str,
    *,
    datasheet: DatasheetFactReport | None = None,
    footprint: FootprintProof | None = None,
    supply: BomProviderResult | None = None,
) -> ComponentSelectionEvidence:
    return ComponentSelectionEvidence(
        datasheet=datasheet,
        footprint=footprint,
        supply=supply,
    )


def _codes(assessment: ComponentCandidateAssessment) -> set[str]:
    return {item.code for item in assessment.diagnostics}


def test_voltage_above_derating_envelope_fails_before_layout() -> None:
    requirement = ComponentSelectionRequirement(
        requirement_id="voltage",
        position="U1",
        category="power",
        operating_voltage_v=5.0,
    )

    assessment = assess_component_candidate(
        requirement,
        _spec("ldo"),
        _evidence("ldo", datasheet=_datasheet_report("ldo")),
    )

    assert assessment.eligible is False
    assert "voltage-limit-exceeded" in _codes(assessment)
    assert assessment.extracted_constraints["recommended_voltage_max_v"] == 5.0
    assert assessment.extracted_constraints["absolute_voltage_max_v"] == 6.0


def test_current_above_derating_envelope_fails_before_layout() -> None:
    requirement = ComponentSelectionRequirement(
        requirement_id="current",
        position="U1",
        category="power",
        operating_current_a=0.9,
    )

    assessment = assess_component_candidate(
        requirement,
        _spec("ldo"),
        _evidence("ldo", datasheet=_datasheet_report("ldo")),
    )

    assert assessment.eligible is False
    assert "current-limit-exceeded" in _codes(assessment)
    assert assessment.extracted_constraints["current_rating_a"] == 1.0


def test_power_above_derating_envelope_fails_before_layout() -> None:
    requirement = ComponentSelectionRequirement(
        requirement_id="power",
        position="U1",
        category="power",
        operating_power_w=0.8,
    )

    assessment = assess_component_candidate(requirement, _spec("ldo"))

    assert assessment.eligible is False
    assert "power-limit-exceeded" in _codes(assessment)


def test_package_and_footprint_mismatch_are_hard_failures() -> None:
    requirement = ComponentSelectionRequirement(
        requirement_id="physical",
        position="U1",
        category="power",
        allowed_packages=["QFN-32"],
        required_footprint="Package:QFN-32",
    )

    assessment = assess_component_candidate(requirement, _spec("ldo"))

    assert assessment.eligible is False
    assert {"package-mismatch", "footprint-mismatch"}.issubset(_codes(assessment))


def test_required_pin_function_mismatch_is_detected() -> None:
    requirement = ComponentSelectionRequirement(
        requirement_id="pins",
        position="U1",
        category="power",
        required_pin_functions={"1": "GND"},
    )

    assessment = assess_component_candidate(requirement, _spec("ldo"))

    assert assessment.eligible is False
    assert "pin-function-mismatch" in _codes(assessment)


def test_physical_package_pin_map_matches_footprint_proof() -> None:
    requirement = ComponentSelectionRequirement(requirement_id="mapped-fp", position="U1", category="power")
    spec = _spec("mapped")
    spec.pins = {
        "VIN": {"function": "VIN"},
        "GND": {"function": "GND"},
        "VOUT": {"function": "VOUT"},
    }
    spec.package_pin_map = {"1": "VIN", "2": "GND", "3": "VOUT"}

    assessment = assess_component_candidate(
        requirement,
        spec,
        _evidence("mapped", footprint=_footprint_proof()),
    )

    assert "footprint-proof-blocked" not in _codes(assessment)
    footprint_score = next(item for item in assessment.score_dimensions if item.name == "footprint")
    assert footprint_score.score == 1.0


def test_physical_package_pin_map_accepts_exposed_thermal_pad() -> None:
    requirement = ComponentSelectionRequirement(requirement_id="thermal-fp", position="U1", category="power")
    spec = _spec("thermal")
    spec.pins["PGND"] = {"function": "PGND"}
    spec.package_pin_map = {"1": "VIN", "2": "GND", "3": "VOUT", "EP": "PGND"}

    assessment = assess_component_candidate(
        requirement,
        spec,
        _evidence("thermal", footprint=_thermal_footprint_proof()),
    )

    assert "footprint-proof-blocked" not in _codes(assessment)
    footprint_score = next(item for item in assessment.score_dimensions if item.name == "footprint")
    assert footprint_score.score == 1.0


def test_unmapped_exposed_thermal_pad_blocks_candidate() -> None:
    requirement = ComponentSelectionRequirement(requirement_id="thermal-fp-missing", position="U1", category="power")
    spec = _spec("thermal-missing")
    spec.package_pin_map = {"1": "VIN", "2": "GND", "3": "VOUT"}

    assessment = assess_component_candidate(
        requirement,
        spec,
        _evidence("thermal-missing", footprint=_thermal_footprint_proof()),
    )

    assert "footprint-proof-blocked" in _codes(assessment)
    footprint_score = next(item for item in assessment.score_dimensions if item.name == "footprint")
    assert footprint_score.score == 0.0


def test_blocked_footprint_proof_rejects_candidate() -> None:
    requirement = ComponentSelectionRequirement(requirement_id="fp", position="U1", category="power")

    assessment = assess_component_candidate(
        requirement,
        _spec("ldo"),
        _evidence("ldo", footprint=_footprint_proof(missing_pad=True)),
    )

    assert assessment.eligible is False
    assert "footprint-proof-blocked" in _codes(assessment)


def test_blocked_datasheet_fact_report_rejects_candidate() -> None:
    requirement = ComponentSelectionRequirement(requirement_id="ds", position="U1", category="power")

    assessment = assess_component_candidate(
        requirement,
        _spec("ldo"),
        _evidence("ldo", datasheet=_datasheet_report("ldo", missing_hash=True)),
    )

    assert assessment.eligible is False
    assert "datasheet-facts-blocked" in _codes(assessment)


def test_obsolete_or_unavailable_supply_evidence_rejects_candidate() -> None:
    requirement = ComponentSelectionRequirement(
        requirement_id="supply",
        position="U1",
        category="power",
        max_supply_risk=RiskLevel.HIGH,
    )
    supply = BomProviderResult(
        provider="fixture",
        mpn="ldo-MPN",
        manufacturer="Acme",
        lifecycle=LifecycleStatus.OBSOLETE,
        stock=0,
        footprint="Package:SOT-23-5",
    )

    assessment = assess_component_candidate(
        requirement,
        _spec("ldo"),
        _evidence("ldo", supply=supply),
    )

    assert assessment.eligible is False
    assert "supply-risk-blocked" in _codes(assessment)
    assert assessment.extracted_constraints["supply_risk"] == "critical"


def test_release_required_selection_rejects_unapproved_heuristic_candidate() -> None:
    requirement = ComponentSelectionRequirement(
        requirement_id="release",
        position="U1",
        category="power",
        require_release_eligible=True,
    )

    assessment = assess_component_candidate(requirement, _spec("ldo"))

    assert assessment.eligible is False
    assert "release-eligibility-required" in _codes(assessment)


def test_missing_optional_evidence_never_claims_release_readiness() -> None:
    requirement = ComponentSelectionRequirement(requirement_id="review", position="U1", category="power")

    assessment = assess_component_candidate(requirement, _spec("ldo"))

    assert assessment.eligible is True
    assert assessment.human_review_required is True
    assert assessment.release_eligible is False


def test_selection_proof_evidence_includes_selected_constraints_and_rationale() -> None:
    requirement = ComponentSelectionRequirement(
        requirement_id="proof-selection",
        position="U1",
        category="power",
        allowed_packages=["SOT-23-5"],
    )

    decision = select_component(requirement, [_spec("ldo")])
    evidence = decision.proof_evidence()

    assert evidence["selected_component_id"] == "ldo"
    assert evidence["rationale"].startswith("selected ldo")
    assert evidence["extracted_constraints"]["package"] == "SOT-23-5"
    assert evidence["extracted_constraints"]["max_voltage_v"] == 6.0


def test_missing_and_nonnumeric_ratings_require_human_review_without_inventing_limits() -> None:
    spec = _spec("unrated")
    spec.electrical_limits = {"max_voltage_v": "not-a-number"}
    requirement = ComponentSelectionRequirement(
        requirement_id="missing-ratings",
        position="U15",
        category="power",
        operating_voltage_v=3.3,
        operating_current_a=0.2,
    )

    assessment = assess_component_candidate(requirement, spec)

    assert assessment.eligible is True
    assert assessment.human_review_required is True
    assert {"voltage-limit-missing", "current-limit-missing"}.issubset(_codes(assessment))


def test_non_maximum_and_unrelated_datasheet_facts_are_not_promoted_to_constraints() -> None:
    report = DatasheetFactReport(
        component_id="ldo",
        datasheet_url="https://manufacturer.example/part.pdf",
        datasheet_sha256="a" * 64,
        recommended_operating=[
            _fact("ldo", "supply_voltage_typ_v", 3.3, DatasheetFactScope.RECOMMENDED_OPERATING),
            _fact("ldo", "temperature_max_c", 125.0, DatasheetFactScope.RECOMMENDED_OPERATING),
        ],
    )

    assessment = assess_component_candidate(
        ComponentSelectionRequirement(requirement_id="fact-filter", position="U16", category="power"),
        _spec("ldo"),
        _evidence("ldo", datasheet=report),
    )

    assert "recommended_voltage_max_v" not in assessment.extracted_constraints
    assert "temperature_rating" not in assessment.extracted_constraints


def test_operating_point_below_derating_envelope_remains_eligible() -> None:
    assessment = assess_component_candidate(
        ComponentSelectionRequirement(
            requirement_id="within-envelope",
            position="U17",
            category="power",
            operating_current_a=0.5,
        ),
        _spec("ldo"),
    )

    assert assessment.eligible is True
    assert "current-limit-exceeded" not in _codes(assessment)


def test_low_confidence_datasheet_fact_requires_human_review() -> None:
    report = DatasheetFactReport(
        component_id="ldo",
        datasheet_url="https://manufacturer.example/part.pdf",
        datasheet_sha256="a" * 64,
        recommended_operating=[
            _fact(
                "ldo",
                "supply_voltage_max_v",
                5.0,
                DatasheetFactScope.RECOMMENDED_OPERATING,
                confidence=0.5,
            )
        ],
    )

    assessment = assess_component_candidate(
        ComponentSelectionRequirement(requirement_id="low-confidence", position="U18", category="power"),
        _spec("ldo"),
        _evidence("ldo", datasheet=report),
    )

    assert assessment.eligible is True
    assert assessment.human_review_required is True
    assert "datasheet-review-required" in _codes(assessment)


def test_attached_footprint_proof_for_another_package_is_rejected() -> None:
    proof = _footprint_proof()
    proof.package_id = "QFN-32"
    proof.footprint_name = "Package:QFN-32"

    assessment = assess_component_candidate(
        ComponentSelectionRequirement(requirement_id="proof-identity", position="U19", category="power"),
        _spec("ldo"),
        _evidence("ldo", footprint=proof),
    )

    assert assessment.eligible is False
    assert "footprint-proof-mismatch" in _codes(assessment)


@pytest.mark.parametrize(
    ("supply", "expected_risk"),
    [
        (BomProviderResult(provider="fixture", mpn="P", lifecycle=LifecycleStatus.NRND, stock=100), RiskLevel.HIGH),
        (
            BomProviderResult(
                provider="fixture",
                mpn="P",
                lifecycle=LifecycleStatus.ACTIVE,
                stock=100,
                footprint="Package:QFN-32",
            ),
            RiskLevel.HIGH,
        ),
        (
            BomProviderResult(provider="fixture", mpn="P", lifecycle=LifecycleStatus.UNKNOWN, stock=100),
            RiskLevel.MEDIUM,
        ),
        (BomProviderResult(provider="fixture", mpn="P", lifecycle=LifecycleStatus.ACTIVE), RiskLevel.MEDIUM),
        (BomProviderResult(provider="fixture", mpn="P", lifecycle=LifecycleStatus.ACTIVE, stock=20), RiskLevel.MEDIUM),
        (
            BomProviderResult(
                provider="fixture",
                mpn="P",
                lifecycle=LifecycleStatus.ACTIVE,
                stock=100,
                cache=CacheMetadata(status=CacheStatus.STALE),
            ),
            RiskLevel.MEDIUM,
        ),
        (BomProviderResult(provider="fixture", mpn="P", lifecycle=LifecycleStatus.ACTIVE, stock=100), RiskLevel.LOW),
    ],
)
def test_supply_risk_classification_is_explicit(
    supply: BomProviderResult,
    expected_risk: RiskLevel,
) -> None:
    assessment = assess_component_candidate(
        ComponentSelectionRequirement(
            requirement_id=f"supply-{expected_risk.value}",
            position="U20",
            category="power",
            max_supply_risk=RiskLevel.CRITICAL,
        ),
        _spec("ldo"),
        _evidence("ldo", supply=supply),
    )

    assert assessment.extracted_constraints["supply_risk"] == expected_risk.value


def test_candidate_without_footprint_receives_zero_footprint_score() -> None:
    spec = _spec("no-footprint")
    spec.footprint = ""

    assessment = assess_component_candidate(
        ComponentSelectionRequirement(requirement_id="no-footprint", position="U21", category="power"),
        spec,
    )

    footprint = next(item for item in assessment.score_dimensions if item.name == "footprint")
    assert footprint.score == 0.0
    assert footprint.explanation == "component has no usable footprint reference"
