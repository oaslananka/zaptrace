"""Tests for datasheet intelligence extraction pipeline."""

from __future__ import annotations

import pytest

from zaptrace.library.datasheet import ExtractedField, extract_datasheet

_LDO_DATASHEET = """
TS2940 Positive Voltage Regulator
Texas Instruments — Low-Dropout Linear Regulator

The TS2940 is a 1A low-dropout regulator.

Features:
  - Supply (Input) Voltage: 5V to 15V
  - Output Voltage: Fixed 5V / 3.3V / Adjustable
  - Output Current: 1 A maximum
  - Dropout Voltage: 500 mV at 1A
  - Quiescent Current: 55 uA typical
  - Operating Temperature: -40°C to +125°C
  - Package: SOT-223

Pin Table:
  Pin 1  IN    Input voltage
  Pin 2  GND   Ground
  Pin 3  OUT   Regulated output
"""


class TestExtractDatasheet:
    def test_part_number_extracted(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.part_number.value is not None
        assert "TS2940" in str(result.part_number.value)
        assert result.part_number.confidence > 0.5

    def test_manufacturer_extracted(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.manufacturer.value is not None
        assert "Texas Instruments" in str(result.manufacturer.value)

    def test_package_extracted(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.package.value is not None
        assert "SOT" in str(result.package.value).upper()

    def test_supply_voltage_range(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.supply_voltage_min_v.value == pytest.approx(5.0)
        assert result.supply_voltage_max_v.value == pytest.approx(15.0)

    def test_output_current_extracted(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.output_current_max_a.value == pytest.approx(1.0, rel=0.01)

    def test_temperature_range(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.operating_temp_min_c.value == pytest.approx(-40.0)
        assert result.operating_temp_max_c.value == pytest.approx(125.0)

    def test_dropout_voltage_mv(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.dropout_voltage_v.value == pytest.approx(0.5, rel=0.01)

    def test_quiescent_current_ua(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.quiescent_current_ua.value == pytest.approx(55.0, rel=0.01)

    def test_pin_functions_extracted(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        # At least GND and OUT should be detected
        assert len(result.pin_functions) >= 2

    def test_fill_rate(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        # Most fields should be filled for this well-structured text
        assert result.fill_rate > 0.5

    def test_serializable(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        d = result.to_dict()
        assert "part_number" in d
        assert "fill_rate" not in d  # property, not a field


class TestEmptyDatasheet:
    def test_empty_text_returns_defaults(self) -> None:
        result = extract_datasheet("")
        assert result.part_number.value is None
        assert result.part_number.confidence == 0.0
        assert result.fill_rate == 0.0

    def test_import_losses_populated(self) -> None:
        result = extract_datasheet("")
        assert len(result.import_losses) > 0


class TestExtractedField:
    def test_to_dict(self) -> None:
        f = ExtractedField(3.3, 0.9, "3.3V supply")
        d = f.to_dict()
        assert d["value"] == 3.3
        assert d["confidence"] == 0.9
        assert d["source_snippet"] == "3.3V supply"


class TestDatasheetFactProvenance:
    def test_datasheet_hash_is_stable(self) -> None:
        from zaptrace.library.datasheet import datasheet_sha256

        assert datasheet_sha256("abc") == datasheet_sha256(b"abc")
        assert len(datasheet_sha256("abc")) == 64

    def test_fact_report_has_hash_page_table_and_scope(self) -> None:
        from zaptrace.library.datasheet import DatasheetFactScope, build_datasheet_fact_report, datasheet_sha256

        report = build_datasheet_fact_report(
            "ts2940",
            _LDO_DATASHEET,
            datasheet_url="https://example.com/ts2940.pdf",
            page=7,
        )

        assert report.datasheet_sha256 == datasheet_sha256(_LDO_DATASHEET)
        assert report.fact_count > 0
        assert report.absolute_maximum == []
        assert report.recommended_operating
        fact = report.recommended_operating[0]
        assert fact.scope == DatasheetFactScope.RECOMMENDED_OPERATING
        assert fact.source.datasheet_sha256 == report.datasheet_sha256
        assert fact.source.page == 7
        assert fact.source.table == "Recommended Operating Conditions"
        assert fact.source.figure == ""
        assert fact.source.source_snippet

    def test_absolute_maximum_and_recommended_operating_are_separate_lists(self) -> None:
        from zaptrace.library.datasheet import (
            DatasheetFact,
            DatasheetFactReport,
            DatasheetFactScope,
            DatasheetSourceRef,
        )

        source = DatasheetSourceRef(
            datasheet_url="https://example.com/ds.pdf",
            datasheet_sha256="a" * 64,
            page=4,
            table="Absolute Maximum Ratings",
            figure="Figure 3",
            section="absolute maximum ratings",
            source_snippet="VIN to GND -0.3V to 20V",
        )
        absolute = DatasheetFact(
            component_id="u1",
            field="vin_abs_max_v",
            value=20.0,
            unit="V",
            scope=DatasheetFactScope.ABSOLUTE_MAXIMUM,
            confidence=0.95,
            source=source,
        )
        recommended = DatasheetFact(
            component_id="u1",
            field="vin_recommended_max_v",
            value=12.0,
            unit="V",
            scope=DatasheetFactScope.RECOMMENDED_OPERATING,
            confidence=0.95,
            source=source.model_copy(update={"table": "Recommended Operating Conditions"}),
        )
        report = DatasheetFactReport(
            component_id="u1",
            datasheet_sha256="a" * 64,
            absolute_maximum=[absolute],
            recommended_operating=[recommended],
        )

        assert report.absolute_maximum[0].scope == DatasheetFactScope.ABSOLUTE_MAXIMUM
        assert report.recommended_operating[0].scope == DatasheetFactScope.RECOMMENDED_OPERATING
        assert report.fact_count == 2
        assert report.absolute_maximum[0].source.table == "Absolute Maximum Ratings"
        assert report.absolute_maximum[0].source.figure == "Figure 3"

    def test_proof_manifest_can_include_datasheet_provenance(self) -> None:
        from zaptrace.proof.manifest import DatasheetProvenanceEvidence, ProofManifest

        manifest = ProofManifest(
            name="datasheet-proof",
            design_path="design.yaml",
            datasheet_provenance=DatasheetProvenanceEvidence(
                report_path="datasheet-facts.json",
                component_count=1,
                fact_count=5,
                absolute_maximum_count=1,
                recommended_operating_count=2,
                missing_hash_count=0,
                message="datasheet provenance recorded",
            ),
        )

        dumped = manifest.model_dump(mode="json")
        assert dumped["datasheet_provenance"]["report_path"] == "datasheet-facts.json"
        assert dumped["datasheet_provenance"]["absolute_maximum_count"] == 1
        assert dumped["datasheet_provenance"]["recommended_operating_count"] == 2


class TestDatasheetConfidenceAndConflicts:
    def test_confidence_level_vocabulary(self) -> None:
        from zaptrace.library.datasheet import DatasheetConfidenceLevel, confidence_level

        assert confidence_level(0.9) == DatasheetConfidenceLevel.HIGH
        assert confidence_level(0.7) == DatasheetConfidenceLevel.MEDIUM
        assert confidence_level(0.2) == DatasheetConfidenceLevel.LOW

    def test_low_confidence_fact_requires_human_review(self) -> None:
        from zaptrace.library.datasheet import (
            DatasheetFact,
            DatasheetFactReport,
            DatasheetFactScope,
            DatasheetSourceRef,
            validate_datasheet_facts,
        )

        source = DatasheetSourceRef(datasheet_sha256="b" * 64, page=2, table="Electrical Characteristics")
        report = DatasheetFactReport(
            component_id="u1",
            datasheet_sha256="b" * 64,
            other_facts=[
                DatasheetFact(
                    component_id="u1",
                    field="dropout_voltage_v",
                    value=0.5,
                    unit="V",
                    scope=DatasheetFactScope.ELECTRICAL_CHARACTERISTIC,
                    confidence=0.4,
                    source=source,
                )
            ],
        )

        validation = validate_datasheet_facts(report)

        assert validation.blocked is False
        assert validation.human_review_required is True
        assert validation.low_confidence_count == 1
        assert validation.diagnostics[0].code == "low-confidence"
        assert validation.diagnostics[0].severity == "warning"

    def test_conflicting_facts_block_validation(self) -> None:
        from zaptrace.library.datasheet import (
            DatasheetFact,
            DatasheetFactReport,
            DatasheetFactScope,
            DatasheetSourceRef,
            validate_datasheet_facts,
        )

        source = DatasheetSourceRef(datasheet_sha256="c" * 64, page=4, table="Recommended Operating Conditions")
        f1 = DatasheetFact(
            component_id="u1",
            field="supply_voltage_max_v",
            value=5.5,
            unit="V",
            scope=DatasheetFactScope.RECOMMENDED_OPERATING,
            confidence=0.95,
            source=source,
        )
        f2 = f1.model_copy(update={"value": 6.0})
        report = DatasheetFactReport(
            component_id="u1",
            datasheet_sha256="c" * 64,
            recommended_operating=[f1, f2],
        )

        validation = validate_datasheet_facts(report)

        assert validation.blocked is True
        assert validation.conflict_count == 1
        assert validation.diagnostics[0].code == "conflicting-facts"
        assert validation.diagnostics[0].severity == "error"

    def test_missing_datasheet_hash_blocks_validation(self) -> None:
        from zaptrace.library.datasheet import (
            DatasheetFact,
            DatasheetFactReport,
            DatasheetFactScope,
            DatasheetSourceRef,
            validate_datasheet_facts,
        )

        report = DatasheetFactReport(
            component_id="u1",
            datasheet_sha256="d" * 64,
            other_facts=[
                DatasheetFact(
                    component_id="u1",
                    field="package",
                    value="SOT-23",
                    scope=DatasheetFactScope.PACKAGE,
                    confidence=0.9,
                    source=DatasheetSourceRef(datasheet_sha256=""),
                )
            ],
        )

        validation = validate_datasheet_facts(report)

        assert validation.blocked is True
        assert validation.missing_hash_count == 1


class TestDatasheetHashReverification:
    def test_matching_hash_keeps_facts_current(self) -> None:
        from zaptrace.library.datasheet import DatasheetHashStatus, build_datasheet_fact_report, verify_datasheet_hash

        report = build_datasheet_fact_report("ts2940", _LDO_DATASHEET)
        result = verify_datasheet_hash(report, _LDO_DATASHEET)

        assert result.status == DatasheetHashStatus.CURRENT
        assert result.stale_fact_count == 0
        assert result.affected_fields == []

    def test_changed_hash_marks_dependent_facts_stale(self) -> None:
        from zaptrace.library.datasheet import DatasheetHashStatus, build_datasheet_fact_report, verify_datasheet_hash

        report = build_datasheet_fact_report("ts2940", _LDO_DATASHEET)
        result = verify_datasheet_hash(report, _LDO_DATASHEET + "\nRevision changed output current table")

        assert result.status == DatasheetHashStatus.STALE
        assert result.stale_fact_count == report.fact_count
        assert result.affected_fields
        assert result.expected_sha256 == report.datasheet_sha256
        assert result.observed_sha256 != report.datasheet_sha256

    def test_missing_source_blocks_reverification_report(self) -> None:
        from zaptrace.library.datasheet import DatasheetHashStatus, build_datasheet_fact_report, verify_datasheet_hashes

        report = build_datasheet_fact_report("ts2940", _LDO_DATASHEET)
        verification = verify_datasheet_hashes([(report, None)])

        assert verification.blocked is True
        assert verification.missing_source_count == 1
        assert verification.items[0].status == DatasheetHashStatus.MISSING_SOURCE

    def test_multiple_hash_reports_aggregate_mismatches(self) -> None:
        from zaptrace.library.datasheet import build_datasheet_fact_report, verify_datasheet_hashes

        ok = build_datasheet_fact_report("ok", _LDO_DATASHEET)
        stale = build_datasheet_fact_report("stale", _LDO_DATASHEET)
        verification = verify_datasheet_hashes([(ok, _LDO_DATASHEET), (stale, "changed")])

        assert verification.blocked is True
        assert verification.item_count == 2
        assert verification.hash_mismatch_count == 1
        assert verification.stale_fact_count == stale.fact_count
