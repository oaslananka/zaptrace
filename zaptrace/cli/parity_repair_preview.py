"""An explicitly mapped source-pinned KiCad parity draft, never engineering approval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from zaptrace.kicad.parity_repair_preview import preview_parity_repair


def _mapping(text: str) -> tuple[str, str]:
    if "=" not in text:
        raise click.BadParameter("Expected OLD=NEW")
    before, after = text.split("=", 1)
    return before, after


@click.command("parity-repair-preview")
@click.argument("original_board", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--reference-map", multiple=True, help="Exact PCB test point alias=schematic TPn")
@click.option("--net-map", multiple=True, help="Exact board net=schematic label, no net merges")
@click.option("--output-dir", required=True, type=click.Path(path_type=Path), help="New, nonexisting draft directory")
@click.option("--json", "as_json", is_flag=True, help="Structured KiCad source and evidence JSON")
def parity_repair_preview(
    original_board: Path,
    reference_map: tuple[str, ...],
    net_map: tuple[str, ...],
    output_dir: Path,
    as_json: bool,
) -> None:
    """Create separate native-checked PCB reference and net-label proposal."""
    try:
        report = preview_parity_repair(
            original_board,
            output_dir,
            reference_mappings=[_mapping(item) for item in reference_map],
            net_mappings=[_mapping(item) for item in net_map],
        )
    except (ValueError, RuntimeError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return
    review: Any = report["native_review"]
    electrical: Any = review["electrical_review"]
    click.echo(f"KiCad {report['native_kicad_version']} unapproved draft at: {output_dir}")
    click.echo(
        f"Schematic-PCB parity: {electrical['baseline_schematic_parity_issues']} -> "
        f"{electrical['candidate_schematic_parity_issues']}; "
        f"PCB DRC: {review['baseline_violations']} -> {review['candidate_violations']}"
    )
    if reference_map:
        click.echo("PCB Reference text on silkscreen changes; physical legibility review REQUIRED.")
    else:
        click.echo("No PCB Reference text change requested; physical validation still REQUIRED.")
    click.echo("Human engineering review REQUIRED. Manufacturing NOT approved.")
