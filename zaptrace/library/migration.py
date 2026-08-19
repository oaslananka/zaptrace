"""Deterministic migration helpers for component schema v2."""

from __future__ import annotations

import copy
from typing import Any
from urllib.parse import urlsplit

from zaptrace.library.schema import ComponentField, validate_component_record

_SCHEMA_VERSION = "2.0"
_MIGRATION_METHOD = "deterministic-schema-v2-migration"
_LEGACY_SOURCE_VERSION = "legacy-library-v1"

_TOP_LEVEL_ORDER = (
    "schema_version",
    "id",
    "name",
    "category",
    "manufacturer",
    "mpn",
    "description",
    "datasheet",
    "package",
    "footprint",
    "lifecycle",
    "voltage_supply",
    "pins",
    "properties",
    "electrical_limits",
    "sourcing",
    "compliance",
    "provenance",
    "trust_tier",
    "field_provenance",
    "human_review",
)


def _fix_description_key(mapping: dict[str, Any], *, location: str) -> None:
    typo = 'description"'
    if typo not in mapping:
        return
    if "description" in mapping and mapping["description"] != mapping[typo]:
        raise ValueError(f"conflicting description and {typo} at {location}")
    mapping["description"] = mapping.pop(typo)


def _fix_malformed_keys(record: dict[str, Any]) -> None:
    _fix_description_key(record, location="record")
    pins = record.get("pins", {})
    if not isinstance(pins, dict):
        return
    for name, raw_pin in pins.items():
        if isinstance(raw_pin, dict):
            _fix_description_key(raw_pin, location=f"pins.{name}")


def _source_type(field: ComponentField, record: dict[str, Any]) -> str:
    datasheet = str(record.get("datasheet", ""))
    provenance = record.get("provenance", {})
    provenance = provenance if isinstance(provenance, dict) else {}
    generated = bool(provenance.get("generation"))
    if field is ComponentField.DATASHEET:
        scheme = urlsplit(datasheet).scheme.lower()
        if scheme == "https":
            return "manufacturer_web"
        if scheme == "internal":
            return "family_template"
        return "internal_manifest"
    if field in {ComponentField.PIN_MAP, ComponentField.PACKAGE, ComponentField.FOOTPRINT} and generated:
        return "family_template"
    return "internal_manifest"


def _source_locator(field: ComponentField, record: dict[str, Any]) -> str:
    provenance = record.get("provenance", {})
    provenance = provenance if isinstance(provenance, dict) else {}
    if field is ComponentField.DATASHEET and record.get("datasheet"):
        return str(record["datasheet"])
    if _source_type(field, record) == "family_template" and provenance.get("generation"):
        return str(provenance["generation"])
    return str(provenance.get("source") or "legacy-component-library")


def _field_evidence(field: ComponentField, record: dict[str, Any]) -> dict[str, Any]:
    component_id = str(record.get("id", "unknown"))
    return {
        "source_type": _source_type(field, record),
        "source_locator": _source_locator(field, record),
        "source_identity": f"component:{component_id}:{field.value}",
        "source_version": _LEGACY_SOURCE_VERSION,
        "extraction_method": _MIGRATION_METHOD,
        "confidence": "low",
    }


def _ordered_record(record: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    for key in _TOP_LEVEL_ORDER:
        if key in record and not (key == "human_review" and record[key] is None):
            ordered[key] = record[key]
    for key, value in record.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def migrate_record(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return a strict heuristic schema-v2 record and whether it changed."""

    original = copy.deepcopy(raw)
    record = copy.deepcopy(raw)
    _fix_malformed_keys(record)
    record["schema_version"] = _SCHEMA_VERSION
    record.setdefault("trust_tier", "heuristic")
    record.setdefault(
        "field_provenance",
        {field.value: _field_evidence(field, record) for field in ComponentField},
    )
    record = _ordered_record(record)
    validate_component_record(record)
    return record, record != original
