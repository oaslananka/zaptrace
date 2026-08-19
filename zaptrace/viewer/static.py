"""Static HTML viewer bundle for schematic, PCB, BOM, DRC/DFM markers, and proof status."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design
from zaptrace.core.parser import parse_file
from zaptrace.export.bom import generate_bom_json
from zaptrace.export.svg import render_schematic_svg


class ViewerBundle(BaseModel):
    """Generated static viewer bundle metadata."""

    model_config = ConfigDict(strict=False)

    index_path: str
    assets: dict[str, str]
    data: dict[str, str]
    non_claims: list[str] = Field(default_factory=list)


def _write_text(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _board_size(design: Design) -> tuple[float, float]:
    board = canonical_board_definition(design)
    return float(board.width), float(board.height)


def _render_pcb_svg(design: Design, *, layer: str) -> str:
    width_mm, height_mm = _board_size(design)
    scale = 8.0
    width = max(320, int(width_mm * scale) + 60)
    height = max(220, int(height_mm * scale) + 80)
    body: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg"',
        f' width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs><style>",
        ".board{fill:#14281d;stroke:#d7f5dd;stroke-width:2}",
        ".component{fill:#243b55;stroke:#d9e2ec;stroke-width:1.2;rx:4}",
        ".label{font:11px sans-serif;fill:#f8fafc}",
        ".route{stroke:#f8c471;stroke-width:2;fill:none;opacity:.85}",
        ".marker{fill:#ef4444;stroke:#fff;stroke-width:1}",
        "</style></defs>",
        f'<text class="label" x="20" y="24">{html.escape(design.meta.name)} — {layer}</text>',
        f'<rect class="board" x="30" y="40" width="{width_mm * scale:.1f}" height="{height_mm * scale:.1f}" rx="8"/>',
    ]
    placement = design.placement or {}
    for index, component in enumerate(design.components.values()):
        x_mm, y_mm = placement.get(component.id, (8 + (index % 8) * 10, 8 + (index // 8) * 10))
        x = 30 + x_mm * scale
        y = 40 + y_mm * scale
        body.append(f'<rect class="component" x="{x:.1f}" y="{y:.1f}" width="42" height="24"/>')
        body.append(f'<text class="label" x="{x + 5:.1f}" y="{y + 16:.1f}">{html.escape(component.ref)}</text>')
    if design.routing:
        for trace in design.routing.traces:
            if getattr(trace, "layer", layer) != layer:
                continue
            x1 = 30 + float(trace.start[0]) * scale
            y1 = 40 + float(trace.start[1]) * scale
            x2 = 30 + float(trace.end[0]) * scale
            y2 = 40 + float(trace.end[1]) * scale
            body.append(f'<path class="route" d="M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}"/>')
    for marker in _validation_markers(design):
        loc = marker.get("location") or {}
        if isinstance(loc, dict):
            x = 30 + float(loc.get("x", 2.0)) * scale
            y = 40 + float(loc.get("y", 2.0)) * scale
            body.append(
                f'<circle class="marker" cx="{x:.1f}" cy="{y:.1f}" r="5">'
                f"<title>{html.escape(marker['message'])}</title></circle>"
            )
    body.append("</svg>")
    return "\n".join(body)


def _validation_markers(design: Design) -> list[dict[str, Any]]:
    result = design.drc_result
    if result is None:
        return []
    markers: list[dict[str, Any]] = []
    for violation in result.violations:
        payload = violation.model_dump(mode="json") if hasattr(violation, "model_dump") else dict(violation)
        markers.append(
            {
                "severity": payload.get("severity", "warning"),
                "message": payload.get("message", "validation marker"),
                "location": payload.get("location"),
            }
        )
    return markers


def _load_proof_summary(proof_path: Path | None) -> dict[str, Any]:
    if proof_path is None:
        return {"present": False, "status": "missing", "checks": []}
    if not proof_path.exists():
        return {"present": False, "status": "missing", "path": str(proof_path), "checks": []}
    raw = yaml.safe_load(proof_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"present": False, "status": "invalid", "path": str(proof_path), "checks": []}
    checks = raw.get("checks", [])
    return {
        "present": True,
        "status": "declared",
        "path": str(proof_path),
        "name": raw.get("name", ""),
        "check_count": len(checks) if isinstance(checks, list) else 0,
        "checks": checks if isinstance(checks, list) else [],
    }


def _viewer_manifest(design: Design, proof_summary: dict[str, Any]) -> dict[str, Any]:
    bom = json.loads(generate_bom_json(design))
    board = canonical_board_definition(design)
    return {
        "schema_version": "1.0",
        "viewer": "zaptrace-static-review-viewer",
        "design": {
            "name": design.meta.name,
            "component_count": len(design.components),
            "net_count": len(design.nets),
            "board": {
                "width_mm": board.width,
                "height_mm": board.height,
                "layers": board.layers,
            },
        },
        "panels": ["schematic", "pcb-top", "pcb-bottom", "validation-markers", "bom", "proof-pack"],
        "validation_markers": _validation_markers(design),
        "bom_summary": {"item_count": len(bom.get("items", [])), "items": bom.get("items", [])},
        "proof_pack": proof_summary,
        "non_claims": [
            "static local review artifact, not cloud upload",
            "viewer is inspection-only and does not mutate designs",
            "human review remains required before fabrication",
        ],
    }


def _render_index(design: Design, manifest: dict[str, Any]) -> str:
    bom_rows = "".join(
        f"<tr><td>{html.escape(str(item.get('ref', '')))}</td><td>{html.escape(str(item.get('value', '')))}</td>"
        f"<td>{html.escape(str(item.get('footprint', '')))}</td><td>{html.escape(str(item.get('flags', '')))}</td></tr>"
        for item in manifest["bom_summary"]["items"]
    )
    markers = manifest["validation_markers"]
    marker_rows = (
        "".join(
            f"<li><strong>{html.escape(str(item.get('severity')))}</strong>: "
            f"{html.escape(str(item.get('message')))}</li>"
            for item in markers
        )
        or "<li>No DRC/DFM markers recorded in this design.</li>"
    )
    proof = manifest["proof_pack"]
    proof_text = f"{html.escape(str(proof.get('status')))} — {proof.get('check_count', 0)} checks"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ZapTrace Review Viewer — {html.escape(design.meta.name)}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; background: #0f172a; color: #e2e8f0; }}
    header {{ padding: 1.25rem 1.5rem; background: #111827; border-bottom: 1px solid #334155; }}
    main {{ display: grid; gap: 1rem; padding: 1rem; }}
    section {{ background: #111827; border: 1px solid #334155; border-radius: 12px; padding: 1rem; }}
    iframe {{ width: 100%; height: 420px; border: 1px solid #334155; background: white; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td, th {{ border-bottom: 1px solid #334155; padding: .45rem; text-align: left; }}
    code {{ color: #93c5fd; }}
  </style>
</head>
<body>
<header>
  <h1>ZapTrace Review Viewer</h1>
  <p><code>{html.escape(design.meta.name)}</code> — {len(design.components)} components, {len(design.nets)} nets</p>
</header>
<main>
  <section><h2>Schematic</h2><iframe src="assets/schematic.svg" title="Schematic SVG"></iframe></section>
  <section><h2>PCB Top Copper</h2><iframe src="assets/pcb-top.svg" title="PCB top layer"></iframe></section>
  <section><h2>PCB Bottom Copper</h2><iframe src="assets/pcb-bottom.svg" title="PCB bottom layer"></iframe></section>
  <section><h2>DRC/DFM markers</h2><ul>{marker_rows}</ul></section>
  <section><h2>BOM summary</h2>
    <table><thead><tr><th>Ref</th><th>Value</th><th>Footprint</th><th>Flags</th></tr></thead>
    <tbody>{bom_rows}</tbody></table>
  </section>
  <section><h2>Proof-pack status</h2><p>{proof_text}</p>
    <p>Manifest: <code>{html.escape(str(proof.get("path", "not provided")))}</code></p>
  </section>
  <section><h2>Manifest</h2><p><a href="data/viewer-manifest.json">Open viewer-manifest.json</a></p></section>
</main>
</body>
</html>
"""


