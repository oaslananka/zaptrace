"""Impedance and stackup computation engine.

Implements IPC-2141 microstrip and differential microstrip formulas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ImpedanceResult:
    trace_width: float
    gap: float | None
    actual_z: float
    target_z: float
    is_diff: bool

    @property
    def tolerance_pct(self) -> float:
        if self.target_z == 0:
            return 0.0
        return abs(self.actual_z - self.target_z) / self.target_z * 100.0


def compute_microstrip_se(target_z: float, h: float, t: float, er: float) -> ImpedanceResult:
    """Compute single-ended microstrip width for a target impedance using IPC-2141.

    Formula: Z0 = (87 / sqrt(Er + 1.41)) * ln(5.98 * H / (0.8 * W + T))
    Tolerance: typically +/- 5-10% depending on manufacturing.
    """
    if target_z <= 0:
        return ImpedanceResult(0.2, None, 0.0, target_z, False)

    exponent = -target_z * math.sqrt(er + 1.41) / 87.0
    term = 5.98 * h * math.exp(exponent)
    w = (term - t) / 0.8

    if w <= 0.05:
        w = 0.05  # practical minimum

    actual_z = (87.0 / math.sqrt(er + 1.41)) * math.log(5.98 * h / (0.8 * w + t))
    return ImpedanceResult(round(w, 4), None, round(actual_z, 2), target_z, False)


def compute_microstrip_diff(
    target_z: float, h: float, t: float, er: float, min_gap: float = 0.15, min_width: float = 0.1
) -> ImpedanceResult:
    """Compute differential microstrip width and gap for a target impedance using IPC-2141.

    Formula: Zdiff = 2 * Z0 * (1 - 0.48 * exp(-0.96 * S / H))
    Tolerance: typically +/- 5-10%.
    """
    if target_z <= 0:
        return ImpedanceResult(0.2, 0.15, 0.0, target_z, True)

    s = min_gap
    # Target Z0 for the given S
    z0_req = target_z / (2.0 * (1.0 - 0.48 * math.exp(-0.96 * s / h)))
    w = compute_microstrip_se(z0_req, h, t, er).trace_width

    if w < min_width:
        w = min_width
        # Re-evaluate Z0 for min_width
        z0_actual = (87.0 / math.sqrt(er + 1.41)) * math.log(5.98 * h / (0.8 * w + t))
        # Solve for S
        ratio = target_z / (2.0 * z0_actual)
        if ratio < 1.0 and ratio > (1 - 0.48):
            term = (1.0 - ratio) / 0.48
            s = -h * math.log(term) / 0.96

    # Verification of achieved Z
    z0 = (87.0 / math.sqrt(er + 1.41)) * math.log(5.98 * h / (0.8 * w + t))
    actual_z = 2 * z0 * (1 - 0.48 * math.exp(-0.96 * s / h))

    return ImpedanceResult(round(w, 4), round(s, 4), round(actual_z, 2), target_z, True)
