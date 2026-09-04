"""Datasheet intelligence pipeline.

Structured extraction schema and heuristic pipeline that turns raw datasheet
text (copy-pasted from a PDF or fetched from a URL) into a machine-readable
:class:`DatasheetExtract`. This is keyword/regex-based extraction — not an LLM
call — so the same intent always yields the same result (verification-first).

Downstream uses:
- Component library enrichment (fill in missing footprint/spec fields).
- ERC rule grounding (ERC024/ERC026 use keyword heuristics today; a parsed
  extract would let them cross-check against datasheet pin-function tables).
- Synthesis parameter validation (verify an LDO dropout voltage against
  the datasheet value).

The ``extract_datasheet()`` function is the public entry point. Every field it
fills in carries a ``confidence`` value in [0.0, 1.0].
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_RECOMMENDED_OPERATING_TABLE = "Recommended Operating Conditions"
_RECOMMENDED_OPERATING_SECTION = "recommended operating conditions"

# ---------------------------------------------------------------------------
# Provenance/fact evidence schema v1
# ---------------------------------------------------------------------------


class DatasheetFactScope(StrEnum):
    """Datasheet fact category with explicit safety semantics."""

    ABSOLUTE_MAXIMUM = "absolute_maximum"
    RECOMMENDED_OPERATING = "recommended_operating"
    PIN_FUNCTION = "pin_function"
    PACKAGE = "package"
    ELECTRICAL_CHARACTERISTIC = "electrical_characteristic"
    THERMAL_CHARACTERISTIC = "thermal_characteristic"


class DatasheetSourceRef(BaseModel):
    """Source locator for a datasheet-derived fact."""

    model_config = ConfigDict(strict=False)

    datasheet_url: str = ""
    datasheet_sha256: str = Field(description="SHA-256 of the source datasheet text/PDF bytes")
    page: int | None = Field(default=None, ge=1)
    table: str = ""
    figure: str = ""
    section: str = ""
    source_snippet: str = ""


class DatasheetFact(BaseModel):
    """One datasheet-derived engineering fact with provenance."""

    model_config = ConfigDict(strict=False)

    component_id: str
    field: str
    value: str | float | int | bool
    unit: str = ""
    scope: DatasheetFactScope
    confidence: float = Field(ge=0, le=1)
    source: DatasheetSourceRef


class DatasheetConfidenceLevel(StrEnum):
    """Discrete confidence classification for extracted facts."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DatasheetDiagnosticSeverity(StrEnum):
    """Severity for datasheet fact validation diagnostics."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DatasheetFactDiagnostic(BaseModel):
    """One datasheet fact validation diagnostic."""

    model_config = ConfigDict(strict=False)

    component_id: str
    field: str
    scope: DatasheetFactScope
    severity: DatasheetDiagnosticSeverity
    code: str
    message: str
    source_hashes: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)


class DatasheetFactValidationReport(BaseModel):
    """Confidence/conflict validation report for datasheet facts."""

    schema_version: str = "1.0"
    fact_count: int
    low_confidence_count: int
    conflict_count: int
    missing_hash_count: int
    human_review_required: bool
    blocked: bool
    diagnostics: list[DatasheetFactDiagnostic]


def confidence_level(confidence: float) -> DatasheetConfidenceLevel:
    """Classify numeric confidence into a stable vocabulary."""
    if confidence >= 0.85:
        return DatasheetConfidenceLevel.HIGH
    if confidence >= 0.6:
        return DatasheetConfidenceLevel.MEDIUM
    return DatasheetConfidenceLevel.LOW


def _fact_key(fact: DatasheetFact) -> tuple[str, DatasheetFactScope, str]:
    return (fact.component_id, fact.scope, fact.field)


def validate_datasheet_facts(
    report: DatasheetFactReport,
    *,
    low_confidence_threshold: float = 0.6,
) -> DatasheetFactValidationReport:
    """Detect low-confidence, missing-provenance, and conflicting datasheet facts."""
    diagnostics: list[DatasheetFactDiagnostic] = []
    facts = report.facts
    for fact in facts:
        if fact.confidence < low_confidence_threshold:
            diagnostics.append(
                DatasheetFactDiagnostic(
                    component_id=fact.component_id,
                    field=fact.field,
                    scope=fact.scope,
                    severity=DatasheetDiagnosticSeverity.WARNING,
                    code="low-confidence",
                    message=f"{fact.field} confidence {fact.confidence:.2f} requires human review",
                    source_hashes=[fact.source.datasheet_sha256] if fact.source.datasheet_sha256 else [],
                    values=[str(fact.value)],
                )
            )
        if not fact.source.datasheet_sha256:
            diagnostics.append(
                DatasheetFactDiagnostic(
                    component_id=fact.component_id,
                    field=fact.field,
                    scope=fact.scope,
                    severity=DatasheetDiagnosticSeverity.ERROR,
                    code="missing-datasheet-hash",
                    message=f"{fact.field} has no datasheet SHA-256 provenance",
                    values=[str(fact.value)],
                )
            )
    by_key: dict[tuple[str, DatasheetFactScope, str], list[DatasheetFact]] = {}
    for fact in facts:
        by_key.setdefault(_fact_key(fact), []).append(fact)
    for (_component_id, _scope, _field), group in sorted(by_key.items(), key=lambda item: item[0]):
        values = {str(fact.value) for fact in group}
        if len(values) <= 1:
            continue
        first = group[0]
        diagnostics.append(
            DatasheetFactDiagnostic(
                component_id=first.component_id,
                field=first.field,
                scope=first.scope,
                severity=DatasheetDiagnosticSeverity.ERROR,
                code="conflicting-facts",
                message=f"{first.field} has conflicting datasheet values: {', '.join(sorted(values))}",
                source_hashes=sorted({fact.source.datasheet_sha256 for fact in group if fact.source.datasheet_sha256}),
                values=sorted(values),
            )
        )
    low = sum(1 for item in diagnostics if item.code == "low-confidence")
    conflicts = sum(1 for item in diagnostics if item.code == "conflicting-facts")
    missing_hash = sum(1 for item in diagnostics if item.code == "missing-datasheet-hash")
    blocked = any(item.severity == DatasheetDiagnosticSeverity.ERROR for item in diagnostics)
    return DatasheetFactValidationReport(
        fact_count=len(facts),
        low_confidence_count=low,
        conflict_count=conflicts,
        missing_hash_count=missing_hash,
        human_review_required=low > 0,
        blocked=blocked,
        diagnostics=diagnostics,
    )


class DatasheetFactReport(BaseModel):
    """Machine-readable datasheet provenance report for one component."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    component_id: str
    datasheet_url: str = ""
    datasheet_sha256: str
    absolute_maximum: list[DatasheetFact] = Field(default_factory=list)
    recommended_operating: list[DatasheetFact] = Field(default_factory=list)
    other_facts: list[DatasheetFact] = Field(default_factory=list)
    import_losses: list[str] = Field(default_factory=list)

    @property
    def facts(self) -> list[DatasheetFact]:
        return [*self.absolute_maximum, *self.recommended_operating, *self.other_facts]

    @property
    def fact_count(self) -> int:
        return len(self.facts)


