"""Interactive browser viewer for ZapTrace designs.

Generates a self-contained HTML bundle with:
- Pan/zoom via pointer events and CSS transforms
- Layer visibility toggles (F.Cu, B.Cu, silkscreen, mask, drill)
- Component hover/click inspection (ref, value, footprint, pins, nets)
- Net highlight (click net → all connected traces highlight)
- DRC/ERC marker click → violation detail popup
- Component/net search bar
- Dark/light theme toggle
- Board measurement tool (click two points → mm distance)
- BOM table with sortable headers
- Proof-pack status summary

The bundle is a single index.html plus a viewer-data.json sidecar,
portable to any static HTTP server or local file:// open.
"""

# ruff: noqa: E501

from __future__ import annotations

import contextlib
import html
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design
from zaptrace.core.parser import parse_file
from zaptrace.export.bom import generate_bom_json

# ---------------------------------------------------------------------------
# Data bundle model
# ---------------------------------------------------------------------------


class ViewerComponent(BaseModel):
    """Serialized component for viewer JSON."""

    model_config = ConfigDict(strict=False)

    id: str
    ref: str
    type: str
    value: str
    footprint: str
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    layer: str = "F.Cu"
    pins: list[dict[str, Any]] = Field(default_factory=list)
    mpn: str = ""
    manufacturer: str = ""
    dnp: bool = False


class ViewerNet(BaseModel):
    """Serialized net for viewer JSON."""

    model_config = ConfigDict(strict=False)

    id: str
    name: str
    type: str = "signal"
    net_class: str = ""
    nodes: list[dict[str, str]] = Field(default_factory=list)


class ViewerTrace(BaseModel):
    """Serialized trace segment for viewer JSON."""

    model_config = ConfigDict(strict=False)

    start_x: float
    start_y: float
    end_x: float
    end_y: float
    width: float = 0.2
    layer: str = "F.Cu"
    net_id: str = ""


class ViewerVia(BaseModel):
    """Serialized via for viewer JSON."""

    model_config = ConfigDict(strict=False)

    x: float
    y: float
    diameter: float = 0.45
    drill: float = 0.2
    net_id: str = ""


class ViewerViolation(BaseModel):
    """Serialized DRC/ERC violation for viewer JSON."""

    model_config = ConfigDict(strict=False)

    rule_id: str = ""
    severity: str = "warning"
    message: str = ""
    x: float | None = None
    y: float | None = None
    net_id: str | None = None
    component_ref: str | None = None


class ViewerBoard(BaseModel):
    """Board geometry for viewer JSON."""

    model_config = ConfigDict(strict=False)

    width_mm: float = 100.0
    height_mm: float = 80.0
    layers: int = 2
    outline: list[tuple[float, float]] = Field(default_factory=list)


class InteractiveViewerBundle(BaseModel):
    """Generated interactive viewer bundle metadata."""

    model_config = ConfigDict(strict=False)

    index_path: str
    data_path: str
    non_claims: list[str] = Field(default_factory=list)


