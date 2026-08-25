"""Live distributor intelligence, rate limiting, and SQLite caching."""

from __future__ import annotations

from zaptrace.supply.contracts import BomIntelligenceProvider
from zaptrace.supply.live.cache import SqliteSupplyCache
from zaptrace.supply.live.digikey import LiveDigiKeyProvider
from zaptrace.supply.live.lcsc import LiveLcscProvider
from zaptrace.supply.live.mouser import LiveMouserProvider
from zaptrace.supply.live.rate_limiter import TokenBucketRateLimiter


def create_live_provider(
    provider_name: str = "lcsc",
    cache: SqliteSupplyCache | None = None,
) -> BomIntelligenceProvider:
    """Create a live BOM intelligence provider by name ('lcsc', 'digikey', 'mouser')."""
    p = provider_name.strip().lower()
    if p == "digikey":
        return LiveDigiKeyProvider(cache=cache)
    if p == "mouser":
        return LiveMouserProvider(cache=cache)
    if p == "lcsc":
        return LiveLcscProvider(cache=cache)
    raise ValueError(f"unknown live distributor: {provider_name}")


__all__ = [
    "LiveDigiKeyProvider",
    "LiveLcscProvider",
    "LiveMouserProvider",
    "SqliteSupplyCache",
    "TokenBucketRateLimiter",
    "create_live_provider",
]