class DatasheetHashStatus(StrEnum):
    """Datasheet source hash re-verification status."""

    CURRENT = "current"
    STALE = "stale"
    MISSING_STORED_HASH = "missing-stored-hash"
    MISSING_SOURCE = "missing-source"


class DatasheetHashVerificationItem(BaseModel):
    """One datasheet hash re-verification result."""

    model_config = ConfigDict(strict=False)

    component_id: str
    expected_sha256: str = ""
    observed_sha256: str = ""
    status: DatasheetHashStatus
    stale_fact_count: int = Field(default=0, ge=0)
    affected_fields: list[str] = Field(default_factory=list)
    message: str = ""


class DatasheetHashVerificationReport(BaseModel):
    """Machine-readable report for datasheet hash re-verification."""

    schema_version: str = "1.0"
    blocked: bool
    item_count: int
    stale_fact_count: int
    hash_mismatch_count: int
    missing_source_count: int
    items: list[DatasheetHashVerificationItem]


def verify_datasheet_hash(
    report: DatasheetFactReport, current_source: str | bytes | None
) -> DatasheetHashVerificationItem:
    """Compare stored datasheet hash in a fact report against current source material."""
    fields = [fact.field for fact in report.facts]
    if not report.datasheet_sha256:
        return DatasheetHashVerificationItem(
            component_id=report.component_id,
            status=DatasheetHashStatus.MISSING_STORED_HASH,
            stale_fact_count=report.fact_count,
            affected_fields=fields,
            message="datasheet fact report has no stored SHA-256",
        )
    if current_source is None:
        return DatasheetHashVerificationItem(
            component_id=report.component_id,
            expected_sha256=report.datasheet_sha256,
            status=DatasheetHashStatus.MISSING_SOURCE,
            stale_fact_count=report.fact_count,
            affected_fields=fields,
            message="current datasheet source material was not provided",
        )
    observed = datasheet_sha256(current_source)
    if observed != report.datasheet_sha256:
        return DatasheetHashVerificationItem(
            component_id=report.component_id,
            expected_sha256=report.datasheet_sha256,
            observed_sha256=observed,
            status=DatasheetHashStatus.STALE,
            stale_fact_count=report.fact_count,
            affected_fields=fields,
            message="datasheet hash changed; dependent facts are stale until reviewed",
        )
    return DatasheetHashVerificationItem(
        component_id=report.component_id,
        expected_sha256=report.datasheet_sha256,
        observed_sha256=observed,
        status=DatasheetHashStatus.CURRENT,
        stale_fact_count=0,
        affected_fields=[],
        message="datasheet hash matches stored provenance",
    )


