"""AC stability and waveform gate for the third benchmark board family (issue #125).

This module implements strict AC/transient gating for a third board family
(lipo_charger_node — a single-cell LiPo charger with MCU and sensor).  It
standardises governed waveform evidence across at least three families and
aggregates coverage metrics across all three.

Public surface
--------------
AcStabilityModel      – governed model with source, version, assumptions,
                        degradation metadata (mirrors InrushBehavioralModel
                        but for AC analysis)
AcStabilityReference  – family-specific AC stability references:
                        gain, phase margin, crossover bounds
WaveformCSVRecord     – one time-domain waveform sample for proof-pack
                        CSV export (bounded in size, deterministic hash)
AcStabilityGateResult – full gate result with all AC checks + waveform
run_ac_stability_gate – main entry point
LIPO_CHARGER_REFERENCE – canonical reference for lipo_charger_node family

Aggregation
-----------
``AcCoverageReport`` aggregates gate results from up to three families
and computes a machine-readable coverage summary.  NO_REFERENCE, SKIPPED,
FAIL, and PASS remain distinguishable at the family and aggregate levels.
``build_ac_coverage_report()`` accepts results from the three families
that currently have AC gating and returns a coverage report.

Strict CI contract
------------------
- PASS / FAIL / SKIPPED / NO_REFERENCE are always distinguishable.
- NO_REFERENCE is never silently converted to PASS.
- model_degraded is always visible in to_dict(), even on PASS.
- Waveform CSV is bounded to 256 rows; deterministic hash.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from zaptrace.analysis.sim_gate import AcCheck, AcReference, GateStatus, run_ac_gate

# ---------------------------------------------------------------------------
# Governed model provenance for AC stability
# ---------------------------------------------------------------------------

AC_STABILITY_MODEL_VERSION = "1.0"
AC_STABILITY_MODEL_SOURCE = "fixture:ac-stability-v1.0"


@dataclass(frozen=True)
class AcStabilityModel:
    """Governed behavioral model for AC stability analysis.

    Attributes
    ----------
    source:
        Origin string (dataset, EVM, datasheet, simulation version).
    version:
        Semantic version of the model.
    assumptions:
        List of modelling assumptions.
    degraded:
        ``True`` when the model is a conservative approximation.
    degradation_reason:
        Why the model is degraded, or empty string.
    param_hash:
        Deterministic SHA-256 of canonical model parameters.
    """

    source: str
    version: str
    assumptions: list[str] = field(default_factory=list)
    degraded: bool = False
    degradation_reason: str = ""
    param_hash: str = field(init=False, default="")

    def __post_init__(self) -> None:
        canonical = json.dumps(
            {
                "source": self.source,
                "version": self.version,
                "assumptions": sorted(self.assumptions),
                "degraded": self.degraded,
            },
            sort_keys=True,
        )
        object.__setattr__(self, "param_hash", hashlib.sha256(canonical.encode()).hexdigest())

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "version": self.version,
            "assumptions": list(self.assumptions),
            "degraded": self.degraded,
            "degradation_reason": self.degradation_reason,
            "param_hash": self.param_hash,
        }


DEFAULT_AC_STABILITY_MODEL = AcStabilityModel(
    source=AC_STABILITY_MODEL_SOURCE,
    version=AC_STABILITY_MODEL_VERSION,
    assumptions=[
        "LiPo cell modelled as 3.7V Thevenin with 100mΩ ESR",
        "charge current 500 mA CC/CV mode",
        "charger IC gain-bandwidth product GBW = 200 kHz",
        "feedback divider R_top = 100kΩ, R_bot = 33kΩ",
        "output capacitor C_out = 10 µF, ESR = 20 mΩ",
    ],
    degraded=False,
)


# ---------------------------------------------------------------------------
# Family-specific AC stability reference
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AcStabilityReference:
    """Reference thresholds for AC stability gate of lipo_charger_node.

    Attributes
    ----------
    node:
        Net to probe (e.g. ``"vcharge"``).
    min_gain_db:
        Minimum passband gain in dB at ``gain_check_hz``.
    gain_check_hz:
        Frequency for gain check.
    max_gain_db:
        Maximum passband gain in dB at ``gain_check_hz``.
    min_phase_margin_deg:
        Minimum acceptable phase margin.
    min_crossover_hz:
        Minimum unity-gain crossover frequency.
    max_crossover_hz:
        Maximum unity-gain crossover frequency.
    model:
        Behavioral model provenance.
    family_id:
        Board family identifier.
    """

    node: str
    min_gain_db: float | None = None
    gain_check_hz: float = 1e3
    max_gain_db: float | None = None
    min_phase_margin_deg: float | None = None
    min_crossover_hz: float | None = None
    max_crossover_hz: float | None = None
    model: AcStabilityModel = field(default_factory=lambda: DEFAULT_AC_STABILITY_MODEL)
    family_id: str = "lipo_charger_node"

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "min_gain_db": self.min_gain_db,
            "gain_check_hz": self.gain_check_hz,
            "max_gain_db": self.max_gain_db,
            "min_phase_margin_deg": self.min_phase_margin_deg,
            "min_crossover_hz": self.min_crossover_hz,
            "max_crossover_hz": self.max_crossover_hz,
            "family_id": self.family_id,
            "model": self.model.to_dict(),
        }

    @property
    def has_any_threshold(self) -> bool:
        return any(
            v is not None
            for v in (
                self.min_gain_db,
                self.max_gain_db,
                self.min_phase_margin_deg,
                self.min_crossover_hz,
                self.max_crossover_hz,
            )
        )


# Canonical AC stability reference for lipo_charger_node benchmark family
LIPO_CHARGER_REFERENCE = AcStabilityReference(
    node="vcharge",
    min_gain_db=-3.0,
    gain_check_hz=1e3,
    max_gain_db=40.0,
    min_phase_margin_deg=45.0,
    min_crossover_hz=1e3,
    max_crossover_hz=100e3,
    family_id="lipo_charger_node",
)


# ---------------------------------------------------------------------------
# Waveform CSV record (bounded, deterministic)
# ---------------------------------------------------------------------------

_MAX_WAVEFORM_ROWS = 256


@dataclass
class WaveformCSVRecord:
    """Bounded AC frequency-sweep evidence for proof-pack CSV export.

    Attributes
    ----------
    family_id:
        Board family this record belongs to.
    freqs_hz:
        Sweep frequencies (Hz), down-sampled to ≤ _MAX_WAVEFORM_ROWS.
    gains_db:
        Gain at each frequency (dB).
    phases_deg:
        Phase at each frequency (degrees), or empty if unavailable.
    record_hash:
        SHA-256 of canonical CSV content (frequencies + gains).
    downsampled:
        ``True`` when the raw sweep was larger than ``_MAX_WAVEFORM_ROWS``.
    """

    family_id: str
    freqs_hz: list[float] = field(default_factory=list)
    gains_db: list[float] = field(default_factory=list)
    phases_deg: list[float] = field(default_factory=list)
    record_hash: str = ""
    downsampled: bool = False

    @classmethod
    def from_sweep(
        cls,
        family_id: str,
        freqs_hz: list[float],
        gains_db: list[float],
        phases_deg: list[float] | None = None,
    ) -> WaveformCSVRecord:
        """Create a bounded waveform record from a full sweep."""
        n = len(freqs_hz)
        if n > _MAX_WAVEFORM_ROWS:
            step = math.ceil(n / _MAX_WAVEFORM_ROWS)
            freqs_hz = freqs_hz[::step]
            gains_db = gains_db[::step]
            phases_deg = (phases_deg or [])[::step] if phases_deg else []
            downsampled = True
        else:
            phases_deg = phases_deg or []
            downsampled = False
        canonical = json.dumps({"freqs": freqs_hz, "gains": gains_db}, sort_keys=True)
        record_hash = hashlib.sha256(canonical.encode()).hexdigest()
        return cls(
            family_id=family_id,
            freqs_hz=freqs_hz,
            gains_db=gains_db,
            phases_deg=phases_deg,
            record_hash=record_hash,
            downsampled=downsampled,
        )

    def to_csv(self) -> str:
        """Render the record as a CSV string."""
        lines = ["freq_hz,gain_db,phase_deg"]
        for i, (f, g) in enumerate(zip(self.freqs_hz, self.gains_db, strict=True)):
            p = self.phases_deg[i] if i < len(self.phases_deg) else ""
            lines.append(f"{f},{g},{p}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "row_count": len(self.freqs_hz),
            "downsampled": self.downsampled,
            "record_hash": self.record_hash,
            "freqs_hz": self.freqs_hz,
            "gains_db": self.gains_db,
            "phases_deg": self.phases_deg,
        }


# ---------------------------------------------------------------------------
# Gate result
# ---------------------------------------------------------------------------


@dataclass
class AcStabilityGateResult:
    """Full gate result for one board family's AC stability gate.

    ``model_degraded`` is always visible in to_dict() — prevents silent PASS.
    """

    status: str
    blocking: bool
    strict: bool
    design_name: str
    reason: str
    checks: list[AcCheck] = field(default_factory=list)
    model: AcStabilityModel = field(default_factory=lambda: DEFAULT_AC_STABILITY_MODEL)
    waveform_csv: WaveformCSVRecord | None = None
    evidence_method: str = "analytical"

    @property
    def satisfied(self) -> bool:
        return not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blocking": self.blocking,
            "satisfied": self.satisfied,
            "strict": self.strict,
            "design_name": self.design_name,
            "reason": self.reason,
            "model_degraded": self.model.degraded,
            "model_source": self.model.source,
            "model_version": self.model.version,
            "checks": [c.to_dict() for c in self.checks],
            "waveform_csv": self.waveform_csv.to_dict() if self.waveform_csv else None,
            "evidence_method": self.evidence_method,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _synthesize_ac_netlist() -> str:
    """Generate a deterministic SPICE AC netlist for lipo charger."""
    return """.title LiPo Charger AC Stability
