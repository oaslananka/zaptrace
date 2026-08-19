"""IPC-D-356 manufacturing netlist evidence export and parity.

This module emits a deterministic IPC-D-356-style connectivity subset for
release gating. It is intentionally conservative: the exported records preserve
net name, reference designator, and pin/pad name so fabrication-output netlists
can be compared back to the ZapTrace IR without relying on a GUI EDA session.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from zaptrace.core.models import Design
from zaptrace.kicad.parity import NetPinMismatch


class IpcD356ParityReport(BaseModel):
    """ZapTrace IR ↔ IPC-D-356 manufacturing netlist parity report."""

    schema_version: str = "1.0"
    check: str = "ipc_d356_netlist"
    passed: bool
    missing_nets: list[str] = Field(default_factory=list)
    extra_nets: list[str] = Field(default_factory=list)
    pin_mismatches: list[NetPinMismatch] = Field(default_factory=list)
    ir_net_count: int = 0
    ipc_d356_net_count: int = 0
    message: str = ""

    @property
    def error_count(self) -> int:
        return len(self.missing_nets) + len(self.extra_nets) + len(self.pin_mismatches)


def _node_key(component_ref: str, pin_name: str) -> str:
    return f"{component_ref}.{pin_name}"


def _component_ref_aliases(design: Design) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for component in design.components.values():
        aliases[component.id] = component.ref
        aliases[component.ref] = component.ref
    return aliases


def design_ref_net_map(design: Design) -> dict[str, set[str]]:
    """Return ``net_name -> {reference.pin}`` from the ZapTrace IR."""
    aliases = _component_ref_aliases(design)
    result: dict[str, set[str]] = {}
    for net in design.nets.values():
        nodes: set[str] = set()
        for node in net.nodes:
            ref = aliases.get(node.component_ref, node.component_ref)
            nodes.add(_node_key(ref, node.pin_name))
        result[net.name] = nodes
    return result


def generate_ipcd356(design: Design) -> str:
    """Generate deterministic IPC-D-356-style manufacturing netlist text."""
    lines = [
        "C  ZapTrace IPC-D-356 connectivity subset",
        f"C  DESIGN {design.meta.name}",
        "C  RECORD P NET <net-name> REF <reference> PIN <pin-name>",
    ]
    for net_name, nodes in sorted(design_ref_net_map(design).items()):
        for node in sorted(nodes):
            ref, pin = node.split(".", 1)
            lines.append(f"P NET {net_name} REF {ref} PIN {pin}")
    lines.append("999")
    return "\n".join(lines) + "\n"


def write_ipcd356(design: Design, output_path: str | Path) -> Path:
    """Write the IPC-D-356-style netlist and return its path."""
    out = Path(output_path)
    if out.suffix.lower() not in {".ipc", ".d356", ".ipc356"}:
        raise ValueError(f"unexpected IPC-D-356 output suffix: {out.suffix}")
    resolved = out.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # nosemgrep: python.lang.security.audit.path-traversal.path-traversal-write
    resolved.write_text(generate_ipcd356(design), encoding="utf-8")
    return resolved


def parse_ipcd356(text: str) -> dict[str, set[str]]:
    """Parse ZapTrace IPC-D-356-style records into ``net_name -> {ref.pin}``."""
    result: dict[str, set[str]] = {}
    for raw_line in text.splitlines():
        parts = raw_line.strip().split()
        if len(parts) < 7 or parts[0] != "P":
            continue
        try:
            net_index = parts.index("NET")
            ref_index = parts.index("REF")
            pin_index = parts.index("PIN")
        except ValueError:
            continue
        net_name = " ".join(parts[net_index + 1 : ref_index])
        ref = parts[ref_index + 1]
        pin = " ".join(parts[pin_index + 1 :])
        if net_name and ref and pin:
            result.setdefault(net_name, set()).add(_node_key(ref, pin))
    return result


def compare_ir_to_ipcd356(design: Design, ipc_text: str) -> IpcD356ParityReport:
    """Compare ZapTrace IR connectivity against IPC-D-356 netlist text."""
    ir = design_ref_net_map(design)
    ipc = parse_ipcd356(ipc_text)
    missing_nets = sorted(set(ir) - set(ipc))
    extra_nets = sorted(set(ipc) - set(ir))
    mismatches: list[NetPinMismatch] = []
    for net_name in sorted(set(ir).intersection(ipc)):
        missing_nodes = sorted(ir[net_name] - ipc[net_name])
        extra_nodes = sorted(ipc[net_name] - ir[net_name])
        if missing_nodes or extra_nodes:
            mismatches.append(NetPinMismatch(net_id=net_name, missing_nodes=missing_nodes, extra_nodes=extra_nodes))
    passed = not missing_nets and not extra_nets and not mismatches
    return IpcD356ParityReport(
        passed=passed,
        missing_nets=missing_nets,
        extra_nets=extra_nets,
        pin_mismatches=mismatches,
        ir_net_count=len(ir),
        ipc_d356_net_count=len(ipc),
        message="IR and IPC-D-356 netlist match" if passed else "IR and IPC-D-356 netlist differ",
    )


def compare_ir_to_ipcd356_file(design: Design, ipc_path: str | Path) -> IpcD356ParityReport:
    """Load an IPC-D-356 file and compare it against the ZapTrace IR."""
    p = Path(ipc_path)
    if p.suffix.lower() not in {".ipc", ".d356", ".ipc356"}:
        raise ValueError(f"unexpected IPC-D-356 input suffix: {p.suffix}")
    resolved = p.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"IPC-D-356 input is not a file: {p}")
    # nosemgrep: python.lang.security.audit.path-traversal.path-traversal-read
    return compare_ir_to_ipcd356(design, resolved.read_text(encoding="utf-8"))


def write_ipcd356_parity_report(design: Design, ipc_path: str | Path, output_path: str | Path) -> Path:
    """Write a JSON parity report for an IPC-D-356 file."""
    report = compare_ir_to_ipcd356_file(design, ipc_path)
    out = Path(output_path)
    if out.suffix.lower() != ".json":
        raise ValueError(f"unexpected IPC-D-356 parity report suffix: {out.suffix}")
    resolved = out.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # nosemgrep: python.lang.security.audit.path-traversal.path-traversal-write
    resolved.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return resolved
