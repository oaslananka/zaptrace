import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from zaptrace.core.models import Component, Design, DesignMeta
from zaptrace.export.bom import generate_bom_csv, generate_bom_json
from zaptrace.supply.client import SupplyClient


@pytest.fixture
def temp_cache_file(tmp_path: Path):
    return tmp_path / ".supply_cache.json"


@pytest.fixture
def mock_design():
    c1 = Component(id="C1", ref="C1", type="capacitor", mpn="CL10A106MQ8NNNC", dnp=False)
    c2 = Component(id="R1", ref="R1", type="resistor", mpn="RC0402FR-0710KL", dnp=True)
    c3 = Component(id="U1", ref="U1", type="ic", lcsc_id="C12345", basic_part=True, stock=1000, dnp=False)
    d = Design(meta=DesignMeta(name="SupplyTestDesign"))
    d.components = {"C1": c1, "R1": c2, "U1": c3}
    return d


def test_supply_client_resolve_network_success(temp_cache_file):
    client = SupplyClient(cache_file=temp_cache_file)

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "result": [{"productCode": "C123", "stockNumber": 500, "basic": True, "productPrice": 0.05}]
    }

    with patch("httpx.Client.post", return_value=mock_response):
        result = client.resolve_mpn("TEST-MPN")

        assert result is not None
        assert result.lcsc_id == "C123"
        assert result.stock == 500
        assert result.basic_part is True
        assert result.price == 0.05
        assert result.stale is False

        # Verify cache was written
        with open(temp_cache_file) as f:
            cache_data = json.load(f)
            assert "TEST-MPN" in cache_data
            assert cache_data["TEST-MPN"]["lcsc_id"] == "C123"


def test_supply_client_offline_fallback(temp_cache_file):
    # Pre-populate cache
    cache_data = {"TEST-MPN": {"lcsc_id": "C999", "stock": 10, "basic_part": False, "price": 0.1, "stale": False}}
    with open(temp_cache_file, "w") as f:
        json.dump(cache_data, f)

    client = SupplyClient(cache_file=temp_cache_file)

    # Mock network error
    with patch("httpx.Client.post", side_effect=httpx.RequestError("Network down", request=MagicMock())):
        result = client.resolve_mpn("TEST-MPN")

        # Should return cached data but marked as stale
        assert result is not None
        assert result.lcsc_id == "C999"
        assert result.stale is True


def test_generate_bom_csv_with_supply(mock_design):
    mock_result = MagicMock()
    mock_result.lcsc_id = "C_MOCKED"
    mock_result.basic_part = False
    mock_result.stock = 0

    with patch.object(SupplyClient, "resolve_mpn", return_value=mock_result):
        csv_data = generate_bom_csv(mock_design)

        lines = csv_data.strip().split("\n")
        header = lines[0]
        assert "LCSC#" in header
        assert "Basic/Extended" in header
        assert "Populate/DNP" in header
        assert "Flags" in header

        # C1: Mpn resolves to C_MOCKED, Extended, Populate, stock=0 -> Out of Stock
        c1_line = next(line for line in lines if line.startswith("C1"))
        assert "C_MOCKED" in c1_line
        assert "Extended" in c1_line
        assert "Populate" in c1_line
        assert "Out of Stock" in c1_line

        # R1: DNP
        r1_line = next(line for line in lines if line.startswith("R1"))
        assert "DNP" in r1_line
        assert "C_MOCKED" in r1_line
        assert "Out of Stock" not in r1_line  # DNP parts shouldn't have out of stock flag

        # U1: Pre-filled, Basic, Populate
        u1_line = next(line for line in lines if line.startswith("U1"))
        assert "C12345" in u1_line
        assert "Basic" in u1_line
        assert "Populate" in u1_line


def test_generate_bom_json_with_supply(mock_design):
    with patch.object(SupplyClient, "resolve_mpn", return_value=None):
        json_str = generate_bom_json(mock_design)
        data = json.loads(json_str)

        assert "items" in data

        c1 = next(item for item in data["items"] if item["ref"] == "C1")
        assert c1["lcsc_id"] is None
        assert c1["populate_dnp"] == "Populate"
        assert "Missing LCSC#" in c1["flags"]

        r1 = next(item for item in data["items"] if item["ref"] == "R1")
        assert r1["populate_dnp"] == "DNP"
        assert "Missing LCSC#" not in r1["flags"]  # DNP ignores missing lcsc

        u1 = next(item for item in data["items"] if item["ref"] == "U1")
        assert u1["lcsc_id"] == "C12345"
        assert u1["basic_extended"] == "Basic"
        assert u1["populate_dnp"] == "Populate"
        assert u1["flags"] == ""
