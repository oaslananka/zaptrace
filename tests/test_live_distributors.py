"""Tests for live distributor intelligence, rate limiting, and SQLite caching."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from zaptrace.supply.contracts import (
    BomProviderResult,
    CacheMetadata,
    CacheStatus,
    LifecycleStatus,
    PriceBreak,
)
from zaptrace.supply.live import create_live_provider
from zaptrace.supply.live.cache import SqliteSupplyCache
from zaptrace.supply.live.digikey import LiveDigiKeyProvider
from zaptrace.supply.live.lcsc import LiveLcscProvider
from zaptrace.supply.live.mouser import LiveMouserProvider
from zaptrace.supply.live.rate_limiter import TokenBucketRateLimiter


@pytest.fixture
def temp_cache(tmp_path: Path) -> SqliteSupplyCache:
    return SqliteSupplyCache(db_path=tmp_path / "test_supply.db")


@pytest.fixture
def sample_result() -> BomProviderResult:
    return BomProviderResult(
        provider="test-dist",
        mpn="STM32F401RET6",
        manufacturer="STMicroelectronics",
        distributor="TestDist",
        distributor_part_number="TEST-12345",
        stock=1500,
        lifecycle=LifecycleStatus.ACTIVE,
        rohs_compliant=True,
        price_breaks=[PriceBreak(quantity=1, unit_price=3.45, currency="USD")],
        footprint="LQFP-64",
        cache=CacheMetadata(status=CacheStatus.FRESH, source="test", offline=False),
    )


class TestSqliteSupplyCache:
    """Test persistent SQLite supply cache."""

    def test_put_and_get_fresh(self, temp_cache: SqliteSupplyCache, sample_result: BomProviderResult) -> None:
        temp_cache.put(sample_result, ttl_seconds=3600)
        cached = temp_cache.get("STM32F401RET6", provider="test-dist")
        assert cached is not None
        assert cached.mpn == "STM32F401RET6"
        assert cached.stock == 1500
        assert cached.cache.status == CacheStatus.FRESH

    def test_case_insensitive_mpn(self, temp_cache: SqliteSupplyCache, sample_result: BomProviderResult) -> None:
        temp_cache.put(sample_result, ttl_seconds=3600)
        cached = temp_cache.get("stm32f401ret6")
        assert cached is not None
        assert cached.mpn == "STM32F401RET6"

    def test_ttl_expiration_allow_stale(self, temp_cache: SqliteSupplyCache, sample_result: BomProviderResult) -> None:
        temp_cache.put(sample_result, ttl_seconds=0)
        time.sleep(0.05)
        # With allow_stale=True, returns result marked as STALE
        stale = temp_cache.get("STM32F401RET6", allow_stale=True)
        assert stale is not None
        assert stale.cache.status == CacheStatus.STALE

        # With allow_stale=False, returns None
        fresh = temp_cache.get("STM32F401RET6", allow_stale=False)
        assert fresh is None

    def test_clear_and_stats(self, temp_cache: SqliteSupplyCache, sample_result: BomProviderResult) -> None:
        temp_cache.put(sample_result, ttl_seconds=3600)
        st = temp_cache.stats()
        assert st["total_entries"] == 1
        assert st["fresh_entries"] == 1

        deleted = temp_cache.clear()
        assert deleted == 1
        assert temp_cache.stats()["total_entries"] == 0


class TestRateLimiter:
    """Test token bucket rate limiter."""

    def test_acquire_burst(self) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=3.0)
        assert limiter.acquire(1.0)
        assert limiter.acquire(1.0)
        assert limiter.acquire(1.0)
        # Exceeded capacity without blocking
        assert not limiter.acquire(1.0, block=False)


class TestDistributorProviders:
    """Test live/fixture distributor provider behaviors."""

    def test_digikey_fixture_fallback(self, temp_cache: SqliteSupplyCache) -> None:
        prov = LiveDigiKeyProvider(cache=temp_cache)
        # Using a part known in fixture or checking non-crash
        result = prov.lookup_mpn("RC0603FR-0710KL")
        # If fixture is populated, returns result, otherwise None without throwing
        if result is not None:
            assert result.provider == "digikey"

    def test_mouser_fixture_fallback(self, temp_cache: SqliteSupplyCache) -> None:
        prov = LiveMouserProvider(cache=temp_cache)
        result = prov.lookup_mpn("RC0603FR-0710KL")
        if result is not None:
            assert result.provider == "mouser"

    def test_lcsc_cache_hit(self, temp_cache: SqliteSupplyCache, sample_result: BomProviderResult) -> None:
        sample_result.provider = "lcsc"
        temp_cache.put(sample_result)
        prov = LiveLcscProvider(cache=temp_cache)
        result = prov.lookup_mpn("STM32F401RET6")
        assert result is not None
        assert result.mpn == "STM32F401RET6"

    def test_factory_creation(self, temp_cache: SqliteSupplyCache) -> None:
        lcsc = create_live_provider("lcsc", cache=temp_cache)
        assert isinstance(lcsc, LiveLcscProvider)
        dk = create_live_provider("digikey", cache=temp_cache)
        assert isinstance(dk, LiveDigiKeyProvider)
        mouser = create_live_provider("mouser", cache=temp_cache)
        assert isinstance(mouser, LiveMouserProvider)
        with pytest.raises(ValueError, match="unknown live distributor"):
            create_live_provider("nonexistent")

    def test_digikey_lookup_mpn_and_empty(self, temp_cache: SqliteSupplyCache) -> None:
        prov = LiveDigiKeyProvider(cache=temp_cache)
        assert prov.lookup_mpn("") is None
        res = prov.lookup_mpn("RC0603FR-0710KL")
        if res is not None:
            assert res.provider == "digikey"

    def test_mouser_lookup_mpn_and_empty(self, temp_cache: SqliteSupplyCache) -> None:
        prov = LiveMouserProvider(cache=temp_cache)
        assert prov.lookup_mpn("") is None
        res = prov.lookup_mpn("RC0603FR-0710KL")
        if res is not None:
            assert res.provider == "mouser"

    def test_lcsc_lookup_mpn_and_empty(self, temp_cache: SqliteSupplyCache) -> None:
        prov = LiveLcscProvider(cache=temp_cache)
        assert prov.lookup_mpn("") is None
        res = prov.lookup_mpn("C12345")
        if res is not None:
            assert res.provider == "lcsc"
