"""Fail-closed physical footprint binding, without arbitrary input paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.core.exceptions import ParseError
from zaptrace.core.parser import dump_str, parse_file, parse_str
from zaptrace.kicad.verified_vendor import _PINNED_FOOTPRINTS, resolve_verified_footprint

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"


def _design_yaml(asset_id: str, *, extra: str = "") -> str:
    return (
        "meta:\n  name: Test\ncomponents:\n"
        "  u1:\n    ref: U1\n    type: mcu\n"
        f"    footprint_asset: {json.dumps(asset_id)}\n{extra}"
        "nets:\n  n1:\n    name: NET\n    nodes: [U1.1]\n"
    )


def test_vendored_bindings_have_concrete_pads_and_roundtrip() -> None:
    d = parse_file(EXAMPLE)
    assert d.components["U1"].footprint_asset == "esp32-wroom-32"
    assert d.components["U2"].footprint_asset == "bme280-lga8"
    assert len(d.components["U1"].footprint_def.pads) == 60
    assert len(d.components["U2"].footprint_def.pads) == 8
    recovered = parse_str(dump_str(d))
    assert recovered.components["U1"].footprint_def == d.components["U1"].footprint_def
    assert recovered.components["U2"].footprint_def == d.components["U2"].footprint_def


@pytest.mark.parametrize("asset", ["../../../../etc/passwd", "/tmp/asset.kicad_mod", "", "unknown"])
def test_unregistered_ids_fail_closed(asset: str) -> None:
    with pytest.raises(ParseError, match="Unknown verified footprint asset"):
        parse_str(_design_yaml(asset))


def test_vendor_digest_mutation_is_rejected_without_modifying_source(monkeypatch: pytest.MonkeyPatch) -> None:
    asset_id = "bme280-lga8"
    filename, _digest = _PINNED_FOOTPRINTS[asset_id]
    monkeypatch.setitem(_PINNED_FOOTPRINTS, asset_id, (filename, "0" * 64))
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        resolve_verified_footprint(asset_id)


def test_inline_override_conflict_fails_closed() -> None:
    original = parse_str(_design_yaml("bme280-lga8"))
    dumped = dump_str(original)
    assert parse_str(dumped).components["u1"].footprint_def == original.components["u1"].footprint_def
    import yaml

    data = yaml.safe_load(dumped)
    data["components"]["u1"]["footprint_def"]["pads"][0]["position"] = [91.0, 93.0]
    with pytest.raises(ParseError, match="conflicts with inline footprint_def"):
        parse_str(yaml.safe_dump(data))


def test_asset_key_must_be_string() -> None:
    with pytest.raises(ParseError, match="footprint_asset must be a registered string"):
        parse_str(_design_yaml("bme280-lga8").replace('"bme280-lga8"', "[1, 2]"))
