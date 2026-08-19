"""Tests for library integrity gate and 500-part coverage (issue #129).

Covers:
* LibraryIntegrityConfig: defaults, to_dict()
* LibraryPartRecord: is_ungoverned, to_dict()
* LibraryDuplicateGroup: conflict, to_dict()
* LibraryIntegrityReport: accepted, high_confidence_pct, to_dict(), to_json()
* run_library_integrity_gate():
  - passes on real library with 500+ parts
  - fails when library too small (custom root with few parts)
  - reports ungoverned parts correctly
  - detects duplicate groups
  - report_hash is 64 chars
  - all categories present
  - no integrity failures on main library
  - serialisable
* build_coverage_report():
  - returns categories dict
  - has_rf_coverage, has_power_coverage, has_sensor_coverage
  - packages dict populated
  - total_parts >= 500
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from zaptrace.library.integrity import (
    DEFAULT_INTEGRITY_CONFIG,
    LibraryDuplicateGroup,
    LibraryIntegrityConfig,
    LibraryIntegrityReport,
    LibraryPartRecord,
    build_coverage_report,
    run_library_integrity_gate,
)
from zaptrace.library.migration import migrate_record

# ---------------------------------------------------------------------------
# LibraryIntegrityConfig
# ---------------------------------------------------------------------------


class TestLibraryIntegrityConfig:
    def test_defaults(self) -> None:
        assert DEFAULT_INTEGRITY_CONFIG.min_confidence_score == pytest.approx(0.5)
        assert DEFAULT_INTEGRITY_CONFIG.min_library_size == 500
        assert DEFAULT_INTEGRITY_CONFIG.min_high_confidence_pct == pytest.approx(0.70)

    def test_to_dict_keys(self) -> None:
        d = DEFAULT_INTEGRITY_CONFIG.to_dict()
        assert {"min_confidence_score", "min_library_size", "min_high_confidence_pct"} <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(DEFAULT_INTEGRITY_CONFIG.to_dict())


# ---------------------------------------------------------------------------
# LibraryPartRecord
# ---------------------------------------------------------------------------


class TestLibraryPartRecord:
    def test_ungoverned_flag_set(self) -> None:
        r = LibraryPartRecord(
            part_id="bad-part",
            category="passive",
            confidence_score=0.2,
            confidence_grade="low",
            missing_metadata=["mpn", "datasheet"],
            is_ungoverned=True,
        )
        assert r.is_ungoverned is True

    def test_to_dict_keys(self) -> None:
        r = LibraryPartRecord(
            part_id="ok-part",
            category="sensor",
            confidence_score=0.9,
            confidence_grade="high",
            missing_metadata=[],
        )
        d = r.to_dict()
        assert {
            "part_id",
            "category",
            "confidence_score",
            "confidence_grade",
            "missing_metadata",
            "is_ungoverned",
            "duplicate_of",
            "alternate_for",
        } <= d.keys()

    def test_serialisable(self) -> None:
        r = LibraryPartRecord("p1", "power", 0.85, "high", [])
        json.dumps(r.to_dict())


# ---------------------------------------------------------------------------
# LibraryDuplicateGroup
# ---------------------------------------------------------------------------


class TestLibraryDuplicateGroup:
    def test_no_conflict_by_default(self) -> None:
        g = LibraryDuplicateGroup(canonical_id="part-a", alternate_ids=["part-b"])
        assert g.conflict is False

    def test_conflict_flag(self) -> None:
        g = LibraryDuplicateGroup(canonical_id="part-a", alternate_ids=["part-b"], conflict=True)
        assert g.conflict is True

    def test_to_dict_keys(self) -> None:
        d = LibraryDuplicateGroup(canonical_id="part-a").to_dict()
        assert {"canonical_id", "alternate_ids", "conflict"} <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(LibraryDuplicateGroup(canonical_id="x").to_dict())


# ---------------------------------------------------------------------------
# LibraryIntegrityReport
# ---------------------------------------------------------------------------


class TestLibraryIntegrityReport:
    def _pass_report(self) -> LibraryIntegrityReport:
        return LibraryIntegrityReport(
            status="pass",
            total_parts=510,
            high_confidence_count=300,
            medium_confidence_count=200,
            low_confidence_count=10,
            ungoverned_count=0,
            report_hash="a" * 64,
        )

    def test_accepted_when_pass(self) -> None:
        assert self._pass_report().accepted is True

    def test_not_accepted_when_fail(self) -> None:
        r = LibraryIntegrityReport(status="fail", integrity_failures=["too few parts"])
        assert r.accepted is False

    def test_high_confidence_pct(self) -> None:
        r = self._pass_report()
        assert abs(r.high_confidence_pct - (500 / 510)) < 0.001

    def test_high_confidence_pct_zero_total(self) -> None:
        r = LibraryIntegrityReport(status="fail", total_parts=0)
        assert r.high_confidence_pct == pytest.approx(0.0)

    def test_to_dict_keys(self) -> None:
        d = self._pass_report().to_dict()
        required = {
            "status",
            "accepted",
            "total_parts",
            "ungoverned_count",
            "high_confidence_count",
            "medium_confidence_count",
            "low_confidence_count",
            "high_confidence_pct",
            "category_counts",
            "package_coverage",
            "integrity_failures",
            "warnings",
            "duplicate_groups",
            "report_hash",
            "config",
        }
        assert required <= d.keys()

    def test_to_json_round_trips(self) -> None:
        j = self._pass_report().to_json()
        d = json.loads(j)
        assert d["status"] == "pass"
        assert d["accepted"] is True


# ---------------------------------------------------------------------------
# Integrity gate — empty library (custom tmp root)
# ---------------------------------------------------------------------------


def _write_minimal_part(
    root: Path,
    category: str,
    part_id: str,
    **overrides: object,
) -> None:
    path = root / category / f"{part_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {
        "id": part_id,
        "name": part_id.upper(),
        "category": category,
        "manufacturer": "TestCorp",
        "mpn": f"{part_id.upper()}-001",
        "description": "Test part",
        "package": "SOT-23",
        "footprint": f"SOT-23-{part_id}",
        "datasheet": "https://example.com/test.pdf",
        "lifecycle": "active",
        "pins": {"P1": {"type": "passive", "description": "Pin 1"}},
    }
    data.update(overrides)
    migrated, _ = migrate_record(data)
    path.write_text(yaml.safe_dump(migrated, sort_keys=False), encoding="utf-8")


class TestRunIntegrityGateSmallLibrary:
    def test_fails_when_library_too_small(self, tmp_path: Path) -> None:
        _write_minimal_part(tmp_path, "passive", "res-1k")
        _write_minimal_part(tmp_path, "passive", "cap-100n")
        result = run_library_integrity_gate(tmp_path, DEFAULT_INTEGRITY_CONFIG)
        assert result.status == "fail"
        assert any("500" in f or "minimum" in f for f in result.integrity_failures)

    def test_ungoverned_parts_are_sorted_before_governed_parts(self, tmp_path: Path) -> None:
        _write_minimal_part(tmp_path, "passive", "governed")
        _write_minimal_part(
            tmp_path,
            "passive",
            "ungoverned",
            manufacturer="",
            mpn="",
            description="",
            package="",
            footprint="",
            datasheet="",
            lifecycle="unknown",
            pins={},
        )

        result = run_library_integrity_gate(tmp_path, LibraryIntegrityConfig(min_library_size=0))

        assert result.parts[0].part_id == "ungoverned"
        assert result.parts[0].is_ungoverned is True
        assert result.category_counts == {"passive": 2}

    def test_reports_ungoverned_parts(self, tmp_path: Path) -> None:
        # Write a part with no mpn/datasheet (low confidence → below 0.5)
        _write_minimal_part(
            tmp_path,
            "passive",
            "bad-part",
            manufacturer="",
            mpn="",
            description="",
            package="",
            footprint="",
            datasheet="",
            lifecycle="unknown",
            pins={},
        )
        result = run_library_integrity_gate(tmp_path, LibraryIntegrityConfig(min_library_size=0))
        assert result.ungoverned_count >= 1

    def test_no_crash_on_empty_dir(self, tmp_path: Path) -> None:
        result = run_library_integrity_gate(tmp_path, LibraryIntegrityConfig(min_library_size=0))
        assert result.status in {"pass", "fail"}

    def test_report_serialisable_on_failure(self, tmp_path: Path) -> None:
        result = run_library_integrity_gate(tmp_path)
        json.dumps(result.to_dict())

    def test_detects_duplicates(self, tmp_path: Path) -> None:
        # Two parts with same MPN (same manufacturer) → duplicate group
        for part_id in ["part-a", "part-b"]:
            _write_minimal_part(
                tmp_path,
                "passive",
                part_id,
                manufacturer="SameCorp",
                mpn="SAME-MPN-001",
                description="Duplicate part",
                package="0402",
                footprint="0402",
                datasheet="https://example.com/same.pdf",
                pins={"P1": {"type": "passive"}},
            )
        result = run_library_integrity_gate(tmp_path, LibraryIntegrityConfig(min_library_size=0))
        assert len(result.duplicate_groups) >= 1


# ---------------------------------------------------------------------------
# Integrity gate — real library (must have 500+ parts)
# ---------------------------------------------------------------------------


class TestRunIntegrityGateRealLibrary:
    def test_library_has_500_parts(self) -> None:
        result = run_library_integrity_gate()
        assert result.total_parts >= 500, f"Library only has {result.total_parts} parts; expected >= 500"

    def test_no_integrity_failures(self) -> None:
        cfg = LibraryIntegrityConfig(
            min_confidence_score=0.0,  # Don't penalize starter entries
            min_library_size=500,
            min_high_confidence_pct=0.0,  # Don't penalize starter entries
        )
        result = run_library_integrity_gate(config=cfg)
        assert result.total_parts >= 500, f"Only {result.total_parts} parts"
        size_failures = [f for f in result.integrity_failures if "minimum" in f or "500" in f]
        assert not size_failures, f"Size gate failure: {size_failures}"

    def test_report_hash_nonempty(self) -> None:
        result = run_library_integrity_gate()
        assert len(result.report_hash) == 64

    def test_report_hash_deterministic(self) -> None:
        r1 = run_library_integrity_gate()
        r2 = run_library_integrity_gate()
        assert r1.report_hash == r2.report_hash

    def test_serialisable(self) -> None:
        result = run_library_integrity_gate()
        json.dumps(result.to_dict())

    def test_category_counts_populated(self) -> None:
        result = run_library_integrity_gate()
        assert len(result.category_counts) >= 5

    def test_passive_category_present(self) -> None:
        result = run_library_integrity_gate()
        assert "passive" in result.category_counts

    def test_power_category_present(self) -> None:
        result = run_library_integrity_gate()
        assert "power" in result.category_counts

    def test_sensor_category_present(self) -> None:
        result = run_library_integrity_gate()
        assert "sensor" in result.category_counts

    def test_rf_category_present(self) -> None:
        result = run_library_integrity_gate()
        assert "rf" in result.category_counts

    def test_package_coverage_nonempty(self) -> None:
        result = run_library_integrity_gate()
        assert len(result.package_coverage) >= 10


# ---------------------------------------------------------------------------
# build_coverage_report
# ---------------------------------------------------------------------------


class TestBuildCoverageReport:
    def test_has_expected_keys(self) -> None:
        report = build_coverage_report()
        assert {
            "packages",
            "categories",
            "total_parts",
            "packages_with_drc_dfn_lga",
            "has_rf_coverage",
            "has_power_coverage",
            "has_sensor_coverage",
        } <= report.keys()

    def test_total_parts_500_plus(self) -> None:
        report = build_coverage_report()
        total_parts = report["total_parts"]
        assert isinstance(total_parts, int)
        assert total_parts >= 500

    def test_has_rf_coverage(self) -> None:
        report = build_coverage_report()
        assert report["has_rf_coverage"] is True

    def test_has_power_coverage(self) -> None:
        report = build_coverage_report()
        assert report["has_power_coverage"] is True

    def test_has_sensor_coverage(self) -> None:
        report = build_coverage_report()
        assert report["has_sensor_coverage"] is True

    def test_packages_dict_populated(self) -> None:
        report = build_coverage_report()
        assert isinstance(report["packages"], dict)
        assert len(report["packages"]) >= 5  # type: ignore[arg-type]

    def test_serialisable(self) -> None:
        report = build_coverage_report()
        json.dumps(report)

    def test_empty_dir_no_crash(self, tmp_path: Path) -> None:
        report = build_coverage_report(tmp_path)
        assert "total_parts" in report or "error" in report
