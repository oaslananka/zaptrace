"""Exports agent tool implementations."""

from __future__ import annotations

from .deps import (
    Any,
    export_kicad_schematic,
    export_spice_netlist,
    generate_bom_csv,
    generate_bom_json,
    generate_report,
    render_schematic_svg,
)
from .runtime import _get_session, _require_release_gate, _validate_path


def tool_export_bom_csv(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Generate Bill of Materials as CSV."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    csv_str = generate_bom_csv(design)
    return {"csv": csv_str, "design": design_name}


def tool_export_bom_json(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Generate Bill of Materials as JSON."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    json_str = generate_bom_json(design)
    return {"json": json_str, "design": design_name}


def tool_export_report(design_name: str, output_path: str | None = None, session_id: str = "default") -> dict[str, Any]:
    """Generate a comprehensive Markdown design report."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    erc_result = session.get("erc_results", {}).get(design_name)
    report = generate_report(design, erc_result=erc_result)
    if output_path:
        out = _validate_path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    return {"report": report, "design": design_name}


def tool_export_svg(design_name: str, output_path: str | None = None, session_id: str = "default") -> dict[str, Any]:
    """Render a schematic overview as SVG."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    positions = session.get("positions", {}).get(design_name)
    svg = render_schematic_svg(design, positions=positions)
    if output_path:
        out = _validate_path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(svg, encoding="utf-8")
    return {"svg": svg, "design": design_name}


def tool_export_kicad(
    design_name: str,
    output_dir: str,
    approval_id: str | None = None,
    fab_profile_skip_reason: str | None = None,
    fab_profile_skip_approval_id: str | None = None,
    risky_package_reviewed: bool = False,
    risky_package_approval_id: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Export to KiCad schematic + PCB format."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    out = _validate_path(output_dir)
    release_gate = _require_release_gate(
        session,
        design_name,
        approval_id,
        session_id=session_id,
        fab_profile_skip_reason=fab_profile_skip_reason,
        fab_profile_skip_approval_id=fab_profile_skip_approval_id,
        risky_package_reviewed=risky_package_reviewed,
        risky_package_approval_id=risky_package_approval_id,
    )
    files = export_kicad_schematic(design, out)
    return {
        "design": design_name,
        "output_dir": str(out),
        "files": {k: str(v) for k, v in files.items()},
        "release_gate": release_gate,
    }


def tool_export_gerber(
    design_name: str,
    output_dir: str | None = None,
    approval_id: str | None = None,
    fab_profile_skip_reason: str | None = None,
    fab_profile_skip_approval_id: str | None = None,
    risky_package_reviewed: bool = False,
    risky_package_approval_id: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Generate Gerber RS-274X files for a design."""
    from zaptrace.export.gerber import generate_gerber

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    out_path = _validate_path(output_dir) if output_dir else None
    release_gate = _require_release_gate(
        session,
        design_name,
        approval_id,
        session_id=session_id,
        fab_profile_skip_reason=fab_profile_skip_reason,
        fab_profile_skip_approval_id=fab_profile_skip_approval_id,
        risky_package_reviewed=risky_package_reviewed,
        risky_package_approval_id=risky_package_approval_id,
    )
    result = generate_gerber(design, output_dir=out_path) if out_path else generate_gerber(design)
    return {
        "design": design_name,
        "layers": list(result.keys()),
        "files": {k: str(v) for k, v in result.items()} if output_dir else result,
        "release_gate": release_gate,
    }


def tool_export_excellon(
    design_name: str,
    output_dir: str | None = None,
    approval_id: str | None = None,
    fab_profile_skip_reason: str | None = None,
    fab_profile_skip_approval_id: str | None = None,
    risky_package_reviewed: bool = False,
    risky_package_approval_id: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Generate Excellon drill files for a design."""
    from zaptrace.export.excellon import generate_composite_drill, generate_excellon

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    out = _validate_path(output_dir) if output_dir else None
    release_gate = _require_release_gate(
        session,
        design_name,
        approval_id,
        session_id=session_id,
        fab_profile_skip_reason=fab_profile_skip_reason,
        fab_profile_skip_approval_id=fab_profile_skip_approval_id,
        risky_package_reviewed=risky_package_reviewed,
        risky_package_approval_id=risky_package_approval_id,
    )
    if out:
        files = generate_excellon(design, output_dir=out)
        return {
            "design": design_name,
            "files": {k: str(v) for k, v in files.items()},
            "release_gate": release_gate,
        }
    drill = generate_composite_drill(design)
    return {"design": design_name, "drill": drill, "release_gate": release_gate}


def tool_export_manufacturing(
    design_name: str,
    output_dir: str,
    approval_id: str | None = None,
    fab_profile_skip_reason: str | None = None,
    fab_profile_skip_approval_id: str | None = None,
    risky_package_reviewed: bool = False,
    risky_package_approval_id: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Generate a complete manufacturing package (Gerber + drill + BOM + PnP + ZIP)."""
    from zaptrace.export.manufacturing import generate_manufacturing_bundle

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    out_dir = _validate_path(output_dir)
    release_gate = _require_release_gate(
        session,
        design_name,
        approval_id,
        session_id=session_id,
        fab_profile_skip_reason=fab_profile_skip_reason,
        fab_profile_skip_approval_id=fab_profile_skip_approval_id,
        risky_package_reviewed=risky_package_reviewed,
        risky_package_approval_id=risky_package_approval_id,
    )
    policy = release_gate["fab_profile_policy"]
    result = generate_manufacturing_bundle(
        design,
        str(out_dir),
        prefix=design_name,
        fab_profile=str(policy.get("fab_profile") or "") or None,
        approved_dfm_skip_reason=str(policy.get("skip_reason") or ""),
        approved_dfm_skip_id=str(policy.get("skip_approval_id") or ""),
    )
    from zaptrace.fab.readiness import require_dfm_release_ready

    require_dfm_release_ready(
        str(result.get("dfm_readiness_status") or ""),
        report_path=str(result.get("dfm_readiness") or ""),
    )
    return {
        "design": design_name,
        "output_dir": output_dir,
        "release_gate": release_gate,
        "gerber_layers": list(result.get("gerber_layers", {}).keys()),
        "bom": result.get("bom", ""),
        "pick_and_place": result.get("pick_and_place", ""),
        "manifest": result.get("manifest", ""),
        "dfm_readiness": result.get("dfm_readiness", ""),
        "dfm_readiness_status": result.get("dfm_readiness_status", "human-review-required"),
        "zip": result.get("zip", ""),
    }


def tool_export_pick_and_place(
    design_name: str,
    approval_id: str | None = None,
    fab_profile_skip_reason: str | None = None,
    fab_profile_skip_approval_id: str | None = None,
    risky_package_reviewed: bool = False,
    risky_package_approval_id: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Generate a pick-and-place (centroid) CSV for a design."""
    from zaptrace.export.manufacturing import generate_pick_and_place

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    release_gate = _require_release_gate(
        session,
        design_name,
        approval_id,
        session_id=session_id,
        fab_profile_skip_reason=fab_profile_skip_reason,
        fab_profile_skip_approval_id=fab_profile_skip_approval_id,
        risky_package_reviewed=risky_package_reviewed,
        risky_package_approval_id=risky_package_approval_id,
    )
    csv = generate_pick_and_place(design)
    return {
        "csv": csv,
        "design": design_name,
        "count": csv.count("\n") - 1,
        "release_gate": release_gate,
    }


def tool_export_spice(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Export a session design as a SPICE netlist string (foundation for simulation)."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    netlist = export_spice_netlist(design)
    unsupported = sum(1 for line in netlist.splitlines() if line.startswith("* Unsupported:"))
    return {"design": design_name, "netlist": netlist, "unsupported_count": unsupported}


__all__ = [
    "tool_export_bom_csv",
    "tool_export_bom_json",
    "tool_export_report",
    "tool_export_svg",
    "tool_export_kicad",
    "tool_export_gerber",
    "tool_export_excellon",
    "tool_export_manufacturing",
    "tool_export_pick_and_place",
    "tool_export_spice",
]
