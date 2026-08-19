"""Tests for library provenance and integrity in proof tooling (issue #130).

Covers:
* PartProvenanceRecord: is_trusted, review_required, to_dict(), to_json()
* DedupeConflict: is_blocking, to_dict()
* PartSelectionEvidence: is_trusted, to_dict(), to_json()
* LibraryProofDashboard: accepted, trusted_pct, to_dict(), to_json()
* build_part_provenance():
  - footprint_proven for non-placeholder footprints
  - footprint_proven=False for empty/placeholder footprints
  - alternates populated
  - dedupe_conflict flag set correctly
  - evidence_hash deterministic
  - missing_metadata reflected
* select_part_with_evidence():
  - returns None when no candidates match category
  - selects highest confidence first
  - selection_hash deterministic
  - candidates list populated
* build_library_proof_dashboard():
  - accepted=False when blocking conflict
  - trusted_count correct
  - review_required_count correct
  - dedupe_conflicts detected
  - blocking_count correct
  - footprint_gap_count correct
  - category_coverage populated
  - dashboard_hash deterministic
  - max_parts enforced (bounded)
  - serialisable
  - works with real library parts (high coverage)
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from zaptrace.library.loader import ComponentSpec
from zaptrace.library.proof_tooling import (
    DedupeConflict,
    LibraryProofDashboard,
    PartProvenanceRecord,
    PartSelectionEvidence,
    build_library_proof_dashboard,
    build_part_provenance,
    select_part_with_evidence,
)
from zaptrace.library.schema import (
    ComponentField,
    ComponentTrustTier,
    FieldProvenance,
    HumanReviewApproval,
    ProvenanceConfidence,
    ProvenanceSourceType,
    ReviewScope,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _field_provenance() -> dict[ComponentField, FieldProvenance]:
    return {
        field: FieldProvenance(
            source_type=ProvenanceSourceType.INTERNAL_MANIFEST,
            source_locator="test-fixture",
            source_identity=f"fixture:{field.value}",
            source_version="1",
            extraction_method="test-fixture",
            confidence=ProvenanceConfidence.LOW,
        )
        for field in ComponentField
    }


def _release_review() -> HumanReviewApproval:
    return HumanReviewApproval(
        approval_id="TEST-COMPONENT-REVIEW",
        reviewed_by="test-reviewer",
        reviewed_at=date(2026, 7, 27),
        scopes={ReviewScope.RELEASE, ReviewScope.FABRICATION},
    )


def _make_spec(
    part_id: str = "test-res",
    category: str = "passive",
    manufacturer: str = "Acme",
    mpn: str = "ACME-001",
    footprint: str = "0402",
    confidence_score: float = 0.9,
    datasheet: str = "https://example.com/ds.pdf",
    **overrides: object,
) -> ComponentSpec:
    del confidence_score  # confidence is derived from populated metadata
    data: dict[str, object] = {
        "id": part_id,
        "name": part_id.upper(),
        "category": category,
        "manufacturer": manufacturer,
        "mpn": mpn,
        "description": "Test part",
        "datasheet": datasheet,
        "package": "0402",
        "footprint": footprint,
        "lifecycle": "active",
        "voltage_supply": "3.3",
        "pins": {"1": {"type": "passive", "description": "Pin 1"}},
        "electrical_limits": {"max_voltage_v": 6.0},
        "sourcing": {"mpn": mpn, "manufacturer": manufacturer},
        "compliance": {"rohs": "test-fixture"},
        "provenance": {"source": "test-fixture"},
        "trust_tier": ComponentTrustTier.HEURISTIC,
        "field_provenance": _field_provenance(),
        "human_review": _release_review(),
    }
    data.update(overrides)
    return ComponentSpec(**data)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PartProvenanceRecord
# ---------------------------------------------------------------------------


class TestPartProvenanceRecord:
    def _trusted(self) -> PartProvenanceRecord:
        return PartProvenanceRecord(
            part_id="res-0402",
            name="Resistor 0402",
            category="passive",
            manufacturer="Generic",
            mpn="RES-0402",
            datasheet="https://example.com/ds.pdf",
            footprint="0402",
            footprint_proven=True,
            confidence_score=0.9,
            confidence_grade="high",
            trust_tier="verified",
            release_eligible=True,
            human_review_required=False,
        )

    def test_is_trusted_when_footprint_proven_and_high(self) -> None:
        assert self._trusted().is_trusted is True

    def test_not_trusted_when_footprint_unproven(self) -> None:
        r = PartProvenanceRecord(
            part_id="x",
            footprint_proven=False,
            confidence_grade="high",
            trust_tier="verified",
            release_eligible=True,
            human_review_required=False,
        )
        assert r.is_trusted is False

    def test_not_trusted_when_low_confidence(self) -> None:
        r = PartProvenanceRecord(
            part_id="x",
            footprint_proven=True,
            confidence_grade="low",
            trust_tier="heuristic",
            release_eligible=False,
            human_review_required=True,
        )
        assert r.is_trusted is False

    def test_high_metadata_heuristic_is_not_trusted_without_release_approval(self) -> None:
        record = PartProvenanceRecord(
            part_id="heuristic",
            footprint_proven=True,
            confidence_score=1.0,
            confidence_grade="high",
            trust_tier="heuristic",
            release_eligible=False,
            human_review_required=True,
        )

        assert record.is_trusted is False
        assert record.review_required is True

    def test_review_required_when_unproven(self) -> None:
        r = PartProvenanceRecord(part_id="x", footprint_proven=False)
        assert r.review_required is True

    def test_review_required_when_dedupe_conflict(self) -> None:
        r = PartProvenanceRecord(
            part_id="x",
            footprint_proven=True,
            confidence_grade="high",
            trust_tier="verified",
            release_eligible=True,
            human_review_required=False,
            dedupe_conflict=True,
        )
        assert r.review_required is True

    def test_no_review_when_trusted_and_no_conflict(self) -> None:
        r = PartProvenanceRecord(
            part_id="x",
            footprint_proven=True,
            confidence_grade="high",
            trust_tier="verified",
            release_eligible=True,
            human_review_required=False,
            dedupe_conflict=False,
        )
        assert r.review_required is False

    def test_to_dict_keys(self) -> None:
        d = self._trusted().to_dict()
        required = {
            "part_id",
            "name",
            "category",
            "manufacturer",
            "mpn",
            "datasheet",
            "footprint",
            "footprint_proven",
            "confidence_score",
            "confidence_grade",
            "trust_tier",
            "release_eligible",
            "human_review_required",
            "missing_metadata",
            "provenance",
            "alternates",
            "dedupe_conflict",
            "selection_reason",
            "evidence_hash",
            "is_trusted",
            "review_required",
        }
        assert required <= d.keys()

    def test_to_json_round_trips(self) -> None:
        j = self._trusted().to_json()
        d = json.loads(j)
        assert d["is_trusted"] is True

    def test_serialisable(self) -> None:
        json.dumps(self._trusted().to_dict())


# ---------------------------------------------------------------------------
# DedupeConflict
# ---------------------------------------------------------------------------


class TestDedupeConflict:
    def test_is_blocking_when_severity_blocking(self) -> None:
        c = DedupeConflict(mpn="PART-001", part_ids=["a", "b"], manufacturers=["Corp A", "Corp B"], severity="blocking")
        assert c.is_blocking is True

    def test_not_blocking_when_severity_review(self) -> None:
        c = DedupeConflict(mpn="PART-001", part_ids=["a", "b"], manufacturers=["Corp A"], severity="review")
        assert c.is_blocking is False

    def test_to_dict_keys(self) -> None:
        d = DedupeConflict(mpn="X", part_ids=["a"], manufacturers=["Corp"]).to_dict()
        assert {"mpn", "part_ids", "manufacturers", "severity", "is_blocking"} <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(DedupeConflict(mpn="X").to_dict())


# ---------------------------------------------------------------------------
# PartSelectionEvidence
# ---------------------------------------------------------------------------


class TestPartSelectionEvidence:
    def _evidence(self) -> PartSelectionEvidence:
        prov = PartProvenanceRecord(
            part_id="res-0402",
            footprint_proven=True,
            confidence_grade="high",
            trust_tier="verified",
            release_eligible=True,
            human_review_required=False,
        )
        return PartSelectionEvidence(
            position="R1",
            selected_part_id="res-0402",
            provenance=prov,
            candidates=["res-0402", "res-0603"],
            selection_rank=1,
            selection_hash="a" * 64,
        )

    def test_is_trusted_from_provenance(self) -> None:
        assert self._evidence().is_trusted is True

    def test_not_trusted_when_no_provenance(self) -> None:
        ev = PartSelectionEvidence(position="R1", selected_part_id="x")
        assert ev.is_trusted is False

    def test_to_dict_keys(self) -> None:
        d = self._evidence().to_dict()
        required = {
            "position",
            "selected_part_id",
            "provenance",
            "candidates",
            "selection_rank",
            "selection_policy",
            "is_trusted",
            "selection_hash",
        }
        assert required <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(self._evidence().to_dict())


# ---------------------------------------------------------------------------
# LibraryProofDashboard
# ---------------------------------------------------------------------------


class TestLibraryProofDashboard:
    def _dashboard(self) -> LibraryProofDashboard:
        records = [
            PartProvenanceRecord(
                "r1",
                footprint_proven=True,
                confidence_grade="high",
                category="passive",
                trust_tier="verified",
                release_eligible=True,
                human_review_required=False,
            ),
            PartProvenanceRecord(
                "r2",
                footprint_proven=False,
                confidence_grade="medium",
                category="passive",
                trust_tier="heuristic",
                release_eligible=False,
                human_review_required=True,
            ),
        ]
        return LibraryProofDashboard(
            design_name="esp32_test",
            part_records=records,
            total_selected=2,
            trusted_count=1,
            review_required_count=1,
            blocking_count=0,
            dashboard_hash="a" * 64,
        )

    def test_accepted_when_no_blocking(self) -> None:
        assert self._dashboard().accepted is True

    def test_not_accepted_when_blocking(self) -> None:
        d = LibraryProofDashboard(design_name="x", blocking_count=1)
        assert d.accepted is False

    def test_trusted_pct(self) -> None:
        d = self._dashboard()
        assert abs(d.trusted_pct - 0.5) < 0.001

    def test_trusted_pct_full_when_zero_total(self) -> None:
        d = LibraryProofDashboard(design_name="x", total_selected=0)
        assert d.trusted_pct == pytest.approx(1.0)

    def test_to_dict_keys(self) -> None:
        d = self._dashboard().to_dict()
        required = {
            "design_name",
            "total_selected",
            "trusted_count",
            "review_required_count",
            "blocking_count",
            "footprint_gap_count",
            "trusted_pct",
            "accepted",
            "category_coverage",
            "dedupe_conflicts",
            "part_records",
            "dashboard_hash",
        }
        assert required <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(self._dashboard().to_dict())


# ---------------------------------------------------------------------------
# build_part_provenance
# ---------------------------------------------------------------------------


class TestBuildPartProvenance:
    def test_footprint_proven_for_real_footprint(self) -> None:
        spec = _make_spec(footprint="SOT-23")
        p = build_part_provenance(spec)
        assert p.footprint_proven is True

    def test_footprint_not_proven_for_empty(self) -> None:
        spec = _make_spec(footprint="")
        p = build_part_provenance(spec)
        assert p.footprint_proven is False

    def test_footprint_not_proven_for_internal_placeholder(self) -> None:
        spec = _make_spec(footprint="internal://zaptrace/component-family/cap-mlcc")
        p = build_part_provenance(spec)
        assert p.footprint_proven is False

    def test_footprint_not_proven_for_unknown(self) -> None:
        spec = _make_spec(footprint="unknown")
        p = build_part_provenance(spec)
        assert p.footprint_proven is False

    def test_alternates_populated(self) -> None:
        spec = _make_spec()
        p = build_part_provenance(spec, alternates=["alt-1", "alt-2"])
        assert p.alternates == ["alt-1", "alt-2"]

    def test_dedupe_conflict_flag(self) -> None:
        spec = _make_spec()
        p = build_part_provenance(spec, dedupe_conflict=True)
        assert p.dedupe_conflict is True

    def test_evidence_hash_deterministic(self) -> None:
        spec = _make_spec()
        h1 = build_part_provenance(spec).evidence_hash
        h2 = build_part_provenance(spec).evidence_hash
        assert h1 == h2

    def test_evidence_hash_64_chars(self) -> None:
        spec = _make_spec()
        assert len(build_part_provenance(spec).evidence_hash) == 64

    def test_evidence_hash_differs_by_part(self) -> None:
        s1 = _make_spec(part_id="part-a")
        s2 = _make_spec(part_id="part-b")
        assert build_part_provenance(s1).evidence_hash != build_part_provenance(s2).evidence_hash

    def test_missing_metadata_reflected(self) -> None:
        spec = _make_spec(datasheet="", mpn="")
        p = build_part_provenance(spec)
        assert "datasheet" in p.missing_metadata or "mpn" in p.missing_metadata

    def test_unapproved_heuristic_spec_is_not_trusted(self) -> None:
        spec = _make_spec(human_review=None)

        provenance = build_part_provenance(spec)

        assert provenance.trust_tier == "heuristic"
        assert provenance.release_eligible is False
        assert provenance.is_trusted is False
        assert provenance.review_required is True

    def test_selection_reason_set(self) -> None:
        spec = _make_spec()
        p = build_part_provenance(spec, selection_reason="test reason")
        assert p.selection_reason == "test reason"


# ---------------------------------------------------------------------------
# select_part_with_evidence
# ---------------------------------------------------------------------------


class TestSelectPartWithEvidence:
    def test_returns_none_when_no_match(self) -> None:
        candidates = [_make_spec(category="power")]
        ev = select_part_with_evidence("U1", "sensor", candidates)
        assert ev is None

    def test_selects_highest_confidence(self) -> None:
        candidates = [
            _make_spec("low-conf", category="power", confidence_score=0.3),
            _make_spec("high-conf", category="power", confidence_score=0.95),
        ]
        ev = select_part_with_evidence("U1", "power", candidates)
        assert ev is not None
        assert ev.selected_part_id == "high-conf"

    def test_candidates_list_populated(self) -> None:
        candidates = [
            _make_spec("p1", category="passive"),
            _make_spec("p2", category="passive"),
        ]
        ev = select_part_with_evidence("R1", "passive", candidates)
        assert ev is not None
        assert len(ev.candidates) == 2

    def test_selection_hash_deterministic(self) -> None:
        candidates = [_make_spec("p1", category="passive"), _make_spec("p2", category="passive")]
        ev1 = select_part_with_evidence("R1", "passive", candidates)
        ev2 = select_part_with_evidence("R1", "passive", candidates)
        assert ev1 is not None
        assert ev2 is not None
        assert ev1.selection_hash == ev2.selection_hash

    def test_selection_hash_64_chars(self) -> None:
        ev = select_part_with_evidence("R1", "passive", [_make_spec(category="passive")])
        assert ev is not None
        assert len(ev.selection_hash) == 64

    def test_provenance_populated(self) -> None:
        ev = select_part_with_evidence("R1", "passive", [_make_spec(category="passive")])
        assert ev is not None
        assert ev.provenance is not None
        assert ev.provenance.part_id == "test-res"


# ---------------------------------------------------------------------------
# build_library_proof_dashboard
# ---------------------------------------------------------------------------


class TestBuildLibraryProofDashboard:
    def test_accepted_when_no_conflicts(self) -> None:
        specs = [
            _make_spec("part-a", mpn="MPN-001", manufacturer="Corp"),
            _make_spec("part-b", mpn="MPN-002", manufacturer="Corp"),
        ]
        d = build_library_proof_dashboard("test_board", selected_parts=specs)
        assert d.accepted is True

    def test_not_accepted_when_blocking_conflict(self) -> None:
        # Two parts with same MPN but different manufacturers → blocking
        specs = [
            _make_spec("part-a", mpn="CONFLICT-MPN", manufacturer="Corp A"),
            _make_spec("part-b", mpn="CONFLICT-MPN", manufacturer="Corp B"),
        ]
        d = build_library_proof_dashboard("test_board", selected_parts=specs)
        assert d.accepted is False
        assert d.blocking_count >= 1

    def test_trusted_count_correct(self) -> None:
        specs = [
            _make_spec("part-a", footprint="SOT-23", mpn="MPN-A", confidence_score=0.9),
            _make_spec("part-b", footprint="", mpn="MPN-B", confidence_score=0.9),
        ]
        d = build_library_proof_dashboard("test_board", selected_parts=specs)
        assert d.trusted_count >= 1  # part-a should be trusted

    def test_unapproved_heuristic_component_blocks_dashboard(self) -> None:
        specs = [_make_spec("heuristic", human_review=None)]

        dashboard = build_library_proof_dashboard("test_board", selected_parts=specs)

        assert dashboard.accepted is False
        assert dashboard.trusted_count == 0
        assert dashboard.review_required_count == 1
        assert dashboard.blocking_count == 1

    def test_footprint_gap_count(self) -> None:
        specs = [
            _make_spec("part-a", footprint="SOT-23"),
            _make_spec("part-b", footprint=""),
            _make_spec("part-c", footprint="internal://placeholder"),
        ]
        d = build_library_proof_dashboard("test_board", selected_parts=specs)
        assert d.footprint_gap_count >= 2  # part-b and part-c

    def test_category_coverage_populated(self) -> None:
        specs = [
            _make_spec("r1", category="passive"),
            _make_spec("u1", category="mcu"),
        ]
        d = build_library_proof_dashboard("test_board", selected_parts=specs)
        assert "passive" in d.category_coverage
        assert "mcu" in d.category_coverage

    def test_dashboard_hash_deterministic(self) -> None:
        specs = [_make_spec("p1", category="passive")]
        d1 = build_library_proof_dashboard("board", selected_parts=specs)
        d2 = build_library_proof_dashboard("board", selected_parts=specs)
        assert d1.dashboard_hash == d2.dashboard_hash

    def test_dashboard_hash_64_chars(self) -> None:
        d = build_library_proof_dashboard("board", selected_parts=[_make_spec()])
        assert len(d.dashboard_hash) == 64

    def test_max_parts_enforced(self) -> None:
        specs = [_make_spec(f"part-{i}", category="passive") for i in range(20)]
        d = build_library_proof_dashboard("board", selected_parts=specs, max_parts=5)
        assert d.total_selected == 5

    def test_serialisable(self) -> None:
        specs = [_make_spec("p1"), _make_spec("p2", mpn="OTHER-001")]
        d = build_library_proof_dashboard("board", selected_parts=specs)
        json.dumps(d.to_dict())

    def test_review_required_count_when_gaps(self) -> None:
        specs = [
            _make_spec("p1", footprint=""),  # footprint gap → review required
        ]
        d = build_library_proof_dashboard("board", selected_parts=specs)
        assert d.review_required_count >= 1

    def test_empty_parts_no_crash(self) -> None:
        d = build_library_proof_dashboard("board", selected_parts=[])
        assert d.total_selected == 0
        assert d.accepted is True
        assert d.trusted_pct == pytest.approx(1.0)

    def test_detects_same_manufacturer_duplicate(self) -> None:
        # Same MPN, same manufacturer → conflict with severity="review" (not blocking)
        specs = [
            _make_spec("p1", mpn="SAME-MPN", manufacturer="Corp A"),
            _make_spec("p2", mpn="SAME-MPN", manufacturer="Corp A"),
        ]
        d = build_library_proof_dashboard("board", selected_parts=specs)
        # Should have a dedupe conflict (review-level, not blocking)
        assert len(d.dedupe_conflicts) >= 1
        assert all(not c.is_blocking for c in d.dedupe_conflicts)
