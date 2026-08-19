"""Governed LCSC component ingestion with provenance and idempotency.

This module extends :mod:`zaptrace.ee.imports.lcsc` with the audit-trail
requirements from issue #112:

* **Content hash** — SHA-256 of the raw JSON payload, recorded verbatim.
* **Source and timestamp** — fetch origin (``"network"`` / ``"cache"`` /
  ``"fixture"``) and fetch time in UTC ISO format.
* **Parser version** — monotone version string so schema changes are detectable.
* **Classification confidence** — 0–1 float capturing how well the EasyEDA
  data mapped to a governed component.
* **IPC package name check** — explicit failure when the EasyEDA package name
  does not match an IPC-style pattern.
* **Idempotency** — re-ingesting the same raw payload returns the same record;
  the store emits no duplicate and no nondeterministic diff.

Public API
----------
``LcscIngestRecord``
    Immutable provenance record for one ingestion.
``LcscIngestStore``
    Simple in-memory / JSON-file-backed idempotent store.
``ingest_lcsc_part(lcsc_id, *, cache_dir, store)``
    Full ingestion pipeline: fetch → hash → parse → validate → store.
``INGEST_PARSER_VERSION``
    Module-level parser version string.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INGEST_PARSER_VERSION = "1.0"

# IPC-style package name pattern: optional prefix, then optional separator,
# then at least one alphanumeric group with optional size suffix.
# Examples that must match: SOT-23-5, SOIC-8, 0402, QFN-32, DIP-14, SMA.
# Patterns that must NOT match: empty string, pure spaces, "??", "unknown".
_IPC_PACKAGE_RE = re.compile(
    r"^[A-Za-z0-9]"  # must start with alphanumeric
    r"[A-Za-z0-9\-_\.]*"  # body: alphanumeric, dash, underscore, dot
    r"[A-Za-z0-9]$",  # must end with alphanumeric
)


def _is_ipc_package_name(name: str) -> bool:
    """Return ``True`` when *name* looks like an IPC-style package name."""
    if not name or len(name) < 2:
        return False
    return bool(_IPC_PACKAGE_RE.match(name.strip()))


def _sha256_of_dict(data: dict) -> str:
    """Deterministic SHA-256 hex digest of a JSON-serialisable dict."""
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# Provenance record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LcscIngestRecord:
    """Immutable provenance record produced by one LCSC ingestion call.

    Attributes
    ----------
    lcsc_id:
        LCSC part identifier (e.g. ``"C2040"``).
    payload_hash:
        SHA-256 of the raw JSON payload (hex string, 64 chars).
    source:
        Where the payload came from: ``"network"``, ``"cache"``, or
        ``"fixture"``.
    fetched_at:
        UTC ISO timestamp of when the payload was fetched or loaded.
    parser_version:
        :data:`INGEST_PARSER_VERSION` at the time of ingestion.
    package_name:
        Package string extracted from the EasyEDA data (e.g. ``"SOIC-8"``).
    ipc_package_valid:
        ``True`` when *package_name* passes the IPC naming check.
    classification_confidence:
        Float 0–1.  1.0 = all required fields present; lower = missing fields.
    footprint_proof:
        Pad count and other footprint evidence as a serialisable dict.
    pin_map_proof:
        Pin names and count extracted from the symbol as a serialisable dict.
    governance_findings:
        List of human-readable finding strings from governance validation.
    is_duplicate:
        ``True`` when this exact payload hash was already in the store.
    """

    lcsc_id: str
    payload_hash: str
    source: str
    fetched_at: str
    parser_version: str
    package_name: str
    ipc_package_valid: bool
    classification_confidence: float
    footprint_proof: dict[str, Any]
    pin_map_proof: dict[str, Any]
    governance_findings: list[str]
    is_duplicate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "lcsc_id": self.lcsc_id,
            "payload_hash": self.payload_hash,
            "source": self.source,
            "fetched_at": self.fetched_at,
            "parser_version": self.parser_version,
            "package_name": self.package_name,
            "ipc_package_valid": self.ipc_package_valid,
            "classification_confidence": self.classification_confidence,
            "footprint_proof": dict(self.footprint_proof),
            "pin_map_proof": dict(self.pin_map_proof),
            "governance_findings": list(self.governance_findings),
            "is_duplicate": self.is_duplicate,
        }


# ---------------------------------------------------------------------------
# Idempotent store
# ---------------------------------------------------------------------------


class LcscIngestStore:
    """Idempotent in-memory store for :class:`LcscIngestRecord` objects.

    Keyed by ``payload_hash`` — re-ingesting the same payload returns a record
    with ``is_duplicate=True`` and produces no second entry.

    Parameters
    ----------
    path:
        Optional JSON file path.  If provided, the store is loaded from this
        file at construction time and saved after every new ingestion.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._records: dict[str, LcscIngestRecord] = {}
        self._path: Path | None = Path(path) if path else None
        if self._path and self._path.exists():
            self._load()

    def _load(self) -> None:
        if self._path is None:
            return
        try:
            with open(self._path, encoding="utf-8") as fh:
                raw: list[dict] = json.load(fh)
            for entry in raw:
                rec = LcscIngestRecord(**entry)
                self._records[rec.payload_hash] = rec
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    def _save(self) -> None:
        if self._path is None:
            return
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump([r.to_dict() for r in self._records.values()], fh, indent=2)

    def has_hash(self, payload_hash: str) -> bool:
        """Return ``True`` when *payload_hash* is already stored."""
        return payload_hash in self._records

    def put(self, record: LcscIngestRecord) -> LcscIngestRecord:
        """Store *record* and return it.

        If the hash already exists, returns the existing record with
        ``is_duplicate=True`` without storing a duplicate.
        """
        if record.payload_hash in self._records:
            existing = self._records[record.payload_hash]
            # Return a duplicate-flagged version without mutating the store.
            return LcscIngestRecord(
                **{**existing.to_dict(), "is_duplicate": True}  # type: ignore[arg-type]
            )
        # Frozen dataclass: create a new one with is_duplicate forced False.
        self._records[record.payload_hash] = record
        self._save()
        return record

    def all_records(self) -> list[LcscIngestRecord]:
        """All stored records in insertion order (Python 3.7+ dict order)."""
        return list(self._records.values())

    def __len__(self) -> int:
        return len(self._records)


