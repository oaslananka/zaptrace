from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from zaptrace.core.models import Component, Design, DesignMeta
from zaptrace.proof.manifest import BomProvenanceEvidence, ProofManifest
from zaptrace.supply import FixtureBomProvider, LcscBomProvider, LifecycleStatus, RiskLevel, enrich_bom_with_provider

FIXTURE = Path("tests/fixtures/supply/benchmark_001_parts.yaml")


def _benchmark_design() -> Design:
    design = Design(meta=DesignMeta(name="benchmark-001-supply-fixture"))
    design.components = {
        "u1": Component(
            id="u1",
            ref="U1",
            type="mcu",
            mpn="ESP32-S3-WROOM-1-N8",
            manufacturer="Espressif",
            footprint="ESP32-S3-WROOM-1",
        ),
        "u2": Component(
            id="u2",
            ref="U2",
            type="sensor",
            mpn="BME280",
            manufacturer="Bosch",
            footprint="LGA-8",
        ),
        "u3": Component(
            id="u3",
            ref="U3",
            type="regulator",
            mpn="AP2112K-3.3",
            manufacturer="Diodes Incorporated",
            footprint="SOT-23-5",
        ),
        "r1": Component(id="r1", ref="R1", type="resistor", mpn="UNKNOWN-10K", footprint="0603"),
        "r2": Component(id="r2", ref="R2", type="resistor", mpn="DNP-ALT", footprint="0603", dnp=True),
    }
    return design


def test_empty_bom_report_preserves_low_unblocked_defaults() -> None:
    provider = FixtureBomProvider({})
    design = Design(meta=DesignMeta(name="empty-bom"))

    report = enrich_bom_with_provider(design, provider, generated_at=datetime(2026, 7, 31, tzinfo=UTC))

    assert report.items == []
    assert report.provenance == []
    assert report.highest_risk == RiskLevel.LOW
    assert report.blocked is False


def test_fixture_provider_returns_typed_output() -> None:
    provider = FixtureBomProvider.from_file(FIXTURE)

    result = provider.lookup_mpn("ESP32-S3-WROOM-1-N8")

    assert result is not None
    assert result.provider == "benchmark-fixture-distributor"
    assert result.lifecycle == LifecycleStatus.ACTIVE
    assert result.cache.offline is True
    assert result.price_breaks[0].quantity == 1
    assert result.alternates[0].mpn == "ESP32-S3-WROOM-1-N16R8"


def test_enrich_bom_flags_unavailable_obsolete_and_provider_miss() -> None:
    provider = FixtureBomProvider.from_file(FIXTURE)
    report = enrich_bom_with_provider(
        _benchmark_design(),
        provider,
        generated_at=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
    )

    by_ref = {item.ref: item for item in report.items}
    assert report.blocked is True
    assert report.highest_risk == RiskLevel.CRITICAL
    assert by_ref["U1"].risk_level == RiskLevel.LOW
    assert by_ref["U2"].risk_level == RiskLevel.CRITICAL
    assert {"unavailable", "obsolete"}.issubset(set(by_ref["U2"].flags))
    assert by_ref["R1"].risk_level == RiskLevel.CRITICAL
    assert "provider-miss" in by_ref["R1"].flags
    assert by_ref["R2"].risk_level == RiskLevel.LOW
    assert by_ref["R2"].flags == ["dnp"]
    assert report.provenance[0]["provider"] == "benchmark-fixture-distributor"


def test_proof_manifest_records_bom_provenance() -> None:
    evidence = BomProvenanceEvidence(
        provider="benchmark-fixture-distributor",
        cache_policy="fixture-only/offline-deterministic",
        generated_at="2026-06-19T12:00:00+00:00",
        report_path="reports/benchmark-001-bom-risk.json",
        highest_risk="critical",
        blocked=True,
        cache_age_hours=0,
        unresolved_required_parts=1,
        obsolete_required_parts=1,
        message="BOM risk blocks benchmark acceptance until alternates are selected.",
    )
    manifest = ProofManifest(
        name="benchmark-001-proof",
        design_path="benchmark-001.design.yaml",
        bom_provenance=[evidence],
    )

    dumped = manifest.model_dump(mode="json")
    assert dumped["bom_provenance"][0]["provider"] == "benchmark-fixture-distributor"
    assert dumped["bom_provenance"][0]["cache_age_hours"] == 0
    assert dumped["bom_provenance"][0]["blocked"] is True


