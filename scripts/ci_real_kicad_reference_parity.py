#!/usr/bin/env python3
"""Measure real, source-pinned KiCad schematic/import parity without editing originals.

This is a G0 *diagnostic*, not a round-trip, hardware sign-off, or AI task score.
Native KiCad export is the independent oracle; missing evidence never passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from defusedxml import ElementTree

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.review_studio_schematic_eco import _run_native  # noqa: E402
from zaptrace.kicad.oracle import get_kicad_version  # noqa: E402
from zaptrace.kicad.project_importer import import_kicad_project  # noqa: E402

MANIFEST = ROOT / "benchmarks/human-reference-corpus/manifest.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def graph_hash(graph: dict[str, set[tuple[str, str]]]) -> str:
    canonical = [(name, sorted(nodes)) for name, nodes in sorted(graph.items())]
    return hashlib.sha256(json.dumps(canonical, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def read_native_netlist(path: Path) -> dict[str, set[tuple[str, str]]]:
    """Parse KiCad's actual exported XML netlist, not ZapTrace-generated evidence."""
    root = ElementTree.parse(path).getroot()
    if root is None:
        raise ValueError("Native KiCad netlist XML has no root")
    nets = root.findall("./nets/net")
    if not nets:
        raise ValueError("KiCad netlist has no nets; cannot establish parity")
    graph: dict[str, set[tuple[str, str]]] = {}
    for net in nets:
        name = net.get("name")
        if not name or name in graph:
            raise ValueError("Missing or duplicate native net name")
        nodes = {(n.get("ref", ""), n.get("pin", "")) for n in net.findall("node")}
        if any(not ref or not pin for ref, pin in nodes):
            raise ValueError(f"Incomplete native net nodes on {name}")
        graph[name] = nodes
    return graph


def read_imported_netlist(project: Path) -> tuple[dict[str, set[tuple[str, str]]], dict[str, Any]]:
    result = import_kicad_project(project)
    graph: dict[str, set[tuple[str, str]]] = {}
    for net in result.design.nets.values():
        if not net.name or net.name in graph:
            raise ValueError("Missing or duplicate imported net name")
        graph[net.name] = {(n.component_ref, n.pin_name) for n in net.nodes}
    findings = {}
    for finding in result.findings:
        findings[finding.kind] = findings.get(finding.kind, 0) + 1
    return graph, {**result.to_dict(), "finding_kinds": dict(sorted(findings.items()))}


def compare_graphs(
    native: dict[str, set[tuple[str, str]]],
    imported: dict[str, set[tuple[str, str]]],
) -> dict[str, Any]:
    """Compare exact original net names and reference/pin tuples; no fuzzy score."""
    native_names, imported_names = set(native), set(imported)
    shared = native_names & imported_names
    mismatched = sorted(name for name in shared if native[name] != imported[name])
    return {
        "native_net_count": len(native),
        "imported_net_count": len(imported),
        "native_pin_node_count": sum(len(nodes) for nodes in native.values()),
        "imported_pin_node_count": sum(len(nodes) for nodes in imported.values()),
        "common_net_count": len(shared),
        "native_missing_net_count": len(native_names - imported_names),
        "imported_extra_net_count": len(imported_names - native_names),
        "pin_mismatch_net_count": len(mismatched),
        "native_missing_examples": sorted(native_names - imported_names)[:12],
        "imported_extra_examples": sorted(imported_names - native_names)[:12],
        "pin_mismatch_examples": mismatched[:12],
        "native_graph_sha256": graph_hash(native),
        "imported_graph_sha256": graph_hash(imported),
        "exact_connectivity_parity": native == imported,
    }


def _verified_artifact(source: Path, artifact: dict[str, Any]) -> tuple[Path, str]:
    """Resolve only in-root files whose bytes and size match the committed manifest."""
    relative = Path(artifact["path"])
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Reference artifact escapes source directory")
    target = (source / relative).resolve()
    if not target.is_relative_to(source) or not target.is_file():
        raise ValueError("Missing or unsafe source artifact")
    actual = sha256_file(target)
    if actual != artifact["sha256"] or target.stat().st_size != artifact["size_bytes"]:
        raise ValueError(f"Source identity mismatch: {relative.name}")
    return relative, actual


def source_artifacts(repo_root: Path, record: dict[str, Any]) -> tuple[Path, Path, dict[str, str]]:
    """Verify manifest-pinned vendored bytes before invoking either design tool."""
    ref_id = record["reference_id"]
    if not ref_id.replace("-", "").isalnum():
        raise ValueError("Invalid reference identity")
    source = (repo_root / "benchmarks/external" / ref_id / "source").resolve()
    allowed_root = (repo_root / "benchmarks/external").resolve()
    if not source.is_relative_to(allowed_root) or not source.is_dir():
        raise ValueError("Reference source directory is unavailable")
    identity: dict[str, str] = {}
    schematics: list[Path] = []
    for artifact in record["artifacts"]:
        relative, actual = _verified_artifact(source, artifact)
        identity[relative.as_posix()] = actual
        if relative.suffix == ".kicad_sch":
            schematics.append(relative)
    if len(schematics) != 1:
        raise ValueError("Expected one manifest-pinned top-level KiCad schematic")
    return source, schematics[0], identity


