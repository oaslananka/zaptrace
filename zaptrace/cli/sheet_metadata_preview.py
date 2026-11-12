"""Single-command source-safe KiCad sheet page/title/revision review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import click

from zaptrace.cli.netclass_preview import _save_review_folder
from zaptrace.kicad.sheet_metadata_edit import preview_native_sheet_metadata


@click.command("sheet-metadata-preview")
@click.argument("schematic", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--field", type=click.Choice(["paper", "title", "rev"]), required=True)
@click.option("--expected-value", required=True, help="Exact current original KiCad field value")
@click.option("--new-value", required=True, help="New requested page/title/revision field value")
@click.option("--output-dir", type=click.Path(path_type=Path), default=None, help="New, separate review directory")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable independent KiCad evidence")
def sheet_metadata_preview(
    schematic: Path,
    field: str,
    expected_value: str,
    new_value: str,
    output_dir: Path | None,
    as_json: bool,
) -> None:
    """Prove one metadata change without modifying the original KiCad project.

    By default the operation is read-only: no file is saved. Optional
    --output-dir must be a NEW directory; only review.kicad_sch and a
    byte-identical matching review.kicad_pro are created there. Requires
    native KiCad 10 netlist/erc parity; no PCB/DRC or fabrication approval.
    """
    try:
        project_path = schematic.with_suffix(".kicad_pro")
        if not project_path.is_file():
            raise ValueError("Matching KiCad .kicad_pro project file is required")
        if output_dir is not None:
            if output_dir.exists():
                raise ValueError("Review output directory already exists; choose a new --output-dir")
            if not output_dir.parent.is_dir():
                raise ValueError("Review output parent directory does not exist")

        original = schematic.read_bytes()
        project = project_path.read_bytes()
        review = preview_native_sheet_metadata(
            schematic,
            field,
            expected_value,
            new_value,
            expected_source_sha256=hashlib.sha256(original).hexdigest(),
            expected_project_sha256=hashlib.sha256(project).hexdigest(),
        )
        if output_dir is not None:
            _save_review_folder(output_dir, review.edited_source_bytes, project)
        result = review.to_dict()
        if output_dir is not None:
            result["draft_directory"] = str(output_dir)
    except (ValueError, OSError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        click.echo(
            f"Native KiCad verified {field}: {expected_value!r} -> {new_value!r}; "
            f"{review.native_net_count} named nets / {review.native_pin_node_count} pin nodes unchanged"
        )
        click.echo(f"ERC findings unchanged ({review.native_erc_findings} existing); PCB/DRC NOT VERIFIED.")
        if output_dir is None:
            click.echo("Read-only preview: no original source files modified.")
        else:
            click.echo(f"New isolated review copy created at {output_dir}")
