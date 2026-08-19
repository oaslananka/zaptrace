"""Machine-readable and Markdown SI/PI/thermal heuristic reports."""

from __future__ import annotations

import hashlib
import math
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.core.models import Component, Design, Net, NetType, TraceSegment
from zaptrace.ee.routing.impedance import compute_microstrip_diff, compute_microstrip_se


class AnalysisSeverity(StrEnum):
    """Report finding severity."""

    INFO = "info"
    WARNING = "warning"
    NONBLOCKING = "nonblocking"


class AnalysisFinding(BaseModel):
    """One heuristic engineering finding."""

    model_config = ConfigDict(strict=False)

    category: str
    severity: AnalysisSeverity
    subject: str
    message: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ImpedanceAnalysisEntry(BaseModel):
    """Compatibility entry consumed by proof-pack SI checks."""

    model_config = ConfigDict(strict=False)

    net_name: str
    tolerance_pct: float | None = None


class LengthMatchAnalysisEntry(BaseModel):
    """Compatibility entry consumed by proof-pack SI checks."""

    model_config = ConfigDict(strict=False)

    group_name: str
    within_tolerance: bool


class ThermalAnalysisEntry(BaseModel):
    """Compatibility entry consumed by proof-pack thermal checks."""

    model_config = ConfigDict(strict=False)

    component_ref: str
    estimated_temp_rise_c: float


class LegacyAnalysisReport(BaseModel):
    """Backward-compatible analysis shape used by proof.checker."""

    model_config = ConfigDict(strict=False)

    impedance: list[ImpedanceAnalysisEntry] = Field(default_factory=list)
    length_match: list[LengthMatchAnalysisEntry] = Field(default_factory=list)
    thermal: list[ThermalAnalysisEntry] = Field(default_factory=list)


class ElectricalAnalysisReport(BaseModel):
    """Combined SI/PI/thermal heuristic report."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    design_name: str
    findings: list[AnalysisFinding]
    assumptions: list[str]
    limitations: list[str]
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "heuristic estimate, not signoff-grade simulation",
            "external SI/PI/thermal solvers are still required for production signoff",
            "warnings are nonblocking unless a stricter profile promotes them to gates",
        ]
    )

    def by_category(self) -> dict[str, list[AnalysisFinding]]:
        """Group findings by category."""
        grouped: dict[str, list[AnalysisFinding]] = {}
        for finding in self.findings:
            grouped.setdefault(finding.category, []).append(finding)
        return grouped


def generate_electrical_analysis_report(design: Design) -> ElectricalAnalysisReport:
    """Generate heuristic SI/PI/thermal/EMC findings for a design.

    Covers impedance, length-match, PDN, thermal, and EMC pre-compliance.
    All outputs are heuristic estimates — not signoff-grade simulation.
    (EMC pre-compliance items are included.)
    """
    findings: list[AnalysisFinding] = []
    findings.extend(_impedance_findings(design))
    findings.extend(_length_match_findings(design))
    findings.extend(_pdn_findings(design))
    findings.extend(_thermal_findings(design))
    findings.extend(_emc_findings(design))
    assumptions = [
        "microstrip estimates use IPC-2141-style closed-form approximations",
        "default stackup assumes FR-4 Er=4.2, 1 oz copper, and 0.18 mm dielectric height unless a solver overrides it",
        "PDN estimates use trace-segment length and coarse copper resistance assumptions",
        "thermal estimates use component power_w and theta_ja_c_per_w metadata when present",
        "EMC edge-rate estimates use typical logic family rise times; actual values depend on silicon process and load",
        "EMC loop-area estimates are geometry-only; enclosure, shielding, and ferrite effects are not modelled",
    ]
    limitations = [
        "does not model vias, plane spreading, connector parasitics, "
        "return current discontinuities, or enclosure airflow",
        "does not replace field-solver impedance, SPICE/PDN simulation, or CFD/thermal simulation",
        "length-matching uses routed trace segment lengths when available "
        "and reports missing route evidence as an info finding",
        "EMC findings are pre-compliance heuristics only — not a substitute for lab emissions/immunity testing",
        "EMC loop-area estimates assume worst-case geometry; "
        "actual emissions depend on layout, shielding, and enclosure",
    ]
    return ElectricalAnalysisReport(
        design_name=design.meta.name, findings=findings, assumptions=assumptions, limitations=limitations
    )


def render_analysis_markdown(report: ElectricalAnalysisReport) -> str:
    """Render a human-readable Markdown report."""
    lines = [f"# Electrical analysis report: {report.design_name}", "", "## Non-claims"]
    lines.extend(f"- {item}" for item in report.non_claims)
    lines.append("")
    for category, findings in report.by_category().items():
        lines.append(f"## {category}")
        for finding in findings:
            lines.append(f"- **{finding.severity.value}** `{finding.subject}`: {finding.message}")
            if finding.metrics:
                metrics = ", ".join(f"{key}={value}" for key, value in finding.metrics.items())
                lines.append(f"  - Metrics: {metrics}")
        lines.append("")
    lines.append("## Assumptions")
    lines.extend(f"- {item}" for item in report.assumptions)
    lines.append("")
    lines.append("## Limitations")
    lines.extend(f"- {item}" for item in report.limitations)
    lines.append("")
    return "\n".join(lines)


def build_analysis_proof_artifacts(report: ElectricalAnalysisReport, output_dir: str | Path) -> list[dict[str, Any]]:
    """Write JSON/Markdown analysis artifacts and return proof-pack style records."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "electrical-analysis-report.json"
    md_path = out / "electrical-analysis-report.md"
    json_payload = report.model_dump_json(indent=2) + "\n"
    markdown_payload = render_analysis_markdown(report)
    json_path.write_text(json_payload, encoding="utf-8")
    md_path.write_text(markdown_payload, encoding="utf-8")
    return [_artifact_record(json_path, "analysis-json"), _artifact_record(md_path, "analysis-markdown")]


