"""Curated 100-part LCSC manifest ingestion (issue #113).

This module defines:

* :data:`MANIFEST_VERSION` — semantic version of the fixture manifest.
* :data:`MANIFEST_PARTS` — 100 curated fixture entries spanning major package
  families (modules, DFN/LGA/aQFN, RJ45, RF, common discretes, through-hole,
  inductors, capacitors, crystals).
* :class:`ManifestEntry` — one row in the manifest: LCSC ID + fixture data.
* :class:`IntegrityViolation` — a specific provenance or structural defect.
* :class:`IntegrityReport` — full deterministic batch report.
* :func:`ingest_manifest` — replay all 100 parts from cache, network-disabled.
* :func:`check_integrity` — produce a report over a list of
  :class:`~zaptrace.ee.imports.lcsc_ingest.LcscIngestRecord` results.

All fixture data is embedded so CI replay requires **zero network access**.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zaptrace.ee.imports.lcsc_ingest import LcscIngestRecord, LcscIngestStore, ingest_lcsc_part

MANIFEST_VERSION: str = "1.0"

# ---------------------------------------------------------------------------
# Fixture data factories
# ---------------------------------------------------------------------------


def _sym(pins: list[str]) -> dict[str, Any]:
    """Minimal EasyEDA-shaped symbol fixture with the given pin names."""
    return {"dataStr": {"shape": [f"P~show~0~1~{-20 * (i + 1)}~0~{name}~id{i}" for i, name in enumerate(pins)]}}


def _fp(package: str, pad_count: int) -> dict[str, Any]:
    """Minimal EasyEDA-shaped footprint fixture."""
    return {
        "dataStr": {
            "head": {"x": 0, "y": 0, "c_para": {"package": package}},
            "shape": [f"PAD~RECT~0~0~1~1~1~{i + 1}" for i in range(pad_count)],
        }
    }


# ---------------------------------------------------------------------------
# ManifestEntry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestEntry:
    """One curated part in the 100-part LCSC manifest.

    Attributes
    ----------
    lcsc_id:
        LCSC part identifier (e.g. ``"C2040"``).
    family:
        Broad package-family label used for coverage accounting.
    fixture_symbol:
        Offline-replayable EasyEDA-shaped symbol data.
    fixture_footprint:
        Offline-replayable EasyEDA-shaped footprint data.
    """

    lcsc_id: str
    family: str
    fixture_symbol: dict[str, Any]
    fixture_footprint: dict[str, Any]


# ---------------------------------------------------------------------------
# 100-part curated manifest
# ---------------------------------------------------------------------------

MANIFEST_PARTS: list[ManifestEntry] = [
    # --- Resistors (0402) ---
    ManifestEntry("C11702", "resistor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C17522", "resistor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C22775", "resistor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C25741", "resistor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C105872", "resistor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C137256", "resistor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C144975", "resistor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C153557", "resistor", _sym(["1", "2"]), _fp("0402", 2)),
    # --- Resistors (0603) ---
    ManifestEntry("C14676", "resistor", _sym(["1", "2"]), _fp("0603", 2)),
    ManifestEntry("C23138", "resistor", _sym(["1", "2"]), _fp("0603", 2)),
    ManifestEntry("C23141", "resistor", _sym(["1", "2"]), _fp("0603", 2)),
    ManifestEntry("C23161", "resistor", _sym(["1", "2"]), _fp("0603", 2)),
    # --- Capacitors (0402) ---
    ManifestEntry("C1525", "capacitor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C1532", "capacitor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C19702", "capacitor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C52923", "capacitor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C65747", "capacitor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C85961", "capacitor", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C107253", "capacitor", _sym(["1", "2"]), _fp("0402", 2)),
    # --- Capacitors (0603 / electrolytic) ---
    ManifestEntry("C16214", "capacitor", _sym(["1", "2"]), _fp("0603", 2)),
    ManifestEntry("C2111524", "capacitor", _sym(["A", "K"]), _fp("CAP-D5.0", 2)),
    ManifestEntry("C2116177", "capacitor", _sym(["A", "K"]), _fp("CAP-D6.3", 2)),
    # --- Inductors ---
    ManifestEntry("C1046", "inductor", _sym(["1", "2"]), _fp("0805", 2)),
    ManifestEntry("C349708", "inductor", _sym(["1", "2"]), _fp("0805", 2)),
    ManifestEntry("C408540", "inductor", _sym(["1", "2"]), _fp("CD75", 2)),
    # --- LEDs ---
    ManifestEntry("C2286", "led", _sym(["A", "K"]), _fp("LED-0603", 2)),
    ManifestEntry("C72043", "led", _sym(["A", "K"]), _fp("LED-0805", 2)),
    ManifestEntry("C189034", "led", _sym(["A", "K"]), _fp("LED-0603", 2)),
    # --- Diodes ---
    ManifestEntry("C8678", "diode", _sym(["A", "K"]), _fp("SOD-323", 2)),
    ManifestEntry("C83541", "diode", _sym(["A", "K"]), _fp("SMA", 2)),
    ManifestEntry("C93873", "diode", _sym(["A", "K"]), _fp("SOD-123", 2)),
    ManifestEntry("C169144", "diode", _sym(["A", "K"]), _fp("DO-214AC", 2)),
    # --- TVS / Zener diodes ---
    ManifestEntry("C2829", "diode", _sym(["A", "K"]), _fp("SOD-323", 2)),
    ManifestEntry("C96345", "tvs", _sym(["A", "K"]), _fp("SMB", 2)),
    # --- MOSFETs ---
    ManifestEntry("C8545", "mosfet", _sym(["G", "D", "S"]), _fp("SOT-23", 3)),
    ManifestEntry("C20917", "mosfet", _sym(["G", "D", "S"]), _fp("SOT-23", 3)),
    ManifestEntry("C190093", "mosfet", _sym(["G", "D", "S"]), _fp("SOT-23", 3)),
    ManifestEntry("C2622522", "mosfet", _sym(["G", "D", "S", "GND"]), _fp("DFN-6", 6)),
    # --- BJTs ---
    ManifestEntry("C526741", "bjt", _sym(["B", "C", "E"]), _fp("SOT-23", 3)),
    ManifestEntry("C33312", "bjt", _sym(["B", "C", "E"]), _fp("SOT-23", 3)),
    # --- LDO regulators ---
    ManifestEntry("C6186", "ldo", _sym(["IN", "OUT", "GND"]), _fp("SOT-23-3", 3)),
    ManifestEntry("C25445", "ldo", _sym(["IN", "OUT", "GND", "EN", "BYPASS"]), _fp("SOT-23-5", 5)),
    ManifestEntry("C86984", "ldo", _sym(["IN", "OUT", "GND"]), _fp("SOT-23-3", 3)),
    # --- DC-DC converters ---
    ManifestEntry("C163836", "dcdc", _sym(["VIN", "VOUT", "GND", "EN", "FB"]), _fp("SOT-23-5", 5)),
    ManifestEntry("C404097", "dcdc", _sym(["VIN", "VOUT", "GND", "EN", "FB", "SS"]), _fp("SOT-23-6", 6)),
    # --- Operational amplifiers ---
    ManifestEntry("C7483", "opamp", _sym(["+IN", "-IN", "OUT", "V+", "V-"]), _fp("SOT-23-5", 5)),
    ManifestEntry(
        "C2644",
        "opamp",
        _sym(["+IN1", "-IN1", "OUT1", "+IN2", "-IN2", "OUT2", "V+", "V-"]),
        _fp("SOIC-8", 8),
    ),
    ManifestEntry("C524371", "opamp", _sym(["+IN", "-IN", "OUT", "V+", "V-", "SD"]), _fp("SOT-23-6", 6)),
    # --- Comparators ---
    ManifestEntry("C163990", "comparator", _sym(["+IN", "-IN", "OUT", "V+", "V-"]), _fp("SOT-23-5", 5)),
    # --- Logic gates ---
    ManifestEntry("C5575", "logic", _sym(["A", "B", "Y", "VCC", "GND"]), _fp("SOT-23-5", 5)),
    ManifestEntry("C5578", "logic", _sym(["A", "B", "Y", "VCC", "GND"]), _fp("SOT-23-5", 5)),
    # --- RS-485 / CAN transceivers ---
    ManifestEntry("C2054", "transceiver", _sym(["A", "B", "DE", "RE", "DI", "RO", "VCC", "GND"]), _fp("SOIC-8", 8)),
    ManifestEntry(
        "C509953",
        "transceiver",
        _sym(["CANH", "CANL", "RS", "TXD", "RXD", "VCC", "GND", "SPLIT"]),
        _fp("SOIC-8", 8),
    ),
    # --- I2C / SPI sensors (common packages) ---
    ManifestEntry("C5165", "sensor", _sym(["SDA", "SCL", "VCC", "GND", "ADD0", "INT"]), _fp("SOT-23-6", 6)),
    ManifestEntry("C84286", "sensor", _sym(["SDA", "SCL", "VCC", "GND", "INT", "DRDY"]), _fp("SOT-23-6", 6)),
    ManifestEntry("C516653", "sensor", _sym(["SDA", "SCL", "VCC", "GND", "CS", "INT"]), _fp("SOIC-8", 8)),
    # --- MCU / modules (SOIC-20 / TSSOP) ---
    ManifestEntry("C14961", "mcu", _sym([f"P{i}" for i in range(20)]), _fp("SOIC-20", 20)),
    ManifestEntry("C16213", "mcu", _sym([f"P{i}" for i in range(20)]), _fp("TSSOP-20", 20)),
    # --- DFN / LGA / aQFN families ---
    ManifestEntry("C2051", "dfn", _sym([f"P{i}" for i in range(8)]), _fp("DFN-8", 8)),
    ManifestEntry("C73122", "dfn", _sym([f"P{i}" for i in range(8)]), _fp("DFN-8", 8)),
    ManifestEntry("C209802", "dfn", _sym([f"P{i}" for i in range(10)]), _fp("DFN-10", 10)),
    ManifestEntry("C179831", "lga", _sym([f"P{i}" for i in range(12)]), _fp("LGA-12", 12)),
    ManifestEntry("C186517", "aqfn", _sym([f"P{i}" for i in range(16)]), _fp("aQFN-16", 16)),
    # --- QFN / QFP families ---
    ManifestEntry("C328088", "qfn", _sym([f"P{i}" for i in range(32)]), _fp("QFN-32", 32)),
    ManifestEntry("C194580", "qfn", _sym([f"P{i}" for i in range(24)]), _fp("QFN-24", 24)),
    ManifestEntry("C2053", "qfp", _sym([f"P{i}" for i in range(44)]), _fp("LQFP-44", 44)),
    # --- BGA ---
    ManifestEntry("C2697733", "bga", _sym([f"P{i}" for i in range(48)]), _fp("BGA-48", 48)),
    # --- RJ45 connectors ---
    ManifestEntry("C64248", "connector", _sym([f"P{i}" for i in range(8)]), _fp("RJ45", 8)),
    ManifestEntry("C114153", "connector", _sym([f"P{i}" for i in range(8)]), _fp("RJ45", 8)),
    # --- USB connectors ---
    ManifestEntry("C165948", "connector", _sym(["VBUS", "D-", "D+", "ID", "GND"]), _fp("USB-A", 5)),
    ManifestEntry("C167566", "connector", _sym(["VBUS", "D-", "D+", "GND"]), _fp("USB-Micro-B", 5)),
    ManifestEntry(
        "C2765186",
        "connector",
        _sym(["VBUS", "D-", "D+", "CC1", "CC2", "SBU1", "SBU2", "GND"]),
        _fp("USB-C", 24),
    ),
    # --- Header / pin connectors ---
    ManifestEntry("C2337", "connector", _sym([f"P{i}" for i in range(8)]), _fp("PH-2.0-8P", 8)),
    ManifestEntry("C124379", "connector", _sym([f"P{i}" for i in range(4)]), _fp("PH-2.0-4P", 4)),
    ManifestEntry("C163404", "connector", _sym([f"P{i}" for i in range(2)]), _fp("2.54mm-2P", 2)),
    # --- RF components ---
    ManifestEntry("C15968", "rf", _sym(["IN", "OUT", "VCC", "GND", "EN"]), _fp("SOT-89-5", 5)),
    ManifestEntry("C193685", "rf", _sym(["RF", "GND"]), _fp("SMA-TH", 2)),
    ManifestEntry("C80805", "rf", _sym(["RF", "GND1", "GND2"]), _fp("0402", 3)),
    ManifestEntry("C2907002", "rf", _sym([f"P{i}" for i in range(6)]), _fp("DFN-6", 6)),
    # --- Crystals / oscillators ---
    ManifestEntry("C9002", "crystal", _sym(["1", "2"]), _fp("3.2x2.5mm", 2)),
    ManifestEntry("C13738", "crystal", _sym(["1", "2"]), _fp("5.0x3.2mm", 2)),
    ManifestEntry("C255909", "oscillator", _sym(["VCC", "GND", "OUT", "OE"]), _fp("OSC-2016", 4)),
    # --- Ferrite beads ---
    ManifestEntry("C1015", "ferrite", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C74942", "ferrite", _sym(["1", "2"]), _fp("0805", 2)),
    # --- Common-mode chokes ---
    ManifestEntry("C513726", "choke", _sym(["1", "2", "3", "4"]), _fp("SMD-0805x4", 4)),
    # --- ESD protection arrays ---
    ManifestEntry("C167973", "esd", _sym(["VCC", "GND", "I/O1", "I/O2", "I/O3", "I/O4"]), _fp("SOT-363", 6)),
    # --- Fuses ---
    ManifestEntry("C210418", "fuse", _sym(["1", "2"]), _fp("0402", 2)),
    ManifestEntry("C88088", "fuse", _sym(["1", "2"]), _fp("1206", 2)),
    # --- Through-hole discretes ---
    ManifestEntry("C17436", "resistor", _sym(["1", "2"]), _fp("R-Axial-DIN0207", 2)),
    ManifestEntry("C35200", "capacitor", _sym(["A", "K"]), _fp("CAP-Radial-D5.0", 2)),
    ManifestEntry("C2085107", "led", _sym(["A", "K"]), _fp("LED-TH-5mm", 2)),
    # --- Power management (DPAK/D2PAK) ---
    ManifestEntry("C153210", "mosfet", _sym(["G", "D", "S"]), _fp("DPAK", 3)),
    ManifestEntry("C156032", "mosfet", _sym(["G", "D", "S"]), _fp("D2PAK", 3)),
    # --- Audio ---
    ManifestEntry(
        "C508530",
        "audio",
        _sym(["VCC", "GND", "OUT+", "OUT-", "IN+", "IN-", "SD", "GAIN"]),
        _fp("SOIC-8", 8),
    ),
    # --- Clock / RTC ---
    ManifestEntry("C404740", "rtc", _sym(["VCC", "GND", "SDA", "SCL", "INT", "RST", "X1", "X2"]), _fp("SOIC-8", 8)),
    # --- Flash / EEPROM ---
    ManifestEntry("C16890", "flash", _sym(["VCC", "GND", "SI", "SO", "CLK", "CS", "WP", "HOLD"]), _fp("SOIC-8", 8)),
    ManifestEntry("C2894862", "eeprom", _sym(["VCC", "GND", "SDA", "SCL", "WP", "A0", "A1", "A2"]), _fp("SOIC-8", 8)),
    # --- Display drivers ---
    ManifestEntry("C2093209", "display", _sym([f"P{i}" for i in range(16)]), _fp("SOIC-16", 16)),
    # --- Motor driver ---
    ManifestEntry(
        "C193070",
        "driver",
        _sym(["VCC", "GND", "IN1", "IN2", "IN3", "IN4", "OUT1", "OUT2"]),
        _fp("SOIC-8", 8),
    ),
    # --- High-side switch ---
    ManifestEntry("C2658030", "switch", _sym(["VCC", "GND", "IN", "OUT", "FAULT"]), _fp("SOT-23-5", 5)),
]

# Verify exactly 100 parts (compile-time check via assertion in module body)
assert len(MANIFEST_PARTS) == 100, f"Manifest must have 100 parts, got {len(MANIFEST_PARTS)}"


# ---------------------------------------------------------------------------
# IntegrityViolation and IntegrityReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntegrityViolation:
    """A specific provenance or structural defect found in one ingested part.

    Attributes
    ----------
    lcsc_id:
        The LCSC identifier of the offending part.
    kind:
        Category of violation: ``"missing_provenance"``, ``"missing_footprint"``,
        ``"missing_pin_map"``, ``"duplicate_identity"``, ``"low_confidence"``.
    detail:
        Human-readable description.
    """

    lcsc_id: str
    kind: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"lcsc_id": self.lcsc_id, "kind": self.kind, "detail": self.detail}


@dataclass
class IntegrityReport:
    """Deterministic integrity report over a batch of ingested parts.

    Attributes
    ----------
    manifest_version:
        Version tag from :data:`MANIFEST_VERSION`.
    generated_at:
        UTC ISO timestamp when the report was generated.
    total_parts:
        Total number of records checked.
    clean_parts:
        Number of records with no violations.
    violations:
        List of all detected violations.
    duplicate_hashes:
        Payload hashes that appear more than once in the batch.
    families_covered:
        Set of distinct ``family`` labels seen in MANIFEST_PARTS.
    """

    manifest_version: str
    generated_at: str
    total_parts: int
    clean_parts: int
    violations: list[IntegrityViolation] = field(default_factory=list)
    duplicate_hashes: list[str] = field(default_factory=list)
    families_covered: set[str] = field(default_factory=set)

    @property
    def passed(self) -> bool:
        """True when there are no integrity violations."""
        return len(self.violations) == 0

    @property
    def violation_count(self) -> int:
        return len(self.violations)

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_version": self.manifest_version,
            "generated_at": self.generated_at,
            "total_parts": self.total_parts,
            "clean_parts": self.clean_parts,
            "violation_count": self.violation_count,
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "duplicate_hashes": self.duplicate_hashes,
            "families_covered": sorted(self.families_covered),
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Deterministic JSON serialisation (keys sorted)."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


# ---------------------------------------------------------------------------
# check_integrity
# ---------------------------------------------------------------------------

_CONFIDENCE_THRESHOLD = 0.5


def _record_integrity_violations(record: LcscIngestRecord) -> list[IntegrityViolation]:
    violations: list[IntegrityViolation] = []
    checks = (
        (not record.payload_hash, "missing_provenance", "payload_hash is empty"),
        (
            record.footprint_proof.get("pad_count", 0) == 0,
            "missing_footprint",
            f"footprint_proof.pad_count = {record.footprint_proof.get('pad_count', 0)}",
        ),
        (
            record.pin_map_proof.get("pin_count", 0) == 0,
            "missing_pin_map",
            f"pin_map_proof.pin_count = {record.pin_map_proof.get('pin_count', 0)}",
        ),
        (
            record.classification_confidence < _CONFIDENCE_THRESHOLD,
            "low_confidence",
            (f"classification_confidence = {record.classification_confidence:.2f} < {_CONFIDENCE_THRESHOLD}"),
        ),
    )
    for failed, kind, detail in checks:
        if failed:
            violations.append(IntegrityViolation(lcsc_id=record.lcsc_id, kind=kind, detail=detail))
    return violations


def _duplicate_identity_violation(
    record: LcscIngestRecord,
    hash_seen: dict[str, str],
    duplicate_hashes: list[str],
) -> IntegrityViolation | None:
    payload_hash = record.payload_hash
    if not payload_hash:
        return None
    first_id = hash_seen.get(payload_hash)
    if first_id is None:
        hash_seen[payload_hash] = record.lcsc_id
        return None
    if payload_hash not in duplicate_hashes:
        duplicate_hashes.append(payload_hash)
    return IntegrityViolation(
        lcsc_id=record.lcsc_id,
        kind="duplicate_identity",
        detail=f"payload_hash already seen for {first_id!r}",
    )


def _clean_record_count(
    records: list[LcscIngestRecord],
    violations: list[IntegrityViolation],
) -> int:
    violating_ids = {violation.lcsc_id for violation in violations}
    return sum(1 for record in records if record.payload_hash and record.lcsc_id not in violating_ids)


def check_integrity(
    records: list[LcscIngestRecord],
) -> IntegrityReport:
    """Produce a deterministic integrity report over ingested records.

    Checks missing provenance, footprint and pin-map evidence, duplicate
    payload identities, and classification confidence below the accepted
    threshold. Violation ordering follows record order and the fixed check
    order used by :func:`_record_integrity_violations`.

    Args:
        records: Ingested LCSC records to inspect.

    Returns:
        An :class:`IntegrityReport` whose ``passed`` property is true only
        when no integrity violations were found.
    """
    violations: list[IntegrityViolation] = []
    hash_seen: dict[str, str] = {}
    duplicate_hashes: list[str] = []
    for record in records:
        violations.extend(_record_integrity_violations(record))
        duplicate_violation = _duplicate_identity_violation(record, hash_seen, duplicate_hashes)
        if duplicate_violation is not None:
            violations.append(duplicate_violation)
    return IntegrityReport(
        manifest_version=MANIFEST_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        total_parts=len(records),
        clean_parts=_clean_record_count(records, violations),
        violations=violations,
        duplicate_hashes=duplicate_hashes,
        families_covered={entry.family for entry in MANIFEST_PARTS},
    )


# ---------------------------------------------------------------------------
# ingest_manifest
# ---------------------------------------------------------------------------


def ingest_manifest(
    *,
    store: LcscIngestStore | None = None,
    store_path: Path | None = None,
) -> tuple[list[LcscIngestRecord], IntegrityReport]:
    """Replay all 100 manifest parts from offline fixture data (no network).

    Parameters
    ----------
    store:
        Optional pre-constructed store; created fresh if not supplied.
    store_path:
        Optional file path for the persistent store.  Passed through to
        :class:`~zaptrace.ee.imports.lcsc_ingest.LcscIngestStore`.

    Returns
    -------
    (records, report)
        ``records`` — list of one :class:`~zaptrace.ee.imports.lcsc_ingest.LcscIngestRecord`
        per manifest entry.
        ``report`` — :class:`IntegrityReport` produced by :func:`check_integrity`.
    """
    if store is None:
        store = LcscIngestStore(path=store_path)

    records: list[LcscIngestRecord] = []
    for entry in MANIFEST_PARTS:
        rec = ingest_lcsc_part(
            entry.lcsc_id,
            store=store,
            _fixture_payload=(entry.fixture_symbol, entry.fixture_footprint),
        )
        records.append(rec)

    report = check_integrity(records)
    return records, report
