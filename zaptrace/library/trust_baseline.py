"""Monotonic component trust-tier baseline and comparison evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from zaptrace.library.governance import validate_governed_component
from zaptrace.library.schema import ComponentTrustTier

_TIER_ORDER = (
    ComponentTrustTier.PLACEHOLDER,
    ComponentTrustTier.HEURISTIC,
    ComponentTrustTier.CURATED,
    ComponentTrustTier.VERIFIED,
)
_TIER_RANK = {tier: rank for rank, tier in enumerate(_TIER_ORDER)}


class TrustBaseline(BaseModel):
    """Committed trust tier for every governed component ID."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    component_schema_version: Literal["2.0"] = "2.0"
    tier_order: tuple[ComponentTrustTier, ...] = _TIER_ORDER
    component_count: int = Field(ge=0)
    component_tiers: dict[str, ComponentTrustTier]
    library_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_count_and_digest(self) -> TrustBaseline:
        if self.component_count != len(self.component_tiers):
            raise ValueError("component_count does not match component_tiers")
        expected = _library_digest(self.component_tiers)
        if self.library_digest != expected:
            raise ValueError("library_digest does not match component_tiers")
        return self


class TrustBaselineViolation(BaseModel):
    """One monotonic-trust policy violation."""

    code: str
    component_id: str
    message: str
    baseline_tier: ComponentTrustTier | None = None
    current_tier: ComponentTrustTier | None = None


class TrustBaselineReport(BaseModel):
    """Deterministic comparison against the committed baseline."""

    schema_version: Literal["1.0"] = "1.0"
    passed: bool
    baseline_count: int = Field(ge=0)
    current_count: int = Field(ge=0)
    new_component_ids: list[str] = Field(default_factory=list)
    removed_component_ids: list[str] = Field(default_factory=list)
    upgraded_component_ids: list[str] = Field(default_factory=list)
    downgraded_component_ids: list[str] = Field(default_factory=list)
    invalid_stronger_claim_ids: list[str] = Field(default_factory=list)
    violations: list[TrustBaselineViolation] = Field(default_factory=list)


def _tier_value(spec: Any) -> ComponentTrustTier:
    value = getattr(spec, "trust_tier", ComponentTrustTier.HEURISTIC)
    return value if isinstance(value, ComponentTrustTier) else ComponentTrustTier(str(value))


def _library_digest(component_tiers: dict[str, ComponentTrustTier]) -> str:
    payload = {component_id: tier.value for component_id, tier in sorted(component_tiers.items())}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def generate_trust_baseline(specs: dict[str, Any]) -> TrustBaseline:
    """Generate a deterministic trust baseline from validated component specs."""

    tiers = {component_id: _tier_value(specs[component_id]) for component_id in sorted(specs)}
    return TrustBaseline(
        component_count=len(tiers),
        component_tiers=tiers,
        library_digest=_library_digest(tiers),
    )


def compare_trust_baseline(current: dict[str, Any], baseline: TrustBaseline) -> TrustBaselineReport:
    """Reject removals, downgrades, and unsupported stronger trust claims."""

    current_ids = set(current)
    baseline_ids = set(baseline.component_tiers)
    new_ids = sorted(current_ids - baseline_ids)
    removed_ids = sorted(baseline_ids - current_ids)
    upgraded: list[str] = []
    downgraded: list[str] = []
    invalid_stronger: list[str] = []
    violations: list[TrustBaselineViolation] = []

    for component_id in removed_ids:
        violations.append(
            TrustBaselineViolation(
                code="baseline-component-removed",
                component_id=component_id,
                baseline_tier=baseline.component_tiers[component_id],
                message="component present in trust baseline is missing from the current library",
            )
        )

    for component_id in sorted(current_ids & baseline_ids):
        baseline_tier = baseline.component_tiers[component_id]
        current_tier = _tier_value(current[component_id])
        if _TIER_RANK[current_tier] < _TIER_RANK[baseline_tier]:
            downgraded.append(component_id)
            violations.append(
                TrustBaselineViolation(
                    code="trust-tier-downgrade",
                    component_id=component_id,
                    baseline_tier=baseline_tier,
                    current_tier=current_tier,
                    message=f"trust tier downgraded from {baseline_tier.value} to {current_tier.value}",
                )
            )
            continue
        if _TIER_RANK[current_tier] > _TIER_RANK[baseline_tier]:
            validation = validate_governed_component(current[component_id])
            if not validation.valid:
                invalid_stronger.append(component_id)
                violations.append(
                    TrustBaselineViolation(
                        code="invalid-stronger-trust-claim",
                        component_id=component_id,
                        baseline_tier=baseline_tier,
                        current_tier=current_tier,
                        message="stronger trust tier lacks the evidence required by schema v2",
                    )
                )
            else:
                upgraded.append(component_id)

    for component_id in new_ids:
        validation = validate_governed_component(current[component_id])
        if not validation.valid:
            violations.append(
                TrustBaselineViolation(
                    code="invalid-new-component",
                    component_id=component_id,
                    current_tier=_tier_value(current[component_id]),
                    message="new component does not satisfy its declared schema-v2 trust claim",
                )
            )

    return TrustBaselineReport(
        passed=not violations,
        baseline_count=baseline.component_count,
        current_count=len(current),
        new_component_ids=new_ids,
        removed_component_ids=removed_ids,
        upgraded_component_ids=upgraded,
        downgraded_component_ids=downgraded,
        invalid_stronger_claim_ids=invalid_stronger,
        violations=violations,
    )


def _validated_baseline_path(path: str | Path, *, allowed_root: str | Path) -> Path:
    """Resolve one regular JSON file below an explicit workspace boundary."""

    root = Path(allowed_root).resolve(strict=True)
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError(f"trust baseline must not be a symbolic link: {candidate}")
    resolved = candidate.resolve(strict=True)
    if resolved.suffix.lower() != ".json":
        raise ValueError(f"trust baseline must be JSON: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"trust baseline is not a regular file: {resolved}")
    if not resolved.is_relative_to(root):
        raise ValueError(f"trust baseline is outside allowed root {root}: {resolved}")
    return resolved


def load_trust_baseline(path: str | Path, *, allowed_root: str | Path) -> TrustBaseline:
    """Load a committed baseline JSON file from an explicit workspace root."""

    resolved = _validated_baseline_path(path, allowed_root=allowed_root)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    return TrustBaseline.model_validate(payload)


def write_trust_baseline(baseline: TrustBaseline, path: str | Path) -> Path:
    """Write deterministic baseline JSON."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(baseline.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target