def verify_datasheet_hashes(
    items: list[tuple[DatasheetFactReport, str | bytes | None]],
) -> DatasheetHashVerificationReport:
    """Verify multiple datasheet fact reports against current source material."""
    results = [verify_datasheet_hash(report, current) for report, current in items]
    stale = sum(item.stale_fact_count for item in results)
    mismatch = sum(1 for item in results if item.status == DatasheetHashStatus.STALE)
    missing_source = sum(1 for item in results if item.status == DatasheetHashStatus.MISSING_SOURCE)
    blocked = any(
        item.status
        in {
            DatasheetHashStatus.STALE,
            DatasheetHashStatus.MISSING_STORED_HASH,
            DatasheetHashStatus.MISSING_SOURCE,
        }
        for item in results
    )
    return DatasheetHashVerificationReport(
        blocked=blocked,
        item_count=len(results),
        stale_fact_count=stale,
        hash_mismatch_count=mismatch,
        missing_source_count=missing_source,
        items=results,
    )


def datasheet_sha256(raw: str | bytes) -> str:
    """Return a stable SHA-256 for datasheet text or bytes."""
    payload = raw.encode("utf-8") if isinstance(raw, str) else raw
    return hashlib.sha256(payload).hexdigest()


def _source(
    *,
    datasheet_url: str,
    digest: str,
    snippet: str,
    section: str,
    page: int | None = None,
    table: str = "",
    figure: str = "",
) -> DatasheetSourceRef:
    return DatasheetSourceRef(
        datasheet_url=datasheet_url,
        datasheet_sha256=digest,
        page=page,
        table=table,
        figure=figure,
        section=section,
        source_snippet=snippet[:240],
    )


def _add_fact(
    facts: list[DatasheetFact],
    *,
    component_id: str,
    field: str,
    value: str | float | int | bool | None,
    unit: str,
    scope: DatasheetFactScope,
    confidence: float,
    source: DatasheetSourceRef,
) -> None:
    if value is None:
        return
    facts.append(
        DatasheetFact(
            component_id=component_id,
            field=field,
            value=value,
            unit=unit,
            scope=scope,
            confidence=confidence,
            source=source,
        )
    )


