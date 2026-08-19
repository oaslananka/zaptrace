"""Manufacturing export — Gerber ZIP, pick-and-place, BOM, drill, and manifest.

Generates a complete, JLCPCB-ready manufacturing package from a ``Design``.
"""

from __future__ import annotations

import csv
import json
import re
import zipfile
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

from zaptrace import __version__
from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design
from zaptrace.export.bom import generate_bom_csv
from zaptrace.export.excellon import generate_composite_drill, generate_excellon
from zaptrace.export.gerber import generate_gerber, write_gerber_job_file
from zaptrace.export.ipcd356 import write_ipcd356
from zaptrace.fab.dfm import DFMChecker
from zaptrace.fab.profile import FabProfile, load_profile
from zaptrace.fab.readiness import build_dfm_readiness_report

# ---------------------------------------------------------------------------
#  Pick-and-place (centroid) CSV
# ---------------------------------------------------------------------------


def _component_side(comp: Any) -> str:
    """Determine which side of the board a component is placed on.

    Defaults to "top". THT components and components with all-layer pads
    are marked "top". Bottom-side placement is inferred from position
    heuristics or a dedicated property.
    """
    if comp.properties and comp.properties.get("side") in ("bottom", "top"):
        return comp.properties["side"]
    if comp.footprint_def:
        pads_on_bottom = sum(1 for p in comp.footprint_def.pads if p.layer.value == "bottom")
        pads_on_top = sum(1 for p in comp.footprint_def.pads if p.layer.value == "top")
        if pads_on_bottom > pads_on_top:
            return "bottom"
    return "top"


def generate_pick_and_place(design: Design) -> str:
    """Generate a pick-and-place (centroid) CSV file for SMD assembly.

    Columns:
        Ref, Value, Package, PosX (mm), PosY (mm), Rotation (deg), Side
    """
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Ref", "Value", "Package", "PosX", "PosY", "Rotation", "Side"])

    placement = design.placement or {}

    for comp in sorted(design.components.values(), key=lambda c: c.ref):
        if comp.dnp:
            continue
        pos = placement.get(comp.id)
        if pos is None and comp.position is not None:
            pos = comp.position
        if pos is None:
            continue

        x, y = pos
        rotation = 0.0
        if comp.properties:
            rotation = float(comp.properties.get("rotation", 0.0))

        pkg = comp.footprint or ""
        side = _component_side(comp)

        writer.writerow(
            [
                comp.ref,
                comp.value or "",
                pkg,
                f"{x:.3f}",
                f"{y:.3f}",
                f"{rotation:.1f}",
                side,
            ]
        )

    return output.getvalue()


# ---------------------------------------------------------------------------
#  Manufacturing manifest
# ---------------------------------------------------------------------------


