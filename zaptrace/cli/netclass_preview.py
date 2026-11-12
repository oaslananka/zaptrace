"""User-first KiCad netclass preview: native proof, optional non-destructive copy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import click

from zaptrace.kicad.netclass_edit import preview_native_netclass_reassignment
from zaptrace.kicad.schematic_importer import import_kicad_schematic


def _find_unique_flag(schematic: Path, from_class: str, flag_uuid: str | None) -> str:
    result = import_kicad_schematic(schematic)
    snapshot = result.source_snapshot
    if snapshot is None:
        raise ValueError("No original KiCad schematic source is available")

    matched: list[str] = []
    for flag in snapshot.nodes("netclass_flag"):
        properties = [
            item for item in flag if isinstance(item, list) and item[:3] == ["property", "Netclass", from_class]
        ]
        uuids = [item for item in flag if isinstance(item, list) and len(item) == 2 and item[0] == "uuid"]
        if len(properties) == 1 and len(uuids) == 1:
            matched.append(str(uuids[0][1]))

    if flag_uuid is not None:
        if flag_uuid not in matched:
            raise ValueError("No netclass directive matches --flag-uuid and --from-class")
        return flag_uuid
    if not matched:
        raise ValueError(f"No netclass directive matches class {from_class!r}")
    if len(matched) != 1:
        raise ValueError(f"Multiple netclass directives match {from_class!r}; use --flag-uuid to select one explicitly")
    return matched[0]


def _save_review_folder(destination: Path, edited_source_bytes: bytes, original_project: bytes) -> None:
    """Only create a new isolated review folder; never replace existing files."""
    if destination.exists():
        raise ValueError("Review output directory already exists; choose a new --output-dir")
    if not destination.parent.is_dir():
        raise ValueError("Review output parent directory does not exist")

    destination.mkdir(mode=0o700, exist_ok=False)
    created: list[Path] = []
    try:
        for filename, contents in (
            ("review.kicad_sch", edited_source_bytes),
            ("review.kicad_pro", original_project),
        ):
            artifact = destination / filename
            with artifact.open("xb") as target:
                target.write(contents)
            created.append(artifact)
    except OSError:
        for artifact in created:
            artifact.unlink(missing_ok=True)
        destination.rmdir()
        raise


@click.command("netclass-preview")
@click.argument("schematic", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--from-class", required=True, help="Existing netclass label on one schematic directive")
@click.option("--to-class", required=True, help="New netclass already defined in the sibling .kicad_pro")
@click.option("--flag-uuid", default=None, help="Select the exact directive if several use the old class")
@click.option(
    "--output-dir", type=click.Path(path_type=Path), default=None, help="New, empty review folder (never overwrite)"
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON proof summary")
def netclass_preview(
    schematic: Path,
    from_class: str,
    to_class: str,
    flag_uuid: str | None,
    output_dir: Path | None,
    as_json: bool,
) -> None:
    """Verify one native netclass edit; leave original schematic and PCB untouched.

    By default this is read-only. --output-dir creates a separate review
    copy of the schematic and project, never modifying an existing design.
    ERC findings remain unchanged; this is not PCB/DRC or hardware signoff.
    """
    try:
        project = schematic.with_suffix(".kicad_pro")
        if not project.is_file():
            raise ValueError("Matching .kicad_pro project file is required")
        if output_dir is not None:
            if output_dir.exists():
                raise ValueError("Review output directory already exists; choose a new --output-dir")
            if not output_dir.parent.is_dir():
                raise ValueError("Review output parent directory does not exist")

        selected_uuid = _find_unique_flag(schematic, from_class, flag_uuid)
        source_sha = hashlib.sha256(schematic.read_bytes()).hexdigest()
        project_bytes = project.read_bytes()
        review = preview_native_netclass_reassignment(
            schematic,
            selected_uuid,
            from_class,
            to_class,
            expected_source_sha256=source_sha,
            expected_project_sha256=hashlib.sha256(project_bytes).hexdigest(),
        )
        if output_dir is not None:
            _save_review_folder(output_dir, review.edited_source_bytes, project_bytes)
        result = {
            **review.to_dict(),
            "source_was_modified": False,
            "pcb_drc_verified": False,
        }
        if output_dir is not None:
            result["draft_directory"] = str(output_dir)
    except (ValueError, RuntimeError, OSError) as error:
        raise click.ClickException(str(error)) from error

    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        click.echo(
            f"Native KiCad verified {result['net_name']}: "
            f"{from_class} -> {to_class}; "
            f"{result['native_net_count']} nets, {result['native_pin_node_count']} pins unchanged."
        )
        click.echo(f"ERC findings unchanged ({result['baseline_erc_findings']} existing); PCB/DRC NOT VERIFIED.")
        if output_dir is not None:
            click.echo(f"Separate review copy created at {output_dir}")
        else:
            click.echo("Read-only preview: original schematic and project unchanged.")