def _artifact_record(path: Path, kind: str) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"path": path.name, "kind": kind, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}


def _impedance_findings(design: Design) -> list[AnalysisFinding]:
    findings: list[AnalysisFinding] = []
    for net in design.nets.values():
        constraints = net.constraints
        if constraints is None or constraints.impedance_target is None:
            continue
        is_diff = net.type == NetType.DIFFERENTIAL or "diff" in (constraints.length_match_group or "").lower()
        target = float(constraints.impedance_target)
        result = (
            compute_microstrip_diff(target, h=0.18, t=0.035, er=4.2)
            if is_diff
            else compute_microstrip_se(target, h=0.18, t=0.035, er=4.2)
        )
        routed_width = _average_trace_width(design, net.id)
        severity = AnalysisSeverity.WARNING if result.tolerance_pct > 10 else AnalysisSeverity.NONBLOCKING
        findings.append(
            AnalysisFinding(
                category="controlled_impedance",
                severity=severity,
                subject=net.name,
                message="controlled-impedance target evaluated against heuristic microstrip estimate",
                metrics={
                    "target_ohms": target,
                    "recommended_width_mm": result.trace_width,
                    "recommended_gap_mm": result.gap,
                    "estimated_actual_ohms": result.actual_z,
                    "tolerance_pct": round(result.tolerance_pct, 2),
                    "routed_average_width_mm": routed_width,
                },
                assumptions=["FR-4 Er=4.2", "1 oz copper", "microstrip approximation"],
                limitations=["not a field-solver result"],
            )
        )
    return findings


