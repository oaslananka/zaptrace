"""KiCad netlist parity checks.

The current KiCad schematic exporter emits a machine-readable
``*.kicad_netlist_evidence.json`` contract alongside the schematic/PCB files.
This module compares that exported evidence back to the ZapTrace IR so missing
nets, extra nets, and pin mismatches are visible and release-gateable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from zaptrace.core.models import Design

_JSON_SUFFIX = ".json"


class NetPinMismatch(BaseModel):
    """Pin-level mismatch for one net."""

    net_id: str
    missing_nodes: list[str] = Field(default_factory=list)
    extra_nodes: list[str] = Field(default_factory=list)


class KiCadNetlistParityReport(BaseModel):
    """IR ↔ KiCad netlist-evidence parity report."""

    schema_version: str = "1.0"
    check: str = "ir_to_kicad_schematic_netlist"
    passed: bool
    missing_nets: list[str] = Field(default_factory=list)
    extra_nets: list[str] = Field(default_factory=list)
    pin_mismatches: list[NetPinMismatch] = Field(default_factory=list)
    ir_net_count: int = 0
    kicad_net_count: int = 0
    message: str = ""

    @property
    def error_count(self) -> int:
        return len(self.missing_nets) + len(self.extra_nets) + len(self.pin_mismatches)


def _read_validated_text(path: str | Path, *, suffixes: set[str]) -> str:
    """Read an expected local KiCad evidence artifact after basic validation."""
    p = Path(path)
    if p.suffix not in suffixes:
        raise ValueError(f"unexpected KiCad parity input suffix: {p.suffix}")
    resolved = p.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"KiCad parity input is not a file: {p}")
    # nosemgrep: python.lang.security.audit.path-traversal.path-traversal-read
    return resolved.read_text(encoding="utf-8")


def _write_validated_text(path: str | Path, text: str, *, suffix: str = _JSON_SUFFIX) -> Path:
    """Write a local parity report after constraining the output suffix."""
    out = Path(path)
    if out.suffix != suffix:
        raise ValueError(f"unexpected KiCad parity output suffix: {out.suffix}")
    resolved = out.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # nosemgrep: python.lang.security.audit.path-traversal.path-traversal-write
    resolved.write_text(text, encoding="utf-8")
    return resolved


def _node_key(component_ref: str, pin_name: str) -> str:
    return f"{component_ref}.{pin_name}"


def ir_net_map(design: Design) -> dict[str, set[str]]:
    """Return ``net_id -> {component.pin}`` for ZapTrace IR connectivity."""
    return {
        net_id: {_node_key(node.component_ref, node.pin_name) for node in net.nodes}
        for net_id, net in design.nets.items()
    }


def kicad_evidence_net_map(evidence: dict[str, Any]) -> dict[str, set[str]]:
    """Return ``net_id -> {component.pin}`` from KiCad netlist evidence JSON."""
    result: dict[str, set[str]] = {}
    for net in evidence.get("nets", []):
        if not isinstance(net, dict):
            continue
        net_id = str(net.get("id", ""))
        if not net_id:
            continue
        nodes: set[str] = set()
        for node in net.get("nodes", []):
            if isinstance(node, dict):
                component_ref = str(node.get("component_ref", ""))
                pin_name = str(node.get("pin_name", ""))
                if component_ref and pin_name:
                    nodes.add(_node_key(component_ref, pin_name))
        result[net_id] = nodes
    return result


def compare_ir_to_kicad_netlist_evidence(design: Design, evidence: dict[str, Any]) -> KiCadNetlistParityReport:
    """Compare ZapTrace IR connectivity against exported KiCad netlist evidence."""
    ir = ir_net_map(design)
    kicad = kicad_evidence_net_map(evidence)
    missing_nets = sorted(set(ir) - set(kicad))
    extra_nets = sorted(set(kicad) - set(ir))
    mismatches: list[NetPinMismatch] = []
    for net_id in sorted(set(ir).intersection(kicad)):
        missing_nodes = sorted(ir[net_id] - kicad[net_id])
        extra_nodes = sorted(kicad[net_id] - ir[net_id])
        if missing_nodes or extra_nodes:
            mismatches.append(NetPinMismatch(net_id=net_id, missing_nodes=missing_nodes, extra_nodes=extra_nodes))
    passed = not missing_nets and not extra_nets and not mismatches
    return KiCadNetlistParityReport(
        passed=passed,
        missing_nets=missing_nets,
        extra_nets=extra_nets,
        pin_mismatches=mismatches,
        ir_net_count=len(ir),
        kicad_net_count=len(kicad),
        message="IR and KiCad netlist evidence match" if passed else "IR and KiCad netlist evidence differ",
    )


def compare_ir_to_kicad_netlist_evidence_file(
    design: Design,
    evidence_path: str | Path,
) -> KiCadNetlistParityReport:
    """Load a KiCad netlist evidence file and compare it to the IR."""
    data = json.loads(_read_validated_text(evidence_path, suffixes={_JSON_SUFFIX}))
    return compare_ir_to_kicad_netlist_evidence(design, data)


def write_kicad_netlist_parity_report(
    design: Design,
    evidence_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Write the parity report JSON and return its path."""
    report = compare_ir_to_kicad_netlist_evidence_file(design, evidence_path)
    return _write_validated_text(output_path, report.model_dump_json(indent=2) + "\n")


