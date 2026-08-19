"""Additional distributor BOM intelligence providers.

These providers follow the same :class:`BomIntelligenceProvider` contract as
:class:`LcscBomProvider` but target DigiKey, Mouser, TME, and Farnell/Newark.

Since real API access requires authentication and rate limiting, these
implementations are fixture-backed for deterministic testing. Production use
would swap in live API clients with proper credentials.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from zaptrace.supply.contracts import (
    BomIntelligenceProvider,
    BomProviderResult,
    CacheStatus,
)


class _FixtureBackedProvider:
    """Base class for fixture-backed distributors."""

    def __init__(
        self,
        fixture_path: str | Path | None = None,
        *,
        name: str,
        cache_policy: str,
        distributor_name: str,
    ) -> None:
        self.name = name
        self.cache_policy = cache_policy
        self._distributor_name = distributor_name
        self._parts: dict[str, Any] = {}
        if fixture_path:
            self._load_fixture(fixture_path)

    def _load_fixture(self, path: str | Path) -> None:
        fixture_path = Path(path)
        if not fixture_path.exists():
            return
        raw = fixture_path.read_text(encoding="utf-8")
        data = json.loads(raw) if fixture_path.suffix.lower() == ".json" else yaml.safe_load(raw)
        if not isinstance(data, dict):
            return
        parts = data.get("parts", data)
        if isinstance(parts, dict):
            self._parts = parts

    def lookup_mpn(self, mpn: str) -> BomProviderResult | None:
        item = self._parts.get(mpn)
        if item is None:
            return None
        if not isinstance(item, dict):
            raise ValueError(f"Fixture part {mpn!r} must be a mapping")
        payload = {
            "provider": self.name,
            "mpn": mpn,
            "distributor": self._distributor_name,
            "cache": {"status": CacheStatus.FIXTURE, "source": self.cache_policy, "offline": True},
            **item,
        }
        return BomProviderResult.model_validate(payload)


class DigiKeyBomProvider(_FixtureBackedProvider):
    """DigiKey BOM intelligence provider (fixture-backed)."""

    def __init__(self, fixture_path: str | Path | None = None) -> None:
        default_fixture = Path(__file__).parent / "fixtures" / "digikey_parts.yaml"
        super().__init__(
            fixture_path or default_fixture,
            name="digikey",
            cache_policy="fixture-only",
            distributor_name="DigiKey",
        )


class MouserBomProvider(_FixtureBackedProvider):
    """Mouser Electronics BOM intelligence provider (fixture-backed)."""

    def __init__(self, fixture_path: str | Path | None = None) -> None:
        default_fixture = Path(__file__).parent / "fixtures" / "mouser_parts.yaml"
        super().__init__(
            fixture_path or default_fixture,
            name="mouser",
            cache_policy="fixture-only",
            distributor_name="Mouser",
        )


class TmeBomProvider(_FixtureBackedProvider):
    """Transfer Multisort Elektronik (TME) BOM intelligence provider (fixture-backed)."""

    def __init__(self, fixture_path: str | Path | None = None) -> None:
        default_fixture = Path(__file__).parent / "fixtures" / "tme_parts.yaml"
        super().__init__(
            fixture_path or default_fixture,
            name="tme",
            cache_policy="fixture-only",
            distributor_name="TME",
        )


class FarnellBomProvider(_FixtureBackedProvider):
    """Farnell/Newark BOM intelligence provider (fixture-backed)."""

    def __init__(self, fixture_path: str | Path | None = None) -> None:
        default_fixture = Path(__file__).parent / "fixtures" / "farnell_parts.yaml"
        super().__init__(
            fixture_path or default_fixture,
            name="farnell",
            cache_policy="fixture-only",
            distributor_name="Farnell/Newark",
        )


class MultiDistributorProvider:
    """Aggregate provider that queries multiple distributors in priority order.

    The first provider to return a non-None result wins. This mirrors real-world
    sourcing workflows where you check preferred distributors first.
    """

    name = "multi-distributor"
    cache_policy = "multi-source"

    def __init__(self, providers: list[BomIntelligenceProvider] | None = None) -> None:
        self.providers = providers or [
            DigiKeyBomProvider(),
            MouserBomProvider(),
            TmeBomProvider(),
            FarnellBomProvider(),
        ]

    def lookup_mpn(self, mpn: str) -> BomProviderResult | None:
        for provider in self.providers:
            result = provider.lookup_mpn(mpn)
            if result is not None:
                return result
        return None


def create_provider_from_env() -> BomIntelligenceProvider:
    """Create a provider based on environment configuration.

    Environment variables:
    - ZAPTRACE_BOM_PROVIDER: "lcsc", "digikey", "mouser", "tme", "farnell", "multi"
    - ZAPTRACE_BOM_FIXTURE_DIR: directory containing distributor fixture files
    """
    provider_name = os.environ.get("ZAPTRACE_BOM_PROVIDER", "lcsc").lower()
    fixture_dir = os.environ.get("ZAPTRACE_BOM_FIXTURE_DIR")

    if provider_name == "digikey":
        fixture = Path(fixture_dir) / "digikey_parts.yaml" if fixture_dir else None
        return DigiKeyBomProvider(fixture)
    if provider_name == "mouser":
        fixture = Path(fixture_dir) / "mouser_parts.yaml" if fixture_dir else None
        return MouserBomProvider(fixture)
    if provider_name == "tme":
        fixture = Path(fixture_dir) / "tme_parts.yaml" if fixture_dir else None
        return TmeBomProvider(fixture)
    if provider_name == "farnell":
        fixture = Path(fixture_dir) / "farnell_parts.yaml" if fixture_dir else None
        return FarnellBomProvider(fixture)
    if provider_name == "multi":
        return MultiDistributorProvider()
    # Default to LCSC
    from zaptrace.supply.client import LcscBomProvider

    return LcscBomProvider()
