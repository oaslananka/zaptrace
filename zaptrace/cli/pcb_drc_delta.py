"""One command to compare original and proposed KiCad PCB using native DRC."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import click

from zaptrace.kicad.pcb_drc_review import review_native_pcb_drc_delta


@click.command("pcb-drc-delta")
@click.argument("original", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("candidate", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable independent native evidence")
@click.option(
    "--electrical-checks",
    is_flag=True,
    help="Also compare native schematic-PCB parity and ERC before and after",
)
@click.option(
    "--candidate-schematic",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Optional proposed top-level .kicad_sch; requires --electrical-checks",
)
def pcb_drc_delta(
    original: Path,
    candidate: Path,
    as_json: bool,
    electrical_checks: bool,
    candidate_schematic: Path | None,
) -> None:
    """Compare an original board and AI candidate; do not modify either.

    Native KiCad 10 compares DRC violations and unconnected items with
    the exact original .kicad_pro settings. New violations cause exit 2.
    No regression is NOT full DRC/ERC, schematic or fabrication approval.
    """
    try:
        project = original.with_suffix(".kicad_pro")
        if not project.is_file():
            raise ValueError("A matching original .kicad_pro is required")
        if candidate_schematic is not None and not electrical_checks:
            raise ValueError("--candidate-schematic requires --electrical-checks")
        original_schematic = original.with_suffix(".kicad_sch")
        if electrical_checks and not original_schematic.is_file():
            raise ValueError("Electrical review requires a matching original .kicad_sch")
        result = review_native_pcb_drc_delta(
            original,
            candidate,
            expected_original_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
            expected_candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
            expected_project_sha256=hashlib.sha256(project.read_bytes()).hexdigest(),
            include_electrical_checks=electrical_checks,
            expected_original_schematic_sha256=(
                hashlib.sha256(original_schematic.read_bytes()).hexdigest() if electrical_checks else None
            ),
            candidate_schematic=candidate_schematic,
            expected_candidate_schematic_sha256=(
                hashlib.sha256(candidate_schematic.read_bytes()).hexdigest()
                if candidate_schematic is not None
                else None
            ),
        )
    except (ValueError, RuntimeError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        click.echo(
            f"KiCad {result.native_kicad_version} PCB DRC: baseline {result.baseline_violations} violations "
            f"/ {result.baseline_unconnected_items} unconnected; candidate {result.candidate_violations} "
            f"violations / {result.candidate_unconnected_items} unconnected."
        )
        click.echo(
            f"New violations: {result.new_violations}; new unconnected: {result.new_unconnected_items}; "
            f"details: {result.new_violation_types}."
        )
        if result.electrical_review is not None:
            e = result.electrical_review
            click.echo(
                f"Schematic-PCB parity: {e.baseline_schematic_parity_issues} existing, "
                f"{e.candidate_schematic_parity_issues} candidate, {e.new_schematic_parity_issues} new; "
                f"ERC: {e.baseline_erc_violations} existing, {e.candidate_erc_violations} candidate, "
                f"{e.new_erc_violations} new."
            )
        click.echo("No original or candidate files changed. NOT ERC/DRC clean or manufacturing approval.")
    if not result.no_review_regression:
        raise click.exceptions.Exit(2)