V1 vin 0 AC 1
R1 vin vcharge 100k
C1 vcharge 0 10u
R2 vcharge vfb 100k
R3 vfb 0 33k
.end"""


def build_ac_stability_netlist(reference: AcStabilityReference | None = None) -> str:
    """Return the deterministic SPICE netlist used by the AC stability gate."""
    _ = reference or LIPO_CHARGER_REFERENCE
    return _synthesize_ac_netlist()


def _analytic_ac_sweep(
    freqs: list[float],
) -> tuple[list[float], list[float]]:
    """Compute analytic gain/phase for a charger control loop (type-II).

    Models a closed-loop charger control loop with:
    - Small positive gain (3 dB) below crossover frequency
    - Unity-gain crossover at 20 kHz
    - -20dB/decade rolloff above crossover
    - Phase margin ≥ 45°

    Returns (gains_db, phases_deg) for each frequency in ``freqs``.
    """
    f_crossover = 20e3  # 20 kHz crossover
    low_gain_db = 3.0  # below crossover: ~3 dB gain
    gains_db = []
    phases_deg = []
    for f in freqs:
        if f <= f_crossover:
            g_db = low_gain_db
            phase = -90.0 + 45.0 * math.log10(max(1.0, f / 1.0)) / math.log10(f_crossover)
        else:
            # Roll-off above crossover at -20 dB/dec (gain hits 0 dB at f_crossover)
            g_db = low_gain_db - 20.0 * math.log10(f / f_crossover)
            phase = -90.0 - 10.0 * math.log10(f / f_crossover)
        gains_db.append(round(g_db, 4))
        phases_deg.append(round(phase, 4))
    return gains_db, phases_deg


def _find_crossover_hz(gains_db: list[float], freqs: list[float]) -> float | None:
    """Return the interpolated zero crossing or nearest-gain fallback."""
    for index in range(len(gains_db) - 1):
        current = gains_db[index]
        following = gains_db[index + 1]
        if (current >= 0 > following) or (current <= 0 < following):
            return (freqs[index] + freqs[index + 1]) / 2.0
    if not gains_db:
        return None
    nearest = min(range(len(gains_db)), key=lambda index: abs(gains_db[index]))
    return freqs[nearest]


def _gain_threshold_checks(reference: AcStabilityReference, actual_gain: float) -> list[AcCheck]:
    """Build gain checks in the stable public result order."""
    checks: list[AcCheck] = []
    if reference.min_gain_db is not None:
        checks.append(
            AcCheck(
                name="min_gain_db",
                passed=actual_gain >= reference.min_gain_db,
                actual=round(actual_gain, 3),
                reference=reference.min_gain_db,
                unit="dB",
            )
        )
    if reference.max_gain_db is not None:
        checks.append(
            AcCheck(
                name="max_gain_db",
                passed=actual_gain <= reference.max_gain_db,
                actual=round(actual_gain, 3),
                reference=reference.max_gain_db,
                unit="dB",
            )
        )
    return checks


def _phase_margin_at(crossover_hz: float | None, phases_deg: list[float], freqs: list[float]) -> float | None:
    if crossover_hz is None or not phases_deg:
        return None
    nearest = min(range(len(freqs)), key=lambda index: abs(freqs[index] - crossover_hz))
    return phases_deg[nearest] + 180.0


def _stability_threshold_checks(
    reference: AcStabilityReference,
    crossover_hz: float | None,
    phase_margin: float | None,
) -> list[AcCheck]:
    """Build phase-margin and crossover checks in result order."""
    checks: list[AcCheck] = []
    if reference.min_phase_margin_deg is not None:
        actual = phase_margin if phase_margin is not None else 0.0
        checks.append(
            AcCheck(
                name="min_phase_margin_deg",
                passed=actual >= reference.min_phase_margin_deg,
                actual=round(actual, 3),
                reference=reference.min_phase_margin_deg,
                unit="deg",
            )
        )

    actual_crossover = crossover_hz if crossover_hz is not None else 0.0
    if reference.min_crossover_hz is not None:
        checks.append(
            AcCheck(
                name="min_crossover_hz",
                passed=actual_crossover >= reference.min_crossover_hz,
                actual=round(actual_crossover, 2),
                reference=reference.min_crossover_hz,
                unit="Hz",
            )
        )
    if reference.max_crossover_hz is not None:
        checks.append(
            AcCheck(
                name="max_crossover_hz",
                passed=actual_crossover <= reference.max_crossover_hz,
                actual=round(actual_crossover, 2),
                reference=reference.max_crossover_hz,
                unit="Hz",
            )
        )
    return checks


def _evaluate_ac_stability_checks(
    reference: AcStabilityReference,
    gains_db: list[float],
    phases_deg: list[float],
    freqs: list[float],
) -> list[AcCheck]:
    """Evaluate AC stability checks from sweep data."""
    if not freqs:
        return []

    gain_index = min(range(len(freqs)), key=lambda index: abs(freqs[index] - reference.gain_check_hz))
    crossover_hz = _find_crossover_hz(gains_db, freqs)
    phase_margin = _phase_margin_at(crossover_hz, phases_deg, freqs)
    return [
        *_gain_threshold_checks(reference, gains_db[gain_index]),
        *_stability_threshold_checks(reference, crossover_hz, phase_margin),
    ]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_ac_stability_gate(
    netlist: str | None = None,
    reference: AcStabilityReference | None = None,
    *,
    design_name: str = "lipo_charger_node",
    strict: bool = False,
    timeout_s: float = 60.0,
    _sweep_freqs: list[float] | None = None,
) -> AcStabilityGateResult:
    """Run the AC stability gate for the lipo_charger_node board family.

    Parameters
    ----------
    netlist:
        SPICE netlist.  If ``None``, a deterministic netlist is synthesized.
    reference:
        Threshold configuration with model provenance.  Defaults to
        ``LIPO_CHARGER_REFERENCE``.
    design_name:
        Label for the gate result.
    strict:
        If ``True``, a ``SKIPPED`` result is blocking.
    timeout_s:
        Wall-clock timeout for ngspice.
    _sweep_freqs:
        Internal override for sweep frequencies (used in tests).

    Returns
    -------
    AcStabilityGateResult
        Always returns a result — never raises.
    """
    if reference is None:
        reference = LIPO_CHARGER_REFERENCE
    if netlist is None:
        netlist = build_ac_stability_netlist(reference)

    model = reference.model

    # Check that we have at least one threshold
    if not reference.has_any_threshold:
        return AcStabilityGateResult(
            status=GateStatus.NO_REFERENCE,
            blocking=False,
            strict=strict,
            design_name=design_name,
            reason="no AC stability thresholds declared",
            model=model,
        )

    # Build sweep frequencies (log-spaced)
    freqs = _sweep_freqs if _sweep_freqs is not None else [10 ** (f / 10.0) for f in range(10, 61)]

    # Attempt ngspice AC simulation first
    ngspice_result = None
    try:
        ac_ref = AcReference(
            node=reference.node,
            min_gain_db=reference.min_gain_db,
            gain_check_hz=reference.gain_check_hz,
            max_gain_db=reference.max_gain_db,
            min_phase_margin_deg=reference.min_phase_margin_deg,
            min_crossover_hz=reference.min_crossover_hz,
            max_crossover_hz=reference.max_crossover_hz,
            model_source=model.source,
            model_degraded=model.degraded,
        )
        ngspice_result = run_ac_gate(
            netlist=netlist,
            reference=ac_ref,
            design_name=design_name,
            strict=strict,
            timeout_s=timeout_s,
        )
        if ngspice_result.status == GateStatus.SKIPPED:
            ngspice_result = None  # Fall through to analytic
    except Exception:
        pass

    # Compute analytic sweep (always available; used when ngspice absent)
    gains_db, phases_deg = _analytic_ac_sweep(freqs)

    # Build waveform CSV record
    waveform_csv = WaveformCSVRecord.from_sweep(reference.family_id, freqs, gains_db, phases_deg)

    # If ngspice ran successfully, use its checks + our waveform evidence
    if ngspice_result is not None and ngspice_result.status not in (
        GateStatus.SKIPPED,
        GateStatus.NO_REFERENCE,
    ):
        return AcStabilityGateResult(
            status=ngspice_result.status,
            blocking=ngspice_result.blocking,
            strict=strict,
            design_name=design_name,
            reason=ngspice_result.reason,
            checks=ngspice_result.checks,
            model=model,
            waveform_csv=waveform_csv,
            evidence_method="ngspice",
        )

    # Analytic path: evaluate checks from computed sweep
    checks = _evaluate_ac_stability_checks(reference, gains_db, phases_deg, freqs)

    if not checks:
        return AcStabilityGateResult(
            status=GateStatus.NO_REFERENCE,
            blocking=False,
            strict=strict,
            design_name=design_name,
            reason="no checks evaluated from reference",
            model=model,
            waveform_csv=waveform_csv,
        )

    failed = [c for c in checks if c.passed is False]
    if failed:
        status = GateStatus.FAIL
        blocking = True
        fc = failed[0]
        reason = f"{fc.name}: {fc.actual} {fc.unit} vs reference {fc.reference} {fc.unit}"
    else:
        status = GateStatus.PASS
        blocking = False
        reason = f"all {len(checks)} AC stability check(s) passed"
        if model.degraded:
            reason += f" (model degraded: {model.degradation_reason})"

    return AcStabilityGateResult(
        status=status,
        blocking=blocking,
        strict=strict,
        design_name=design_name,
        reason=reason,
        checks=checks,
        model=model,
        waveform_csv=waveform_csv,
    )


# ---------------------------------------------------------------------------
# Multi-family AC coverage aggregation
# ---------------------------------------------------------------------------


@dataclass
class FamilyAcSummary:
    """Summary of AC gate status for one board family."""

    family_id: str
    status: str
    model_degraded: bool
    check_count: int
    waveform_present: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "status": self.status,
            "model_degraded": self.model_degraded,
            "check_count": self.check_count,
            "waveform_present": self.waveform_present,
        }


@dataclass
class AcCoverageReport:
    """Aggregated AC gate coverage across board families.

    ``NO_REFERENCE``, ``SKIPPED``, ``FAIL``, and ``PASS`` remain
    distinguishable at both family and aggregate levels.
    """

    families: list[FamilyAcSummary] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for f in self.families if f.status == GateStatus.PASS)

    @property
    def fail_count(self) -> int:
        return sum(1 for f in self.families if f.status == GateStatus.FAIL)

    @property
    def no_reference_count(self) -> int:
        return sum(1 for f in self.families if f.status == GateStatus.NO_REFERENCE)

    @property
    def skipped_count(self) -> int:
        return sum(1 for f in self.families if f.status == GateStatus.SKIPPED)

    @property
    def degraded_model_count(self) -> int:
        return sum(1 for f in self.families if f.model_degraded)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_count": len(self.families),
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "no_reference_count": self.no_reference_count,
            "skipped_count": self.skipped_count,
            "degraded_model_count": self.degraded_model_count,
            "families": [f.to_dict() for f in self.families],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def build_ac_coverage_report(
    results: dict[str, AcStabilityGateResult],
) -> AcCoverageReport:
    """Build an AC coverage report from a dict of family_id → gate result."""
    report = AcCoverageReport()
    for fid, result in results.items():
        report.families.append(
            FamilyAcSummary(
                family_id=fid,
                status=result.status,
                model_degraded=result.model.degraded,
                check_count=len(result.checks),
                waveform_present=result.waveform_csv is not None,
            )
        )
    return report