def generate_static_viewer(
    design: Design | Path | str, output_dir: Path | str, *, proof_path: Path | str | None = None
) -> ViewerBundle:
    """Generate a local static browser viewer bundle for a design/proof-pack pair."""
    design_obj = parse_file(Path(design)) if isinstance(design, (str, Path)) else design
    out = Path(output_dir)
    proof = Path(proof_path) if proof_path is not None else None
    proof_summary = _load_proof_summary(proof)
    manifest = _viewer_manifest(design_obj, proof_summary)

    assets = {
        "schematic": _write_text(out / "assets" / "schematic.svg", render_schematic_svg(design_obj)),
        "pcb_top": _write_text(out / "assets" / "pcb-top.svg", _render_pcb_svg(design_obj, layer="F.Cu")),
        "pcb_bottom": _write_text(out / "assets" / "pcb-bottom.svg", _render_pcb_svg(design_obj, layer="B.Cu")),
    }
    data = {
        "bom": _write_text(
            out / "data" / "bom.json", json.dumps(json.loads(generate_bom_json(design_obj)), indent=2) + "\n"
        ),
        "proof": _write_text(out / "data" / "proof-summary.json", json.dumps(proof_summary, indent=2) + "\n"),
        "manifest": _write_text(out / "data" / "viewer-manifest.json", json.dumps(manifest, indent=2) + "\n"),
    }
    index_path = _write_text(out / "index.html", _render_index(design_obj, manifest))
    return ViewerBundle(index_path=index_path, assets=assets, data=data, non_claims=manifest["non_claims"])