class ViewerData(BaseModel):
    """Complete viewer data bundle for JSON serialization."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "2.0"
    viewer: str = "zaptrace-interactive-viewer"
    design_name: str = ""
    board: ViewerBoard = Field(default_factory=ViewerBoard)
    components: list[ViewerComponent] = Field(default_factory=list)
    nets: list[ViewerNet] = Field(default_factory=list)
    traces: list[ViewerTrace] = Field(default_factory=list)
    vias: list[ViewerVia] = Field(default_factory=list)
    violations: list[ViewerViolation] = Field(default_factory=list)
    bom: list[dict[str, Any]] = Field(default_factory=list)
    proof_pack: dict[str, Any] = Field(default_factory=dict)
    non_claims: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Data extraction from Design model
# ---------------------------------------------------------------------------


def _extract_viewer_data(design: Design) -> ViewerData:
    """Convert a Design to a ViewerData bundle."""
    board_def = canonical_board_definition(design)

    # Components
    placement = design.placement or {}
    components: list[ViewerComponent] = []
    for comp in design.components.values():
        pos = placement.get(comp.id, comp.position or (0.0, 0.0))
        pins = [{"name": p.name, "type": p.type, "net": p.net or ""} for p in comp.pins.values()]
        components.append(
            ViewerComponent(
                id=comp.id,
                ref=comp.ref,
                type=comp.type,
                value=comp.value or "",
                footprint=comp.footprint,
                x=float(pos[0]),
                y=float(pos[1]),
                pins=pins,
                mpn=comp.mpn or "",
                manufacturer=comp.manufacturer or "",
                dnp=comp.dnp,
            )
        )

    # Nets
    net_classes = design.net_classes or {}
    nets: list[ViewerNet] = []
    for net in design.nets.values():
        nets.append(
            ViewerNet(
                id=net.id,
                name=net.name,
                type=net.type,
                net_class=net_classes.get(net.id, ""),
                nodes=[{"ref": n.component_ref, "pin": n.pin_name} for n in net.nodes],
            )
        )

    # Traces and vias
    traces: list[ViewerTrace] = []
    vias: list[ViewerVia] = []
    if design.routing:
        for seg in design.routing.traces:
            traces.append(
                ViewerTrace(
                    start_x=float(seg.start[0]),
                    start_y=float(seg.start[1]),
                    end_x=float(seg.end[0]),
                    end_y=float(seg.end[1]),
                    width=seg.width,
                    layer=seg.layer,
                    net_id=seg.net_id,
                )
            )
        for via_tuple in design.routing.vias:
            net_id = via_tuple[4] if len(via_tuple) > 4 else ""
            vias.append(
                ViewerVia(
                    x=float(via_tuple[0]),
                    y=float(via_tuple[1]),
                    diameter=float(via_tuple[2]),
                    drill=float(via_tuple[3]),
                    net_id=str(net_id),
                )
            )

    # Violations
    violations: list[ViewerViolation] = []
    if design.drc_result:
        for v in design.drc_result.violations:
            loc = v.location
            vx, vy = None, None
            if isinstance(loc, str) and "," in loc:
                parts = loc.strip("() ").split(",")
                with contextlib.suppress(ValueError, IndexError):
                    vx, vy = float(parts[0]), float(parts[1])
            violations.append(
                ViewerViolation(
                    rule_id=v.rule_id,
                    severity=v.severity,
                    message=v.message,
                    x=vx,
                    y=vy,
                    net_id=v.net_id,
                    component_ref=v.component_id,
                )
            )

    # BOM
    bom_items: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        bom_json = json.loads(generate_bom_json(design))
        bom_items = bom_json.get("items", [])

    # Board
    board = ViewerBoard(
        width_mm=board_def.width,
        height_mm=board_def.height,
        layers=board_def.layers,
        outline=board_def.outline if board_def.outline else [],
    )

    return ViewerData(
        design_name=design.meta.name,
        board=board,
        components=components,
        nets=nets,
        traces=traces,
        vias=vias,
        violations=violations,
        bom=bom_items,
        non_claims=[
            "interactive local review artifact, not cloud upload",
            "viewer is inspection-only and does not mutate designs",
            "human review remains required before fabrication",
        ],
    )


# ---------------------------------------------------------------------------
# HTML/CSS/JS template — full interactive viewer
# ---------------------------------------------------------------------------


def _build_interactive_html(design_name: str, data_json_str: str) -> str:
    """Build the complete interactive HTML string.

    Uses ``%`` substitution for the two dynamic values to avoid
    conflicting with JavaScript's ``{{`` braces.
    """
    dn = html.escape(design_name)

    # The template uses %DESIGN_NAME% and %DATA_JSON% as placeholders.
    template = _INTERACTIVE_TEMPLATE.replace("%DESIGN_NAME%", dn).replace("%DATA_JSON%", data_json_str)
    return template


# ponytail: single-file HTML viewer — upgrade to Vite/React when interactive
# editing (not just inspection) is requested.
_INTERACTIVE_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ZapTrace Interactive Viewer — %DESIGN_NAME%</title>
<style>
:root {
  --bg-primary: #0a0e1a;
  --bg-card: #111827;
  --bg-hover: #1e293b;
  --border: #2d3748;
  --text-primary: #e2e8f0;
  --text-secondary: #94a3b8;
  --accent: #6366f1;
  --accent-hover: #818cf8;
  --success: #22c55e;
  --warning: #f59e0b;
  --error: #ef4444;
  --info: #3b82f6;
  --trace-color: #f8c471;
  --highlight-color: #22d3ee;
  --board-fill: #14281d;
  --board-stroke: #d7f5dd;
  --component-fill: #243b55;
  --component-stroke: #d9e2ec;
}
[data-theme="light"] {
  --bg-primary: #f0f4f8;
  --bg-card: #ffffff;
  --bg-hover: #e2e8f0;
  --border: #cbd5e1;
  --text-primary: #1e293b;
  --text-secondary: #64748b;
  --board-fill: #e8f5e9;
  --board-stroke: #2e7d32;
  --component-fill: #e3f2fd;
  --component-stroke: #1565c0;
  --trace-color: #e65100;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Inter', system-ui, -apple-system, sans-serif; background: var(--bg-primary); color: var(--text-primary); overflow: hidden; height: 100vh; }
.app { display: grid; grid-template-columns: 280px 1fr; grid-template-rows: 56px 1fr; height: 100vh; }
.header { grid-column: 1/-1; display: flex; align-items: center; justify-content: space-between; padding: 0 20px; background: var(--bg-card); border-bottom: 1px solid var(--border); z-index: 100; }
.header h1 { font-size: 16px; font-weight: 600; }
.header h1 span { color: var(--accent); }
.header-meta { font-size: 12px; color: var(--text-secondary); }
.header-actions { display: flex; gap: 8px; }
.btn { padding: 6px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-card); color: var(--text-primary); font-size: 12px; cursor: pointer; transition: all 0.15s; }
.btn:hover { background: var(--bg-hover); border-color: var(--accent); }
.btn.active { background: var(--accent); color: white; border-color: var(--accent); }
.sidebar { background: var(--bg-card); border-right: 1px solid var(--border); overflow-y: auto; padding: 12px; }
.sidebar-section { margin-bottom: 16px; }
.sidebar-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); margin-bottom: 8px; }
.search-input { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-primary); color: var(--text-primary); font-size: 13px; outline: none; }
.search-input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(99,102,241,0.15); }
.layer-toggle { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; cursor: pointer; font-size: 13px; transition: background 0.1s; }
.layer-toggle:hover { background: var(--bg-hover); }
.layer-dot { width: 10px; height: 10px; border-radius: 50%; }
.layer-toggle input { display: none; }
.layer-toggle.off .layer-dot { opacity: 0.3; }
.comp-item { padding: 6px 8px; border-radius: 6px; font-size: 12px; cursor: pointer; display: flex; justify-content: space-between; transition: background 0.1s; }
.comp-item:hover { background: var(--bg-hover); }
.comp-item.selected { background: var(--accent); color: white; }
.comp-ref { font-weight: 600; }
.comp-val { color: var(--text-secondary); }
.violation-item { padding: 6px 8px; border-radius: 6px; font-size: 12px; cursor: pointer; border-left: 3px solid; margin-bottom: 2px; }
.violation-item.error { border-color: var(--error); }
.violation-item.warning { border-color: var(--warning); }
.violation-item.info { border-color: var(--info); }
.violation-item:hover { background: var(--bg-hover); }
.canvas-area { position: relative; overflow: hidden; background: var(--bg-primary); }
.canvas-area svg { position: absolute; top: 0; left: 0; transform-origin: 0 0; }
.info-panel { position: absolute; right: 16px; top: 16px; width: 280px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; z-index: 50; box-shadow: 0 8px 32px rgba(0,0,0,0.4); display: none; max-height: 400px; overflow-y: auto; }
.info-panel.visible { display: block; }
.info-panel h3 { font-size: 14px; margin-bottom: 8px; }
.info-panel .field { font-size: 12px; margin-bottom: 4px; }
.info-panel .field-label { color: var(--text-secondary); }
.info-panel .field-value { font-weight: 500; }
.info-close { position: absolute; top: 8px; right: 12px; cursor: pointer; font-size: 16px; color: var(--text-secondary); }
.status-bar { position: absolute; bottom: 0; left: 0; right: 0; height: 28px; background: var(--bg-card); border-top: 1px solid var(--border); display: flex; align-items: center; padding: 0 12px; font-size: 11px; color: var(--text-secondary); gap: 16px; z-index: 50; }
.status-bar .sep { color: var(--border); }
.measure-line { stroke: var(--highlight-color); stroke-width: 2; stroke-dasharray: 5,5; pointer-events: none; }
.measure-dot { fill: var(--highlight-color); pointer-events: none; }
.measure-label { fill: var(--highlight-color); font: 12px monospace; pointer-events: none; }
.tab-bar { display: flex; gap: 2px; margin-bottom: 8px; }
.tab { padding: 6px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; color: var(--text-secondary); }
.tab.active { background: var(--accent); color: white; }
.bom-panel { display: none; position: absolute; left: 0; right: 0; bottom: 28px; height: 240px; background: var(--bg-card); border-top: 1px solid var(--border); z-index: 40; overflow: auto; }
.bom-panel.visible { display: block; }
.bom-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.bom-table th { position: sticky; top: 0; background: var(--bg-card); border-bottom: 2px solid var(--border); padding: 8px; text-align: left; cursor: pointer; user-select: none; }
.bom-table th:hover { color: var(--accent); }
.bom-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
.bom-table tr:hover td { background: var(--bg-hover); }
</style>
</head>
<body>
<div class="app" id="app">
  <header class="header">
    <div>
      <h1>⚡ <span>ZapTrace</span> Interactive Viewer</h1>
      <div class="header-meta" id="headerMeta"></div>
    </div>
    <div class="header-actions">
      <button class="btn" id="btnMeasure" title="Measurement tool">📏 Measure</button>
      <button class="btn" id="btnBom" title="Toggle BOM panel">📋 BOM</button>
      <button class="btn" id="btnFitAll" title="Fit all">⊞ Fit</button>
      <button class="btn" id="btnTheme" title="Toggle theme">🌙</button>
    </div>
  </header>
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-section">
      <div class="sidebar-title">Search</div>
      <input class="search-input" id="searchInput" placeholder="Component ref or net name…" />
    </div>
    <div class="sidebar-section" id="layerSection"></div>
    <div class="sidebar-section">
      <div class="tab-bar">
        <div class="tab active" data-tab="components">Components</div>
        <div class="tab" data-tab="nets">Nets</div>
        <div class="tab" data-tab="violations">DRC</div>
      </div>
      <div id="tabContent"></div>
    </div>
  </aside>
  <div class="canvas-area" id="canvasArea">
    <svg id="boardSvg" xmlns="http://www.w3.org/2000/svg"></svg>
    <div class="info-panel" id="infoPanel">
      <span class="info-close" id="infoClose">✕</span>
      <div id="infoPanelContent"></div>
    </div>
    <div class="status-bar" id="statusBar">
      <span id="statusCoord">X: 0.00 Y: 0.00</span>
      <span class="sep">|</span>
      <span id="statusZoom">Zoom: 100%</span>
      <span class="sep">|</span>
      <span id="statusInfo"></span>
    </div>
  </div>
  <div class="bom-panel" id="bomPanel"></div>
</div>
<script>
(function() {
"use strict";
var DATA = %DATA_JSON%;
var scl = 8.0, zoom = 1.0, panX = 40, panY = 60;
var dragging = false, dragSX = 0, dragSY = 0, panSX = 0, panSY = 0;
var selectedComp = null, highlightedNet = null;
var measureMode = false, measurePts = [];
var activeTab = "components", darkTheme = true, bomVis = false;
var layerVis = {"F.Cu":true,"B.Cu":true,"F.SilkS":true,"B.SilkS":true,"drill":true};
var LC = {"F.Cu":"#e74c3c","B.Cu":"#2980b9","F.SilkS":"#f1c40f","B.SilkS":"#1abc9c","drill":"#bdc3c7"};

function esc(s) { var d = document.createElement("div"); d.textContent = s||""; return d.innerHTML; }

function init() {
  document.getElementById("headerMeta").textContent =
    DATA.design_name + " \u2014 " + DATA.components.length + " components, " +
    DATA.nets.length + " nets, " + DATA.board.layers + "-layer";
  buildLayers(); buildTabs(); buildBom(); renderBoard(); fitAll(); bindEvents();
}

function buildLayers() {
  var sec = document.getElementById("layerSection");
  var h = '<div class="sidebar-title">Layers</div>';
  for (var layer in LC) {
    var off = layerVis[layer] ? "" : " off";
    h += '<label class="layer-toggle' + off + '" data-layer="' + layer + '">' +
      '<span class="layer-dot" style="background:' + LC[layer] + '"></span>' +
      '<input type="checkbox" ' + (layerVis[layer] ? 'checked' : '') + '/>' + layer + '</label>';
  }
  sec.innerHTML = h;
  sec.querySelectorAll(".layer-toggle").forEach(function(el) {
    el.addEventListener("click", function() {
      var l = this.dataset.layer;
      layerVis[l] = !layerVis[l];
      this.classList.toggle("off", !layerVis[l]);
      this.querySelector("input").checked = layerVis[l];
      renderBoard();
    });
  });
}

function buildTabs() {
  document.querySelectorAll(".tab").forEach(function(t) {
    t.addEventListener("click", function() {
      document.querySelectorAll(".tab").forEach(function(x){ x.classList.remove("active"); });
      this.classList.add("active");
      activeTab = this.dataset.tab;
      renderTab();
    });
  });
  renderTab();
}

function renderTab() {
  var c = document.getElementById("tabContent");
  var q = (document.getElementById("searchInput").value || "").toLowerCase();
  if (activeTab === "components") {
    var items = DATA.components;
    if (q) items = items.filter(function(x){ return x.ref.toLowerCase().indexOf(q)>=0 || (x.value||"").toLowerCase().indexOf(q)>=0; });
    c.innerHTML = items.map(function(x){
      return '<div class="comp-item' + (selectedComp===x.id?' selected':'') +
        '" data-id="'+x.id+'"><span class="comp-ref">'+esc(x.ref)+'</span><span class="comp-val">'+esc(x.value)+'</span></div>';
    }).join("");
    c.querySelectorAll(".comp-item").forEach(function(el){ el.addEventListener("click", function(){ selComp(this.dataset.id); }); });
  } else if (activeTab === "nets") {
    var ni = DATA.nets;
    if (q) ni = ni.filter(function(n){ return n.name.toLowerCase().indexOf(q)>=0; });
    c.innerHTML = ni.map(function(n){
      return '<div class="comp-item' + (highlightedNet===n.id?' selected':'') +
        '" data-id="'+n.id+'"><span class="comp-ref">'+esc(n.name)+'</span><span class="comp-val">'+n.type+' ('+n.nodes.length+')</span></div>';
    }).join("");
    c.querySelectorAll(".comp-item").forEach(function(el){ el.addEventListener("click", function(){ hlNet(this.dataset.id); }); });
  } else {
    c.innerHTML = DATA.violations.map(function(v,i){
      return '<div class="violation-item '+v.severity+'" data-idx="'+i+'"><strong>'+esc(v.rule_id)+'</strong>: '+esc(v.message)+'</div>';
    }).join("") || '<div style="padding:8px;color:var(--text-secondary)">No violations</div>';
    c.querySelectorAll(".violation-item").forEach(function(el){
      el.addEventListener("click", function(){
        var v = DATA.violations[parseInt(this.dataset.idx)];
        if (v.x!=null && v.y!=null) panTo(v.x,v.y);
        showViol(v);
      });
    });
  }
}

function renderBoard() {
  var bw = DATA.board.width_mm, bh = DATA.board.height_mm;
  var W = Math.max(400, bw*scl+100), H = Math.max(300, bh*scl+120);
  var svg = document.getElementById("boardSvg");
  svg.setAttribute("width", W); svg.setAttribute("height", H);
  svg.setAttribute("viewBox", "0 0 "+W+" "+H);
  var p = [];
  p.push('<rect x="30" y="40" width="'+(bw*scl)+'" height="'+(bh*scl)+'" rx="6" fill="var(--board-fill)" stroke="var(--board-stroke)" stroke-width="2"/>');
  DATA.traces.forEach(function(t){
    if (!layerVis[t.layer]) return;
    var col = (highlightedNet && t.net_id===highlightedNet) ? "var(--highlight-color)" : (LC[t.layer]||"var(--trace-color)");
    var op = (highlightedNet && t.net_id!==highlightedNet) ? 0.15 : 0.85;
    var w = Math.max(1, t.width*scl);
    p.push('<line data-net="'+esc(t.net_id)+'" data-layer="'+esc(t.layer)+'" x1="'+(30+t.start_x*scl)+'" y1="'+(40+t.start_y*scl)+'" x2="'+(30+t.end_x*scl)+'" y2="'+(40+t.end_y*scl)+'" stroke="'+col+'" stroke-width="'+w+'" stroke-linecap="round" opacity="'+op+'"/>');
  });
  if (layerVis["drill"]) {
    DATA.vias.forEach(function(v){
      var cx=30+v.x*scl, cy=40+v.y*scl, r=(v.diameter/2)*scl;
      var col = (highlightedNet && v.net_id===highlightedNet) ? "var(--highlight-color)" : "#bdc3c7";
      p.push('<circle data-net="'+esc(v.net_id)+'" cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="'+col+'" stroke="#333" stroke-width="1" opacity="0.9"><title>Via '+esc(v.net_id)+'</title></circle>');
    });
  }
  DATA.components.forEach(function(c){
    var layer = c.layer||"F.Cu";
    if (!layerVis[layer]) return;
    var x=30+c.x*scl, y=40+c.y*scl;
    var isSel = selectedComp===c.id;
    var hasNet = highlightedNet && c.pins.some(function(pin){ return DATA.nets.some(function(n){ return n.id===highlightedNet && n.nodes.some(function(nd){ return nd.ref===c.ref && nd.pin===pin.name; }); }); });
    var op = (highlightedNet && !hasNet) ? 0.2 : 1;
    var fill = isSel?"var(--accent)":"var(--component-fill)";
    var stroke = isSel?"var(--accent-hover)":"var(--component-stroke)";
    p.push('<g data-ref="'+esc(c.ref)+'" data-id="'+esc(c.id)+'" class="cg" style="cursor:pointer;opacity:'+op+'">' +
      '<rect x="'+x+'" y="'+y+'" width="42" height="24" rx="4" fill="'+fill+'" stroke="'+stroke+'" stroke-width="1.2"/>' +
      '<text x="'+(x+5)+'" y="'+(y+11)+'" fill="var(--text-primary)" font-size="10" font-weight="600">'+esc(c.ref)+'</text>' +
      '<text x="'+(x+5)+'" y="'+(y+20)+'" fill="var(--text-secondary)" font-size="8">'+esc(c.value).substring(0,8)+'</text></g>');
  });
  DATA.violations.forEach(function(v){
    if (v.x==null||v.y==null) return;
    var cx=30+v.x*scl, cy=40+v.y*scl;
    var col = v.severity==="error"?"var(--error)":v.severity==="warning"?"var(--warning)":"var(--info)";
    p.push('<circle cx="'+cx+'" cy="'+cy+'" r="6" fill="'+col+'" stroke="#fff" stroke-width="1.5" opacity="0.9" style="cursor:pointer" class="dm"><title>'+esc(v.rule_id+": "+v.message)+'</title></circle>');
  });
  if (measurePts.length>0) {
    measurePts.forEach(function(mp){ p.push('<circle class="measure-dot" cx="'+(30+mp.x*scl)+'" cy="'+(40+mp.y*scl)+'" r="4"/>'); });
    if (measurePts.length===2) {
      var a=measurePts[0],b=measurePts[1];
      var sx0=30+a.x*scl,sy0=40+a.y*scl,sx1=30+b.x*scl,sy1=40+b.y*scl;
      var dist=Math.sqrt(Math.pow(b.x-a.x,2)+Math.pow(b.y-a.y,2));
      p.push('<line class="measure-line" x1="'+sx0+'" y1="'+sy0+'" x2="'+sx1+'" y2="'+sy1+'"/>');
      p.push('<text class="measure-label" x="'+((sx0+sx1)/2+8)+'" y="'+((sy0+sy1)/2-6)+'">'+dist.toFixed(2)+' mm</text>');
    }
  }
  svg.innerHTML = p.join("\n");
  applyTx();
  svg.querySelectorAll(".cg").forEach(function(g){
    g.addEventListener("click", function(e){ e.stopPropagation(); selComp(this.dataset.id); });
  });
}

function applyTx() {
  document.getElementById("boardSvg").style.transform = "translate("+panX+"px,"+panY+"px) scale("+zoom+")";
  document.getElementById("statusZoom").textContent = "Zoom: "+Math.round(zoom*100)+"%";
}

function selComp(id) {
  selectedComp = (selectedComp===id)?null:id;
  var comp = DATA.components.find(function(c){ return c.id===id; });
  if (comp && selectedComp) { showCompInfo(comp); panTo(comp.x, comp.y); } else hideInfo();
  renderBoard(); renderTab();
}

function hlNet(id) {
  highlightedNet = (highlightedNet===id)?null:id;
  var net = DATA.nets.find(function(n){ return n.id===id; });
  if (net && highlightedNet) showNetInfo(net); else hideInfo();
  renderBoard(); renderTab();
}

function panTo(x, y) {
  var area = document.getElementById("canvasArea");
  panX = area.clientWidth/2 - (30+x*scl)*zoom;
  panY = area.clientHeight/2 - (40+y*scl)*zoom;
  applyTx();
}

function fitAll() {
  var area = document.getElementById("canvasArea");
  var bw=DATA.board.width_mm*scl+80, bh=DATA.board.height_mm*scl+100;
  zoom = Math.min(area.clientWidth/bw, (area.clientHeight-28)/bh, 3);
  panX = (area.clientWidth-bw*zoom)/2;
  panY = (area.clientHeight-28-bh*zoom)/2;
  applyTx();
}

function showCompInfo(c) {
  var pins = c.pins.map(function(p){ return '<div class="field"><span class="field-label">'+esc(p.name)+'</span> \u2192 <span class="field-value">'+(p.net||"NC")+'</span> ('+p.type+')</div>'; }).join("");
  document.getElementById("infoPanelContent").innerHTML =
    '<h3>\ud83d\udce6 '+esc(c.ref)+'</h3>'+
    '<div class="field"><span class="field-label">Value: </span><span class="field-value">'+esc(c.value)+'</span></div>'+
    '<div class="field"><span class="field-label">Footprint: </span><span class="field-value">'+esc(c.footprint)+'</span></div>'+
    '<div class="field"><span class="field-label">MPN: </span><span class="field-value">'+esc(c.mpn||"\u2014")+'</span></div>'+
    '<div class="field"><span class="field-label">Manufacturer: </span><span class="field-value">'+esc(c.manufacturer||"\u2014")+'</span></div>'+
    '<div class="field"><span class="field-label">Position: </span><span class="field-value">'+c.x.toFixed(2)+', '+c.y.toFixed(2)+' mm</span></div>'+
    (c.dnp?'<div class="field" style="color:var(--warning)">\u26a0\ufe0f Do Not Populate</div>':'')+
    '<div class="sidebar-title" style="margin-top:12px">Pins ('+c.pins.length+')</div>'+pins;
  document.getElementById("infoPanel").classList.add("visible");
}

function showNetInfo(n) {
  var nodes = n.nodes.map(function(nd){ return '<div class="field">'+esc(nd.ref)+'.'+esc(nd.pin)+'</div>'; }).join("");
  var tc = DATA.traces.filter(function(t){ return t.net_id===n.id; }).length;
  document.getElementById("infoPanelContent").innerHTML =
    '<h3>\ud83d\udd0c '+esc(n.name)+'</h3>'+
    '<div class="field"><span class="field-label">Type: </span><span class="field-value">'+n.type+'</span></div>'+
    '<div class="field"><span class="field-label">Class: </span><span class="field-value">'+(n.net_class||"\u2014")+'</span></div>'+
    '<div class="field"><span class="field-label">Traces: </span><span class="field-value">'+tc+'</span></div>'+
    '<div class="sidebar-title" style="margin-top:12px">Connections ('+n.nodes.length+')</div>'+nodes;
  document.getElementById("infoPanel").classList.add("visible");
}

function showViol(v) {
  document.getElementById("infoPanelContent").innerHTML =
    '<h3>\u26a0\ufe0f '+esc(v.rule_id)+'</h3>'+
    '<div class="field"><span class="field-label">Severity: </span><span class="field-value" style="color:var(--'+v.severity+')">'+v.severity+'</span></div>'+
    '<div class="field"><span class="field-label">Message: </span><span class="field-value">'+esc(v.message)+'</span></div>'+
    (v.component_ref?'<div class="field"><span class="field-label">Component: </span><span class="field-value">'+esc(v.component_ref)+'</span></div>':'')+
    (v.net_id?'<div class="field"><span class="field-label">Net: </span><span class="field-value">'+esc(v.net_id)+'</span></div>':'');
  document.getElementById("infoPanel").classList.add("visible");
}

function hideInfo() { document.getElementById("infoPanel").classList.remove("visible"); }

function buildBom() {
  if (!DATA.bom.length) return;
  var cols=["ref","value","footprint","mpn","manufacturer"], sortCol="ref", sortAsc=true;
  function render() {
    var sorted=[].concat(DATA.bom).sort(function(a,b){
      var av=String(a[sortCol]||""),bv=String(b[sortCol]||"");
      return sortAsc?av.localeCompare(bv):bv.localeCompare(av);
    });
    var hdr=cols.map(function(c){ return '<th data-col="'+c+'">'+c.charAt(0).toUpperCase()+c.slice(1)+(sortCol===c?(sortAsc?" \u25b2":" \u25bc"):"")+'</th>'; }).join("");
    var rows=sorted.map(function(item){ return '<tr>'+cols.map(function(c){ return '<td>'+esc(String(item[c]||""))+'</td>'; }).join("")+'</tr>'; }).join("");
    document.getElementById("bomPanel").innerHTML='<table class="bom-table"><thead><tr>'+hdr+'</tr></thead><tbody>'+rows+'</tbody></table>';
    document.querySelectorAll(".bom-table th").forEach(function(th){
      th.addEventListener("click", function(){
        if(sortCol===this.dataset.col)sortAsc=!sortAsc;else{sortCol=this.dataset.col;sortAsc=true;}
        render();
      });
    });
  }
  render();
}

function bindEvents() {
  var area = document.getElementById("canvasArea");
  area.addEventListener("pointerdown", function(e){
    if (measureMode) {
      var rect=area.getBoundingClientRect();
      var mx=(e.clientX-rect.left-panX)/zoom, my=(e.clientY-rect.top-panY)/zoom;
      var bx=(mx-30)/scl, by=(my-40)/scl;
      measurePts.push({x:bx,y:by});
      if(measurePts.length>2)measurePts=[measurePts[measurePts.length-1]];
      renderBoard();
      if(measurePts.length===2){
        var d=Math.sqrt(Math.pow(measurePts[1].x-measurePts[0].x,2)+Math.pow(measurePts[1].y-measurePts[0].y,2));
        document.getElementById("statusInfo").textContent="Distance: "+d.toFixed(3)+" mm";
      }
      return;
    }
    dragging=true; dragSX=e.clientX; dragSY=e.clientY; panSX=panX; panSY=panY;
    area.setPointerCapture(e.pointerId);
  });
  area.addEventListener("pointermove", function(e){
    var rect=area.getBoundingClientRect();
    var mx=(e.clientX-rect.left-panX)/zoom, my=(e.clientY-rect.top-panY)/zoom;
    document.getElementById("statusCoord").textContent="X: "+((mx-30)/scl).toFixed(2)+" Y: "+((my-40)/scl).toFixed(2);
    if(!dragging)return;
    panX=panSX+(e.clientX-dragSX); panY=panSY+(e.clientY-dragSY);
    applyTx();
  });
  area.addEventListener("pointerup", function(e){ dragging=false; area.releasePointerCapture(e.pointerId); });
  area.addEventListener("wheel", function(e){
    e.preventDefault();
    var rect=area.getBoundingClientRect();
    var mx=e.clientX-rect.left, my=e.clientY-rect.top;
    var old=zoom;
    zoom*=e.deltaY<0?1.15:0.87;
    zoom=Math.max(0.1,Math.min(20,zoom));
    panX=mx-(mx-panX)*(zoom/old); panY=my-(my-panY)*(zoom/old);
    applyTx();
  }, {passive:false});
  document.getElementById("searchInput").addEventListener("input", renderTab);
  document.getElementById("btnFitAll").addEventListener("click", fitAll);
  document.getElementById("btnTheme").addEventListener("click", function(){
    darkTheme=!darkTheme;
    document.documentElement.setAttribute("data-theme",darkTheme?"":"light");
    this.textContent=darkTheme?"\ud83c\udf19":"\u2600\ufe0f";
  });
  document.getElementById("btnMeasure").addEventListener("click", function(){
    measureMode=!measureMode; this.classList.toggle("active",measureMode);
    if(!measureMode){measurePts=[];renderBoard();document.getElementById("statusInfo").textContent="";}
    else document.getElementById("statusInfo").textContent="Click two points to measure";
  });
  document.getElementById("btnBom").addEventListener("click", function(){
    bomVis=!bomVis;
    document.getElementById("bomPanel").classList.toggle("visible",bomVis);
    this.classList.toggle("active",bomVis);
  });
  document.getElementById("infoClose").addEventListener("click", hideInfo);
  area.addEventListener("click", function(e){
    if(e.target===area||e.target.id==="boardSvg"){
      if(!measureMode){selectedComp=null;highlightedNet=null;hideInfo();renderBoard();renderTab();}
    }
  });
  document.addEventListener("keydown", function(e){
    if(e.key==="Escape"){
      selectedComp=null;highlightedNet=null;measureMode=false;measurePts=[];
      hideInfo();renderBoard();renderTab();
      document.getElementById("btnMeasure").classList.remove("active");
      document.getElementById("statusInfo").textContent="";
    }
  });
  window.addEventListener("resize", fitAll);
}

init();
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _write_text(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def generate_interactive_viewer(
    design: Design | Path | str,
    output_dir: Path | str,
    *,
    proof_path: Path | str | None = None,
) -> InteractiveViewerBundle:
    """Generate an interactive browser viewer bundle for a design.

    The bundle is a single ``index.html`` with embedded CSS/JS plus a
    ``viewer-data.json`` sidecar.  Open ``index.html`` in any modern
    browser to inspect the board.
    """
    from zaptrace.viewer.static import _load_proof_summary

    design_obj = parse_file(Path(design)) if isinstance(design, (str, Path)) else design
    out = Path(output_dir)

    proof = Path(proof_path) if proof_path is not None else None
    proof_summary = _load_proof_summary(proof)

    viewer_data = _extract_viewer_data(design_obj)
    viewer_data.proof_pack = proof_summary

    data_json = viewer_data.model_dump(mode="json")
    data_json_str = json.dumps(data_json, separators=(",", ":"))

    html_content = _build_interactive_html(design_obj.meta.name, data_json_str)

    index_path = _write_text(out / "index.html", html_content)
    data_path = _write_text(
        out / "viewer-data.json",
        json.dumps(data_json, indent=2) + "\n",
    )

    return InteractiveViewerBundle(
        index_path=index_path,
        data_path=data_path,
        non_claims=viewer_data.non_claims,
    )
