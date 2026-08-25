"""Routing defaults, impedance control, length matching, and clearance tables."""

from __future__ import annotations

from zaptrace.ee.routing.impedance import (
    ImpedanceResult,
    compute_microstrip_diff,
    compute_microstrip_se,
)
from zaptrace.ee.routing.length_matching import (
    STANDARD_STACKUPS,
    PcbStackup,
    SkewReport,
    StackupLayer,
    analyze_diff_pair_skew,
    generate_meander_segments,
    signal_propagation_delay_ps_per_mm,
)

__all__ = [
    "ImpedanceResult",
    "PcbStackup",
    "STANDARD_STACKUPS",
    "SkewReport",
    "StackupLayer",
    "analyze_diff_pair_skew",
    "compute_microstrip_diff",
    "compute_microstrip_se",
    "generate_meander_segments",
    "signal_propagation_delay_ps_per_mm",
]
