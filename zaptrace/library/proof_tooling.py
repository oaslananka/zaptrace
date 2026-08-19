"""Library provenance and integrity in proof tooling (issue #130).

Makes library provenance reviewable from proof packs so synthesized designs
can explain why each selected part and footprint is trusted.

Public surface
--------------
PartProvenanceRecord    – per-part evidence: provenance, footprint proof,
                          confidence, alternates
DedupeConflict          – blocking finding for conflicting manufacturer identity
PartSelectionEvidence   – why a specific part was chosen (confidence, alternates,
                          dedupe status)
LibraryProofDashboard   – aggregate coverage + integrity for a design's library
build_part_provenance   – build provenance record from a ComponentSpec
select_part_with_evidence – select a part with full evidence record
build_library_proof_dashboard – aggregate dashboard for a set of selected parts
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from zaptrace.library.governance import validate_governed_component
from zaptrace.library.loader import ComponentSpec, LibraryLoader

# ---------------------------------------------------------------------------
# Per-part provenance
# ---------------------------------------------------------------------------


@dataclass
class PartProvenanceRecord:
    """Evidence record for one selected library part.

    Attributes:
        part_id:           Part identifier.
        name:              Human-readable name.
        category:          Part category.
        manufacturer:      Manufacturer name.
        mpn:               Manufacturer part number.
        datasheet:         Datasheet URL (empty string if absent).
        footprint:         Footprint reference.
        footprint_proven:  True if footprint is non-empty and not a placeholder.
        confidence_score:  Governance confidence 0..1.
        confidence_grade:  "high", "medium", or "low".
        missing_metadata:  Governance fields that are absent.
        provenance:        Raw provenance dict from the library entry.
        alternates:        List of alternate part IDs for this MPN.
        dedupe_conflict:   True if this part has a conflicting manufacturer identity.
        selection_reason:  Why this part was chosen over alternates.
        evidence_hash:     Deterministic SHA-256 of the key evidence fields.
    """

    part_id: str
    name: str = ""
    category: str = ""
    manufacturer: str = ""
    mpn: str = ""
    datasheet: str = ""
    footprint: str = ""
    footprint_proven: bool = False
    confidence_score: float = 0.0
    confidence_grade: str = "low"
    trust_tier: str = "placeholder"
    release_eligible: bool = False
    human_review_required: bool = True
    missing_metadata: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    alternates: list[str] = field(default_factory=list)
    dedupe_conflict: bool = False
    selection_reason: str = ""
    evidence_hash: str = ""

    @property
    def is_trusted(self) -> bool:
        """True only when trust policy permits release use and footprint evidence is usable."""
        return self.release_eligible and self.footprint_proven and not self.dedupe_conflict

    @property
    def review_required(self) -> bool:
        """True when trust, footprint, or identity evidence needs human resolution."""
        return (
            self.human_review_required or not self.release_eligible or self.dedupe_conflict or not self.footprint_proven
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "name": self.name,
            "category": self.category,
            "manufacturer": self.manufacturer,
            "mpn": self.mpn,
            "datasheet": self.datasheet,
            "footprint": self.footprint,
            "footprint_proven": self.footprint_proven,
            "confidence_score": self.confidence_score,
            "confidence_grade": self.confidence_grade,
            "trust_tier": self.trust_tier,
            "release_eligible": self.release_eligible,
            "human_review_required": self.human_review_required,
            "missing_metadata": list(self.missing_metadata),
            "provenance": dict(self.provenance),
            "alternates": list(self.alternates),
            "dedupe_conflict": self.dedupe_conflict,
            "selection_reason": self.selection_reason,
            "evidence_hash": self.evidence_hash,
            "is_trusted": self.is_trusted,
            "review_required": self.review_required,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass
class DedupeConflict:
    """A blocking finding for conflicting manufacturer identity.

    Attributes:
        mpn:            The MPN with conflicting entries.
        part_ids:       All part IDs sharing this MPN.
        manufacturers:  Set of manufacturer names (must be 1 for clean state).
        severity:       "blocking" if multi-manufacturer, "review" if same manufacturer.
    """

    mpn: str
    part_ids: list[str] = field(default_factory=list)
    manufacturers: list[str] = field(default_factory=list)
    severity: str = "blocking"

    @property
    def is_blocking(self) -> bool:
        return self.severity == "blocking"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mpn": self.mpn,
            "part_ids": list(self.part_ids),
            "manufacturers": list(self.manufacturers),
            "severity": self.severity,
            "is_blocking": self.is_blocking,
        }


@dataclass
class PartSelectionEvidence:
    """Why a specific part was chosen for a design position.

    Attributes:
        position:        Board position reference (e.g. "U1").
        selected_part_id: The part that was chosen.
        provenance:      Full provenance record for the selected part.
        candidates:      IDs of other parts that were considered.
        selection_rank:  1-based rank (1 = highest confidence first).
        selection_policy: Policy that determined the selection
                          (e.g. "highest_confidence", "first_match").
        selection_hash:   Deterministic SHA-256 of the selection evidence.
    """

    position: str
    selected_part_id: str
    provenance: PartProvenanceRecord | None = None
    candidates: list[str] = field(default_factory=list)
    selection_rank: int = 1
    selection_policy: str = "highest_confidence"
    selection_hash: str = ""

    @property
    def is_trusted(self) -> bool:
        return self.provenance is not None and self.provenance.is_trusted

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "selected_part_id": self.selected_part_id,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "candidates": list(self.candidates),
            "selection_rank": self.selection_rank,
            "selection_policy": self.selection_policy,
            "is_trusted": self.is_trusted,
            "selection_hash": self.selection_hash,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass
class LibraryProofDashboard:
    """Aggregate provenance and integrity dashboard for a design's library.

    Attributes:
        design_name:         Board family identifier.
        part_records:        Per-part provenance records for selected parts.
        dedupe_conflicts:    Blocking or review-required dedupe findings.
        total_selected:      Number of parts selected for this design.
        trusted_count:       Parts with footprint_proven AND medium/high confidence.
        review_required_count: Parts needing human review.
        blocking_count:      Parts with blocking dedupe conflicts.
        category_coverage:   Categories covered by selected parts.
        footprint_gap_count: Parts where footprint is empty or placeholder.
        dashboard_hash:      Deterministic SHA-256 of the dashboard.
    """

    design_name: str
    part_records: list[PartProvenanceRecord] = field(default_factory=list)
    dedupe_conflicts: list[DedupeConflict] = field(default_factory=list)
    total_selected: int = 0
    trusted_count: int = 0
    review_required_count: int = 0
    blocking_count: int = 0
    category_coverage: list[str] = field(default_factory=list)
    footprint_gap_count: int = 0
    dashboard_hash: str = ""

    @property
    def accepted(self) -> bool:
        """True if no blocking dedupe conflicts and all trusted or review-only."""
        return self.blocking_count == 0

    @property
    def trusted_pct(self) -> float:
        if self.total_selected == 0:
            return 1.0
        return self.trusted_count / self.total_selected

    def to_dict(self) -> dict[str, Any]:
        return {
            "design_name": self.design_name,
            "total_selected": self.total_selected,
            "trusted_count": self.trusted_count,
            "review_required_count": self.review_required_count,
            "blocking_count": self.blocking_count,
            "footprint_gap_count": self.footprint_gap_count,
            "trusted_pct": round(self.trusted_pct, 4),
            "accepted": self.accepted,
            "category_coverage": sorted(self.category_coverage),
            "dedupe_conflicts": [c.to_dict() for c in self.dedupe_conflicts],
            "part_records": [r.to_dict() for r in self.part_records],
            "dashboard_hash": self.dashboard_hash,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_FOOTPRINT_PLACEHOLDER_PATTERNS = (
    "internal://",
    "placeholder",
    "todo",
    "unknown",
    "none",
    "tbd",
)


def _is_footprint_proven(footprint: str) -> bool:
    """True if footprint is non-empty and not a generic placeholder."""
    if not footprint or not footprint.strip():
        return False
    lower = footprint.strip().lower()
    return not any(pat in lower for pat in _FOOTPRINT_PLACEHOLDER_PATTERNS)


def _build_evidence_hash(
    part_id: str,
    mpn: str,
    manufacturer: str,
    footprint: str,
    trust_tier: str,
    release_eligible: bool,
) -> str:
    payload = {
        "part_id": part_id,
        "mpn": mpn,
        "manufacturer": manufacturer,
        "footprint": footprint,
        "trust_tier": trust_tier,
        "release_eligible": release_eligible,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _build_selection_hash(position: str, part_id: str, candidates: list[str]) -> str:
    payload = {
        "position": position,
        "part_id": part_id,
        "candidates": sorted(candidates),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _build_dashboard_hash(design_name: str, selected_ids: list[str], blocking_count: int) -> str:
    payload = {
        "design_name": design_name,
        "selected_part_ids": sorted(selected_ids),
        "blocking_count": blocking_count,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _detect_dedupe_conflicts(specs: list[ComponentSpec]) -> list[DedupeConflict]:
    """Detect duplicate MPN entries with conflicting manufacturer identities."""
    by_mpn: dict[str, list[ComponentSpec]] = {}
    for spec in specs:
        key = spec.mpn.strip().upper()
        if key:
            by_mpn.setdefault(key, []).append(spec)

    conflicts: list[DedupeConflict] = []
    for mpn, mpn_specs in by_mpn.items():
        if len(mpn_specs) < 2:
            continue
        manufacturers = sorted({s.manufacturer.strip() for s in mpn_specs})
        is_multi_manufacturer = len(manufacturers) > 1
        conflicts.append(
            DedupeConflict(
                mpn=mpn,
                part_ids=[s.id for s in mpn_specs],
                manufacturers=manufacturers,
                severity="blocking" if is_multi_manufacturer else "review",
            )
        )
    return conflicts


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def build_part_provenance(
    spec: ComponentSpec,
    alternates: list[str] | None = None,
    dedupe_conflict: bool = False,
    selection_reason: str = "",
) -> PartProvenanceRecord:
    """Build a provenance record from a ComponentSpec.

    Args:
        spec:             The component specification.
        alternates:       Other part IDs with the same MPN.
        dedupe_conflict:  True if this part has conflicting manufacturer identity.
        selection_reason: Why this part was selected (optional evidence note).

    Returns:
        PartProvenanceRecord with all evidence fields populated.
    """
    footprint_proven = _is_footprint_proven(spec.footprint)
    validation = validate_governed_component(spec)
    trust_tier = validation.trust_tier.value
    evidence_hash = _build_evidence_hash(
        spec.id,
        spec.mpn,
        spec.manufacturer,
        spec.footprint,
        trust_tier,
        validation.release_eligible,
    )

    return PartProvenanceRecord(
        part_id=spec.id,
        name=spec.name,
        category=spec.category,
        manufacturer=spec.manufacturer,
        mpn=spec.mpn,
        datasheet=spec.datasheet,
        footprint=spec.footprint,
        footprint_proven=footprint_proven,
        confidence_score=spec.confidence_score,
        confidence_grade=spec.confidence_grade,
        trust_tier=trust_tier,
        release_eligible=validation.release_eligible,
        human_review_required=validation.human_review_required,
        missing_metadata=spec.missing_metadata,
        provenance=dict(spec.provenance),
        alternates=list(alternates or []),
        dedupe_conflict=dedupe_conflict,
        selection_reason=selection_reason,
        evidence_hash=evidence_hash,
    )


def select_part_with_evidence(
    position: str,
    category: str,
    candidates: list[ComponentSpec],
    selection_policy: str = "highest_confidence",
) -> PartSelectionEvidence | None:
    """Select the best part for a design position with full evidence.

    Args:
        position:         Board position reference (e.g. "U1").
        category:         Required category filter.
        candidates:       Available parts to choose from.
        selection_policy: Ordering policy ("highest_confidence" or "first_match").

    Returns:
        PartSelectionEvidence, or None if no candidates match.
    """
    matching = [s for s in candidates if s.category == category]
    if not matching:
        return None

    if selection_policy == "highest_confidence":
        matching = sorted(matching, key=lambda s: (-s.confidence_score, s.id))

    selected = matching[0]
    candidate_ids = [s.id for s in matching]
    provenance = build_part_provenance(
        selected,
        alternates=candidate_ids[1:],
        selection_reason=f"{selection_policy} policy; rank 1 of {len(matching)}",
    )

    selection_hash = _build_selection_hash(position, selected.id, candidate_ids)
    return PartSelectionEvidence(
        position=position,
        selected_part_id=selected.id,
        provenance=provenance,
        candidates=candidate_ids,
        selection_rank=1,
        selection_policy=selection_policy,
        selection_hash=selection_hash,
    )


@dataclass
class _DashboardSummary:
    records: list[PartProvenanceRecord] = field(default_factory=list)
    trusted_count: int = 0
    review_count: int = 0
    blocking_count: int = 0
    footprint_gap_count: int = 0
    categories: set[str] = field(default_factory=set)


def _load_dashboard_specs(
    selected_parts: list[ComponentSpec] | None,
    library_root: None,
    max_parts: int,
) -> list[ComponentSpec]:
    if selected_parts is not None:
        return selected_parts[:max_parts]

    from pathlib import Path

    default_root = Path(__file__).parent.parent.parent / "data" / "library"
    root = Path(library_root) if library_root else default_root
    return list(LibraryLoader(root).load_all().values())[:max_parts]


def _alternates_by_part(specs: list[ComponentSpec]) -> dict[str, list[str]]:
    by_mpn: dict[str, list[str]] = {}
    for spec in specs:
        key = spec.mpn.strip().upper()
        if key:
            by_mpn.setdefault(key, []).append(spec.id)
    return {
        spec.id: [part_id for part_id in by_mpn.get(spec.mpn.strip().upper(), []) if part_id != spec.id]
        for spec in specs
    }


def _part_has_blocking_conflict(spec: ComponentSpec, conflicts: list[DedupeConflict]) -> bool:
    return any(conflict.is_blocking for conflict in conflicts if spec.id in conflict.part_ids)


def _summarize_dashboard_parts(
    specs: list[ComponentSpec],
    conflicts: list[DedupeConflict],
) -> _DashboardSummary:
    conflict_parts = {part_id for conflict in conflicts for part_id in conflict.part_ids}
    alternates = _alternates_by_part(specs)
    summary = _DashboardSummary()
    for spec in specs:
        has_conflict = spec.id in conflict_parts
        provenance = build_part_provenance(
            spec,
            alternates=alternates.get(spec.id, []),
            dedupe_conflict=has_conflict,
        )
        summary.records.append(provenance)
        summary.trusted_count += int(provenance.is_trusted)
        summary.review_count += int(provenance.review_required)
        summary.blocking_count += int(_part_has_blocking_conflict(spec, conflicts) or not provenance.release_eligible)
        summary.footprint_gap_count += int(not provenance.footprint_proven)
        summary.categories.add(spec.category)
    return summary


def build_library_proof_dashboard(
    design_name: str,
    selected_parts: list[ComponentSpec] | None = None,
    library_root: None = None,
    max_parts: int = 100,
) -> LibraryProofDashboard:
    """Build an aggregate provenance and integrity dashboard.

    Args:
        design_name:    Board family identifier.
        selected_parts: Parts selected for this design. If None, loads all from library.
        library_root:   Override library root path.
        max_parts:      Maximum parts to include in the dashboard (bounded for determinism).

    Returns:
        LibraryProofDashboard with per-part records, dedupe conflicts, and hashes.
    """
    specs = _load_dashboard_specs(selected_parts, library_root, max_parts)
    conflicts = _detect_dedupe_conflicts(specs)
    summary = _summarize_dashboard_parts(specs, conflicts)
    selected_ids = [record.part_id for record in summary.records]
    dashboard_hash = _build_dashboard_hash(design_name, selected_ids, summary.blocking_count)
    return LibraryProofDashboard(
        design_name=design_name,
        part_records=summary.records,
        dedupe_conflicts=conflicts,
        total_selected=len(summary.records),
        trusted_count=summary.trusted_count,
        review_required_count=summary.review_count,
        blocking_count=summary.blocking_count,
        category_coverage=list(summary.categories),
        footprint_gap_count=summary.footprint_gap_count,
        dashboard_hash=dashboard_hash,
    )
