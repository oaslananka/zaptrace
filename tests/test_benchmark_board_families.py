from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.benchmark.families import (
    BoardFamilyManifest,
    builtin_board_family_manifest,
    get_board_family,
    list_board_families,
    load_board_family_manifest,
    manifest_json,
    validate_board_family_manifest,
)

MANIFEST_PATH = Path("zaptrace/benchmark/manifests/board-families-v1.json")


def test_builtin_board_family_manifest_is_versioned_and_has_12_families() -> None:
    manifest = builtin_board_family_manifest()

    assert manifest.schema_version == "1.0"
    assert manifest.manifest_version == "2026.06"
    assert manifest.family_count == 12
    assert validate_board_family_manifest(manifest) == []


def test_each_board_family_has_required_artifacts_and_thresholds() -> None:
    manifest = builtin_board_family_manifest()

    for family in manifest.families:
        assert len(family.required_artifacts) >= 4
        assert len(family.acceptance_thresholds) >= 3
        assert all(
            artifact.path_pattern.startswith(f"benchmarks/{family.family_id}/")
            for artifact in family.required_artifacts
        )
        assert any(threshold.metric == "proof_pack.autonomous_status" for threshold in family.acceptance_thresholds)
        assert any(threshold.release_blocking for threshold in family.acceptance_thresholds)


def test_manifest_family_ids_are_unique_and_cover_domains() -> None:
    manifest = builtin_board_family_manifest()
    ids = [family.family_id for family in manifest.families]
    domains = {family.domain for family in manifest.families}

    assert len(ids) == len(set(ids))
    assert {"iot", "industrial", "wireless", "power", "battery", "power-control"} <= domains


def test_list_and_get_board_families() -> None:
    assert get_board_family("esp32_usb_sensor").title == "ESP32 USB sensor node"
    assert all("ble" in family.tags for family in list_board_families(tags=["ble"]))
    assert all(family.domain == "power" for family in list_board_families(domain="power"))


def test_get_unknown_board_family_raises() -> None:
    with pytest.raises(ValueError, match="No benchmark board family"):
        get_board_family("missing")


def test_manifest_json_round_trip() -> None:
    data = json.loads(manifest_json())
    manifest = BoardFamilyManifest.model_validate(data)

    assert manifest.family_count == 12
    assert validate_board_family_manifest(manifest) == []


def test_committed_board_family_manifest_fixture_matches_builtin() -> None:
    loaded = load_board_family_manifest(MANIFEST_PATH)

    assert loaded.model_dump(mode="json") == builtin_board_family_manifest().model_dump(mode="json")
    assert validate_board_family_manifest(loaded) == []
