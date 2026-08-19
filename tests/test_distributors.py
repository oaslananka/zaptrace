"""Tests for additional distributor BOM intelligence providers."""

from __future__ import annotations

from pathlib import Path

from zaptrace.supply import (
    DigiKeyBomProvider,
    FarnellBomProvider,
    MouserBomProvider,
    MultiDistributorProvider,
    TmeBomProvider,
)
from zaptrace.supply.contracts import LifecycleStatus


def _fixture_dir() -> Path:
    return Path(__file__).parent.parent / "zaptrace" / "supply" / "fixtures"


class TestDigiKeyBomProvider:
    def test_loads_fixture(self) -> None:
        provider = DigiKeyBomProvider(_fixture_dir() / "digikey_parts.yaml")
        assert provider.name == "digikey"
        assert provider.cache_policy == "fixture-only"

    def test_lookup_existing_mpn(self) -> None:
        provider = DigiKeyBomProvider(_fixture_dir() / "digikey_parts.yaml")
        result = provider.lookup_mpn("ESP32-S3-WROOM-1-N8")
        assert result is not None
        assert result.provider == "digikey"
        assert result.distributor == "DigiKey"
        assert result.distributor_part_number == "ESP32-S3-WROOM-1-N8-ND"
        assert result.stock == 1500
        assert result.lifecycle == LifecycleStatus.ACTIVE
        assert result.rohs_compliant is True
        assert "REACH" in result.compliance_flags
        assert len(result.price_breaks) == 3
        assert result.price_breaks[0].unit_price == 3.45
        assert len(result.alternates) == 1
        assert result.alternates[0].mpn == "ESP32-S3-WROOM-1-N16R8"
        assert result.footprint == "ESP32-S3-WROOM-1"

    def test_lookup_missing_mpn(self) -> None:
        provider = DigiKeyBomProvider(_fixture_dir() / "digikey_parts.yaml")
        result = provider.lookup_mpn("NONEXISTENT-MPN")
        assert result is None


class TestMouserBomProvider:
    def test_loads_fixture(self) -> None:
        provider = MouserBomProvider(_fixture_dir() / "mouser_parts.yaml")
        assert provider.name == "mouser"
        assert provider.cache_policy == "fixture-only"

    def test_lookup_existing_mpn(self) -> None:
        provider = MouserBomProvider(_fixture_dir() / "mouser_parts.yaml")
        result = provider.lookup_mpn("ESP32-S3-WROOM-1-N8")
        assert result is not None
        assert result.provider == "mouser"
        assert result.distributor == "Mouser"
        assert result.distributor_part_number == "913-ESP32-S3-WROOM-1-N8"
        assert result.stock == 2100
        assert result.lifecycle == LifecycleStatus.ACTIVE
        assert result.rohs_compliant is True
        assert "REACH" in result.compliance_flags
        assert len(result.price_breaks) == 3
        assert result.price_breaks[0].unit_price == 3.38
        assert len(result.alternates) == 1
        assert result.alternates[0].mpn == "ESP32-S3-WROOM-1-N16R8"
        assert result.footprint == "ESP32-S3-WROOM-1"

    def test_lookup_missing_mpn(self) -> None:
        provider = MouserBomProvider(_fixture_dir() / "mouser_parts.yaml")
        result = provider.lookup_mpn("NONEXISTENT-MPN")
        assert result is None


class TestTmeBomProvider:
    def test_loads_fixture(self) -> None:
        provider = TmeBomProvider(_fixture_dir() / "tme_parts.yaml")
        assert provider.name == "tme"
        assert provider.cache_policy == "fixture-only"

    def test_lookup_existing_mpn(self) -> None:
        provider = TmeBomProvider(_fixture_dir() / "tme_parts.yaml")
        result = provider.lookup_mpn("ESP32-S3-WROOM-1-N8")
        assert result is not None
        assert result.provider == "tme"
        assert result.distributor == "TME"
        assert result.distributor_part_number == "ESP32-S3-WROOM-1-N8"
        assert result.stock == 980
        assert result.lifecycle == LifecycleStatus.ACTIVE
        assert result.rohs_compliant is True
        assert "REACH" in result.compliance_flags
        assert len(result.price_breaks) == 3
        assert result.price_breaks[0].unit_price == 3.52
        assert result.price_breaks[0].currency == "EUR"
        assert len(result.alternates) == 1
        assert result.alternates[0].mpn == "ESP32-S3-WROOM-1-N16R8"
        assert result.footprint == "ESP32-S3-WROOM-1"

    def test_lookup_missing_mpn(self) -> None:
        provider = TmeBomProvider(_fixture_dir() / "tme_parts.yaml")
        result = provider.lookup_mpn("NONEXISTENT-MPN")
        assert result is None