def measure_reference(repo_root: Path, record: dict[str, Any], *, tool: str) -> dict[str, Any]:
    ref_id = record["reference_id"]
    output: dict[str, Any] = {
        "reference_id": ref_id,
        "upstream_commit": record["upstream_commit"],
        "source_verification": record["source_verification"],
        "status": "not_run",
    }
    if record["source_verification"] != "vendored-byte-exact":
        output["reason"] = "reference-only; byte-pinned source not vendored"
        return output
    start = time.monotonic()
    try:
        source, schematic, identity = source_artifacts(repo_root, record)
        output["source_artifact_sha256"] = identity
        executable = shutil.which("kicad-cli") if tool == "kicad-cli" else None
        if executable is None:
            output["reason"] = "native KiCad CLI unavailable"
            return output
        # Only the expected KiCad executable is eligible; no shell or custom command.
        executable = str(Path(executable).resolve(strict=True))
        with tempfile.TemporaryDirectory(prefix="zaptrace-real-kicad-") as folder:
            temp = Path(folder)
            copied = temp / "source"
            copied.mkdir()
            # Copy only hashed, manifest-approved artifacts. Ignore local KiCad
            # session files and any unrelated contents of the reference folder.
            for relative in identity:
                target = copied / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / relative, target)
            native_xml = temp / "native-netlist.xml"
            # Reuse the existing bounded native KiCad execution contract.
            result = _run_native(
                [
                    executable,
                    "sch",
                    "export",
                    "netlist",
                    "--format",
                    "kicadxml",
                    "--output",
                    str(native_xml),
                    str(copied / schematic),
                ],
                timeout=90,
            )
            if result.returncode or not native_xml.is_file():
                raise ValueError("native KiCad export produced no valid netlist")
            native = read_native_netlist(native_xml)
            imported, metadata = read_imported_netlist(copied)
            comparison = compare_graphs(native, imported)
            output["native_netlist_sha256"] = sha256_file(native_xml)
            output["comparison"] = comparison
            output["import_findings"] = {
                "error_count": metadata["error_count"],
                "warning_count": metadata["warning_count"],
                "finding_kinds": metadata["finding_kinds"],
                "importer_net_score": metadata["net_score"],
            }
            clean = comparison["exact_connectivity_parity"] and metadata["error_count"] == 0
            clean = clean and metadata["finding_kinds"].get("unsupported_construct", 0) == 0
            output["status"] = "verified" if clean else "blocked"
            if not clean:
                output["reason"] = "native/imported electrical graph or import completeness differs"
    except (
        OSError,
        ValueError,
        RuntimeError,
        ElementTree.ParseError,
        KeyError,
        TypeError,
    ) as exc:
        output["status"] = "blocked"
        output["reason"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    finally:
        output["elapsed_seconds"] = round(time.monotonic() - start, 3)
    return output


def build_report(repo_root: Path = ROOT, manifest: Path = MANIFEST, tool: str = "kicad-cli") -> dict[str, Any]:
    records = json.loads(manifest.read_text(encoding="utf-8"))["references"]
    version = get_kicad_version() if tool == "kicad-cli" else None
    outcomes = [measure_reference(repo_root, record, tool=tool) for record in records]
    statuses = [item["status"] for item in outcomes]
    return {
        "schema_version": "1.0",
        "gate": "g0-native-schematic-import-parity",
        "scope": "read-only schematic connectivity; not round-trip, AI success, or fabrication sign-off",
        "manifest_sha256": sha256_file(manifest),
        "native_tool_version": version or "not_available",
        "status": "verified" if statuses and all(s == "verified" for s in statuses) else "blocked",
        "measured": sum(s in ("verified", "blocked") for s in statuses),
        "verified": statuses.count("verified"),
        "blocked": statuses.count("blocked"),
        "not_run": statuses.count("not_run"),
        "references": outcomes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--strict", action="store_true", help="Return failure unless all reference outcomes are verified"
    )
    args = parser.parse_args(argv)
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"G0 native import parity: {report['status']} — {report['measured']} measured, "
        f"{report['verified']} verified, {report['blocked']} blocked, {report['not_run']} not run"
    )
    return 1 if args.strict and report["status"] != "verified" else 0


if __name__ == "__main__":
    raise SystemExit(main())