def build_datasheet_fact_report(
    component_id: str,
    raw_text: str,
    *,
    datasheet_url: str = "",
    page: int | None = None,
    extract: DatasheetExtract | None = None,
) -> DatasheetFactReport:
    """Build a provenance report from datasheet text and optional extraction."""
    parsed = extract or extract_datasheet(raw_text)
    digest = datasheet_sha256(raw_text)
    recommended: list[DatasheetFact] = []
    other: list[DatasheetFact] = []

    _add_fact(
        recommended,
        component_id=component_id,
        field="supply_voltage_min_v",
        value=parsed.supply_voltage_min_v.value,
        unit="V",
        scope=DatasheetFactScope.RECOMMENDED_OPERATING,
        confidence=parsed.supply_voltage_min_v.confidence,
        source=_source(
            datasheet_url=datasheet_url,
            digest=digest,
            page=page,
            table=_RECOMMENDED_OPERATING_TABLE,
            section=_RECOMMENDED_OPERATING_SECTION,
            snippet=parsed.supply_voltage_min_v.source_snippet,
        ),
    )
    _add_fact(
        recommended,
        component_id=component_id,
        field="supply_voltage_max_v",
        value=parsed.supply_voltage_max_v.value,
        unit="V",
        scope=DatasheetFactScope.RECOMMENDED_OPERATING,
        confidence=parsed.supply_voltage_max_v.confidence,
        source=_source(
            datasheet_url=datasheet_url,
            digest=digest,
            page=page,
            table=_RECOMMENDED_OPERATING_TABLE,
            section=_RECOMMENDED_OPERATING_SECTION,
            snippet=parsed.supply_voltage_max_v.source_snippet,
        ),
    )
    _add_fact(
        recommended,
        component_id=component_id,
        field="operating_temp_min_c",
        value=parsed.operating_temp_min_c.value,
        unit="C",
        scope=DatasheetFactScope.RECOMMENDED_OPERATING,
        confidence=parsed.operating_temp_min_c.confidence,
        source=_source(
            datasheet_url=datasheet_url,
            digest=digest,
            page=page,
            table=_RECOMMENDED_OPERATING_TABLE,
            section=_RECOMMENDED_OPERATING_SECTION,
            snippet=parsed.operating_temp_min_c.source_snippet,
        ),
    )
    _add_fact(
        recommended,
        component_id=component_id,
        field="operating_temp_max_c",
        value=parsed.operating_temp_max_c.value,
        unit="C",
        scope=DatasheetFactScope.RECOMMENDED_OPERATING,
        confidence=parsed.operating_temp_max_c.confidence,
        source=_source(
            datasheet_url=datasheet_url,
            digest=digest,
            page=page,
            table=_RECOMMENDED_OPERATING_TABLE,
            section=_RECOMMENDED_OPERATING_SECTION,
            snippet=parsed.operating_temp_max_c.source_snippet,
        ),
    )
    _add_fact(
        other,
        component_id=component_id,
        field="output_current_max_a",
        value=parsed.output_current_max_a.value,
        unit="A",
        scope=DatasheetFactScope.ELECTRICAL_CHARACTERISTIC,
        confidence=parsed.output_current_max_a.confidence,
        source=_source(
            datasheet_url=datasheet_url,
            digest=digest,
            page=page,
            table="Electrical Characteristics",
            section="electrical characteristics",
            snippet=parsed.output_current_max_a.source_snippet,
        ),
    )
    _add_fact(
        other,
        component_id=component_id,
        field="package",
        value=parsed.package.value,
        unit="",
        scope=DatasheetFactScope.PACKAGE,
        confidence=parsed.package.confidence,
        source=_source(
            datasheet_url=datasheet_url,
            digest=digest,
            page=page,
            section="package information",
            snippet=parsed.package.source_snippet,
        ),
    )
    for pin_name, function in sorted(parsed.pin_functions.items()):
        _add_fact(
            other,
            component_id=component_id,
            field=f"pin_functions.{pin_name}",
            value=function,
            unit="",
            scope=DatasheetFactScope.PIN_FUNCTION,
            confidence=0.75,
            source=_source(
                datasheet_url=datasheet_url,
                digest=digest,
                page=page,
                table="Pin Functions",
                section="pin functions",
                snippet=function,
            ),
        )
    return DatasheetFactReport(
        component_id=component_id,
        datasheet_url=datasheet_url,
        datasheet_sha256=digest,
        recommended_operating=recommended,
        other_facts=other,
        import_losses=parsed.import_losses,
    )


# ---------------------------------------------------------------------------
# Extraction schema
# ---------------------------------------------------------------------------


@dataclass
class ExtractedField:
    """A single extracted field with a confidence score."""

    value: str | float | None
    confidence: float  # 0.0 (no evidence) → 1.0 (exact regex match)
    source_snippet: str = ""  # short excerpt that triggered the extraction

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DatasheetExtract:
    """Structured data extracted from a component datasheet.

    All fields are ``ExtractedField`` objects with a confidence score.
    Missing data fields have ``value=None, confidence=0.0``.
    """

    part_number: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    manufacturer: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    description: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    package: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    supply_voltage_min_v: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    supply_voltage_max_v: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    output_current_max_a: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    operating_temp_min_c: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    operating_temp_max_c: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    dropout_voltage_v: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    quiescent_current_ua: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    # Pin-function table: pin name → function string
    pin_functions: dict[str, str] = field(default_factory=dict)
    # Raw import losses: fields we could not extract
    import_losses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def fill_rate(self) -> float:
        """Fraction of scalar fields that have a non-None value."""
        fields = [
            self.part_number,
            self.manufacturer,
            self.description,
            self.package,
            self.supply_voltage_min_v,
            self.supply_voltage_max_v,
            self.output_current_max_a,
            self.operating_temp_min_c,
            self.operating_temp_max_c,
            self.dropout_voltage_v,
            self.quiescent_current_ua,
        ]
        return sum(1 for f in fields if f.value is not None) / len(fields)


# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------

_PART_RE = re.compile(
    r"\b([A-Z]{1,4}\d{3,10}[A-Z0-9\-]*)\b",
    re.IGNORECASE,
)
_VOLTAGE_RANGE_RE = re.compile(
    r"(?:supply|input|vcc|vin|vdd)[^\n]{0,30}voltage[^\n]{0,30}?"
    r"([0-9]{1,12}(?:\.[0-9]{1,12})?)\s{0,32}v\s{1,32}to\s{1,32}"
    r"([0-9]{1,12}(?:\.[0-9]{1,12})?)\s{0,32}v",
    re.IGNORECASE,
)
_VOLTAGE_MAX_RE = re.compile(
    r"(?:supply|input|vcc|vin|vdd)\s{1,32}voltage[^.\n]{0,160}?"
    r"(?:max(?:imum)?)?[^.\n]{0,160}?([0-9]{1,12}(?:\.[0-9]{1,12})?)\s{0,32}v\b",
    re.IGNORECASE,
)
_CURRENT_RE = re.compile(
    r"(?:output|max(?:imum)?\s{1,32})?current[^.\n]{0,160}?"
    r"([0-9]{1,12}(?:\.[0-9]{1,12})?)\s{0,32}(ma|a)\b",
    re.IGNORECASE,
)
_TEMP_RANGE_RE = re.compile(
    r"(?:operating|ambient)\s{1,32}temp(?:erature)?[^.\n]{0,160}?"
    r"(-?[0-9]{1,4})\s{0,32}°?c[\s\S]{0,160}?to\s{0,32}\+?"
    r"(-?[0-9]{1,4})\s{0,32}°?c",
    re.IGNORECASE,
)
_DROPOUT_RE = re.compile(
    r"dropout\s{1,32}voltage[^.\n]{0,160}?"
    r"([0-9]{1,12}(?:\.[0-9]{1,12})?)\s{0,32}(mv|v)\b",
    re.IGNORECASE,
)
_QUIESCENT_RE = re.compile(
    r"quiescent[^.\n]{0,160}?(\d{1,12}(?:\.\d{1,12})?)\s{0,32}(ua|ma|µa|μa)\b",
    re.IGNORECASE | re.ASCII,
)
_PACKAGE_RE = re.compile(
    r"\b(SOT-?\d{2,3}|SOIC-?\d+|TSSOP-?\d+|QFN-?\d+|BGA-?\d+|DFN-?\d+|"
    r"TO-?92|TO-?220|TO-?252|SOP-?\d+|WSON-?\d+|VQFN-?\d+|LFCSP-?\d+|"
    r"SC-?\d{2,3}|SOD-?\d{2,3}|DPAK|D2PAK)\b",
    re.IGNORECASE,
)
_MANUFACTURER_RE = re.compile(
    r"^(?:manufactured|produced|by|©|from)?\s*(Texas Instruments|Microchip|STMicroelectronics|NXP|"
    r"Analog Devices|Maxim|ON Semiconductor|Diodes Inc|Vishay|Bourns|Murata|TDK|Würth|ROHM|"
    r"Infineon|Renesas|Nordic Semiconductor|Espressif|Silicon Labs|Semtech)\b",
    re.IGNORECASE | re.MULTILINE,
)
_PIN_TABLE_RE = re.compile(
    r"(?:pin|pad)\s+(\d+|[A-Z]\d*)\s+([A-Z][A-Z0-9_/\-]{1,20})\s+([^\n]{5,60})",
    re.IGNORECASE,
)


def _first(text: str, pattern: re.Pattern[str]) -> tuple[str, str] | None:
    m = pattern.search(text)
    if m:
        return m.group(0), m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
    return None


