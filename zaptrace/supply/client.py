from __future__ import annotations

import json
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict

from zaptrace.supply.contracts import BomProviderResult, CacheMetadata, CacheStatus, LifecycleStatus, PriceBreak


class SupplyResult(BaseModel):
    model_config = ConfigDict(strict=False)

    lcsc_id: str
    stock: int
    basic_part: bool
    price: float
    stale: bool = False


class SupplyClient:
    """Client for resolving MPNs to LCSC part numbers and fetching supply data."""

    def __init__(self, cache_file: str | Path = ".supply_cache.json") -> None:
        self.cache_file = Path(cache_file)
        self._cache: dict[str, dict] = self._load_cache()
        self._hot_cache: dict[str, dict] = {}
        # Using a generic endpoint pattern for LCSC/JLCPCB searches.
        self.api_url = "https://wmsc.lcsc.com/ftpc/front/product/search"

    def _load_cache(self) -> dict[str, dict]:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_cache(self) -> None:
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except OSError:
            pass

    def resolve_mpn(self, mpn: str) -> SupplyResult | None:
        """Resolve a manufacturer part number to an LCSC component."""
        if not mpn:
            return None

        # Check in-memory hot cache first to avoid duplicate network calls
        if mpn in self._hot_cache and not self._hot_cache[mpn].get("stale"):
            return SupplyResult(**self._hot_cache[mpn])

        # Network request
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.post(
                    self.api_url,
                    json={"keyword": mpn},
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()

                # Mock parsing logic based on a typical LCSC/JLCPCB response shape
                # Since the real API is behind Cloudflare, we assume the response format
                # would be handled here. We'll simulate success if 'result' is in the payload.
                # If we get here in tests, we've patched httpx or it succeeded.
                if data and "result" in data and isinstance(data["result"], list) and len(data["result"]) > 0:
                    first_match = data["result"][0]
                    # Map the typical fields
                    result = SupplyResult(
                        lcsc_id=first_match.get("productCode", ""),
                        stock=first_match.get("stockNumber", 0),
                        basic_part=first_match.get("basic", False),
                        price=first_match.get("productPrice", 0.0),
                        stale=False,
                    )

                    # Update cache
                    dump = result.model_dump()
                    self._cache[mpn] = dump
                    self._hot_cache[mpn] = dump
                    self._save_cache()
                    return result
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
            pass

        # Fallback to cache on network error
        if mpn in self._cache:
            cached_data = self._cache[mpn].copy()
            cached_data["stale"] = True
            return SupplyResult(**cached_data)

        return None


class LcscBomProvider:
    """Provider-contract adapter for the existing LCSC/JLCPCB supply resolver.

    The adapter never fabricates distributor data: it returns ``None`` when the
    underlying resolver has no live or cached match. Cached fallback results are
    marked as stale in the returned provenance metadata.
    """

    name = "lcsc-jlcpcb"
    cache_policy = "live-lcsc-with-stale-cache-fallback"

    def __init__(self, client: SupplyClient | None = None) -> None:
        self.client = client or SupplyClient()

    def lookup_mpn(self, mpn: str) -> BomProviderResult | None:
        result = self.client.resolve_mpn(mpn)
        if result is None:
            return None
        cache_status = CacheStatus.STALE if result.stale else CacheStatus.FRESH
        return BomProviderResult(
            provider=self.name,
            mpn=mpn,
            distributor="LCSC/JLCPCB",
            distributor_part_number=result.lcsc_id,
            stock=result.stock,
            lifecycle=LifecycleStatus.UNKNOWN,
            price_breaks=[PriceBreak(quantity=1, unit_price=result.price, currency="USD")],
            cache=CacheMetadata(
                status=cache_status,
                source="lcsc-cache" if result.stale else "lcsc-api",
                offline=result.stale,
            ),
            raw={"basic_part": result.basic_part},
        )
