"""Tests for 100-part LCSC manifest ingestion and integrity (issue #113).

Covers:
* MANIFEST_PARTS: exactly 100 entries, unique LCSC IDs, non-empty families
* ManifestEntry: immutable, correct factory data
* check_integrity: all clean on valid records, missing provenance, missing
  footprint, missing pin map, low confidence, duplicate identity
* IntegrityReport: passed flag, violation_count, to_dict, to_json
* ingest_manifest: returns 100 records, zero violations, correct families
* Determinism: two runs produce identical payload hashes
* Family coverage: all required families present (modules, DFN/LGA/aQFN,
  RJ45, RF, common discretes)
* CLI: lcsc ingest-manifest succeeds; lcsc ingest --help
* Network-disabled: no httpx/network calls are made during ingest_manifest
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from zaptrace.cli.main import cli
from zaptrace.ee.imports.lcsc_ingest import LcscIngestRecord, LcscIngestStore
from zaptrace.ee.imports.lcsc_manifest import (
    MANIFEST_PARTS,
    MANIFEST_VERSION,
    IntegrityReport,
    _clean_record_count,
    _duplicate_identity_violation,
    _record_integrity_violations,
    check_integrity,
    ingest_manifest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runner() -> CliRunner:
    return CliRunner()


def _make_record(
    lcsc_id: str = "C1234",
    *,
    payload_hash: str = "a" * 64,
    footprint_pad_count: int = 8,
    pin_count: int = 8,
    confidence: float = 1.0,
    is_duplicate: bool = False,
) -> LcscIngestRecord:
    from datetime import UTC, datetime

    return LcscIngestRecord(
        lcsc_id=lcsc_id,
        payload_hash=payload_hash,
        source="fixture",
        fetched_at=datetime.now(UTC).isoformat(),
        parser_version="1.0",
        package_name="SOIC-8",
        ipc_package_valid=True,
        classification_confidence=confidence,
        footprint_proof={"pad_count": footprint_pad_count, "package": "SOIC-8"},
        pin_map_proof={"pin_count": pin_count, "pins": []},
        governance_findings=[],
        is_duplicate=is_duplicate,
    )


# ---------------------------------------------------------------------------
# MANIFEST_PARTS structure
# ---------------------------------------------------------------------------


class TestManifestParts:
    def test_exactly_100_parts(self) -> None:
        assert len(MANIFEST_PARTS) == 100

    def test_all_lcsc_ids_unique(self) -> None:
        ids = [e.lcsc_id for e in MANIFEST_PARTS]
        assert len(ids) == len(set(ids)), "Duplicate LCSC IDs in manifest"

    def test_all_ids_start_with_c(self) -> None:
        for entry in MANIFEST_PARTS:
            assert entry.lcsc_id.startswith("C"), f"Bad ID: {entry.lcsc_id}"

    def test_all_families_nonempty(self) -> None:
        for entry in MANIFEST_PARTS:
            assert entry.family, f"Empty family for {entry.lcsc_id}"

    def test_families_cover_required_categories(self) -> None:
        families = {e.family for e in MANIFEST_PARTS}
        required = {"resistor", "capacitor", "inductor", "led", "diode", "mosfet", "connector", "rf", "sensor"}
        missing = required - families
        assert not missing, f"Missing required families: {missing}"

    def test_rj45_connector_present(self) -> None:
        """At least one RJ45 connector entry."""
        rj45 = [e for e in MANIFEST_PARTS if "RJ45" in e.fixture_footprint["dataStr"]["head"]["c_para"]["package"]]
        assert len(rj45) >= 1

    def test_dfn_family_present(self) -> None:
        dfn = [e for e in MANIFEST_PARTS if e.family == "dfn"]
        assert len(dfn) >= 1

    def test_qfn_family_present(self) -> None:
        qfn = [e for e in MANIFEST_PARTS if e.family == "qfn"]
        assert len(qfn) >= 1

    def test_bga_family_present(self) -> None:
        bga = [e for e in MANIFEST_PARTS if e.family == "bga"]
        assert len(bga) >= 1

    def test_rf_family_present(self) -> None:
        rf = [e for e in MANIFEST_PARTS if e.family == "rf"]
        assert len(rf) >= 1

    def test_crystal_oscillator_families_present(self) -> None:
        families = {e.family for e in MANIFEST_PARTS}
        assert "crystal" in families or "oscillator" in families

    def test_all_fixture_symbols_have_pins(self) -> None:
        for entry in MANIFEST_PARTS:
            shape = entry.fixture_symbol["dataStr"]["shape"]
            assert len(shape) > 0, f"No pins for {entry.lcsc_id}"

    def test_all_fixture_footprints_have_pads(self) -> None:
        for entry in MANIFEST_PARTS:
            shape = entry.fixture_footprint["dataStr"]["shape"]
            assert len(shape) > 0, f"No pads for {entry.lcsc_id}"

    def test_version_is_semver_string(self) -> None:
        parts = MANIFEST_VERSION.split(".")
        assert len(parts) >= 1
        assert parts[0].isdigit()


# ---------------------------------------------------------------------------
# ManifestEntry
# ---------------------------------------------------------------------------


class TestManifestEntry:
    def test_frozen_immutability(self) -> None:
        import dataclasses

        entry = MANIFEST_PARTS[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.lcsc_id = "MUTATED"  # type: ignore[misc]

    def test_entry_has_required_fields(self) -> None:
        entry = MANIFEST_PARTS[0]
        assert entry.lcsc_id
        assert entry.family
        assert entry.fixture_symbol
        assert entry.fixture_footprint


# ---------------------------------------------------------------------------
# check_integrity
# ---------------------------------------------------------------------------


class TestCheckIntegrityClean:
    def test_all_clean_records_pass(self) -> None:
        records = [_make_record(f"C{1000 + i}", payload_hash="a" * 63 + str(i % 10)) for i in range(5)]
        report = check_integrity(records)
        assert report.passed
        assert report.violation_count == 0

    def test_empty_list_passes(self) -> None:
        report = check_integrity([])
        assert report.passed
        assert report.total_parts == 0


class TestCheckIntegrityViolations:
    def test_missing_provenance(self) -> None:
        rec = _make_record("C1", payload_hash="")
        report = check_integrity([rec])
        assert not report.passed
        assert any(v.kind == "missing_provenance" for v in report.violations)

    def test_missing_footprint(self) -> None:
        rec = _make_record("C1", footprint_pad_count=0)
        report = check_integrity([rec])
        assert not report.passed
        assert any(v.kind == "missing_footprint" for v in report.violations)

    def test_missing_pin_map(self) -> None:
        rec = _make_record("C1", pin_count=0)
        report = check_integrity([rec])
        assert not report.passed
        assert any(v.kind == "missing_pin_map" for v in report.violations)

    def test_low_confidence(self) -> None:
        rec = _make_record("C1", confidence=0.3)
        report = check_integrity([rec])
        assert not report.passed
        assert any(v.kind == "low_confidence" for v in report.violations)

    def test_confidence_at_threshold_passes(self) -> None:
        rec = _make_record("C1", confidence=0.5)
        report = check_integrity([rec])
        # 0.5 == threshold, should pass (not < threshold)
        violations = [v for v in report.violations if v.kind == "low_confidence"]
        assert not violations

    def test_duplicate_identity(self) -> None:
        same_hash = "b" * 64
        rec1 = _make_record("C1", payload_hash=same_hash)
        rec2 = _make_record("C2", payload_hash=same_hash)
        report = check_integrity([rec1, rec2])
        assert not report.passed
        dup = [v for v in report.violations if v.kind == "duplicate_identity"]
        assert len(dup) >= 1
        assert same_hash in report.duplicate_hashes

    def test_multiple_violations_same_record(self) -> None:
        rec = _make_record("C1", payload_hash="", footprint_pad_count=0, pin_count=0)
        report = check_integrity([rec])
        assert report.violation_count >= 3

    def test_violation_lcsc_id_matches(self) -> None:
        rec = _make_record("C9999", footprint_pad_count=0)
        report = check_integrity([rec])
        assert all(v.lcsc_id == "C9999" for v in report.violations)


def test_record_integrity_helper_reports_all_independent_failures() -> None:
    record = _make_record("C1", payload_hash="", footprint_pad_count=0, pin_count=0, confidence=0.1)
    assert {item.kind for item in _record_integrity_violations(record)} == {
        "missing_provenance",
        "missing_footprint",
        "missing_pin_map",
        "low_confidence",
    }


def test_duplicate_helper_records_first_seen_identity_once() -> None:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    first = _make_record("C1", payload_hash="b" * 64)
    second = _make_record("C2", payload_hash="b" * 64)
    assert _duplicate_identity_violation(first, seen, duplicates) is None
    violation = _duplicate_identity_violation(second, seen, duplicates)
    assert violation is not None
    assert "C1" in violation.detail
    assert duplicates == ["b" * 64]


def test_clean_count_uses_record_identity_not_violation_scan() -> None:
    records = [_make_record("C1"), _make_record("C2", payload_hash="c" * 64)]
    violations = _record_integrity_violations(_make_record("C2", payload_hash="", footprint_pad_count=0))
    assert _clean_record_count(records, violations) == 1


# ---------------------------------------------------------------------------
# IntegrityReport
# ---------------------------------------------------------------------------


class TestIntegrityReport:
    def _clean_report(self) -> IntegrityReport:
        records = [_make_record(f"C{1000 + i}", payload_hash="a" * 63 + str(i % 10)) for i in range(3)]
        return check_integrity(records)

    def test_to_dict_has_required_keys(self) -> None:
        report = self._clean_report()
        d = report.to_dict()
        required = {
            "manifest_version",
            "generated_at",
            "total_parts",
            "clean_parts",
            "violation_count",
            "passed",
            "violations",
            "duplicate_hashes",
            "families_covered",
        }
        assert required <= d.keys()

    def test_to_json_is_valid_json(self) -> None:
        report = self._clean_report()
        j = report.to_json()
        decoded = json.loads(j)
        assert decoded["passed"] is True

    def test_to_json_is_deterministic(self) -> None:
        records = [_make_record(f"C{1000 + i}", payload_hash="a" * 63 + str(i % 10)) for i in range(3)]
        r1 = check_integrity(records)
        r2 = check_integrity(records)
        # Generated_at will differ; compare everything else
        d1 = r1.to_dict()
        d2 = r2.to_dict()
        d1.pop("generated_at")
        d2.pop("generated_at")
        assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)

    def test_violation_count_property(self) -> None:
        rec = _make_record("C1", footprint_pad_count=0)
        report = check_integrity([rec])
        assert report.violation_count == len(report.violations)

    def test_families_covered_is_set(self) -> None:
        report = self._clean_report()
        # The integrity report gets families from MANIFEST_PARTS which is the global manifest
        assert isinstance(report.families_covered, set)


# ---------------------------------------------------------------------------
# ingest_manifest
# ---------------------------------------------------------------------------


class TestIngestManifest:
    def test_returns_100_records(self) -> None:
        records, _ = ingest_manifest()
        assert len(records) == 100

    def test_zero_violations(self) -> None:
        _, report = ingest_manifest()
        assert report.passed
        assert report.violation_count == 0

    def test_all_records_have_hashes(self) -> None:
        records, _ = ingest_manifest()
        for rec in records:
            assert len(rec.payload_hash) == 64

    def test_all_records_have_footprint_proof(self) -> None:
        records, _ = ingest_manifest()
        for rec in records:
            assert rec.footprint_proof["pad_count"] > 0

    def test_all_records_have_pin_map_proof(self) -> None:
        records, _ = ingest_manifest()
        for rec in records:
            assert rec.pin_map_proof["pin_count"] > 0

    def test_all_records_have_full_confidence(self) -> None:
        records, _ = ingest_manifest()
        for rec in records:
            assert rec.classification_confidence == pytest.approx(1.0)

    def test_store_has_100_entries(self) -> None:
        store = LcscIngestStore()
        ingest_manifest(store=store)
        assert len(store) == 100

    def test_deterministic_hashes(self) -> None:
        """Two runs produce identical payload hashes for every part."""
        store1 = LcscIngestStore()
        store2 = LcscIngestStore()
        recs1, _ = ingest_manifest(store=store1)
        recs2, _ = ingest_manifest(store=store2)
        for r1, r2 in zip(recs1, recs2, strict=True):
            assert r1.payload_hash == r2.payload_hash

    def test_idempotent_second_run(self) -> None:
        """Second run marks all records as duplicates."""
        store = LcscIngestStore()
        recs1, _ = ingest_manifest(store=store)
        recs2, _ = ingest_manifest(store=store)
        assert all(r.is_duplicate is False for r in recs1)
        assert all(r.is_duplicate is True for r in recs2)

    def test_families_covered_include_required(self) -> None:
        _, report = ingest_manifest()
        required = {"resistor", "capacitor", "connector", "rf"}
        assert required <= report.families_covered

    def test_file_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "manifest_store.json"
            ingest_manifest(store_path=store_path)
            assert store_path.exists()
            # Load fresh
            store2 = LcscIngestStore(path=store_path)
            assert len(store2) == 100

    def test_no_network_calls_made(self) -> None:
        """The fixture path must not call fetch_lcsc_component."""
        with patch("zaptrace.ee.imports.lcsc.fetch_lcsc_component") as mock_fetch:
            ingest_manifest()
        mock_fetch.assert_not_called()

    def test_source_is_fixture(self) -> None:
        records, _ = ingest_manifest()
        for rec in records:
            assert rec.source == "fixture"


# ---------------------------------------------------------------------------
# CLI: lcsc commands
# ---------------------------------------------------------------------------


class TestLcscCLI:
    def test_lcsc_help(self) -> None:
        result = _runner().invoke(cli, ["lcsc", "--help"])
        assert result.exit_code == 0
        assert "ingest" in result.output

    def test_lcsc_ingest_manifest_succeeds(self) -> None:
        result = _runner().invoke(cli, ["lcsc", "ingest-manifest"])
        assert result.exit_code == 0
        assert "100 parts" in result.output
        assert "0 violation" in result.output

    def test_lcsc_ingest_manifest_report_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "report.json"
            result = _runner().invoke(cli, ["lcsc", "ingest-manifest", "--report", str(report_path)])
            assert result.exit_code == 0
            assert report_path.exists()
            d = json.loads(report_path.read_text())
            assert d["passed"] is True
            assert d["total_parts"] == 100

    def test_lcsc_ingest_help(self) -> None:
        result = _runner().invoke(cli, ["lcsc", "ingest", "--help"])
        assert result.exit_code == 0
        assert "LCSC_ID" in result.output
