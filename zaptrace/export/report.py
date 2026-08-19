from __future__ import annotations

from datetime import UTC, datetime

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design
from zaptrace.erc.models import ERCResult

_REPORT_GENERATED_AT = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _summary_lines(design: Design, erc_result: ERCResult | None) -> list[str]:
    board = canonical_board_definition(design)
    lines = [
        f"# Design Report: {design.meta.name}",
        "",
        f"**Version:** {design.meta.version}  ",
        f"**Revision:** {design.meta.revision}  ",
        f"**Author:** {design.meta.author or 'N/A'}  ",
        f"**Generated:** {_REPORT_GENERATED_AT}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Components | {len(design.components)} |",
        f"| Nets | {len(design.nets)} |",
        f"| Board size | {board.width} x {board.height} mm |",
        f"| Layers | {board.layers} |",
    ]
    if erc_result is None:
        return lines

    status = "PASS" if erc_result.passed else "FAIL"
    lines.extend(
        [
            f"| ERC status | {status} |",
            f"| ERC errors | {erc_result.total_errors} |",
            f"| ERC warnings | {erc_result.total_warnings} |",
        ]
    )
    if erc_result.checks_run:
        lines.append(f"| ERC coverage | {erc_result.coverage_summary()} |")
    return lines


def _component_lines(design: Design) -> list[str]:
    lines = [
        "",
        "## Components",
        "",
        "| Ref | Type | Value | Footprint | MPN |",
        "|-----|------|-------|-----------|-----|",
    ]
    lines.extend(
        f"| {comp.ref} | {comp.type} | {comp.value or ''} | {comp.footprint} | {comp.mpn or ''} |"
        for comp in sorted(design.components.values(), key=lambda component: component.ref)
    )
    return lines


def _net_lines(design: Design) -> list[str]:
    lines = ["", "## Nets", ""]
    for net in sorted(design.nets.values(), key=lambda item: item.name):
        node_str = ", ".join(f"{node.component_ref}.{node.pin_name}" for node in net.nodes)
        lines.append(f"- **{net.name}** ({net.type.value}): {node_str}")
    return lines


def _erc_violation_lines(erc_result: ERCResult | None) -> list[str]:
    if erc_result is None or not erc_result.violations:
        return []

    lines = ["", "## ERC Violations", ""]
    for violation in erc_result.violations:
        icon = {"error": "E", "warning": "W", "info": "I"}.get(violation.severity.value, ".")
        lines.append(f"- **{icon}** `{violation.rule_id}` {violation.message}")
        if violation.patch_suggestion:
            lines.append(f"  - Suggestion: {violation.patch_suggestion}")
    return lines


def _erc_coverage_gap_lines(erc_result: ERCResult | None) -> list[str]:
    if erc_result is None or not erc_result.coverage_gaps:
        return []

    return [
        "",
        "## ERC Coverage Gaps",
        "",
        "ERC is a rule-based pre-check, not full electrical verification. Not yet checked:",
        "",
        *(f"- {gap}" for gap in erc_result.coverage_gaps),
    ]


def generate_report(design: Design, erc_result: ERCResult | None = None) -> str:
    """Generate a comprehensive Markdown design report.

    The generated timestamp is fixed for the lifetime of the Python process.
    That keeps normal CLI reports tied to the run that produced them while
    preventing long in-process benchmark suites from producing different
    artifact hashes when two otherwise identical reports cross a minute
    boundary.
    """
    lines = _summary_lines(design, erc_result)
    lines.extend(_component_lines(design))
    lines.extend(_net_lines(design))
    lines.extend(_erc_violation_lines(erc_result))
    lines.extend(_erc_coverage_gap_lines(erc_result))
    return "\n".join(lines)