class KiCadPcbParityReport(BaseModel):
    """KiCad schematic-evidence ↔ PCB pad-net parity report."""

    schema_version: str = "1.0"
    check: str = "kicad_schematic_to_pcb_netlist"
    passed: bool
    missing_nets: list[str] = Field(default_factory=list)
    extra_nets: list[str] = Field(default_factory=list)
    pin_mismatches: list[NetPinMismatch] = Field(default_factory=list)
    schematic_net_count: int = 0
    pcb_net_count: int = 0
    message: str = ""

    @property
    def error_count(self) -> int:
        return len(self.missing_nets) + len(self.extra_nets) + len(self.pin_mismatches)


def _component_ref_aliases(design: Design) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for component in design.components.values():
        aliases[component.id] = component.ref
        aliases[component.ref] = component.ref
    return aliases


def _physical_node_keys(design: Design, component_ref: str, pin_name: str) -> set[str]:
    component = next(
        (item for item in design.components.values() if component_ref in (item.id, item.ref)),
        None,
    )
    if component is None or not component.package_pin_map:
        return {_node_key(component_ref, pin_name)}
    pad_ids = {pad_id for pad_id, logical_pin in component.package_pin_map.items() if logical_pin == pin_name}
    if not pad_ids:
        return {_node_key(component.ref, pin_name)}
    return {_node_key(component.ref, pad_id) for pad_id in pad_ids}


def schematic_evidence_ref_net_map(design: Design, evidence: dict[str, Any]) -> dict[str, set[str]]:
    """Return ``net_name -> {reference.pin}`` from KiCad schematic netlist evidence."""
    aliases = _component_ref_aliases(design)
    result: dict[str, set[str]] = {}
    for net in evidence.get("nets", []):
        if not isinstance(net, dict):
            continue
        net_name = str(net.get("name", ""))
        if not net_name:
            continue
        nodes: set[str] = set()
        for node in net.get("nodes", []):
            if not isinstance(node, dict):
                continue
            component_ref = str(node.get("component_ref", ""))
            pin_name = str(node.get("pin_name", ""))
            canonical_ref = aliases.get(component_ref, component_ref)
            if canonical_ref and pin_name:
                nodes.update(_physical_node_keys(design, canonical_ref, pin_name))
        result[net_name] = nodes
    return result


def parse_kicad_pcb_pad_net_map(pcb_text: str) -> dict[str, set[str]]:
    """Parse exported KiCad PCB text into ``net_name -> {reference.pad}``.

    This parser is intentionally conservative and targets the KiCad S-expression
    subset emitted by ZapTrace. It records only footprint references and pad net
    assignments; missing pad net assignments remain visible as absent nodes.
    """
    import re

    result: dict[str, set[str]] = {}
    current_ref = ""
    current_pad = ""
    in_footprint = False
    for raw_line in pcb_text.splitlines():
        line = raw_line.strip()
        if line.startswith("(footprint "):
            in_footprint = True
            current_ref = ""
            current_pad = ""
            continue
        if in_footprint and line == ")":
            current_pad = ""
            continue
        if not in_footprint:
            continue
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', line)
        if ref_match:
            current_ref = ref_match.group(1)
            continue
        pad_match = re.search(r'\(pad\s+"([^"]+)"', line)
        if pad_match:
            current_pad = pad_match.group(1)
            continue
        net_match = re.search(r'\(net\s+\d+\s+"([^"]+)"\)', line)
        if net_match and current_ref and current_pad:
            result.setdefault(net_match.group(1), set()).add(_node_key(current_ref, current_pad))
    return result


def compare_kicad_schematic_to_pcb(
    design: Design,
    schematic_evidence: dict[str, Any],
    pcb_text: str,
) -> KiCadPcbParityReport:
    """Compare KiCad schematic netlist evidence against PCB pad-net assignments."""
    schematic = schematic_evidence_ref_net_map(design, schematic_evidence)
    pcb = parse_kicad_pcb_pad_net_map(pcb_text)
    missing_nets = sorted(set(schematic) - set(pcb))
    extra_nets = sorted(set(pcb) - set(schematic))
    mismatches: list[NetPinMismatch] = []
    for net_name in sorted(set(schematic).intersection(pcb)):
        missing_nodes = sorted(schematic[net_name] - pcb[net_name])
        extra_nodes = sorted(pcb[net_name] - schematic[net_name])
        if missing_nodes or extra_nodes:
            mismatches.append(NetPinMismatch(net_id=net_name, missing_nodes=missing_nodes, extra_nodes=extra_nodes))
    passed = not missing_nets and not extra_nets and not mismatches
    return KiCadPcbParityReport(
        passed=passed,
        missing_nets=missing_nets,
        extra_nets=extra_nets,
        pin_mismatches=mismatches,
        schematic_net_count=len(schematic),
        pcb_net_count=len(pcb),
        message="KiCad schematic and PCB connectivity match"
        if passed
        else "KiCad schematic and PCB connectivity differ",
    )


def compare_kicad_schematic_to_pcb_files(
    design: Design,
    schematic_evidence_path: str | Path,
    pcb_path: str | Path,
) -> KiCadPcbParityReport:
    evidence = json.loads(_read_validated_text(schematic_evidence_path, suffixes={_JSON_SUFFIX}))
    pcb_text = _read_validated_text(pcb_path, suffixes={".kicad_pcb"})
    return compare_kicad_schematic_to_pcb(design, evidence, pcb_text)


def write_kicad_pcb_parity_report(
    design: Design,
    schematic_evidence_path: str | Path,
    pcb_path: str | Path,
    output_path: str | Path,
) -> Path:
    report = compare_kicad_schematic_to_pcb_files(design, schematic_evidence_path, pcb_path)
    return _write_validated_text(output_path, report.model_dump_json(indent=2) + "\n")
