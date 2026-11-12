"""Generate a KiCad resistor/capacitor value ECO draft with native checks."""

from __future__ import annotations

import json
from pathlib import Path

import click

from zaptrace.kicad.passive_eco_preview import preview_passive_value_eco


@click.command("passive-eco-preview")
@click.argument("original_board", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--reference", required=True, help="Unique generic KiCad passive reference, e.g. R1")
@click.option("--from-value", "old_value", required=True, help="Exact current schematic and PCB value")
@click.option("--to-value", "new_value", required=True, help="Requested new source component value")
@click.option("--output-dir", required=True, type=click.Path(path_type=Path), help="New, non-existing draft directory")
@click.option("--json", "as_json", is_flag=True, help="Return structured source and native KiCad evidence")
def passive_eco_preview(
    original_board: Path,
    reference: str,
    old_value: str,
    new_value: str,
    output_dir: Path,
    as_json: bool,
) -> None:
    """Prepare a guarded native-reviewed KiCad ECO; not engineering signoff."""
    try:
        report = preview_passive_value_eco(original_board, reference, old_value, new_value, output_dir)
    except (ValueError, OSError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        click.echo(f"Created source-preserving KiCad ECO draft (not approved) at: {output_dir}")
        click.echo(
            f"{reference}: {old_value} -> {new_value}; native KiCad {report['native_kicad_version']} "
            "DRC/ERC/parity added 0 defects."
        )
        native = report["native_review"]
        if not isinstance(native, dict):
            raise click.ClickException("Missing native KiCad review evidence")
        electrical = native["electrical_review"]
        if not isinstance(electrical, dict):
            raise click.ClickException("Missing native electrical evidence")
        drc = int(native["candidate_violations"])
        unconnected = int(native["candidate_unconnected_items"])
        erc = int(electrical["candidate_erc_violations"])
        parity = int(electrical["candidate_schematic_parity_issues"])
        click.echo(
            f"Candidate has {drc} DRC, {unconnected} unconnected, {erc} ERC, "
            f"{parity} unresolved schematic-PCB parity findings."
        )
        parity_types = electrical["candidate_schematic_parity_types"]
        if not isinstance(parity_types, dict):
            raise click.ClickException("Missing KiCad parity type evidence")
        if parity_types:
            kinds = ", ".join(f"{kind}: {count}" for kind, count in sorted(parity_types.items()))
            click.echo(f"Remaining parity finding types: {kinds}.")
        if any((drc, unconnected, erc, parity)):
            click.echo("NOT electrically clean: the existing findings still require investigation.")
        else:
            click.echo("0 remaining native KiCad findings. Functional and component evidence are still missing.")
        click.echo("Human engineering and functional review REQUIRED. Manufacturing NOT approved.")
