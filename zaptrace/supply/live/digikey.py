"""Live and fixture-enhanced DigiKey BOM intelligence provider."""

from __future__ import annotations

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


class LiveDigiKeyProvider:
    """DigiKey BOM intelligence provider with API access, SQLite cache, and fixture fallback."""

    name = "digikey-live"
    cache_policy = "live-first-with-fixture-fallback"

    def __init__(
        self,
        cache: SqliteSupplyCache | None = None,
        rate_limiter: TokenBucketRateLimiter | None = None,
        fixture_path: str | Path | None = None,
    ) -> None:
        self.cache = cache or SqliteSupplyCache()
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter(rate=2.0, capacity=10.0)
        self.client_id = os.environ.get("ZAPTRACE_DIGIKEY_CLIENT_ID", "")
        self.client_secret = os.environ.get("ZAPTRACE_DIGIKEY_CLIENT_SECRET", "")
        self._fixture_parts: dict[str, Any] = {}
        self._load_fixture(fixture_path or Path(__file__).parent.parent / "fixtures" / "digikey_parts.yaml")

    def _load_fixture(self, path: str | Path) -> None:
        p = Path(path)
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._fixture_parts = data.get("parts", data)
            except Exception:
                pass

    def lookup_mpn(self, mpn: str) -> BomProviderResult | None:
        """Lookup MPN via Cache -> Live API (if credentials present) -> Fixture."""
        if not mpn:
            return None

        # 1. Check fresh cache
        cached = self.cache.get(mpn, provider="digikey", allow_stale=False)
        if cached is not None:
            return cached

        # 2. Live API if credentials available
        if self.client_id and self.client_secret:
            live_result = self._query_live_api(mpn)
            if live_result is not None:
                self.cache.put(live_result)
                return live_result

        # 3. Check stale cache
        stale = self.cache.get(mpn, provider="digikey", allow_stale=True)
        if stale is not None:
            return stale

        # 4. Fixture fallback
        return self._lookup_fixture(mpn)

    def _query_live_api(self, mpn: str) -> BomProviderResult | None:
        if not self.rate_limiter.acquire(timeout=2.0):
            return None
        try:
            # DigiKey v4 Product Search API
            token_url = "https://api.digikey.com/v1/oauth2/token"
            with httpx.Client(timeout=6.0) as client:
                token_resp = client.post(
                    token_url,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "grant_type": "client_credentials",
                    },
                )
                if token_resp.status_code != 200:
                    return None
                token = token_resp.json().get("access_token")

                search_url = "https://api.digikey.com/products/v4/search/keyword"
                resp = client.post(
                    search_url,
                    json={"Keywords": mpn, "RecordCount": 1},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-DIGIKEY-Client-Id": self.client_id,
                        "Accept": "application/json",
                    },
                )
                if resp.status_code == 200:
                    return self._parse_api_response(mpn, resp.json())
        except Exception:
            pass
        return None

    def _parse_api_response(self, mpn: str, data: dict[str, Any]) -> BomProviderResult | None:
        products = data.get("Products", [])
        if not products:
            return None
        p = products[0]
        breaks = [
            PriceBreak(
                quantity=int(pb.get("BreakQuantity", 1)),
                unit_price=float(pb.get("UnitPrice", 0.0)),
                currency="USD",
            )
            for pb in p.get("StandardPricing", [])
        ]
        status_val = p.get("ProductStatus", {}).get("Value", "").lower()
        lifecycle = LifecycleStatus.ACTIVE if status_val == "active" else LifecycleStatus.UNKNOWN
        rohs = True if "rohs" in str(p.get("Classifications", {})).lower() else None

        return BomProviderResult(
            provider="digikey",
            mpn=mpn,
            manufacturer=p.get("Manufacturer", {}).get("Value", ""),
            distributor="DigiKey",
            distributor_part_number=p.get("DigiKeyPartNumber", ""),
            stock=p.get("QuantityAvailable", 0),
            lifecycle=lifecycle,
            rohs_compliant=rohs,
            price_breaks=breaks,
            footprint=p.get("PackageType", {}).get("Value", ""),
            cache=CacheMetadata(status=CacheStatus.FRESH, source="live:digikey", offline=False),
            raw=p,
        )

    def _lookup_fixture(self, mpn: str) -> BomProviderResult | None:
        item = self._fixture_parts.get(mpn)
        if item is None or not isinstance(item, dict):
            return None
        payload = {
            "provider": "digikey",
            "mpn": mpn,
            "distributor": "DigiKey",
            "cache": {"status": CacheStatus.FIXTURE, "source": "fixture:digikey", "offline": True},
            **item,
        }
        return BomProviderResult.model_validate(payload)
