"""ZapTrace CLI — 18 commands for electronics design."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import click
import yaml

from zaptrace import __version__
from zaptrace.agent._tool_impls import (
    tool_design_diff,
    tool_design_inspect,
    tool_design_list_nets,
    tool_design_parse_file,
    tool_erc_list_rules,
    tool_erc_validate,
    tool_export_bom_csv,
    tool_export_bom_json,
    tool_export_kicad,
    tool_export_report,
    tool_export_svg,
    tool_library_get,
    tool_library_search,
    tool_list_synthesis_templates,
    tool_pipeline_run,
    tool_place_components,
    tool_proof_run,
    tool_route_nets,
    tool_synthesize_design,
)
from zaptrace.cli.output import (
    console,
    print_json,
    print_panel,
    print_summary,
    print_table,
)

_SESSION = "cli-default"


@click.group()
@click.version_option(version=__version__, prog_name="zaptrace")
def cli() -> None:
    """ZapTrace — Agent-native electronics design core."""


# ---------------------------------------------------------------------------
# 1. parse
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("path", type=click.Path(exists=True))
def parse(path: str) -> None:
    """Parse a design YAML file."""
    try:
        result = tool_design_parse_file(session_id=_SESSION, path=path)
        print_summary(True, f"Parsed: {result['design_name']}")
        print_json(result)
    except Exception as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 2. inspect
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("name")
def inspect(name: str) -> None:
    """Inspect a parsed design."""
    try:
        result = tool_design_inspect(session_id=_SESSION, design_name=name)
        print_json(result)
    except ValueError as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 3. nets
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("name")
def nets(name: str) -> None:
    """List all nets in a design."""
    try:
        result = tool_design_list_nets(session_id=_SESSION, design_name=name)
        print_json(result)
    except ValueError as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 4. synthesize
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("intent")
def synthesize(intent: str) -> None:
    """Select the best-matching pre-built template for an intent (template selection, not circuit synthesis)."""
    try:
        result = tool_synthesize_design(session_id=_SESSION, intent=intent)
        print_summary(True, f"Selected template: {result['design_name']}")
        print_json(result)
    except Exception as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 5. templates
# ---------------------------------------------------------------------------


@cli.command()
def templates() -> None:
    """List available synthesis templates."""
    result = tool_list_synthesis_templates()
    if not result:
        print_summary(False, "No templates found")
        return
    print_table(
        "Synthesis Templates",
        columns=["ID", "Name", "Description", "Tags"],
        rows=[
            [
                t.get("id", ""),
                t.get("name", ""),
                t.get("description", "")[:40],
                ", ".join(t.get("tags", [])),
            ]
            for t in result
        ],
    )


# ---------------------------------------------------------------------------
# 5b. requirements
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("intent")
@click.option(
    "--output", "-o", type=click.Path(), default=None, help="Directory for requirements.json + constraints.yaml"
)
def requirements(intent: str, output: str | None) -> None:
    """Extract machine-readable requirements + constraints from a design intent."""
    from zaptrace.synthesis.requirements import (
        classify_risk,
        freeze_requirements,
        parse_requirements,
        requirements_assumptions,
        requirements_conflicts,
        requirements_coverage,
        requirements_to_constraints,
        review_assumptions,
        write_requirements_artifacts,
    )

    if output:
        paths = write_requirements_artifacts(intent, output)
        print_summary(True, f"Wrote {paths['requirements']} and {paths['constraints']}")
    else:
        req = parse_requirements(intent)
        print_json(
            {
                "requirements": req.to_dict(),
                "constraints": requirements_to_constraints(req).model_dump(),
                "coverage": requirements_coverage(req),
                "assumptions": requirements_assumptions(req),
                "conflicts": requirements_conflicts(req),
                "freeze": freeze_requirements(req),
                "assumption_review": review_assumptions(req),
                "risk": classify_risk(req),
            }
        )


# ---------------------------------------------------------------------------
# 6. erc
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("name")
def erc(name: str) -> None:
    """Run ERC validation on a design."""
    try:
        result = tool_erc_validate(session_id=_SESSION, design_name=name)
        if result["passed"]:
            print_summary(True, f"ERC passed ({name})")
        else:
            print_summary(
                False, f"ERC failed ({name}): {result['total_errors']} errors, {result['total_warnings']} warnings"
            )
        print_json(result)
    except ValueError as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 7. erc-rules
# ---------------------------------------------------------------------------


@cli.command(name="erc-rules")
def erc_rules() -> None:
    """List all ERC rules."""
    result = tool_erc_list_rules()
    print_table(
        "ERC Rules",
        columns=["ID", "Description"],
        rows=[[r["id"], r["description"][:70]] for r in result["rules"]],
    )


# ---------------------------------------------------------------------------
# 8. place
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("name")
def place(name: str) -> None:
    """Place components on the board."""
    try:
        result = tool_place_components(session_id=_SESSION, design_name=name)
        print_summary(True, f"Placed {result['component_count']} components")
        print_json(result)
    except ValueError as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 9. route
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("name")
def route_net(name: str) -> None:
    """Route all nets."""
    try:
        result = tool_route_nets(session_id=_SESSION, design_name=name)
        print_summary(True, f"Routed {result['routed_nets']}/{result['total_nets']} nets")
        print_json(result)
    except ValueError as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 10. bom
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("name")
@click.option("--format", "-f", type=click.Choice(["csv", "json"]), default="csv")
def bom(name: str, format: str) -> None:  # noqa: A002
    """Generate Bill of Materials."""
    try:
        if format == "csv":
            result = tool_export_bom_csv(session_id=_SESSION, design_name=name)
            console.print(result["csv"])
        else:
            result = tool_export_bom_json(session_id=_SESSION, design_name=name)
            print_json(result)
    except ValueError as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 11. report
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("name")
@click.option("--output", "-o", type=click.Path(), default=None)
def report(name: str, output: str | None) -> None:
    """Generate a Markdown design report."""
    try:
        result = tool_export_report(
            session_id=_SESSION,
            design_name=name,
            output_path=output,
        )
        if output:
            print_summary(True, f"Report written to {output}")
        else:
            console.print(result["report"])
    except ValueError as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 12. svg
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("name")
@click.option("--output", "-o", type=click.Path(), default=None)
def svg(name: str, output: str | None) -> None:
    """Render a schematic overview as SVG."""
    try:
        result = tool_export_svg(
            session_id=_SESSION,
            design_name=name,
            output_path=output,
        )
        if output:
            print_summary(True, f"SVG written to {output}")
        else:
            print_panel("SVG generated", f"{len(result['svg'])} chars")
    except ValueError as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 13. kicad (group)
# ---------------------------------------------------------------------------


@cli.group()
def kicad() -> None:
    """Export designs to KiCad format and run KiCad verification via kicad-cli."""


@kicad.command()
@click.argument("name")
@click.argument("output_dir", type=click.Path())
@click.option("--approval-id", required=True, help="External release approval or gate identifier")
@click.option(
    "--fab-profile-skip-reason",
    default=None,
    help="Approved reason when no manufacturer fabrication profile applies",
)
@click.option(
    "--fab-profile-skip-approval-id",
    default=None,
    help="Approval identifier authorizing the fabrication-profile skip",
)
@click.option("--risky-package-reviewed", is_flag=True, help="Confirm explicit review of risky package footprints")
@click.option("--risky-package-approval-id", default=None, help="Approval identifier for risky package evidence")
def export(
    name: str,
    output_dir: str,
    approval_id: str,
    fab_profile_skip_reason: str | None,
    fab_profile_skip_approval_id: str | None,
    risky_package_reviewed: bool,
    risky_package_approval_id: str | None,
) -> None:
    """Export a design to KiCad schematic and PCB files."""
    try:
        result = tool_export_kicad(
            session_id=_SESSION,
            design_name=name,
            output_dir=output_dir,
            approval_id=approval_id,
            fab_profile_skip_reason=fab_profile_skip_reason,
            fab_profile_skip_approval_id=fab_profile_skip_approval_id,
            risky_package_reviewed=risky_package_reviewed,
            risky_package_approval_id=risky_package_approval_id,
        )
        print_summary(True, f"KiCad export to {result['output_dir']}")
        for kind, path in result["files"].items():
            console.print(f"  {kind}: {path}")
    except ValueError as e:
        print_summary(False, str(e))
        raise click.Abort() from e


def _print_kicad_check_result(label: str, result: Any) -> None:
    if result.error:
        print_summary(False, f"{label} error: {result.error}")
    else:
        summary = (
            f"{label}: {result.violation_count} violations "
            f"({result.error_count} errors, {result.warning_count} warnings)"
        )
        print_summary(result.violation_count == 0, summary)
    for violation in result.violations:
        console.print(f"  [dim]{violation}[/]")


@kicad.command()
@click.option("--erc", "erc_path", type=click.Path(exists=True), default=None, help="Schematic file to run ERC on")
@click.option("--drc", "drc_path", type=click.Path(exists=True), default=None, help="PCB file to run DRC on")
def oracle(erc_path: str | None, drc_path: str | None) -> None:
    """Run KiCad ERC/DRC verification via kicad-cli.

    At least one of --erc or --drc must be provided. If both are given, both
    are run and reported together. Results include violation counts per severity
    and full violation details in JSON mode.
    """
    from zaptrace.kicad.oracle import KiCadOracle

    if not erc_path and not drc_path:
        console.print("[red]Provide at least --erc <schematic> or --drc <pcb>[/]")
        raise click.Abort()

    oracle = KiCadOracle()
    if not oracle.available:
        print_summary(False, "KiCad CLI (kicad-cli) not found on PATH or known install paths")
        raise click.Abort()

    console.print(f"[dim]KiCad:[/] {oracle.version}")

    if erc_path:
        _print_kicad_check_result("ERC", oracle.run_erc(erc_path))
    if drc_path:
        _print_kicad_check_result("DRC", oracle.run_drc(drc_path))


# ---------------------------------------------------------------------------
# 14. diff
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("design_a")
@click.argument("design_b")
def diff(design_a: str, design_b: str) -> None:
    """Diff two designs."""
    try:
        result = tool_design_diff(
            session_id=_SESSION,
            design_a_name=design_a,
            design_b_name=design_b,
        )
        print_summary(True, result["summary"])
        print_json(result)
    except ValueError as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 15. library search
# ---------------------------------------------------------------------------


@cli.group()
def library() -> None:
    """Search and inspect the component library."""


@library.command()
@click.argument("query")
@click.option("--max", "-m", "max_results", type=int, default=10)
def search(query: str, max_results: int) -> None:
    """Search the component library."""
    result = tool_library_search(query=query, max_results=max_results)
    if result["count"] == 0:
        print_summary(False, "No matches found")
        return
    print_table(
        f"Library Search: {query}",
        columns=["ID", "Name", "Category", "Manufacturer", "MPN", "Package"],
        rows=[
            [
                r["id"],
                r["name"],
                r["category"],
                r["manufacturer"],
                r["mpn"],
                r["package"],
            ]
            for r in result["results"]
        ],
    )


@library.command()
@click.argument("component_id")
def get(component_id: str) -> None:
    """Get full details for a library component."""

    try:
        result = tool_library_get(component_id=component_id)
        print_json(result)
    except Exception as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 16. library get (via group) - already above
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 17. pipeline
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--source", "-s", type=click.Path(exists=True), default=None)
@click.option("--intent", "-i", default=None)
@click.option("--output", "-o", type=click.Path(), default=None)
def pipeline(source: str | None, intent: str | None, output: str | None) -> None:
    """Run the full design pipeline."""
    if not source and not intent:
        console.print("[red]Provide --source (file path) or --intent (synthesis)[/]")
        raise click.Abort()
    try:
        result = tool_pipeline_run(
            session_id=_SESSION,
            source=source,
            intent=intent,
            output_dir=output,
        )
        stages = result.get("stages", {})
        for stage_name, stage_data in stages.items():
            success = stage_data.get("success", False)
            icon = "✓" if success else "✗"
            err = stage_data.get("error")
            line = f"  [{stage_name}] {icon}"
            if err:
                line += f" — {err}"
            console.print(line)
        print_summary(
            result["all_successful"],
            f"Pipeline completed: {result['stages_completed']} stages in {result['duration_seconds']}s",
        )
    except Exception as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 18. doctor
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--strict", is_flag=True, help="Fail if required validation tools are missing")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON evidence")
@click.option("--output", type=click.Path(), default=None, help="Write JSON evidence to this path")
def doctor(strict: bool, json_output: bool, output: str | None) -> None:
    """Run system diagnostics and validation toolchain checks."""
    import platform
    import sys
    from pathlib import Path

    from scripts.ci_validation_environment import build_report, render_text, report_json

    report = build_report()
    if output:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report_json(report), encoding="utf-8")
    if json_output:
        console.print_json(report_json(report))
    else:
        console.print(f"Python: {sys.version.split()[0]}")
        console.print(f"Platform: {platform.platform()}")
        console.print(f"zaptrace version: {__version__}")
        console.print(render_text(report))
    if strict and not report["passed"]:
        raise click.Abort()


# ---------------------------------------------------------------------------
# 19. proof-pack (standalone)
# ---------------------------------------------------------------------------


def _proof_pack_checks(profile: str | None) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = [
        {"name": "footprints_exist", "type": "footprint_exists", "severity": "error"},
        {"name": "all_routed", "type": "routed", "severity": "warning"},
        {"name": "drc_clean", "type": "drc", "severity": "error", "expected_count": 0},
        {"name": "erc_clean", "type": "erc", "severity": "error", "expected_count": 0},
        {"name": "clearance_check", "type": "clearance", "severity": "warning"},
    ]
    if profile:
        checks.append({"name": "dfm_check", "type": "dfm", "severity": "error", "params": {"profile": profile}})
    return checks


def _proof_pack_manifest(design_abs: Path, profile: str | None) -> dict[str, object]:
    return {
        "version": "1.0",
        "name": design_abs.stem,
        "design_path": str(design_abs),
        "model": {"min_clearance_mm": 0.15, "min_trace_width_mm": 0.15},
        "checks": _proof_pack_checks(profile),
    }


def _render_proof_pack_result(result: dict[str, Any], *, output_format: str, verbose: bool) -> bool:
    passed = bool(result.get("passed", False))
    if output_format == "json":
        click.echo(json.dumps(result, indent=2))
        return passed

    total = result.get("total", 0)
    passed_count = result.get("passed_count", 0)
    failed_count = result.get("failed_count", 0)
    signoff = result.get("autonomous_signoff", {})
    signoff_status = signoff.get("status", "unknown") if isinstance(signoff, dict) else "unknown"
    print_summary(passed, f"Proof Pack: {result.get('name', '?')}")
    print_summary(passed, f"Checks: {passed_count}/{total} passed, {failed_count} failed")
    print_summary(signoff_status == "autonomous-pass", f"Autonomous status: {signoff_status}")
    result_items = result.get("results")
    if verbose and isinstance(result_items, list):
        for item in result_items:
            if not isinstance(item, dict):
                continue
            icon = "✓" if item.get("status") == "pass" else "✗"
            console.print(f"  {icon} {item.get('name', '?')}: {item.get('message', '')}")
    return passed


def _write_proof_pack_bundle(
    output: str,
    proof_data: dict[str, object],
    result: dict[str, Any],
) -> Path:
    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "proof.yaml").write_text(yaml.safe_dump(proof_data), encoding="utf-8")
    (out_dir / "results.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print_summary(True, f"Proof Pack bundle written to {out_dir.resolve()}")
    return out_dir


@cli.command(name="proof-pack")
@click.argument("design_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None, help="Output directory for the proof pack bundle")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed check output")
@click.option("--format", "-f", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.option("--profile", default=None, help="Fabrication profile for DFM check (e.g. jlcpcb-2layer)")
def proof_pack(design_path: str, output: str | None, verbose: bool, output_format: str, profile: str | None) -> None:
    """Build a Proof Pack from a design YAML file — run all checks and optionally export the bundle.

    DESIGN_PATH is the path to a design YAML file.
    """
    design_abs = Path(design_path).resolve()
    tmp_dir = Path.cwd().resolve() / ".zaptrace" / "tmp" / f"proof-{design_abs.stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    proof_yaml = tmp_dir / "proof.yaml"
    proof_data = _proof_pack_manifest(design_abs, profile)
    proof_yaml.write_text(yaml.safe_dump(proof_data), encoding="utf-8")

    try:
        result = tool_proof_run(path=str(proof_yaml))
        passed = _render_proof_pack_result(result, output_format=output_format, verbose=verbose)
        if output:
            _write_proof_pack_bundle(output, proof_data, result)
        if not passed:
            raise SystemExit(1)
    except FileNotFoundError as e:
        print_summary(False, str(e))
        raise click.Abort() from e
    except Exception as e:
        print_summary(False, f"Proof Pack failed: {e}")
        raise click.Abort() from e
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# -------------------------------------------

# ---------------------------------------------------------------------------
# 20. proof group (run, list, info)
# ---------------------------------------------------------------------------


from zaptrace.cli.proof import proof as proof_group  # noqa: E402, F811

cli.add_command(proof_group)


# ---------------------------------------------------------------------------
# 21. profile group (list, show, validate)
# ---------------------------------------------------------------------------


@cli.group()
def profile() -> None:
    """List, inspect, and validate against fabrication profiles."""


@profile.command(name="list")
def profile_list() -> None:
    """List all built-in fabrication profiles."""
    from zaptrace.fab.profile import get_builtin_profile_names, load_profile

    names = get_builtin_profile_names()
    if not names:
        print_summary(False, "No built-in profiles found")
        return
    rows = []
    for name in names:
        try:
            p = load_profile(name)
            rows.append(
                [
                    p.name,
                    p.manufacturer,
                    p.description[:60],
                    f"{p.min_trace_mm}/{p.min_space_mm}",
                    f"{p.min_drill_mm}mm",
                    str(max(p.capabilities.layer_counts) if p.capabilities.layer_counts else 2),
                ]
            )
        except ValueError:
            continue
    print_table(
        "Fabrication Profiles",
        columns=["Name", "Manufacturer", "Description", "Trace/Space", "Min Drill", "Max Layers"],
        rows=rows,
    )


@profile.command(name="show")
@click.argument("profile_name")
def profile_show(profile_name: str) -> None:
    """Show full details for a fabrication profile."""
    from zaptrace.fab.profile import load_profile

    try:
        p = load_profile(profile_name)
    except ValueError as e:
        print_summary(False, str(e))
        raise click.Abort() from e

    print_panel(f"Fab Profile: {p.name}", f"[bold]{p.manufacturer}[/] — {p.description}")
    lines = [
        f"[bold]Min trace:[/]       {p.min_trace_mm}mm   [bold]Min space:[/]      {p.min_space_mm}mm",
        f"[bold]Min drill:[/]      {p.min_drill_mm}mm   [bold]Max drill:[/]      {p.max_drill_mm}mm",
        f"[bold]Min annular:[/]    {p.min_annular_ring_mm}mm   [bold]Min via hole:[/]   {p.min_via_hole_mm}mm",
        f"[bold]Board size:[/]     {p.min_board_width_mm}x{p.min_board_height_mm} — "
        f"{p.max_board_width_mm}x{p.max_board_height_mm}mm",
        f"[bold]Layer counts:[/]   {p.capabilities.layer_counts}",
        f"[bold]Copper weights:[/] {p.capabilities.copper_weights_oz}oz",
        f"[bold]Materials:[/]      {', '.join(p.capabilities.materials)}",
        f"[bold]Finishes:[/]       {', '.join(p.capabilities.surface_finishes)}",
        f"[bold]Colors:[/]         {', '.join(p.capabilities.solder_mask_colors)}",
        f"[bold]Impedance:[/]      {'Yes (±' + str(p.impedance_tolerance_pct) + '%)' if p.impedance_control else 'No'}",
        f"[bold]Castellated:[/]    {'Yes' if p.castellated_pads else 'No'}",
        f"[bold]Edge plating:[/]   {'Yes' if p.edge_plating else 'No'}",
        f"[bold]Blind/buried:[/]   {'Yes' if p.blind_buried_vias else 'No'}",
    ]
    console.print("\n".join(lines))


@profile.command(name="validate")
@click.argument("design_path", type=click.Path(exists=True))
@click.option("--profile", "-p", "profile_name", default="jlcpcb-2layer", help="Fab profile to validate against")
def profile_validate(design_path: str, profile_name: str) -> None:
    """Validate a design against a fabrication profile."""
    from pathlib import Path

    from zaptrace.core.parser import parse_file
    from zaptrace.fab.dfm import DFMChecker
    from zaptrace.fab.profile import load_profile

    try:
        profile = load_profile(profile_name)
    except ValueError as e:
        print_summary(False, str(e))
        raise click.Abort() from e

    design = parse_file(Path(design_path))
    checker = DFMChecker(profile)
    result = checker.check(design)

    if result.passed:
        print_summary(True, f"Design passed DFM validation against {profile_name}")
    else:
        print_summary(
            False,
            f"DFM: {result.errors} errors, {result.warnings} warnings against {profile_name}",
        )
    for v in result.violations:
        icon = "[red]✗[/]" if v.severity == "error" else "[yellow]⚠[/]"
        console.print(f"  {icon} [{v.rule_id}] {v.message}")
        if v.location:
            console.print(f"       Location: {v.location}")


# ---------------------------------------------------------------------------
# 22. viewer
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("design_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default="review-viewer", help="Static viewer output directory")
@click.option("--proof", "proof_path", type=click.Path(exists=True), default=None, help="Optional proof.yaml path")
def viewer(design_path: str, output: str, proof_path: str | None) -> None:
    """Generate a local static browser review viewer bundle."""
    from pathlib import Path

    from zaptrace.viewer import generate_static_viewer

    try:
        bundle = generate_static_viewer(
            Path(design_path),
            Path(output),
            proof_path=Path(proof_path) if proof_path else None,
        )
        print_summary(True, f"Static viewer written to {bundle.index_path}")
        print_json(bundle.model_dump(mode="json"))
    except Exception as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# 23. lcsc — LCSC component ingestion commands
# ---------------------------------------------------------------------------


@cli.group()
def lcsc() -> None:
    """LCSC component ingestion commands."""


@lcsc.command("ingest")
@click.argument("lcsc_id")
@click.option("--store", "store_path", type=click.Path(), default=None, help="Persistent store path (JSON)")
def lcsc_ingest(lcsc_id: str, store_path: str | None) -> None:
    """Ingest one LCSC part by identifier.

    Fetches from the LCSC/EasyEDA API (or cache) and records a governed
    provenance entry.  Use --store to persist results across runs.
    """
    from pathlib import Path

    from zaptrace.ee.imports.lcsc_ingest import LcscIngestStore, ingest_lcsc_part

    store = LcscIngestStore(path=Path(store_path) if store_path else None)
    try:
        rec = ingest_lcsc_part(lcsc_id, store=store)
        print_summary(not rec.governance_findings, f"Ingested {lcsc_id} ({rec.package_name})")
        print_json(rec.to_dict())
    except Exception as e:
        print_summary(False, str(e))
        raise click.Abort() from e


@lcsc.command("ingest-manifest")
@click.option("--store", "store_path", type=click.Path(), default=None, help="Persistent store path (JSON)")
@click.option(
    "--report", "report_path", type=click.Path(), default=None, help="Write integrity report JSON to this path"
)
@click.option("--offline", is_flag=True, default=True, help="Use offline fixture data only (default: true)")
def lcsc_ingest_manifest(store_path: str | None, report_path: str | None, offline: bool) -> None:
    """Replay the 100-part curated LCSC manifest (network-disabled by default).

    Ingests every part in the built-in fixture manifest, then produces a
    deterministic integrity report proving that all 100 entries have
    provenance, footprint proof, and pin mapping.
    """
    from pathlib import Path

    from zaptrace.ee.imports.lcsc_ingest import LcscIngestStore
    from zaptrace.ee.imports.lcsc_manifest import ingest_manifest

    store = LcscIngestStore(path=Path(store_path) if store_path else None)
    try:
        _, report = ingest_manifest(store=store)
        ok = report.passed
        print_summary(
            ok,
            f"Manifest v{report.manifest_version}: "
            f"{report.total_parts} parts, {report.clean_parts} clean, "
            f"{report.violation_count} violation(s)",
        )
        if report.violations:
            for v in report.violations[:10]:
                console.print(f"  [red]✗[/] [{v.kind}] {v.lcsc_id}: {v.detail}")
            if len(report.violations) > 10:
                console.print(f"  ... and {len(report.violations) - 10} more")
        if report_path:
            Path(report_path).write_text(report.to_json(), encoding="utf-8")
            console.print(f"  Report written to {report_path}")
        if not ok:
            raise click.Abort()
    except click.Abort:
        raise
    except Exception as e:
        print_summary(False, str(e))
        raise click.Abort() from e


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