def generate_manufacturing_manifest(design: Design) -> str:
    """Generate a JSON manifest describing the manufacturing output.

    Includes design metadata, layer stack, component count, net count, and
    file listing.
    """
    board = canonical_board_definition(design)
    bw = board.width
    bh = board.height
    layers = board.layers

    manifest: dict[str, Any] = {
        "design": {
            "name": design.meta.name,
            "version": design.meta.version,
            "author": design.meta.author,
            "revision": design.meta.revision,
            "description": design.meta.description,
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "board": {
            "width_mm": bw,
            "height_mm": bh,
            "layers": layers,
            "copper_pour_gnd": board.copper_pour_gnd,
        },
        "statistics": {
            "components": len(design.components),
            "nets": len(design.nets),
            "placed_components": sum(
                1 for c in design.components.values() if design.placement and c.id in design.placement
            ),
        },
        "output_files": [
            {
                "file": ".GTL",
                "layer": "Top copper",
                "description": "Top signal layer",
            },
            {
                "file": ".GBL",
                "layer": "Bottom copper",
                "description": "Bottom signal layer",
            },
            {
                "file": ".GTO",
                "layer": "Top overlay",
                "description": "Top silkscreen",
            },
            {
                "file": ".GTS",
                "layer": "Top solder mask",
                "description": "Top solder mask (green)",
            },
            {
                "file": ".GBS",
                "layer": "Bottom solder mask",
                "description": "Bottom solder mask (green)",
            },
            {
                "file": ".GKO",
                "layer": "Board outline",
                "description": "PCB edge cuts",
            },
            {
                "file": ".GPT",
                "layer": "Top paste",
                "description": "Solder paste stencil",
            },
            {
                "file": ".TXT",
                "layer": "Excellon drill",
                "description": "NC drill file (PTH + NPTH)",
            },
            {
                "file": ".IPC",
                "layer": "Manufacturing netlist",
                "description": "IPC-D-356 connectivity evidence",
            },
            {
                "file": ".GBRJOB",
                "layer": "Gerber job file",
                "description": "Machine-readable Gerber layer metadata",
            },
            {
                "file": "-dfm-readiness.json",
                "layer": "DFM readiness report",
                "description": "Manufacturer profile, assembly checks, skips, and artifact hashes",
            },
        ],
        "tool": "ZapTrace AI-EDA",
        "tool_version": __version__,
    }

    return json.dumps(manifest, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
#  Manufacturing ZIP bundle
# ---------------------------------------------------------------------------


def _resolve_fab_profile(profile: str | FabProfile | None) -> FabProfile | None:
    if isinstance(profile, FabProfile):
        return profile
    if isinstance(profile, str) and profile.strip():
        return load_profile(profile)
    return None


def _safe_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    return re.sub(r"[^\w.-]", "_", name)


def _generate_bundle_artifacts(
    design: Design,
    out: Path,
    prefix: str,
) -> tuple[dict[str, Any], dict[str, str], dict[str, str | Path], str | Path | None]:
    """Generate the non-archive manufacturing artifacts."""
    result: dict[str, Any] = {}
    gerber_files = generate_gerber(design, output_dir=str(out), prefix=prefix)
    result["gerber_layers"] = gerber_files
    result["gerber_job"] = str(write_gerber_job_file(design, gerber_files, out / f"{prefix}.gbrjob"))

    drill_files = generate_excellon(design, output_dir=str(out), prefix=prefix)
    result.update({f"drill_{kind}": path for kind, path in drill_files.items()})
    composite = generate_composite_drill(design, output_dir=str(out), prefix=prefix)
    if composite:
        result["drill_composite"] = composite

    bom_path = out / f"{prefix}-bom.csv"
    bom_path.write_text(generate_bom_csv(design), encoding="utf-8")
    result["bom"] = str(bom_path)

    pnp_path = out / f"{prefix}-pick-and-place.csv"
    pnp_path.write_text(generate_pick_and_place(design), encoding="utf-8")
    result["pick_and_place"] = str(pnp_path)

    result["ipc_d356"] = str(write_ipcd356(design, out / f"{prefix}.ipc"))
    manifest_path = out / f"{prefix}-manifest.json"
    manifest_path.write_text(generate_manufacturing_manifest(design), encoding="utf-8")
    result["manifest"] = str(manifest_path)
    return result, gerber_files, drill_files, composite


def _result_artifact_paths(result: dict[str, Any]) -> list[Path]:
    """Flatten generated result values into artifact paths for hashing."""
    paths: list[Path] = []
    for value in result.values():
        if isinstance(value, dict):
            paths.extend(Path(item) for item in value.values() if isinstance(item, (str, Path)))
        elif isinstance(value, (str, Path)):
            paths.append(Path(value))
    return paths


def _write_readiness_report(
    design: Design,
    out: Path,
    prefix: str,
    result: dict[str, Any],
    *,
    fab_profile: str | FabProfile | None,
    approved_dfm_skip_reason: str,
    approved_dfm_skip_id: str,
) -> None:
    """Build and persist the profile-bound DFM readiness report."""
    selected_profile = _resolve_fab_profile(fab_profile)
    dfm_result = DFMChecker(selected_profile).check(design) if selected_profile is not None else None
    readiness = build_dfm_readiness_report(
        design.meta.name,
        _result_artifact_paths(result),
        profile=selected_profile,
        result=dfm_result,
        approved_skip_reason=approved_dfm_skip_reason,
        approved_skip_id=approved_dfm_skip_id,
    )
    readiness_path = out / f"{prefix}-dfm-readiness.json"
    readiness_path.write_text(
        json.dumps(readiness.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result["dfm_readiness"] = str(readiness_path)
    result["dfm_readiness_status"] = readiness.status.value


def _write_manufacturing_zip(
    zip_path: Path,
    result: dict[str, Any],
    gerber_files: dict[str, str],
    drill_files: dict[str, str | Path],
    composite: str | Path | None,
) -> None:
    """Archive generated manufacturing artifacts without changing their identities."""
    archive_paths = [Path(path) for path in gerber_files.values()]
    archive_paths.extend(Path(path) for path in drill_files.values())
    if composite:
        archive_paths.append(Path(composite))
    archive_paths.extend(
        Path(result[label])
        for label in ("bom", "pick_and_place", "ipc_d356", "gerber_job", "manifest", "dfm_readiness")
    )
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in archive_paths:
            if path.exists():
                archive.write(path, arcname=path.name)


def generate_manufacturing_bundle(
    design: Design,
    output_dir: str | Path,
    prefix: str | None = None,
    *,
    fab_profile: str | FabProfile | None = None,
    approved_dfm_skip_reason: str = "",
    approved_dfm_skip_id: str = "",
) -> dict[str, Any]:
    """Generate a complete manufacturing package as individual files + ZIP.

    Args:
        design: The design to export.
        output_dir: Directory to write output files to.
        prefix: Optional filename prefix (defaults to design name).
        fab_profile: Built-in profile name or trusted profile object used for DFM readiness.
        approved_dfm_skip_reason: Human-readable rationale when a profile is intentionally skipped.
        approved_dfm_skip_id: Approval identity binding the profile skip.

    Returns:
        Dict of ``{label: file_path | content_string}``.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    safe_prefix = _safe_filename(prefix or design.meta.name or "board")
    result, gerber_files, drill_files, composite = _generate_bundle_artifacts(design, out, safe_prefix)
    _write_readiness_report(
        design,
        out,
        safe_prefix,
        result,
        fab_profile=fab_profile,
        approved_dfm_skip_reason=approved_dfm_skip_reason,
        approved_dfm_skip_id=approved_dfm_skip_id,
    )
    zip_path = out / f"{safe_prefix}.zip"
    _write_manufacturing_zip(zip_path, result, gerber_files, drill_files, composite)
    result["zip"] = str(zip_path)
    return result
