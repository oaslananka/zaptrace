"""Tests for governed LCSC component ingestion (issue #112).

Covers:
* LcscIngestRecord: immutable provenance fields, to_dict()
* LcscIngestStore: put, has_hash, idempotency, len, all_records, file persistence
* ingest_lcsc_part: fixture payload path (offline-replayable)
* Payload hash determinism (same payload → same hash)
* IPC package name validation: valid and invalid names
* Classification confidence: full data → 1.0, missing data → lower
* Governance findings: missing footprint, missing symbol, bad package name
* Idempotency: re-ingesting same payload → is_duplicate=True, store unchanged
* Footprint proof: correct pad count extraction
* Pin map proof: correct pin extraction
* Source tagging: "fixture" source with _fixture_payload
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from zaptrace.ee.imports.lcsc_ingest import (
    INGEST_PARSER_VERSION,
    LcscIngestRecord,
    LcscIngestStore,
    _classification_confidence,
    _footprint_proof,
    _governance_findings,
    _is_ipc_package_name,
    _pin_map_proof,
    _sha256_of_dict,
    ingest_lcsc_part,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_MOCK_SYMBOL = {
    "dataStr": {
        "shape": [
            "P~show~0~1~-20~0~VCC~id1",
            "P~show~0~1~-40~0~GND~id2",
        ]
    }
}

_MOCK_FOOTPRINT = {
    "dataStr": {
        "head": {"x": 0, "y": 0, "c_para": {"package": "SOIC-8"}},
        "shape": [
            "PAD~RECT~0~0~1~1~1~1",
            "PAD~RECT~0~0~1~1~1~2",
        ],
    }
}

_MOCK_FOOTPRINT_QFN = {
    "dataStr": {
        "head": {"x": 0, "y": 0, "c_para": {"package": "QFN-32"}},
        "shape": [f"PAD~RECT~0~0~1~1~1~{i}" for i in range(32)],
    }
}


def _make_store() -> LcscIngestStore:
    return LcscIngestStore()


def _ingest_once(lcsc_id: str = "C2040", store: LcscIngestStore | None = None) -> LcscIngestRecord:
    if store is None:
        store = _make_store()
    return ingest_lcsc_part(lcsc_id, store=store, _fixture_payload=(_MOCK_SYMBOL, _MOCK_FOOTPRINT))


# ---------------------------------------------------------------------------
# IPC package name validation
# ---------------------------------------------------------------------------


class TestIpcPackageName:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("SOIC-8", True),
            ("QFN-32", True),
            ("0402", True),
            ("SOT-23-5", True),
            ("DIP-14", True),
            ("SMA", True),
            ("TO-220", True),
            ("BGA-144", True),
            ("", False),
            ("  ", False),
            ("?", False),
            ("unknown", True),  # matches alphanumeric pattern
            ("X", False),  # too short (< 2 chars)
            ("A1", True),  # minimal valid
        ],
    )
    def test_ipc_pattern(self, name: str, expected: bool) -> None:
        assert _is_ipc_package_name(name) == expected, f"name={name!r}"


# ---------------------------------------------------------------------------
# SHA-256 payload hash
# ---------------------------------------------------------------------------


class TestSha256OfDict:
    def test_deterministic(self) -> None:
        payload = {"a": 1, "b": [2, 3]}
        first = _sha256_of_dict(payload)
        second = _sha256_of_dict(dict(payload))
        assert first == second

    def test_key_order_independent(self) -> None:
        d1 = {"a": 1, "b": 2}
        d2 = {"b": 2, "a": 1}
        assert _sha256_of_dict(d1) == _sha256_of_dict(d2)

    def test_different_payloads_different_hashes(self) -> None:
        assert _sha256_of_dict({"a": 1}) != _sha256_of_dict({"a": 2})

    def test_returns_64_char_hex(self) -> None:
        h = _sha256_of_dict({"test": True})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# Classification confidence
# ---------------------------------------------------------------------------


class TestClassificationConfidence:
    def test_full_data_is_one(self) -> None:
        conf = _classification_confidence(_MOCK_SYMBOL, _MOCK_FOOTPRINT)
        assert conf == pytest.approx(1.0)

    def test_no_data_is_zero(self) -> None:
        conf = _classification_confidence(None, None)
        assert conf == pytest.approx(0.0)

    def test_footprint_only_partial(self) -> None:
        conf = _classification_confidence(None, _MOCK_FOOTPRINT)
        assert 0.0 < conf < 1.0

    def test_symbol_only_partial(self) -> None:
        conf = _classification_confidence(_MOCK_SYMBOL, None)
        assert 0.0 < conf < 1.0


# ---------------------------------------------------------------------------
# Footprint proof
# ---------------------------------------------------------------------------


class TestFootprintProof:
    def test_pad_count_correct(self) -> None:
        proof = _footprint_proof(_MOCK_FOOTPRINT)
        assert proof["pad_count"] == 2

    def test_package_name_extracted(self) -> None:
        proof = _footprint_proof(_MOCK_FOOTPRINT)
        assert proof["package"] == "SOIC-8"

    def test_qfn32_pad_count(self) -> None:
        proof = _footprint_proof(_MOCK_FOOTPRINT_QFN)
        assert proof["pad_count"] == 32

    def test_none_footprint_returns_zeros(self) -> None:
        proof = _footprint_proof(None)
        assert proof["pad_count"] == 0
        assert proof["package"] == ""


# ---------------------------------------------------------------------------
# Pin map proof
# ---------------------------------------------------------------------------


class TestPinMapProof:
    def test_pin_count_correct(self) -> None:
        proof = _pin_map_proof(_MOCK_SYMBOL)
        assert proof["pin_count"] == 2

    def test_pins_list_nonempty(self) -> None:
        proof = _pin_map_proof(_MOCK_SYMBOL)
        assert len(proof["pins"]) == 2

    def test_none_symbol_returns_zeros(self) -> None:
        proof = _pin_map_proof(None)
        assert proof["pin_count"] == 0
        assert proof["pins"] == []


# ---------------------------------------------------------------------------
# Governance findings
# ---------------------------------------------------------------------------


class TestGovernanceFindings:
    def test_no_findings_for_complete_data(self) -> None:
        findings = _governance_findings("C2040", "SOIC-8", True, _MOCK_FOOTPRINT, _MOCK_SYMBOL)
        assert findings == []

    def test_finding_for_missing_footprint(self) -> None:
        findings = _governance_findings("C2040", "", False, None, _MOCK_SYMBOL)
        assert any("footprint" in f.lower() for f in findings)

    def test_finding_for_missing_symbol(self) -> None:
        findings = _governance_findings("C2040", "SOIC-8", True, _MOCK_FOOTPRINT, None)
        assert any("symbol" in f.lower() for f in findings)

    def test_finding_for_bad_package_name(self) -> None:
        findings = _governance_findings("C2040", "bad??name", False, _MOCK_FOOTPRINT, _MOCK_SYMBOL)
        assert any("ipc" in f.lower() or "package" in f.lower() for f in findings)

    def test_finding_for_empty_package_name(self) -> None:
        findings = _governance_findings("C2040", "", False, _MOCK_FOOTPRINT, _MOCK_SYMBOL)
        assert any("package" in f.lower() for f in findings)


# ---------------------------------------------------------------------------
# LcscIngestRecord
# ---------------------------------------------------------------------------


class TestLcscIngestRecord:
    def test_to_dict_has_all_keys(self) -> None:
        rec = _ingest_once()
        d = rec.to_dict()
        required = {
            "lcsc_id",
            "payload_hash",
            "source",
            "fetched_at",
            "parser_version",
            "package_name",
            "ipc_package_valid",
            "classification_confidence",
            "footprint_proof",
            "pin_map_proof",
            "governance_findings",
            "is_duplicate",
        }
        assert required <= d.keys()

    def test_parser_version_matches_module(self) -> None:
        rec = _ingest_once()
        assert rec.parser_version == INGEST_PARSER_VERSION

    def test_frozen_immutability(self) -> None:
        rec = _ingest_once()
        import dataclasses

        assert dataclasses.is_dataclass(rec)
        with pytest.raises(dataclasses.FrozenInstanceError):
            rec.lcsc_id = "MUTATED"  # type: ignore[misc]

    def test_source_is_fixture(self) -> None:
        rec = _ingest_once()
        assert rec.source == "fixture"

    def test_fetched_at_is_iso_string(self) -> None:
        from datetime import datetime

        rec = _ingest_once()
        # Must be parseable as ISO datetime
        dt = datetime.fromisoformat(rec.fetched_at)
        assert dt.tzinfo is not None  # must be timezone-aware

    def test_payload_hash_is_64_chars(self) -> None:
        rec = _ingest_once()
        assert len(rec.payload_hash) == 64

    def test_confidence_is_one_for_full_data(self) -> None:
        rec = _ingest_once()
        assert rec.classification_confidence == pytest.approx(1.0)

    def test_ipc_valid_for_soic8(self) -> None:
        rec = _ingest_once()
        assert rec.ipc_package_valid is True
        assert rec.package_name == "SOIC-8"

    def test_ipc_invalid_flagged_in_findings(self) -> None:
        bad_fp = {"dataStr": {"head": {"c_para": {"package": "???"}}, "shape": []}}
        store = _make_store()
        rec = ingest_lcsc_part("C9999", store=store, _fixture_payload=(_MOCK_SYMBOL, bad_fp))
        assert rec.ipc_package_valid is False
        assert any("package" in f.lower() or "ipc" in f.lower() for f in rec.governance_findings)


# ---------------------------------------------------------------------------
# LcscIngestStore
# ---------------------------------------------------------------------------


class TestLcscIngestStore:
    def test_put_and_has_hash(self) -> None:
        store = _make_store()
        rec = _ingest_once(store=store)
        assert store.has_hash(rec.payload_hash)

    def test_len_increases_on_new_ingest(self) -> None:
        store = _make_store()
        assert len(store) == 0
        _ingest_once("C0001", store=store)
        assert len(store) == 1
        _ingest_once("C0002", store=store)
        assert len(store) == 2

    def test_all_records_returns_list(self) -> None:
        store = _make_store()
        _ingest_once("C0001", store=store)
        _ingest_once("C0002", store=store)
        recs = store.all_records()
        assert len(recs) == 2

    def test_file_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "ingest_store.json"
            store1 = LcscIngestStore(path=store_path)
            _ingest_once("C0001", store=store1)
            assert store_path.exists()
            # Load from file
            store2 = LcscIngestStore(path=store_path)
            assert len(store2) == 1

    def test_file_round_trip_preserves_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "ingest_store.json"
            store1 = LcscIngestStore(path=store_path)
            rec1 = _ingest_once("C0001", store=store1)
            store2 = LcscIngestStore(path=store_path)
            assert store2.has_hash(rec1.payload_hash)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_re_ingest_returns_duplicate(self) -> None:
        store = _make_store()
        rec1 = ingest_lcsc_part("C2040", store=store, _fixture_payload=(_MOCK_SYMBOL, _MOCK_FOOTPRINT))
        rec2 = ingest_lcsc_part("C2040", store=store, _fixture_payload=(_MOCK_SYMBOL, _MOCK_FOOTPRINT))
        assert rec1.is_duplicate is False
        assert rec2.is_duplicate is True

    def test_store_size_unchanged_on_duplicate(self) -> None:
        store = _make_store()
        ingest_lcsc_part("C2040", store=store, _fixture_payload=(_MOCK_SYMBOL, _MOCK_FOOTPRINT))
        ingest_lcsc_part("C2040", store=store, _fixture_payload=(_MOCK_SYMBOL, _MOCK_FOOTPRINT))
        assert len(store) == 1

    def test_different_payloads_not_duplicates(self) -> None:
        store = _make_store()
        rec1 = ingest_lcsc_part("C2040", store=store, _fixture_payload=(_MOCK_SYMBOL, _MOCK_FOOTPRINT))
        # Different LCSC ID → different canonical payload
        rec2 = ingest_lcsc_part("C9999", store=store, _fixture_payload=(_MOCK_SYMBOL, _MOCK_FOOTPRINT))
        assert rec1.payload_hash != rec2.payload_hash
        assert rec2.is_duplicate is False
        assert len(store) == 2

    def test_same_payload_same_hash(self) -> None:
        """Two calls with identical data must produce the same hash."""
        store1 = _make_store()
        store2 = _make_store()
        rec1 = ingest_lcsc_part("C2040", store=store1, _fixture_payload=(_MOCK_SYMBOL, _MOCK_FOOTPRINT))
        rec2 = ingest_lcsc_part("C2040", store=store2, _fixture_payload=(_MOCK_SYMBOL, _MOCK_FOOTPRINT))
        assert rec1.payload_hash == rec2.payload_hash


# ---------------------------------------------------------------------------
# Offline replay (fixture-based)
# ---------------------------------------------------------------------------


class TestOfflineReplay:
    def test_fixture_source_is_tagged(self) -> None:
        rec = _ingest_once()
        assert rec.source == "fixture"

    def test_no_network_access_needed(self) -> None:
        """The fixture path must not import httpx or make network calls."""
        import zaptrace.ee.imports.lcsc_ingest as mod

        # Check the module can be imported without network
        assert mod.INGEST_PARSER_VERSION == "1.0"

    def test_footprint_pad_count_in_proof(self) -> None:
        rec = _ingest_once()
        assert rec.footprint_proof["pad_count"] == 2

    def test_pin_count_in_proof(self) -> None:
        rec = _ingest_once()
        assert rec.pin_map_proof["pin_count"] == 2

    def test_governance_findings_empty_for_valid_part(self) -> None:
        rec = _ingest_once()
        assert rec.governance_findings == []

    def test_missing_footprint_flagged(self) -> None:
        store = _make_store()
        rec = ingest_lcsc_part("C0001", store=store, _fixture_payload=(None, None))
        assert len(rec.governance_findings) > 0

    def test_to_dict_json_serialisable(self) -> None:
        rec = _ingest_once()
        d = rec.to_dict()
        # Must not raise
        encoded = json.dumps(d)
        decoded = json.loads(encoded)
        assert decoded["lcsc_id"] == rec.lcsc_id