def test_sample_benchmark_report_shape_is_json_serializable() -> None:
    provider = FixtureBomProvider.from_file(FIXTURE)
    report = enrich_bom_with_provider(
        _benchmark_design(),
        provider,
        generated_at=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
    )

    payload = report.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True)

    assert "benchmark-fixture-distributor" in encoded
    by_ref = {item["ref"]: item for item in payload["items"]}
    assert by_ref["U2"]["flags"] == ["unavailable", "obsolete"]


def test_lcsc_provider_adapter_maps_live_results_to_contract() -> None:
    class FakeClient:
        def resolve_mpn(self, mpn: str):
            from zaptrace.supply.client import SupplyResult

            assert mpn == "ESP32-S3-WROOM-1-N8"
            return SupplyResult(lcsc_id="C2913203", stock=2048, basic_part=False, price=2.74, stale=False)

    provider = LcscBomProvider(FakeClient())

    result = provider.lookup_mpn("ESP32-S3-WROOM-1-N8")

    assert result is not None
    assert result.provider == "lcsc-jlcpcb"
    assert result.distributor == "LCSC/JLCPCB"
    assert result.distributor_part_number == "C2913203"
    assert result.stock == 2048
    assert result.cache.status == "fresh"
    assert result.cache.offline is False
    assert result.price_breaks[0].unit_price == 2.74
    assert result.raw == {"basic_part": False}


def test_lcsc_provider_adapter_preserves_miss_and_stale_cache() -> None:
    from zaptrace.supply.client import SupplyResult

    class MissingClient:
        def resolve_mpn(self, mpn: str):
            return None

    class StaleClient:
        def resolve_mpn(self, mpn: str):
            return SupplyResult(lcsc_id="CACHED", stock=7, basic_part=True, price=0.11, stale=True)

    assert LcscBomProvider(MissingClient()).lookup_mpn("NOPE") is None

    stale = LcscBomProvider(StaleClient()).lookup_mpn("CACHE-MPN")
    assert stale is not None
    assert stale.cache.status == "stale"
    assert stale.cache.offline is True
    assert stale.cache.source == "lcsc-cache"


def test_low_availability_single_source_raises_supply_risk() -> None:
    provider = FixtureBomProvider(
        {
            "LOW-STOCK": {
                "manufacturer": "Acme",
                "stock": 42,
                "lifecycle": "active",
                "rohs_compliant": True,
                "footprint": "0603",
                "alternates": [],
            }
        }
    )
    design = Design(meta=DesignMeta(name="low-stock"))
    design.components = {"r1": Component(id="r1", ref="R1", type="resistor", mpn="LOW-STOCK", footprint="0603")}

    report = enrich_bom_with_provider(design, provider, generated_at=datetime(2026, 6, 30, tzinfo=UTC))
    item = report.items[0]

    assert item.risk_level == RiskLevel.MEDIUM
    assert "low-availability" in item.flags
    assert "single-source" in item.flags
    assert item.lifecycle == LifecycleStatus.ACTIVE


def test_lifecycle_status_is_serialized_in_bom_risk_evidence() -> None:
    provider = FixtureBomProvider(
        {
            "NRND-PART": {
                "manufacturer": "Acme",
                "stock": 500,
                "lifecycle": "nrnd",
                "rohs_compliant": True,
                "alternates": [{"mpn": "ALT", "lifecycle": "active"}],
            }
        }
    )
    design = Design(meta=DesignMeta(name="lifecycle"))
    design.components = {"u1": Component(id="u1", ref="U1", type="ic", mpn="NRND-PART")}

    payload = enrich_bom_with_provider(design, provider).model_dump(mode="json")

    assert payload["items"][0]["lifecycle"] == "nrnd"
    assert "nrnd" in payload["items"][0]["flags"]