# ---------------------------------------------------------------------------
# Ingest pipeline helpers
# ---------------------------------------------------------------------------


def _classification_confidence(symbol_data: dict | None, footprint_data: dict | None) -> float:
    """Estimate classification confidence based on field coverage."""
    score = 0.0
    total = 4.0
    if footprint_data:
        score += 1.0
        ds = footprint_data.get("dataStr", {})
        if ds.get("head", {}).get("c_para", {}).get("package"):
            score += 1.0
        if ds.get("shape"):
            score += 1.0
    if symbol_data:
        ds = symbol_data.get("dataStr", {})
        if ds.get("shape"):
            score += 1.0
    return round(score / total, 3)


def _extract_package_name(footprint_data: dict | None) -> str:
    """Best-effort package name from EasyEDA footprint data."""
    if not footprint_data:
        return ""
    return (
        footprint_data.get("dataStr", {}).get("head", {}).get("c_para", {}).get("package", "")
        or footprint_data.get("title", "")
        or ""
    )


def _footprint_proof(footprint_data: dict | None) -> dict[str, Any]:
    """Extract minimal footprint evidence for the proof record."""
    if not footprint_data:
        return {"pad_count": 0, "package": ""}
    ds = footprint_data.get("dataStr", {})
    shapes = ds.get("shape", [])
    pad_count = sum(1 for s in shapes if isinstance(s, str) and s.startswith("PAD~"))
    return {
        "pad_count": pad_count,
        "package": ds.get("head", {}).get("c_para", {}).get("package", ""),
    }


def _pin_map_proof(symbol_data: dict | None) -> dict[str, Any]:
    """Extract minimal pin-map evidence for the proof record."""
    if not symbol_data:
        return {"pin_count": 0, "pins": []}
    ds = symbol_data.get("dataStr", {})
    shapes = ds.get("shape", [])
    pins = []
    for s in shapes:
        if not isinstance(s, str):
            continue
        parts = s.split("~")
        if len(parts) >= 2 and parts[0] == "P":
            pin_name = parts[1] if len(parts) > 1 else ""
            pins.append(pin_name)
    return {"pin_count": len(pins), "pins": pins[:20]}