class TestFarnellBomProvider:
    def test_loads_fixture(self) -> None:
        provider = FarnellBomProvider(_fixture_dir() / "farnell_parts.yaml")
        assert provider.name == "farnell"
        assert provider.cache_policy == "fixture-only"

    def test_lookup_existing_mpn(self) -> None:
        provider = FarnellBomProvider(_fixture_dir() / "farnell_parts.yaml")
        result = provider.lookup_mpn("ESP32-S3-WROOM-1-N8")
        assert result is not None
        assert result.provider == "farnell"
        assert result.distributor == "Farnell/Newark"
        assert result.distributor_part_number == "3891234"
        assert result.stock == 420
        assert result.lifecycle == LifecycleStatus.ACTIVE
        assert result.rohs_compliant is True
        assert "REACH" in result.compliance_flags
        assert "RoHS" in result.compliance_flags
        assert len(result.price_breaks) == 3
        assert result.price_breaks[0].unit_price == 4.15
        assert result.price_breaks[0].currency == "GBP"
        assert len(result.alternates) == 1
        assert result.alternates[0].mpn == "ESP32-S3-WROOM-1-N16R8"
        assert result.footprint == "ESP32-S3-WROOM-1"

    def test_lookup_missing_mpn(self) -> None:
        provider = FarnellBomProvider(_fixture_dir() / "farnell_parts.yaml")
        result = provider.lookup_mpn("NONEXISTENT-MPN")
        assert result is None


class TestMultiDistributorProvider:
    def test_queries_in_priority_order(self) -> None:
        # DigiKey is first in the default list
        provider = MultiDistributorProvider()
        result = provider.lookup_mpn("ESP32-S3-WROOM-1-N8")
        assert result is not None
        assert result.provider == "digikey"

    def test_falls_back_to_next_provider(self) -> None:
        # Create a custom provider list where first has no match
        from zaptrace.supply import FixtureBomProvider

        empty_provider = FixtureBomProvider({}, name="empty", cache_policy="fixture-only")
        digikey = DigiKeyBomProvider(_fixture_dir() / "digikey_parts.yaml")
        provider = MultiDistributorProvider([empty_provider, digikey])

        result = provider.lookup_mpn("ESP32-S3-WROOM-1-N8")
        assert result is not None
        assert result.provider == "digikey"

    def test_returns_none_when_all_miss(self) -> None:
        from zaptrace.supply import FixtureBomProvider

        empty1 = FixtureBomProvider({}, name="empty1", cache_policy="fixture-only")
        empty2 = FixtureBomProvider({}, name="empty2", cache_policy="fixture-only")
        provider = MultiDistributorProvider([empty1, empty2])

        result = provider.lookup_mpn("NONEXISTENT")
        assert result is None

    def test_name_and_cache_policy(self) -> None:
        provider = MultiDistributorProvider()
        assert provider.name == "multi-distributor"
        assert provider.cache_policy == "multi-source"


class TestDistributorFixturesExist:
    """Ensure all fixture files are present and valid."""

    def test_digikey_fixture_exists(self) -> None:
        path = _fixture_dir() / "digikey_parts.yaml"
        assert path.exists()

    def test_mouser_fixture_exists(self) -> None:
        path = _fixture_dir() / "mouser_parts.yaml"
        assert path.exists()

    def test_tme_fixture_exists(self) -> None:
        path = _fixture_dir() / "tme_parts.yaml"
        assert path.exists()

    def test_farnell_fixture_exists(self) -> None:
        path = _fixture_dir() / "farnell_parts.yaml"
        assert path.exists()