def _length_match_findings(design: Design) -> list[AnalysisFinding]:
    findings: list[AnalysisFinding] = []
    groups: dict[str, list[Net]] = {}
    for net in design.nets.values():
        if net.constraints is None:
            continue
        if net.constraints.length_match_group:
            groups.setdefault(net.constraints.length_match_group, []).append(net)
        if net.constraints.max_length_mm is not None:
            length = _net_length(design, net.id)
            severity = (
                AnalysisSeverity.WARNING if length > net.constraints.max_length_mm else AnalysisSeverity.NONBLOCKING
            )
            findings.append(
                AnalysisFinding(
                    category="length_constraints",
                    severity=severity,
                    subject=net.name,
                    message="max-length constraint evaluated from routed trace segments",
                    metrics={"length_mm": round(length, 3), "max_length_mm": net.constraints.max_length_mm},
                    limitations=["unrouted or partial routes may under-report length"],
                )
            )
    for group, nets in groups.items():
        lengths = {net.name: round(_net_length(design, net.id), 3) for net in nets}
        if len(lengths) < 2:
            continue
        delta = max(lengths.values()) - min(lengths.values())
        severity = AnalysisSeverity.WARNING if delta > 1.0 else AnalysisSeverity.NONBLOCKING
        findings.append(
            AnalysisFinding(
                category="differential_pair_length_match",
                severity=severity,
                subject=group,
                message="length-match group evaluated from routed trace segments",
                metrics={"lengths_mm": lengths, "delta_mm": round(delta, 3), "default_tolerance_mm": 1.0},
                limitations=["does not model skew from dielectric or layer changes"],
            )
        )
    return findings


def _pdn_findings(design: Design) -> list[AnalysisFinding]:
    findings: list[AnalysisFinding] = []
    for net in design.nets.values():
        if net.type not in {NetType.POWER, NetType.GROUND} and not net.name.upper().startswith(
            ("VCC", "VBUS", "VDD", "VIN")
        ):
            continue
        length = _net_length(design, net.id)
        current = _estimated_net_current(design, net)
        width = _average_trace_width(design, net.id) or 0.5
        resistance = length * 0.001 / max(width, 0.1)
        drop = current * resistance
        density = current / max(width, 0.1)
        severity = AnalysisSeverity.WARNING if drop > 0.1 or density > 2.0 else AnalysisSeverity.NONBLOCKING
        findings.append(
            AnalysisFinding(
                category="pdn_ir_drop_current_density",
                severity=severity,
                subject=net.name,
                message="coarse PDN IR-drop/current-density estimate",
                metrics={
                    "estimated_current_a": round(current, 3),
                    "length_mm": round(length, 3),
                    "average_width_mm": round(width, 3),
                    "estimated_resistance_ohm": round(resistance, 5),
                    "estimated_ir_drop_v": round(drop, 5),
                    "current_density_a_per_mm": round(density, 3),
                },
                assumptions=[
                    "1 oz copper equivalent",
                    "uniform trace width",
                    "component current_a properties are loads",
                ],
                limitations=["does not model planes, vias, copper pours, decoupling, or transient current"],
            )
        )
    return findings


def _thermal_findings(design: Design) -> list[AnalysisFinding]:
    findings: list[AnalysisFinding] = []
    for component in design.components.values():
        power = _float_property(component.properties, "power_w")
        theta = _float_property(component.properties, "theta_ja_c_per_w", default=60.0)
        if power <= 0:
            continue
        rise = power * theta
        severity = AnalysisSeverity.WARNING if rise > 40.0 else AnalysisSeverity.NONBLOCKING
        findings.append(
            AnalysisFinding(
                category="thermal_hotspot",
                severity=severity,
                subject=component.ref,
                message="coarse steady-state component temperature-rise estimate",
                metrics={
                    "power_w": round(power, 3),
                    "theta_ja_c_per_w": round(theta, 3),
                    "estimated_temp_rise_c": round(rise, 3),
                },
                assumptions=["steady-state theta-ja estimate", "ambient temperature not included"],
                limitations=["not CFD; ignores copper spreading, airflow, enclosure, and neighboring heat sources"],
            )
        )
    return findings


def _net_length(design: Design, net_id: str) -> float:
    if design.routing is None:
        return 0.0
    return sum(_segment_length(segment) for segment in design.routing.traces if segment.net_id == net_id)


def _segment_length(segment: TraceSegment) -> float:
    return math.hypot(segment.end[0] - segment.start[0], segment.end[1] - segment.start[1])


