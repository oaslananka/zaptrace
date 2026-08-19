"""Provider-agnostic BOM intelligence contracts and deterministic fixture provider."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field

from zaptrace.core.models import Component, Design


class LifecycleStatus(StrEnum):
    ACTIVE = "active"
    NRND = "nrnd"
    OBSOLETE = "obsolete"
    UNKNOWN = "unknown"


class CacheStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISS = "miss"
    FIXTURE = "fixture"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CacheMetadata(BaseModel):
    """Cache provenance and freshness metadata for one provider lookup."""

    model_config = ConfigDict(strict=False)

    status: CacheStatus = CacheStatus.MISS
    source: str = ""
    fetched_at: str | None = None
    max_age_hours: int = Field(default=24, ge=0)
    age_hours: float | None = Field(default=None, ge=0)
    offline: bool = False

    @property
    def stale(self) -> bool:
        return self.status == CacheStatus.STALE or (
            self.age_hours is not None and self.max_age_hours > 0 and self.age_hours > self.max_age_hours
        )


class PriceBreak(BaseModel):
    model_config = ConfigDict(strict=False)

    quantity: int = Field(ge=1)
    unit_price: float = Field(ge=0)
    currency: str = "USD"


class AlternatePart(BaseModel):
    model_config = ConfigDict(strict=False)

    mpn: str
    manufacturer: str = ""
    distributor_part_number: str = ""
    reason: str = ""
    footprint: str = ""
    lifecycle: LifecycleStatus = LifecycleStatus.UNKNOWN


class BomProviderResult(BaseModel):
    """Provider-agnostic typed output for one manufacturer part lookup."""

    model_config = ConfigDict(strict=False)

    provider: str
    mpn: str
    manufacturer: str = ""
    distributor: str = ""
    distributor_part_number: str = ""
    stock: int | None = Field(default=None, ge=0)
    lifecycle: LifecycleStatus = LifecycleStatus.UNKNOWN
    rohs_compliant: bool | None = None
    compliance_flags: list[str] = Field(default_factory=list)
    price_breaks: list[PriceBreak] = Field(default_factory=list)
    alternates: list[AlternatePart] = Field(default_factory=list)
    footprint: str = ""
    cache: CacheMetadata = Field(default_factory=CacheMetadata)
    raw: dict[str, Any] = Field(default_factory=dict)


class BomLineRisk(BaseModel):
    """Risk assessment for one design component after BOM enrichment."""

    model_config = ConfigDict(strict=False)

    ref: str
    mpn: str = ""
    manufacturer: str = ""
    provider: str = ""
    distributor_part_number: str = ""
    stock: int | None = None
    lifecycle: LifecycleStatus = LifecycleStatus.UNKNOWN
    risk_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    flags: list[str] = Field(default_factory=list)
    alternates: list[AlternatePart] = Field(default_factory=list)
    cache: CacheMetadata = Field(default_factory=CacheMetadata)
    dnp: bool = False


class BomRiskReport(BaseModel):
    """Complete deterministic BOM risk report with provider provenance."""

    model_config = ConfigDict(strict=False)

    design: str
    generated_at: str
    provider: str
    cache_policy: str
    blocked: bool
    highest_risk: RiskLevel
    items: list[BomLineRisk]
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "BOM intelligence is provider evidence, not procurement approval.",
            "Stock and price data can change after the cache timestamp.",
            "Human review is required before purchasing or fabrication.",
        ]
    )


class BomIntelligenceProvider(Protocol):
    """Provider interface for deterministic BOM enrichment."""

    name: str
    cache_policy: str

    def lookup_mpn(self, mpn: str) -> BomProviderResult | None:
        """Return typed intelligence for an MPN, or ``None`` when the provider has no match."""
        ...


class FixtureBomProvider:
    """Deterministic BOM provider backed by a JSON/YAML fixture."""

    def __init__(self, parts: dict[str, Any], *, name: str = "fixture", cache_policy: str = "fixture-only") -> None:
        self.name = name
        self.cache_policy = cache_policy
        self._parts = parts

    @classmethod
    def from_file(cls, path: str | Path) -> FixtureBomProvider:
        fixture_path = Path(path)
        raw = fixture_path.read_text(encoding="utf-8")
        data = json.loads(raw) if fixture_path.suffix.lower() == ".json" else yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError(f"BOM fixture must be a mapping: {fixture_path}")
        provider = str(data.get("provider", fixture_path.stem))
        cache_policy = str(data.get("cache_policy", "fixture-only"))
        parts = data.get("parts", data)
        if not isinstance(parts, dict):
            raise ValueError(f"BOM fixture parts must be a mapping: {fixture_path}")
        return cls(parts, name=provider, cache_policy=cache_policy)

    def lookup_mpn(self, mpn: str) -> BomProviderResult | None:
        item = self._parts.get(mpn)
        if item is None:
            return None
        if not isinstance(item, dict):
            raise ValueError(f"Fixture part {mpn!r} must be a mapping")
        payload = {
            "provider": self.name,
            "mpn": mpn,
            "cache": {"status": CacheStatus.FIXTURE, "source": self.cache_policy, "offline": True},
            **item,
        }
        return BomProviderResult.model_validate(payload)


def _risk_level(score: int) -> RiskLevel:
    if score >= 80:
        return RiskLevel.CRITICAL
    if score >= 50:
        return RiskLevel.HIGH
    if score >= 20:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _component_mpn(component: Component) -> str:
    return component.mpn or component.lcsc_id or component.value or component.ref


def _score_component(component: Component, result: BomProviderResult | None) -> tuple[int, list[str]]:
    if component.dnp:
        return 0, ["dnp"]

    score = 0
    flags: list[str] = []
    if result is None:
        return 90, ["provider-miss", "unresolved-required-part"]

    if result.stock is None:
        score += 15
        flags.append("stock-unknown")
    elif result.stock == 0:
        score += 45
        flags.append("unavailable")
    elif result.stock < 100:
        score += 15
        flags.append("low-availability")

    if result.lifecycle == LifecycleStatus.OBSOLETE:
        score += 55
        flags.append("obsolete")
    elif result.lifecycle == LifecycleStatus.NRND:
        score += 25
        flags.append("nrnd")
    elif result.lifecycle == LifecycleStatus.UNKNOWN:
        score += 10
        flags.append("lifecycle-unknown")

    if result.rohs_compliant is False:
        score += 25
        flags.append("non-rohs")
    if result.compliance_flags:
        score += min(20, 5 * len(result.compliance_flags))
        flags.extend(f"compliance:{flag}" for flag in result.compliance_flags)
    if not result.alternates:
        score += 10
        flags.append("single-source")
    if result.cache.stale:
        score += 10
        flags.append("cache-stale")
    if component.footprint and result.footprint and component.footprint != result.footprint:
        score += 25
        flags.append("footprint-mismatch")

    return min(score, 100), flags


def _bom_line_for_component(component: Component, provider: BomIntelligenceProvider) -> BomLineRisk:
    mpn = _component_mpn(component)
    result = provider.lookup_mpn(mpn) if mpn else None
    score, flags = _score_component(component, result)
    cache = result.cache if result else CacheMetadata(status=CacheStatus.MISS, source=provider.cache_policy)
    return BomLineRisk(
        ref=component.ref,
        mpn=mpn,
        manufacturer=result.manufacturer if result else (component.manufacturer or ""),
        provider=result.provider if result else provider.name,
        distributor_part_number=result.distributor_part_number if result else "",
        stock=result.stock if result else None,
        lifecycle=result.lifecycle if result else LifecycleStatus.UNKNOWN,
        risk_score=score,
        risk_level=_risk_level(score),
        flags=flags,
        alternates=result.alternates if result else [],
        cache=cache,
        dnp=component.dnp,
    )


def _bom_line_provenance(line: BomLineRisk) -> dict[str, Any]:
    return {
        "ref": line.ref,
        "mpn": line.mpn,
        "provider": line.provider,
        "cache_status": line.cache.status,
        "cache_age_hours": line.cache.age_hours,
        "source": line.cache.source,
    }


def _highest_bom_risk(items: list[BomLineRisk]) -> RiskLevel:
    return max(
        (item.risk_level for item in items),
        key=lambda level: list(RiskLevel).index(level),
        default=RiskLevel.LOW,
    )


def _bom_report_blocked(items: list[BomLineRisk]) -> bool:
    return any(item.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL} for item in items if not item.dnp)


def enrich_bom_with_provider(
    design: Design,
    provider: BomIntelligenceProvider,
    *,
    generated_at: datetime | None = None,
) -> BomRiskReport:
    """Enrich a design BOM and return a deterministic risk/provenance report."""
    now = generated_at or datetime.now(UTC)
    items = [
        _bom_line_for_component(component, provider)
        for component in sorted(design.components.values(), key=lambda item: item.ref)
    ]
    return BomRiskReport(
        design=design.meta.name,
        generated_at=now.isoformat(),
        provider=provider.name,
        cache_policy=provider.cache_policy,
        blocked=_bom_report_blocked(items),
        highest_risk=_highest_bom_risk(items),
        items=items,
        provenance=[_bom_line_provenance(item) for item in items],
    )
