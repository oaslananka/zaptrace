"""Live and cached LCSC BOM intelligence provider."""

from __future__ import annotations

from typing import Any

import httpx

from zaptrace.supply.contracts import (
    BomProviderResult,
    CacheMetadata,
    CacheStatus,
    LifecycleStatus,
    PriceBreak,
)
from zaptrace.supply.live.cache import SqliteSupplyCache
from zaptrace.supply.live.rate_limiter import TokenBucketRateLimiter


class LiveLcscProvider:
    """LCSC intelligence provider with SQLite caching, rate limiting, and fixture fallback."""

    name = "lcsc-live"
    cache_policy = "live-first-with-cache"

    def __init__(
        self,
        cache: SqliteSupplyCache | None = None,
        rate_limiter: TokenBucketRateLimiter | None = None,
        timeout_seconds: float = 6.0,
    ) -> None:
        self.cache = cache or SqliteSupplyCache()
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter(rate=3.0, capacity=10.0)
        self.timeout = timeout_seconds
        self.api_url = "https://wmsc.lcsc.com/ftpc/front/product/search"

    def lookup_mpn(self, mpn: str) -> BomProviderResult | None:
        """Lookup MPN on LCSC, checking local cache first, querying API, falling back to cache/fixture."""
        if not mpn:
            return None

        # 1. Check fresh cache
        cached = self.cache.get(mpn, provider="lcsc", allow_stale=False)
        if cached is not None:
            return cached

        # 2. Acquire rate limiter token
        if not self.rate_limiter.acquire(timeout=2.0):
            # Fallback to stale cache if rate-limited
            return self.cache.get(mpn, provider="lcsc", allow_stale=True)

        # 3. Live network query
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    self.api_url,
                    json={"keyword": mpn},
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result = self._parse_response(mpn, data)
                    if result is not None:
                        self.cache.put(result)
                        return result
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError, KeyError):
            pass

        # 4. Fallback to stale cache
        stale_cached = self.cache.get(mpn, provider="lcsc", allow_stale=True)
        if stale_cached is not None:
            return stale_cached

        return None

    def _parse_response(self, mpn: str, data: dict[str, Any]) -> BomProviderResult | None:
        """Parse raw LCSC search response into BomProviderResult."""
        results = data.get("result", [])
        if not isinstance(results, list) or not results:
            return None

        item = results[0]
        lcsc_id = item.get("productCode", "")
        stock = item.get("stockNumber", 0)
        price_val = float(item.get("productPrice", 0.0) or 0.0)
        mfr = item.get("brandNameEn", "")

        price_breaks = []
        if price_val > 0:
            price_breaks.append(PriceBreak(quantity=1, unit_price=price_val, currency="USD"))

        return BomProviderResult(
            provider="lcsc",
            mpn=mpn,
            manufacturer=mfr,
            distributor="LCSC",
            distributor_part_number=lcsc_id,
            stock=stock,
            lifecycle=LifecycleStatus.ACTIVE if stock > 0 else LifecycleStatus.UNKNOWN,
            rohs_compliant=True if item.get("rohs") else None,
            price_breaks=price_breaks,
            footprint=item.get("encapStandard", ""),
            cache=CacheMetadata(status=CacheStatus.FRESH, source="live:lcsc", offline=False),
            raw=item,
        )