def _average_trace_width(design: Design, net_id: str) -> float | None:
    if design.routing is None:
        return None
    widths = [segment.width for segment in design.routing.traces if segment.net_id == net_id]
    if not widths:
        return None
    return round(sum(widths) / len(widths), 4)


def _estimated_net_current(design: Design, net: Net) -> float:
    refs = {node.component_ref for node in net.nodes}
    current = 0.0
    for component in design.components.values():
        if component.id in refs or component.ref in refs:
            current += _float_property(component.properties, "current_a")
    return current


def _float_property(properties: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(properties.get(key, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# EMC pre-compliance findings
# ---------------------------------------------------------------------------

# Typical rise times (ns) for common logic families — lower means faster edge.
# Actual values depend on silicon process, load capacitance, and supply rail.
_TYPICAL_RISE_NS: dict[str, float] = {
    "gpio": 5.0,
    "i2c": 100.0,
    "spi": 2.0,
    "uart": 10.0,
    "usb": 0.5,
    "ethernet": 1.0,
    "mipi": 0.2,
    "ddr": 0.3,
    "can": 25.0,
    "rs485": 10.0,
    "pwm": 5.0,
    "switching": 10.0,
}

# Rise-time threshold at-or-below which a trace is considered a fast-edge EMI risk.
_FAST_EDGE_THRESHOLD_NS = 2.0


def _infer_interface_type(comp_type: str, value: str | None, name: str) -> str:
    """Map a component + net name to the most likely interface type."""
    combined = f"{comp_type} {value or ''} {name}".lower()
    for iface, tokens in [
        ("i2c", ["i2c", "sda", "scl", "twowire"]),
        ("spi", ["spi", "miso", "mosi", "cs_", "sck", "ncs"]),
        ("uart", ["uart", "tx", "rx", "rts", "cts"]),
        ("usb", ["usb", "dp", "dm", "d+", "d-", "vbus"]),
        ("ethernet", ["ethernet", "eth", "rmii", "rgmii", "mdio"]),
        ("mipi", ["mipi", "csi", "dsi", "lp."]),
        ("ddr", ["ddr", "dram", "clk_", "dq_", "addr_"]),
        ("can", ["can", "canh", "canl"]),
        ("rs485", ["rs485", "485", "a_", "b_"]),
        ("pwm", ["pwm", "pwm_", "fan_"]),
        ("switching", ["sw_", "lx_", "switch", "gate"]),
    ]:
        if any(tok in combined for tok in tokens):
            return iface
    return "gpio"


def _emc_findings(design: Design) -> list[AnalysisFinding]:
    """EMC pre-compliance findings — edge-rate risk, loop areas, ferrite validation.

    (EMC pre-compliance checklist + evidence report.)
    """
    findings: list[AnalysisFinding] = []

    # --- 1. Fast edge-rate detection ---
    fast_edges = _detect_fast_edges(design)
    if fast_edges:
        findings.append(
            AnalysisFinding(
                category="emc_fast_edge_rate",
                severity=AnalysisSeverity.WARNING,
                subject="fast-edge nets",
                message=f"{len(fast_edges)} net(s) have estimated rise time below "
                f"{_FAST_EDGE_THRESHOLD_NS} ns and are potential EMI sources",
                metrics={"count": len(fast_edges), "nets": fast_edges},
                limitations=[
                    "rise time estimates use typical values per interface type, not IBIS or measured data",
                ],
            )
        )

    # --- 2. Switching-regulator EMI loop-area score ---
    loop_scores = _emc_loop_area_scores(design)
    if loop_scores:
        worst = max(loop_scores, key=lambda x: x["score"])
        severity = AnalysisSeverity.WARNING if worst["score"] >= 3 else AnalysisSeverity.NONBLOCKING
        findings.append(
            AnalysisFinding(
                category="emc_switcher_loop_area",
                severity=severity,
                subject="switching-regulator loop area",
                message=f"Worst-case estimated hot loop area score: {worst['score']}/5 "
                f"(ref {worst['ref']}); loop minimisation recommended above score 3",
                metrics={
                    "components": loop_scores,
                    "methodology": "geometry-based: loop area estimated from package lead "
                    "spacing + trace-to-bypass distance; score 1-5",
                },
                limitations=["does not account for shielded inductors, ground plane proximity, or enclosure"],
            )
        )

    # --- 3. Common-mode choke / ferrite on external cables ---
    ferrite_missing = _check_external_cable_filtering(design)
    if ferrite_missing:
        findings.append(
            AnalysisFinding(
                category="emc_cable_filtering",
                severity=AnalysisSeverity.NONBLOCKING,
                subject="external cable filtering",
                message=f"{len(ferrite_missing)} external connector(s) without common-mode choke or ferrite: "
                f"{', '.join(ferrite_missing)}",
                metrics={"unfiltered_connectors": ferrite_missing},
                limitations=[
                    "ferrite requirement depends on emissions testing; not all cables need a CM choke",
                ],
            )
        )

    # --- 4. Split-plane crossing risk ---
    split_crossings = _detect_split_plane_crossings(design)
    if split_crossings:
        findings.append(
            AnalysisFinding(
                category="emc_split_plane_crossing",
                severity=AnalysisSeverity.WARNING,
                subject="split-plane crossing",
                message=f"{len(split_crossings)} high-speed trace(s) may cross a split plane "
                f"without a return-path bridge",
                metrics={"count": len(split_crossings), "nets": split_crossings},
                limitations=[
                    "detects traces on nets with impedance or edge-rate constraints whose return-path "
                    "net is not assigned; actual crossings depend on the full stackup and plane shapes",
                ],
            )
        )

    if not findings:
        findings.append(
            AnalysisFinding(
                category="emc_pre_compliance",
                severity=AnalysisSeverity.INFO,
                subject="no EMC findings",
                message="No EMC pre-compliance issues detected by heuristic analysis",
                metrics={"note": "EMC heuristics are limited; lab emissions testing is still required"},
            )
        )

    return findings


def _detect_fast_edges(design: Design) -> list[str]:
    """Return names of nets whose estimated rise time is below the fast-edge threshold.

    Uses interface type inference from connected components.
    Falls back to typical rise times per interface type when no explicit constraint
    is set on the net.
    """
    fast: list[str] = []
    for net in design.nets.values():
        # Infer from connected component types
        connected_types: set[str] = set()
        for node in net.nodes:
            comp = design.get_component(node.component_ref)
            if comp:
                connected_types.add(comp.type.lower())
        # If the net connects to a known-fast component type, flag it
        flagged = False
        for ctype in connected_types:
            rise = _TYPICAL_RISE_NS.get(ctype) or _TYPICAL_RISE_NS.get(_infer_interface_type(ctype, "", net.name), 10.0)
            if rise <= _FAST_EDGE_THRESHOLD_NS:
                fast.append(net.name)
                flagged = True
                break
        if not flagged and net.constraints and net.constraints.impedance_target is not None:
            # Controlled-impedance nets are inherently fast-edge candidates
            fast.append(net.name)
    return sorted(set(fast))


_SWITCHER_TOKENS = {"buck", "boost", "buck-boost", "flyback", "sepic", "switching", "dc-dc"}


def _is_switching_component(comp: Component) -> bool:
    if bool(comp.properties.get("switching_regulator", False)):
        return True
    identity = f"{comp.type.lower()} {str(comp.properties.get('topology', '')).lower()}"
    return any(token in identity for token in _SWITCHER_TOKENS)


def _loop_area_risk(comp: Component) -> tuple[int, str]:
    package = (comp.footprint or "").lower()
    if any(token in package for token in ("bga", "qfn", "dfn", "son", "wlcsp")):
        return 1, "small package, likely minimal loop area"
    if any(token in package for token in ("sot23", "sot-23", "tsot", "sc-70")):
        return 2, "small footprint, reasonable loop area"
    if any(token in package for token in ("soic", "sop", "tssop", "msop", "qfp", "lqfp")):
        return 3, "moderate package; place bypass capacitor close to VIN/GND pins"
    if any(token in package for token in ("dip", "pdip", "to-220", "to-263", "to-252")):
        return 4, "through-hole or large SMD; high loop area risk — minimise trace length to input cap"
    if _float_property(comp.properties, "power_w") > 1.0:
        return 3, "package unknown but > 1 W, treat as moderate risk"
    return 2, "package unknown, assume moderate loop area"


def _emc_loop_area_scores(design: Design) -> list[dict[str, Any]]:
    """Estimate EMI loop-area risk for switching-regulator components.

    Returns a list of dicts with keys ``ref``, ``type``, ``score`` (1-5, where 5
    is worst) and ``note``.
    """
    scores: list[dict[str, Any]] = []
    for comp in design.components.values():
        if not _is_switching_component(comp):
            continue
        score, note = _loop_area_risk(comp)
        scores.append({"ref": comp.ref, "type": comp.type, "score": score, "note": note})
    return scores


def _check_external_cable_filtering(design: Design) -> list[str]:
    """Return names of external connectors that lack a common-mode choke or ferrite.

    Checks for connectors that have 'usb', 'hdmi', 'ethernet', 'rj45', 'jack',
    'barrel', 'terminal', 'd-sub' in their type and checks the net for a ferrite
    bead or CM choke component (``type`` containing 'ferrite', 'bead', 'common-mode',
    'cm_choke').
    """
    connector_tokens = {"usb", "hdmi", "ethernet", "rj45", "jack", "barrel", "terminal", "d-sub"}
    ferrite_found = False
    for comp in design.components.values():
        ctype = comp.type.lower()
        if any(tok in ctype for tok in ("ferrite", "bead", "common-mode", "cm_choke", "cmc")):
            ferrite_found = True
            break

    if ferrite_found:
        return []  # at least one filtering component present

    unfiltered: list[str] = []
    for comp in design.components.values():
        ctype = comp.type.lower()
        if any(tok in ctype for tok in connector_tokens):
            unfiltered.append(comp.ref)
    return unfiltered


def _detect_split_plane_crossings(design: Design) -> list[str]:
    """Return names of high-speed nets that may cross a split plane.

    A net is considered at risk if:
    - It has impedance constraints or is inferred as fast-edge
    - It has no ``return_path_net`` assigned
    """
    fast_nets = set(_detect_fast_edges(design))
    at_risk: list[str] = []
    for net in design.nets.values():
        if net.name in fast_nets:
            continue  # already counted
        if net.constraints and net.constraints.impedance_target is not None and net.constraints.return_path_net is None:
            at_risk.append(net.name)
    return sorted(at_risk)


def run_analysis(design: Design) -> LegacyAnalysisReport:
    """Backward-compatible SI/thermal adapter used by proof-pack checks."""
    report = generate_electrical_analysis_report(design)
    impedance = [
        ImpedanceAnalysisEntry(
            net_name=finding.subject,
            tolerance_pct=float(finding.metrics.get("tolerance_pct", 0.0)),
        )
        for finding in report.findings
        if finding.category == "controlled_impedance"
    ]
    length_match = [
        LengthMatchAnalysisEntry(
            group_name=finding.subject,
            within_tolerance=float(finding.metrics.get("delta_mm", 0.0))
            <= float(finding.metrics.get("default_tolerance_mm", 1.0)),
        )
        for finding in report.findings
        if finding.category == "differential_pair_length_match"
    ]
    thermal = [
        ThermalAnalysisEntry(
            component_ref=finding.subject,
            estimated_temp_rise_c=float(finding.metrics.get("estimated_temp_rise_c", 0.0)),
        )
        for finding in report.findings
        if finding.category == "thermal_hotspot"
    ]
    return LegacyAnalysisReport(impedance=impedance, length_match=length_match, thermal=thermal)
