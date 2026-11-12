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
        click.echo(f"Created reviewed KiCad ECO draft at: {output_dir}")
        click.echo(
            f"{reference}: {old_value} -> {new_value}; native KiCad {report['native_kicad_version']} "
            "DRC/ERC/parity added 0 defects."
        )
        click.echo("Human engineering and functional review REQUIRED. Manufacturing NOT approved.")