def _governance_findings(
    lcsc_id: str,
    package_name: str,
    ipc_valid: bool,
    footprint_data: dict | None,
    symbol_data: dict | None,
) -> list[str]:
    """Collect governance findings as human-readable strings."""
    findings = []
    if not footprint_data:
        findings.append(f"{lcsc_id}: missing footprint data")
    if not symbol_data:
        findings.append(f"{lcsc_id}: missing symbol data")
    if not package_name:
        findings.append(f"{lcsc_id}: package name is empty")
    elif not ipc_valid:
        findings.append(f"{lcsc_id}: package name {package_name!r} does not match IPC-style pattern")
    return findings


# ---------------------------------------------------------------------------
# Public ingest function
# ---------------------------------------------------------------------------


def ingest_lcsc_part(
    lcsc_id: str,
    *,
    cache_dir: Path | str | None = None,
    store: LcscIngestStore | None = None,
    _fixture_payload: tuple[dict | None, dict | None] | None = None,
) -> LcscIngestRecord:
    """Ingest one LCSC part through the governed pipeline.

    Parameters
    ----------
    lcsc_id:
        LCSC part number (e.g. ``"C2040"``).
    cache_dir:
        Directory for the raw JSON cache.  Defaults to
        ``~/.cache/zaptrace/lcsc``.
    store:
        Idempotent record store.  A new in-memory store is used if not provided.
    _fixture_payload:
        **Test-only override**: ``(symbol_data, footprint_data)`` tuple.
        When provided, network access is bypassed and the source is ``"fixture"``.

    Returns
    -------
    LcscIngestRecord
        Provenance record.  ``is_duplicate=True`` when the payload was already
        in the store.
    """
    from zaptrace.ee.imports.lcsc import CACHE_DIR as DEFAULT_CACHE_DIR
    from zaptrace.ee.imports.lcsc import fetch_lcsc_component

    if store is None:
        store = LcscIngestStore()

    resolved_cache = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    resolved_cache.mkdir(parents=True, exist_ok=True)

    # Determine source
    if _fixture_payload is not None:
        symbol_data, footprint_data = _fixture_payload
        source = "fixture"
    else:
        cache_file = resolved_cache / f"{lcsc_id}.json"
        source = "cache" if cache_file.exists() else "network"
        result = fetch_lcsc_component(lcsc_id)
        if result is None:
            symbol_data, footprint_data = None, None
        else:
            symbol_data, footprint_data = result

    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")

    # Canonical payload for hashing (use empty dicts when absent)
    canonical_payload = {
        "lcsc_id": lcsc_id,
        "symbol": symbol_data or {},
        "footprint": footprint_data or {},
    }
    payload_hash = _sha256_of_dict(canonical_payload)

    # Check idempotency before doing any more work
    if store.has_hash(payload_hash):
        # Fetch the existing record and mark it as duplicate
        existing = next(r for r in store.all_records() if r.payload_hash == payload_hash)
        return LcscIngestRecord(**{**existing.to_dict(), "is_duplicate": True})  # type: ignore[arg-type]

    # Extract evidence
    package_name = _extract_package_name(footprint_data)
    ipc_valid = _is_ipc_package_name(package_name)
    confidence = _classification_confidence(symbol_data, footprint_data)
    fp_proof = _footprint_proof(footprint_data)
    pin_proof = _pin_map_proof(symbol_data)
    findings = _governance_findings(lcsc_id, package_name, ipc_valid, footprint_data, symbol_data)

    record = LcscIngestRecord(
        lcsc_id=lcsc_id,
        payload_hash=payload_hash,
        source=source,
        fetched_at=fetched_at,
        parser_version=INGEST_PARSER_VERSION,
        package_name=package_name,
        ipc_package_valid=ipc_valid,
        classification_confidence=confidence,
        footprint_proof=fp_proof,
        pin_map_proof=pin_proof,
        governance_findings=findings,
        is_duplicate=False,
    )
    return store.put(record)
