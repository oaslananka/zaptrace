"""High-speed length matching, meander generation, and differential pair skew analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass

from zaptrace.core.models import TraceSegment

# Speed of light in vacuum in mm/ps
_C_MM_PER_PS = 0.299792458


@dataclass
class StackupLayer:
    name: str
    thickness_mm: float
    dielectric_er: float = 4.4  # Standard FR4
    is_copper: bool = False


@dataclass
class PcbStackup:
    name: str
    layer_count: int
    total_thickness_mm: float
    layers: list[StackupLayer]
    outer_copper_t_mm: float = 0.035  # 1 oz copper = 35um
    inner_copper_t_mm: float = 0.0175  # 0.5 oz copper
    outer_dielectric_h_mm: float = 0.1  # Height to GND plane
    dielectric_er: float = 4.2  # FR-4 at 1 GHz


# Industry-standard JLC / PCBWay 4-layer and 6-layer stackup presets
STANDARD_STACKUPS: dict[str, PcbStackup] = {
    "2-layer-1.6mm": PcbStackup(
        name="Standard 2-Layer 1.6mm",
        layer_count=2,
        total_thickness_mm=1.6,
        layers=[
            StackupLayer(name="F.Cu", thickness_mm=0.035, is_copper=True),
            StackupLayer(name="Core", thickness_mm=1.53, dielectric_er=4.4),
            StackupLayer(name="B.Cu", thickness_mm=0.035, is_copper=True),
        ],
        outer_dielectric_h_mm=1.53,
        dielectric_er=4.4,
    ),
    "4-layer-jlc04161h": PcbStackup(
        name="JLC04161H-7628 4-Layer 1.6mm",
        layer_count=4,
        total_thickness_mm=1.6,
        layers=[
            StackupLayer(name="F.Cu", thickness_mm=0.035, is_copper=True),
            StackupLayer(name="Prepreg-7628", thickness_mm=0.21, dielectric_er=4.2),
            StackupLayer(name="In1.Cu", thickness_mm=0.0175, is_copper=True),
            StackupLayer(name="Core", thickness_mm=1.065, dielectric_er=4.5),
            StackupLayer(name="In2.Cu", thickness_mm=0.0175, is_copper=True),
            StackupLayer(name="Prepreg-7628", thickness_mm=0.21, dielectric_er=4.2),
            StackupLayer(name="B.Cu", thickness_mm=0.035, is_copper=True),
        ],
        outer_dielectric_h_mm=0.21,
        dielectric_er=4.2,
    ),
    "6-layer-jlc06161h": PcbStackup(
        name="JLC06161H-7628 6-Layer 1.6mm",
        layer_count=6,
        total_thickness_mm=1.6,
        layers=[
            StackupLayer(name="F.Cu", thickness_mm=0.035, is_copper=True),
            StackupLayer(name="Prepreg", thickness_mm=0.1, dielectric_er=4.1),
            StackupLayer(name="In1.Cu", thickness_mm=0.0175, is_copper=True),
            StackupLayer(name="Core1", thickness_mm=0.45, dielectric_er=4.4),
            StackupLayer(name="In2.Cu", thickness_mm=0.0175, is_copper=True),
            StackupLayer(name="Prepreg_Mid", thickness_mm=0.2, dielectric_er=4.1),
            StackupLayer(name="In3.Cu", thickness_mm=0.0175, is_copper=True),
            StackupLayer(name="Core2", thickness_mm=0.45, dielectric_er=4.4),
            StackupLayer(name="In4.Cu", thickness_mm=0.0175, is_copper=True),
            StackupLayer(name="Prepreg", thickness_mm=0.1, dielectric_er=4.1),
            StackupLayer(name="B.Cu", thickness_mm=0.035, is_copper=True),
        ],
        outer_dielectric_h_mm=0.1,
        dielectric_er=4.1,
    ),
}


def signal_propagation_delay_ps_per_mm(er: float = 4.2) -> float:
    """Calculate signal propagation delay in picoseconds per mm.

    For microstrip: effective dielectric constant Er_eff ≈ (Er + 1)/2 + (Er - 1)/2 * 1/sqrt(1 + 12*H/W)
    Average microstrip: delay ≈ sqrt(Er_eff) / c
    """
    er_eff = (er + 1.0) / 2.0 + (er - 1.0) / 4.0
    v_mm_per_ps = _C_MM_PER_PS / math.sqrt(er_eff)
    return 1.0 / v_mm_per_ps


@dataclass
class SkewReport:
    net_p: str
    net_n: str
    length_p_mm: float
    length_n_mm: float
    delta_length_mm: float
    skew_ps: float
    passed: bool
    max_skew_ps_limit: float


def analyze_diff_pair_skew(
    traces_p: list[TraceSegment],
    traces_n: list[TraceSegment],
    max_skew_ps: float = 5.0,  # 5ps standard intra-pair skew limit (USB 3.0 / PCIe)
    er: float = 4.2,
) -> SkewReport:
    """Analyze intra-pair length and propagation delay skew between differential pair traces."""
    len_p = sum(
        math.hypot(t.end[0] - t.start[0], t.end[1] - t.start[1])
        for t in traces_p
    )
    len_n = sum(
        math.hypot(t.end[0] - t.start[0], t.end[1] - t.start[1])
        for t in traces_n
    )

    delta_len = abs(len_p - len_n)
    delay_per_mm = signal_propagation_delay_ps_per_mm(er)
    skew_ps = delta_len * delay_per_mm

    net_p_name = traces_p[0].net_id if traces_p else "P"
    net_n_name = traces_n[0].net_id if traces_n else "N"

    return SkewReport(
        net_p=net_p_name,
        net_n=net_n_name,
        length_p_mm=round(len_p, 3),
        length_n_mm=round(len_n, 3),
        delta_length_mm=round(delta_len, 3),
        skew_ps=round(skew_ps, 2),
        passed=skew_ps <= max_skew_ps,
        max_skew_ps_limit=max_skew_ps,
    )


def generate_meander_segments(
    start: tuple[float, float],
    end: tuple[float, float],
    target_length_mm: float,
    amplitude_mm: float = 1.0,
    pitch_mm: float = 1.0,
    layer: str = "F.Cu",
    width: float = 0.2,
    net_id: str = "",
) -> list[TraceSegment]:
    """Generate accordion meanders along a straight trace segment to reach target length."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    direct_dist = math.hypot(dx, dy)

    if direct_dist <= 0.0 or target_length_mm <= direct_dist:
        # No meander needed
        return [TraceSegment(layer=layer, start=start, end=end, width=width, net_id=net_id)]

    extra_needed = target_length_mm - direct_dist
    # Each meander cycle adds 2 * amplitude length
    cycle_extra = 2.0 * amplitude_mm
    num_cycles = max(1, int(round(extra_needed / cycle_extra)))

    # Direction vectors
    ux = dx / direct_dist
    uy = dy / direct_dist
    # Perpendicular unit vector
    px = -uy
    py = ux

    segments: list[TraceSegment] = []
    # Reserve straight lead-in and lead-out
    margin = 1.0
    active_span = max(0.1, direct_dist - 2 * margin)
    step = active_span / (num_cycles * 2)

    cur = start
    first_point = (start[0] + ux * margin, start[1] + uy * margin)
    segments.append(TraceSegment(layer=layer, start=cur, end=first_point, width=width, net_id=net_id))
    cur = first_point

    side = 1.0
    for _ in range(num_cycles):
        # Step forward along baseline
        p1 = (cur[0] + ux * (step / 2), cur[1] + uy * (step / 2))
        # Outward peak
        p2 = (p1[0] + px * (amplitude_mm * side), p1[1] + py * (amplitude_mm * side))
        # Across peak
        p3 = (p2[0] + ux * step, p2[1] + uy * step)
        # Return to baseline
        p4 = (p1[0] + ux * step, p1[1] + uy * step)

        segments.append(TraceSegment(layer=layer, start=cur, end=p2, width=width, net_id=net_id))
        segments.append(TraceSegment(layer=layer, start=p2, end=p3, width=width, net_id=net_id))
        segments.append(TraceSegment(layer=layer, start=p3, end=p4, width=width, net_id=net_id))
        cur = p4
        side *= -1.0  # Alternate sides

    # Final straight lead-out to target end
    segments.append(TraceSegment(layer=layer, start=cur, end=end, width=width, net_id=net_id))
    return segments
