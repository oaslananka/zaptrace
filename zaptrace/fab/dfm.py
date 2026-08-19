"""DFM checker — validates a Design against a manufacturer's FabProfile."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Component, Design, DRCViolation, FootprintDef, Pad, TraceSegment
from zaptrace.core.net_identity import canonical_routing_net_ids
from zaptrace.fab.profile import FabProfile


class DFMReadinessStatus(StrEnum):
    """Top-level manufacturing readiness state."""

    PASS = "pass"
    HARD_FAIL = "hard-fail"
    WARNING = "warning"
    APPROVED_SKIP = "approved-skip"
    HUMAN_REVIEW_REQUIRED = "human-review-required"


@dataclass
class DFMViolation:
    """A single DFM violation found during validation."""

    rule_id: str
    severity: str  # error | warning | info | approved-skip | human-review-required
    message: str
    location: str = ""
    actual: str = ""
    expected: str = ""


_TraceBBox = tuple[float, float, float, float]


def _expanded_trace_bbox(trace: TraceSegment, margin: float) -> _TraceBBox:
    x1, y1 = trace.start[0], trace.start[1]
    x2, y2 = trace.end[0], trace.end[1]
    return (
        min(x1, x2) - margin,
        min(y1, y2) - margin,
        max(x1, x2) + margin,
        max(y1, y2) + margin,
    )


def _bbox_overlaps(first: _TraceBBox, second: _TraceBBox) -> bool:
    left1, top1, right1, bottom1 = first
    left2, top2, right2, bottom2 = second
    return not (right1 < left2 or right2 < left1 or bottom1 < top2 or bottom2 < top1)


def _clearance_violation(
    first: TraceSegment,
    second: TraceSegment,
    min_space: float,
    distance_fn: Callable[[TraceSegment, TraceSegment], float],
) -> DFMViolation | None:
    if first.net_id and second.net_id and first.net_id == second.net_id:
        return None
    distance = distance_fn(first, second)
    if distance >= min_space:
        return None
    return DFMViolation(
        rule_id="clearance",
        severity="error",
        message=f"Clearance {distance:.3f}mm below minimum {min_space:.3f}mm",
        location=f"{first.net_id or '?'} / {second.net_id or '?'}",
        actual=f"{distance:.3f}mm",
        expected=f">= {min_space:.3f}mm",
    )


def _trace_clearance_violations(
    traces: list[TraceSegment],
    min_space: float,
    distance_fn: Callable[[TraceSegment, TraceSegment], float],
) -> list[DFMViolation]:
    boxes = [_expanded_trace_bbox(trace, min_space) for trace in traces]
    violations: list[DFMViolation] = []
    for index, first in enumerate(traces):
        for offset, second in enumerate(traces[index + 1 :], start=index + 1):
            if not _bbox_overlaps(boxes[index], boxes[offset]):
                continue
            violation = _clearance_violation(first, second, min_space, distance_fn)
            if violation is not None:
                violations.append(violation)
    return violations


def _pad_drill_diameter(pad: Pad) -> float | None:
    if pad.drill is None:
        return None
    diameter = float(pad.drill)
    return diameter if diameter > 0 else None


def _drill_violations(ref: str, pad: Pad, min_diameter: float, max_diameter: float) -> list[DFMViolation]:
    diameter = _pad_drill_diameter(pad)
    if diameter is None:
        return []
    location = f"{ref} pad {pad.id}"
    violations: list[DFMViolation] = []
    if diameter < min_diameter:
        violations.append(
            DFMViolation(
                rule_id="drill-min",
                severity="error",
                message=f"Drill hole {diameter:.3f}mm below minimum {min_diameter:.3f}mm",
                location=location,
                actual=f"{diameter:.3f}mm",
                expected=f">= {min_diameter:.3f}mm",
            )
        )
    if diameter > max_diameter:
        violations.append(
            DFMViolation(
                rule_id="drill-max",
                severity="warning",
                message=f"Drill hole {diameter:.3f}mm exceeds maximum {max_diameter:.3f}mm",
                location=location,
                actual=f"{diameter:.3f}mm",
                expected=f"<= {max_diameter:.3f}mm",
            )
        )
    return violations


_ViaMeasurement = tuple[float, float, str]


def _via_dimension_violations(
    *,
    diameter: float,
    hole: float,
    location: str,
    min_diameter: float,
    min_hole: float,
    max_hole: float,
) -> list[DFMViolation]:
    """Return deterministic diameter/hole violations for one normalized via."""
    violations: list[DFMViolation] = []
    if diameter < min_diameter:
        violations.append(
            DFMViolation(
                rule_id="via-diameter-min",
                severity="warning",
                message=f"Via diameter {diameter:.3f}mm below minimum {min_diameter:.3f}mm",
                location=location,
                actual=f"{diameter:.3f}mm",
                expected=f">= {min_diameter:.3f}mm",
            )
        )
    if hole < min_hole:
        violations.append(
            DFMViolation(
                rule_id="via-hole-min",
                severity="error",
                message=f"Via hole {hole:.3f}mm below minimum {min_hole:.3f}mm",
                location=location,
                actual=f"{hole:.3f}mm",
                expected=f">= {min_hole:.3f}mm",
            )
        )
    if hole > max_hole:
        violations.append(
            DFMViolation(
                rule_id="via-hole-max",
                severity="warning",
                message=f"Via hole {hole:.3f}mm exceeds maximum {max_hole:.3f}mm",
                location=location,
                actual=f"{hole:.3f}mm",
                expected=f"<= {max_hole:.3f}mm",
            )
        )
    return violations


def _legacy_via_measurements(vias: Sequence[Any]) -> list[_ViaMeasurement]:
    """Normalize tuple-based routing vias while preserving their source index."""
    measurements: list[_ViaMeasurement] = []
    for index, via in enumerate(vias):
        if len(via) < 4:
            continue
        _x, _y, diameter, hole, *rest = via
        net_id = str(rest[0]) if rest else ""
        measurements.append((float(diameter), float(hole), f"{net_id or '?'} via#{index}"))
    return measurements


def _trace_via_measurements(traces: Sequence[TraceSegment]) -> list[_ViaMeasurement]:
    """Normalize trace-attached vias while preserving their trace index."""
    return [
        (trace.via_diameter, trace.via_hole, f"{trace.net_id} seg#{index}")
        for index, trace in enumerate(traces)
        if trace.via
    ]


@dataclass
class DFMCheckResult:
    """Complete DFM validation result."""

    violations: list[DFMViolation] = field(default_factory=list)
    profile_name: str = ""
    profile_manufacturer: str = ""
    profile_version: str = ""
    profile_sha256: str = ""
    profile_last_verified: str = ""

    @property
    def passed(self) -> bool:
        return self.errors == 0

    @property
    def total_violations(self) -> int:
        return len(self.violations)

    @property
    def errors(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for v in self.violations if v.severity == "warning")

    @property
    def human_reviews(self) -> int:
        return sum(1 for v in self.violations if v.severity == "human-review-required")

    @property
    def approved_skips(self) -> int:
        return sum(1 for v in self.violations if v.severity == "approved-skip")

    @property
    def readiness_status(self) -> DFMReadinessStatus:
        if self.errors:
            return DFMReadinessStatus.HARD_FAIL
        if self.human_reviews:
            return DFMReadinessStatus.HUMAN_REVIEW_REQUIRED
        if self.approved_skips:
            return DFMReadinessStatus.APPROVED_SKIP
        if self.warnings:
            return DFMReadinessStatus.WARNING
        return DFMReadinessStatus.PASS

    def _add(self, rule_id: str, severity: str, message: str, **kw: str) -> None:
        self.violations.append(DFMViolation(rule_id=rule_id, severity=severity, message=message, **kw))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "profile": self.profile_name,
            "profile_identity": {
                "name": self.profile_name,
                "manufacturer": self.profile_manufacturer,
                "version": self.profile_version,
                "sha256": self.profile_sha256,
                "last_verified": self.profile_last_verified,
            },
            "readiness_status": self.readiness_status.value,
            "total": self.total_violations,
            "errors": self.errors,
            "warnings": self.warnings,
            "human_reviews": self.human_reviews,
            "approved_skips": self.approved_skips,
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "severity": v.severity,
                    "message": v.message,
                    "location": v.location,
                    "actual": v.actual,
                    "expected": v.expected,
                }
                for v in self.violations
            ],
        }

    def to_drc_violations(self) -> list[DRCViolation]:
        """Convert DFM violations to standard DRC violation format."""
        from zaptrace.core.models import DRCSeverity

        return [
            DRCViolation(
                rule_id=v.rule_id,
                severity=DRCSeverity.ERROR if v.severity == "error" else DRCSeverity.WARNING,
                message=v.message,
                location=v.location,
            )
            for v in self.violations
        ]


def _trace_width_violation(
    design: Design,
    seg: TraceSegment,
    index: int,
    min_signal_mm: float,
    min_power_mm: float,
) -> DFMViolation | None:
    net = design.nets.get(seg.net_id) if seg.net_id else None
    is_power = net is not None and net.type in ("power", "ground")
    threshold = min_power_mm if is_power else min_signal_mm
    if seg.width >= threshold:
        return None
    kind = "power" if is_power else "signal"
    return DFMViolation(
        rule_id="trace-width",
        severity="error" if is_power else "warning",
        message=f"Trace width {seg.width:.3f}mm below {kind} minimum {threshold:.3f}mm",
        location=f"{seg.net_id} seg#{index}",
        actual=f"{seg.width:.3f}mm",
        expected=f">= {threshold:.3f}mm",
    )


class DFMChecker:
    """Validate a Design against a manufacturer's FabProfile.

    Usage:
        profile = load_profile("jlcpcb-2layer")
        checker = DFMChecker(profile)
        result = checker.check(design)
    """

    def __init__(self, profile: FabProfile) -> None:
        self.profile = profile

    def check(self, design: Design) -> DFMCheckResult:
        """Run all DFM checks against the design."""
        result = DFMCheckResult(
            profile_name=self.profile.name,
            profile_manufacturer=self.profile.manufacturer,
            profile_version=self.profile.profile_version,
            profile_sha256=self.profile.identity_sha256(),
            profile_last_verified=self.profile.last_verified,
        )
        self._check_profile_freshness(result)

        self._check_board_dimensions(design, result)
        self._check_trace_widths(design, result)
        self._check_clearances(design, result)
        self._check_drill_holes(design, result)
        self._check_vias(design, result)
        self._check_layer_count(design, result)
        self._check_annular_ring(design, result)
        self._check_solder_mask(design, result)
        self._check_silkscreen(design, result)
        self._check_assembly(design, result)
        self._check_special_features(design, result)

        return result

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_profile_freshness(self, result: DFMCheckResult) -> None:
        for warning in self.profile.freshness_warnings():
            result._add(
                "fab-profile-stale",
                "human-review-required",
                warning,
                expected="recent sourced fab capability metadata",
            )

    def _check_board_dimensions(self, design: Design, result: DFMCheckResult) -> None:
        bd = canonical_board_definition(design)
        w = bd.width
        h = bd.height

        if w is not None and w < self.profile.min_board_width_mm:
            result._add(
                "board-width-min",
                "error",
                f"Board width ({w:.1f}mm) below minimum ({self.profile.min_board_width_mm}mm)",
                actual=f"{w:.1f}mm",
                expected=f">= {self.profile.min_board_width_mm}mm",
            )
        if w is not None and w > self.profile.max_board_width_mm:
            result._add(
                "board-width-max",
                "error",
                f"Board width ({w:.1f}mm) exceeds maximum ({self.profile.max_board_width_mm}mm)",
                actual=f"{w:.1f}mm",
                expected=f"<= {self.profile.max_board_width_mm}mm",
            )
        if h is not None and h < self.profile.min_board_height_mm:
            result._add(
                "board-height-min",
                "error",
                f"Board height ({h:.1f}mm) below minimum ({self.profile.min_board_height_mm}mm)",
                actual=f"{h:.1f}mm",
                expected=f">= {self.profile.min_board_height_mm}mm",
            )
        if h is not None and h > self.profile.max_board_height_mm:
            result._add(
                "board-height-max",
                "error",
                f"Board height ({h:.1f}mm) exceeds maximum ({self.profile.max_board_height_mm}mm)",
                actual=f"{h:.1f}mm",
                expected=f"<= {self.profile.max_board_height_mm}mm",
            )

    def _check_trace_widths(self, design: Design, result: DFMCheckResult) -> None:
        routing = design.routing
        canonical_routing_net_ids(design, routing)
        if routing is None or not routing.traces:
            return

        for index, seg in enumerate(routing.traces):
            violation = _trace_width_violation(
                design,
                seg,
                index,
                self.profile.min_trace_mm,
                self.profile.min_trace_power_mm,
            )
            if violation is not None:
                result.violations.append(violation)

    def _check_clearances(self, design: Design, result: DFMCheckResult) -> None:
        routing = design.routing
        canonical_routing_net_ids(design, routing)
        if routing is None or not routing.traces:
            return
        result.violations.extend(
            _trace_clearance_violations(
                list(routing.traces),
                self.profile.min_space_mm,
                self._segment_distance,
            )
        )

    def _check_drill_holes(self, design: Design, result: DFMCheckResult) -> None:
        for component in design.components.values():
            if component.footprint_def is None:
                continue
            for pad in component.footprint_def.pads:
                result.violations.extend(
                    _drill_violations(
                        component.ref,
                        pad,
                        self.profile.min_drill_mm,
                        self.profile.max_drill_mm,
                    )
                )

    def _check_vias(self, design: Design, result: DFMCheckResult) -> None:
        routing = design.routing
        canonical_routing_net_ids(design, routing)
        if routing is None:
            return

        measurements = _legacy_via_measurements(routing.vias)
        measurements.extend(_trace_via_measurements(routing.traces))
        for diameter, hole, location in measurements:
            result.violations.extend(
                _via_dimension_violations(
                    diameter=diameter,
                    hole=hole,
                    location=location,
                    min_diameter=self.profile.min_via_diameter_mm,
                    min_hole=self.profile.min_via_hole_mm,
                    max_hole=self.profile.max_via_hole_mm,
                )
            )

    def _check_layer_count(self, design: Design, result: DFMCheckResult) -> None:
        bd = canonical_board_definition(design)
        layers = bd.layers
        allowed = self.profile.capabilities.layer_counts
        if allowed and layers not in allowed:
            result._add(
                "layer-count",
                "error",
                f"Layer count ({layers}) not supported by {self.profile.name} (supported: {allowed})",
                actual=str(layers),
                expected=str(allowed),
            )

    def _check_annular_ring(self, design: Design, result: DFMCheckResult) -> None:
        min_ring = self.profile.min_annular_ring_mm
        routing = design.routing
        if routing is None:
            return
        for i, seg in enumerate(routing.traces):
            if not seg.via:
                continue
            ring = (seg.via_diameter - seg.via_hole) / 2
            if ring < min_ring:
                result._add(
                    "annular-ring",
                    "error",
                    f"Annular ring {ring:.3f}mm below minimum {min_ring:.3f}mm",
                    location=f"{seg.net_id} seg#{i}",
                    actual=f"{ring:.3f}mm",
                    expected=f">= {min_ring:.3f}mm",
                )

    def _check_solder_mask(self, design: Design, result: DFMCheckResult) -> None:
        """Check solder-mask sliver clearance between routed copper features."""
        min_sliver = self.profile.min_solder_mask_sliver_mm
        routing = design.routing
        canonical_routing_net_ids(design, routing)
        if routing is None or not routing.traces:
            return
        traces = list(routing.traces)
        for i, t1 in enumerate(traces):
            for j, t2 in enumerate(traces[i + 1 :], start=i + 1):
                if t1.layer != t2.layer:
                    continue
                if t1.net_id and t2.net_id and t1.net_id == t2.net_id:
                    continue
                center_gap = self._segment_distance(t1, t2)
                copper_gap = center_gap - (t1.width + t2.width) / 2
                if copper_gap < min_sliver:
                    result._add(
                        "solder-mask-sliver",
                        "warning",
                        f"Solder mask sliver {copper_gap:.3f}mm below minimum {min_sliver:.3f}mm",
                        location=f"trace#{i}/trace#{j}",
                        actual=f"{copper_gap:.3f}mm",
                        expected=f">= {min_sliver:.3f}mm",
                    )

    def _check_silkscreen(self, design: Design, result: DFMCheckResult) -> None:
        """Validate modeled silkscreen stroke widths against the profile."""
        minimum = self.profile.min_silkscreen_width_mm
        for component in design.components.values():
            footprint = component.footprint_def
            if footprint is None:
                continue
            for index, command in enumerate(footprint.outline):
                width = command.params.get("stroke_width", command.params.get("width"))
                if not isinstance(width, (int, float)):
                    continue
                if float(width) < minimum:
                    result._add(
                        "silkscreen-width",
                        "warning",
                        f"Silkscreen width {float(width):.3f}mm below minimum {minimum:.3f}mm",
                        location=f"{component.ref} outline#{index}",
                        actual=f"{float(width):.3f}mm",
                        expected=f">= {minimum:.3f}mm",
                    )

    def _check_assembly(self, design: Design, result: DFMCheckResult) -> None:
        """Validate populated component geometry against assembly limits."""
        limits = self.profile.assembly
        if not limits.service_available:
            result._add(
                "assembly-service-unavailable",
                "human-review-required",
                f"{self.profile.name} does not define an integrated assembly service",
                expected="select and verify an external assembly profile",
            )
            return
        placement = design.placement or {}
        for component in design.components.values():
            self._check_assembly_component(component, placement, result)

    def _check_assembly_component(
        self,
        component: Component,
        placement: dict[str, tuple[float, float]],
        result: DFMCheckResult,
    ) -> None:
        if component.dnp:
            return
        footprint = component.footprint_def
        if footprint is None:
            result._add(
                "assembly-footprint-unverified",
                "human-review-required",
                f"{component.ref} has no footprint geometry for assembly validation",
                location=component.ref,
                expected="verified footprint pad geometry",
            )
            return
        self._check_assembly_placement(component, placement, result)
        self._check_assembly_side(component, result)
        self._check_assembly_height(component, footprint, result)
        self._check_assembly_through_hole(component, footprint, result)
        self._check_assembly_pitch(component, footprint, result)
        self._check_stencil_aperture(component, footprint, result)

    @staticmethod
    def _check_assembly_placement(
        component: Component,
        placement: dict[str, tuple[float, float]],
        result: DFMCheckResult,
    ) -> None:
        if component.position is not None or component.id in placement:
            return
        result._add(
            "assembly-placement-missing",
            "human-review-required",
            f"{component.ref} has no assembly placement",
            location=component.ref,
            expected="placed component centroid",
        )

    def _check_assembly_side(self, component: Component, result: DFMCheckResult) -> None:
        side = str((component.properties or {}).get("side", "top")).lower()
        if side != "bottom" or self.profile.assembly.supports_double_sided_assembly:
            return
        result._add(
            "assembly-bottom-side",
            "error",
            f"{self.profile.name} assembly profile does not support bottom-side population",
            location=component.ref,
        )

    def _check_assembly_height(
        self,
        component: Component,
        footprint: FootprintDef,
        result: DFMCheckResult,
    ) -> None:
        maximum = self.profile.assembly.max_component_height_mm
        if maximum is None or footprint.height <= maximum:
            return
        result._add(
            "assembly-component-height",
            "error",
            f"Component height {footprint.height:.3f}mm exceeds assembly limit {maximum:.3f}mm",
            location=component.ref,
            actual=f"{footprint.height:.3f}mm",
            expected=f"<= {maximum:.3f}mm",
        )

    def _check_assembly_through_hole(
        self,
        component: Component,
        footprint: FootprintDef,
        result: DFMCheckResult,
    ) -> None:
        has_drilled_pad = any((pad.drill or 0) > 0 for pad in footprint.pads)
        if not has_drilled_pad or self.profile.assembly.supports_through_hole_assembly:
            return
        result._add(
            "assembly-through-hole",
            "error",
            f"{self.profile.name} assembly profile does not support through-hole population",
            location=component.ref,
        )

    def _check_assembly_pitch(
        self,
        component: Component,
        footprint: FootprintDef,
        result: DFMCheckResult,
    ) -> None:
        pitch = self._minimum_pad_pitch(footprint.pads)
        if pitch is None:
            return
        is_bga = self._is_bga(component)
        limits = self.profile.assembly
        minimum = limits.min_bga_pitch_mm if is_bga else limits.min_component_pitch_mm
        if minimum is None or pitch >= minimum:
            return
        result._add(
            "assembly-bga-pitch" if is_bga else "assembly-component-pitch",
            "error",
            f"Pad pitch {pitch:.3f}mm below assembly limit {minimum:.3f}mm",
            location=component.ref,
            actual=f"{pitch:.3f}mm",
            expected=f">= {minimum:.3f}mm",
        )

    @staticmethod
    def _is_bga(component: Component) -> bool:
        family = str((component.properties or {}).get("package_family", "")).lower()
        return "bga" in component.footprint.lower() or family == "bga"

    def _check_stencil_aperture(
        self,
        component: Component,
        footprint: FootprintDef,
        result: DFMCheckResult,
    ) -> None:
        aperture = min((min(pad.size) for pad in footprint.pads if pad.solder_paste), default=None)
        minimum = self.profile.assembly.min_stencil_aperture_mm
        if minimum is None or aperture is None or aperture >= minimum:
            return
        result._add(
            "assembly-stencil-aperture",
            "warning",
            f"Stencil aperture {aperture:.3f}mm below profile limit {minimum:.3f}mm",
            location=component.ref,
            actual=f"{aperture:.3f}mm",
            expected=f">= {minimum:.3f}mm",
        )

    @staticmethod
    def _minimum_pad_pitch(pads: list[Pad]) -> float | None:
        positions = [pad.position for pad in pads]
        if len(positions) < 2:
            return None
        distances = [
            math.dist(positions[index], positions[other])
            for index in range(len(positions))
            for other in range(index + 1, len(positions))
            if positions[index] != positions[other]
        ]
        return min(distances) if distances else None

    def _check_special_features(self, design: Design, result: DFMCheckResult) -> None:
        needs = self._detect_special_features(design)
        if needs.get("castellated") and not self.profile.castellated_pads:
            result._add(
                "castellated-pads",
                "error",
                f"Design uses castellated pads but {self.profile.name} does not support them",
            )
        if needs.get("edge_plating") and not self.profile.edge_plating:
            result._add(
                "edge-plating",
                "warning",
                f"Design uses edge plating but {self.profile.name} does not support it",
            )
        if needs.get("impedance") and not self.profile.impedance_control:
            result._add(
                "impedance-control",
                "error",
                "Design requires controlled impedance but profile does not support it",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_special_features(design: Design) -> dict[str, bool]:
        features: dict[str, bool] = {}
        for comp in design.components.values():
            props = comp.properties or {}
            if props.get("castellated"):
                features["castellated"] = True
            if props.get("edge_plating") or props.get("half_cut"):
                features["edge_plating"] = True
        for net in design.nets.values():
            c = net.constraints
            if c and c.impedance_target is not None:
                features["impedance"] = True
        return features

    @staticmethod
    def _segment_distance(s1: TraceSegment, s2: TraceSegment) -> float:
        try:
            a = (s1.start[0], s1.start[1])
            b = (s1.end[0], s1.end[1])
            c = (s2.start[0], s2.start[1])
            d = (s2.end[0], s2.end[1])

            # Check for segment intersection first — crossing segments have distance 0
            if DFMChecker._segments_intersect(a, b, c, d):
                return 0.0

            return min(
                DFMChecker._point_segment_dist(a, c, d),
                DFMChecker._point_segment_dist(b, c, d),
                DFMChecker._point_segment_dist(c, a, b),
                DFMChecker._point_segment_dist(d, a, b),
            )
        except (AttributeError, IndexError, TypeError, ValueError):
            return float("inf")

    @staticmethod
    def _segments_intersect(
        a: tuple[float, float],
        b: tuple[float, float],
        c: tuple[float, float],
        d: tuple[float, float],
    ) -> bool:
        """Return True if segment AB intersects segment CD (including endpoints)."""

        def orient(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:  # noqa: ANN001
            return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

        def on_segment(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> bool:  # noqa: ANN001
            return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])

        o1 = orient(a, b, c)
        o2 = orient(a, b, d)
        o3 = orient(c, d, a)
        o4 = orient(c, d, b)
        if o1 == 0 and on_segment(a, c, b):
            return True
        if o2 == 0 and on_segment(a, d, b):
            return True
        if o3 == 0 and on_segment(c, a, d):
            return True
        if o4 == 0 and on_segment(c, b, d):
            return True
        return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)

    @staticmethod
    def _point_segment_dist(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        px, py = p
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        proj_x = ax + t * dx
        proj_y = ay + t * dy
        return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)

    @staticmethod
    def _gap_between(s1: object, s2: object) -> float | None:
        """Estimate gap between two slot-like objects."""
        get = getattr
        for obj in (s1, s2):
            pos = get(obj, "position", None) or get(obj, "center", None)
            if pos is None:
                return None
        p1 = get(s1, "position", None) or get(s1, "center")
        p2 = get(s2, "position", None) or get(s2, "center")
        w1 = get(s1, "width", 0) or 0
        w2 = get(s2, "width", 0) or 0
        cx = (p1[0] - p2[0]) ** 2
        cy = (p1[1] - p2[1]) ** 2
        dist = math.sqrt(cx + cy)
        return dist - (w1 + w2) / 2