def _extract_identity(raw_text: str, extract: DatasheetExtract, losses: list[str]) -> None:
    part_matches = _PART_RE.findall(raw_text[:500])
    if part_matches:
        part_number = max(part_matches, key=len)
        extract.part_number = ExtractedField(part_number, 0.8, part_number)
    else:
        losses.append("part_number: no alphanumeric part number found in header")

    manufacturer = _MANUFACTURER_RE.search(raw_text)
    if manufacturer:
        extract.manufacturer = ExtractedField(manufacturer.group(1), 0.9, manufacturer.group(0))
    else:
        losses.append("manufacturer: not recognized")

    package = _PACKAGE_RE.search(raw_text)
    if package:
        extract.package = ExtractedField(package.group(0).upper(), 0.85, package.group(0))
    else:
        losses.append("package: not detected")


def _extract_voltage_range(raw_text: str, extract: DatasheetExtract, losses: list[str]) -> None:
    match = _VOLTAGE_RANGE_RE.search(raw_text)
    if not match:
        losses.append("supply_voltage_min_v/max_v: no range pattern found")
        return
    try:
        extract.supply_voltage_min_v = ExtractedField(float(match.group(1)), 0.9, match.group(0)[:50])
        extract.supply_voltage_max_v = ExtractedField(float(match.group(2)), 0.9, match.group(0)[:50])
    except ValueError:
        losses.append("supply_voltage: range parse failed")


def _extract_output_current(raw_text: str, extract: DatasheetExtract, losses: list[str]) -> None:
    match = _CURRENT_RE.search(raw_text)
    if not match:
        losses.append("output_current_max_a: not found")
        return
    try:
        value = float(match.group(1))
        if match.group(2).lower() == "ma":
            value /= 1000.0
        extract.output_current_max_a = ExtractedField(value, 0.8, match.group(0))
    except (ValueError, IndexError):
        losses.append("output_current: parse failed")


def _extract_temperature(raw_text: str, extract: DatasheetExtract, losses: list[str]) -> None:
    match = _TEMP_RANGE_RE.search(raw_text)
    if not match:
        losses.append("operating_temp_min_c/max_c: not found")
        return
    try:
        extract.operating_temp_min_c = ExtractedField(float(match.group(1)), 0.85, match.group(0)[:50])
        extract.operating_temp_max_c = ExtractedField(float(match.group(2)), 0.85, match.group(0)[:50])
    except (ValueError, IndexError):
        losses.append("operating_temp: range parse failed")


def _extract_dropout(raw_text: str, extract: DatasheetExtract, losses: list[str]) -> None:
    match = _DROPOUT_RE.search(raw_text)
    if not match:
        losses.append("dropout_voltage_v: not detected (may not be applicable)")
        return
    try:
        value = float(match.group(1))
        if match.group(2).lower() == "mv":
            value /= 1000.0
        extract.dropout_voltage_v = ExtractedField(value, 0.9, match.group(0))
    except (ValueError, IndexError):
        losses.append("dropout_voltage: parse failed")


def _extract_quiescent_current(raw_text: str, extract: DatasheetExtract, losses: list[str]) -> None:
    match = _QUIESCENT_RE.search(raw_text)
    if not match:
        losses.append("quiescent_current_ua: not found")
        return
    try:
        value = float(match.group(1))
        if match.group(2).lower() == "ma":
            value *= 1000.0
        extract.quiescent_current_ua = ExtractedField(value, 0.85, match.group(0))
    except (ValueError, IndexError):
        losses.append("quiescent_current: parse failed")


def _extract_pin_functions(raw_text: str, extract: DatasheetExtract, losses: list[str]) -> None:
    for match in _PIN_TABLE_RE.finditer(raw_text):
        extract.pin_functions[match.group(2).upper()] = match.group(3).strip()[:80]
    if not extract.pin_functions:
        losses.append("pin_functions: no pin table detected")


def extract_datasheet(raw_text: str) -> DatasheetExtract:
    """Heuristically extract structured data from raw datasheet text."""
    extract = DatasheetExtract()
    losses: list[str] = []
    _extract_identity(raw_text, extract, losses)
    _extract_voltage_range(raw_text, extract, losses)
    _extract_output_current(raw_text, extract, losses)
    _extract_temperature(raw_text, extract, losses)
    _extract_dropout(raw_text, extract, losses)
    _extract_quiescent_current(raw_text, extract, losses)
    _extract_pin_functions(raw_text, extract, losses)
    extract.import_losses = losses
    return extract
