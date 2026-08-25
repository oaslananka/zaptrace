"""Live and fixture-enhanced Mouser BOM intelligence provider."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

import httpx
import yaml

from zaptrace.supply.contracts import (
    BomProviderResult,
    CacheMetadata,
    CacheStatus,
    LifecycleStatus,
    PriceBreak,
)
from zaptrace.supply.live.cache import SqliteSupplyCache
from zaptrace.supply.live.rate_limiter import TokenBucketRateLimiter


class LiveMouserProvider:
    """Mouser BOM intelligence provider with API access, SQLite cache, and fixture fallback."""

    name = "mouser-live"
    cache_policy = "live-first-with-fixture-fallback"

    def __init__(
        self,
        cache: SqliteSupplyCache | None = None,
        rate_limiter: TokenBucketRateLimiter | None = None,
        fixture_path: str | Path | None = None,
    ) -> None:
        self.cache = cache or SqliteSupplyCache()
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter(rate=1.0, capacity=5.0)
        self.api_key = os.environ.get("ZAPTRACE_MOUSER_API_KEY", "")
        self._fixture_parts: dict[str, Any] = {}
        self._load_fixture(
            fixture_path or Path(__file__).parent.parent / "fixtures" / "mouser_parts.yaml"
        )

    def _load_fixture(self, path: Path) -> None:
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._fixture_parts = data.get("parts", data)
            except Exception:
                pass

    def lookup_mpn(self, mpn: str) -> BomProviderResult | None:
        """Lookup MPN via Cache -> Live API (if API key present) -> Fixture."""
        if not mpn:
            return None

        # 1. Check fresh cache
        cached = self.cache.get(mpn, provider="mouser", allow_stale=False)
        if cached is not None:
            return cached

        # 2. Live API if API key available
        if self.api_key:
            live_result = self._query_live_api(mpn)
            if live_result is not None:
                self.cache.put(live_result)
                return live_result

        # 3. Check stale cache
        stale = self.cache.get(mpn, provider="mouser", allow_stale=True)
        if stale is not None:
            return stale

        # 4. Fixture fallback
        return self._lookup_fixture(mpn)

    def _query_live_api(self, mpn: str) -> BomProviderResult | None:
        if not self.rate_limiter.acquire(timeout=2.0):
            return None
        try:
            url = f"https://api.mouser.com/api/v2/search/partnumber?apiKey={self.api_key}"
            with httpx.Client(timeout=6.0) as client:
                resp = client.post(
                    url,
                    json={"SearchByPartRequest": {"mouserPartNumber": mpn, "partSearchOptions": "Exact"}},
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    return self._parse_api_response(mpn, resp.json())
        except Exception:
            pass
        return None

    def _parse_api_response(self, mpn: str, data: dict[str, Any]) -> BomProviderResult | None:
        search_results = data.get("SearchResults", {}).get("Parts", [])
        if not search_results:
            return None
        p = search_results[0]
        price_breaks = []
        for pb in p.get("PriceBreaks", []):
            try:
                price_str = pb.get("Price", "").replace("$", "").replace(",", "")
                price_breaks.append(
                    PriceBreak(
                        quantity=int(pb.get("Quantity", 1)),
                        unit_price=float(price_str),
                        currency=pb.get("Currency", "USD"),
                    )
                )
            except (ValueError, TypeError):
                pass

        stock_val = 0
        with contextlib.suppress(ValueError, IndexError):
            stock_val = int(p.get("AvailabilityInStock", "0").split()[0])

        return BomProviderResult(
            provider="mouser",
            mpn=mpn,
            manufacturer=p.get("Manufacturer", ""),
            distributor="Mouser",
            distributor_part_number=p.get("MouserPartNumber", ""),
            stock=stock_val,
            lifecycle=LifecycleStatus.ACTIVE if stock_val > 0 else LifecycleStatus.UNKNOWN,
            rohs_compliant=True if "rohs" in p.get("ROHSStatus", "").lower() else None,
            price_breaks=price_breaks,
            footprint=p.get("Package", ""),
            cache=CacheMetadata(status=CacheStatus.FRESH, source="live:mouser", offline=False),
            raw=p,
        )

    def _lookup_fixture(self, mpn: str) -> BomProviderResult | None:
        item = self._fixture_parts.get(mpn)
        if item is None or not isinstance(item, dict):
            return None
        payload = {
            "provider": "mouser",
            "mpn": mpn,
            "distributor": "Mouser",
            "cache": {"status": CacheStatus.FIXTURE, "source": "fixture:mouser", "offline": True},
            **item,
        }
        return BomProviderResult.model_validate(payload)
