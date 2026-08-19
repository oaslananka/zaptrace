from __future__ import annotations

from pathlib import Path

import yaml

from scripts.migrate_component_schema_v2 import main, migrate_file, migrate_record
from zaptrace.library.schema import ComponentField, ComponentTrustTier, validate_component_record


def legacy_record() -> dict[str, object]:
    return {
        "id": "legacy-rf",
        "name": "Legacy RF",
        "category": "rf",
        "manufacturer": "Acme",
        "mpn": "ACME-RF-1",
        'description"': "legacy typo",
        "datasheet": "https://manufacturer.example/rf.pdf",
        "package": "QFN-20",
        "footprint": "ACME-QFN20",
        "lifecycle": "active",
        "voltage_supply": "3.3",
        "pins": {
            "VDD": {"type": "power", 'description"': "supply typo"},
            "GND": {"type": "power", "description": "Ground"},
        },
        "properties": {"interface": "spi"},
        "electrical_limits": {"voltage_supply": "3.3"},
        "sourcing": {
            "mpn": "ACME-RF-1",
            "manufacturer": "Acme",
            "status": "starter-library-entry",
            "production_note": "confirm before production",
        },
        "compliance": {
            "rohs": "supplier-confirmation-required",
            "reach": "supplier-confirmation-required",
            "production_note": "not certification",
        },
        "provenance": {
            "source": "offline-manifest",
            "reviewed_by": "unreviewed",
            "generation": "scripts/generate_library_expansion.py",
        },
    }


def test_migration_adds_schema_tier_and_all_critical_field_provenance() -> None:
    migrated, changed = migrate_record(legacy_record())
    record = validate_component_record(migrated)

    assert changed is True
    assert record.schema_version == "2.0"
    assert record.trust_tier is ComponentTrustTier.HEURISTIC
    assert set(record.field_provenance) == set(ComponentField)
    assert record.human_review is None
    assert migrated["description"] == "legacy typo"
    assert 'description"' not in migrated
    assert migrated["pins"]["VDD"]["description"] == "supply typo"  # type: ignore[index]
    assert 'description"' not in migrated["pins"]["VDD"]  # type: ignore[operator,index]


def test_migration_classifies_datasheet_and_family_template_sources_honestly() -> None:
    migrated, _ = migrate_record(legacy_record())
    datasheet = migrated["field_provenance"]["datasheet"]  # type: ignore[index]
    pin_map = migrated["field_provenance"]["pin_map"]  # type: ignore[index]

    assert datasheet["source_type"] == "manufacturer_web"
    assert datasheet["source_locator"] == "https://manufacturer.example/rf.pdf"
    assert datasheet["confidence"] == "low"
    assert not datasheet.get("source_sha256")
    assert pin_map["source_type"] == "family_template"
    assert pin_map["source_locator"] == "scripts/generate_library_expansion.py"


def test_migration_is_idempotent_for_memory_and_file_output(tmp_path: Path) -> None:
    first, first_changed = migrate_record(legacy_record())
    second, second_changed = migrate_record(first)

    assert first_changed is True
    assert second_changed is False
    assert second == first

    path = tmp_path / "library" / "rf" / "legacy-rf.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(legacy_record(), sort_keys=False), encoding="utf-8")

    assert migrate_file(path, write=True) is True
    after_first = path.read_text(encoding="utf-8")
    assert migrate_file(path, write=True) is False
    assert path.read_text(encoding="utf-8") == after_first


def test_library_expansion_generator_emits_strict_schema_v2_records() -> None:
    from scripts.generate_library_expansion import collect_all_parts

    generated = collect_all_parts()

    assert generated
    for _category, _part_id, raw in generated:
        record = validate_component_record(raw)
        assert record.trust_tier is ComponentTrustTier.HEURISTIC
        assert record.lifecycle == "active"
        assert set(record.field_provenance) == set(ComponentField)


def test_check_mode_is_explicit_and_fails_on_schema_drift(tmp_path: Path) -> None:
    path = tmp_path / "library" / "rf" / "legacy-rf.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(legacy_record(), sort_keys=False), encoding="utf-8")

    assert main(["--library-root", str(tmp_path / "library"), "--check", "--strict"]) == 1
    assert main(["--library-root", str(tmp_path / "library"), "--write", "--strict"]) == 0
    assert main(["--library-root", str(tmp_path / "library"), "--check", "--strict"]) == 0


def test_insecure_datasheet_url_is_not_promoted_to_manufacturer_evidence() -> None:
    raw = legacy_record()
    raw["datasheet"] = "http://manufacturer.example/part.pdf"

    migrated, _ = migrate_record(raw)

    assert migrated["field_provenance"]["datasheet"]["source_type"] == "internal_manifest"
