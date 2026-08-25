# ruff: noqa: E501

"""3D WebGL Board Viewer bundle generator using Three.js."""

from __future__ import annotations

import html
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design
from zaptrace.core.parser import parse_file
from zaptrace.export.mesh import _estimate_height


class ThreeDeeBundle(BaseModel):
    """Result of generating a 3D board viewer bundle."""

    model_config = ConfigDict(strict=False)

    index_path: str
    design_name: str
    board_width_mm: float
    board_height_mm: float
    component_count: int


_3D_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>%DESIGN_NAME% — ZapTrace 3D Board Viewer</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #131a29;
      --border: #1e293b;
      --text: #f1f5f9;
      --accent: #38bdf8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      height: 100vh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    header {
      height: 48px;
      background: var(--card-bg);
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 16px;
      z-index: 10;
    }
    .brand { font-weight: bold; color: var(--accent); display: flex; align-items: center; gap: 8px; }
    .controls { display: flex; gap: 8px; align-items: center; }
    .btn {
      background: #1e293b;
      color: #e2e8f0;
      border: 1px solid #334155;
      padding: 6px 12px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 500;
    }
    .btn:hover { background: #334155; }
    #canvas-container { flex: 1; position: relative; width: 100%; height: 100%; }
    #canvas3d { width: 100%; height: 100%; display: block; }
    .overlay-info {
      position: absolute;
      bottom: 16px;
      left: 16px;
      background: rgba(19, 26, 41, 0.85);
      border: 1px solid var(--border);
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 12px;
      pointer-events: none;
      backdrop-filter: blur(4px);
    }
  </style>
  <script src="https://unpkg.com/three@0.160.0/build/three.min.js"></script>
  <script src="https://unpkg.com/three@0.160.0/examples/js/controls/OrbitControls.js"></script>
</head>
<body>
  <header>
    <div class="brand">&#129690; %DESIGN_NAME% <span style="font-size:11px;color:#94a3b8;margin-left:8px">(3D PCB Preview)</span></div>
    <div class="controls">
      <button class="btn" id="btnColorGreen" style="background:#064e3b;border-color:#059669">Green</button>
      <button class="btn" id="btnColorBlack" style="background:#09090b;border-color:#27272a">Black</button>
      <button class="btn" id="btnColorBlue" style="background:#1e3a8a;border-color:#2563eb">Blue</button>
      <button class="btn" id="btnReset">Reset View</button>
    </div>
  </header>
  <div id="canvas-container">
    <canvas id="canvas3d"></canvas>
    <div class="overlay-info">
      <div><strong>Board:</strong> %WIDTH% &times; %HEIGHT% mm</div>
      <div><strong>Components:</strong> %COMP_COUNT% placed</div>
      <div style="color:#94a3b8;font-size:10px;margin-top:4px">Left click: Orbit &bull; Right click: Pan &bull; Wheel: Zoom</div>
    </div>
  </div>

  <script>
    const DATA = %DATA_JSON%;

    function init3D() {
      const container = document.getElementById("canvas-container");
      const canvas = document.getElementById("canvas3d");
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x090d16);

      const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 1, 2000);
      const dist = Math.max(DATA.board.width, DATA.board.height) * 2.2;
      camera.position.set(0, -dist * 0.8, dist * 1.1);
      camera.up.set(0, 0, 1);

      const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
      renderer.setSize(container.clientWidth, container.clientHeight);
      renderer.setPixelRatio(window.devicePixelRatio || 1);
      renderer.shadowMap.enabled = true;

      const controls = new THREE.OrbitControls(camera, canvas);
      controls.enableDamping = true;
      controls.dampingFactor = 0.05;

      // Lights
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
      scene.add(ambientLight);

      const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.8);
      dirLight1.position.set(50, 50, 150);
      scene.add(dirLight1);

      const dirLight2 = new THREE.DirectionalLight(0x90b0d0, 0.4);
      dirLight2.position.set(-50, -50, -100);
      scene.add(dirLight2);

      // Substrate
      const bw = DATA.board.width;
      const bh = DATA.board.height;
      const bt = 1.6;

      const subGeom = new THREE.BoxGeometry(bw, bh, bt);
      let subMat = new THREE.MeshStandardMaterial({
        color: 0x064e3b,
        roughness: 0.4,
        metalness: 0.1,
      });
      const substrate = new THREE.Mesh(subGeom, subMat);
      substrate.position.set(0, 0, -bt / 2);
      scene.add(substrate);

      // Components
      const compMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.5, metalness: 0.2 });
      const pinMat = new THREE.MeshStandardMaterial({ color: 0xd4af37, roughness: 0.2, metalness: 0.8 });

      DATA.components.forEach(function(c) {
        const h = c.height || 1.0;
        const cw = 4.0;
        const ch = 4.0;
        const compGeom = new THREE.BoxGeometry(cw, ch, h);
        const compMesh = new THREE.Mesh(compGeom, compMat);
        compMesh.position.set(c.x - bw / 2, c.y - bh / 2, h / 2);
        scene.add(compMesh);
      });

      // Animate
      function animate() {
        requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
      }
      animate();

      window.addEventListener("resize", function() {
        camera.aspect = container.clientWidth / container.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(container.clientWidth, container.clientHeight);
      });

      document.getElementById("btnColorGreen").onclick = function() { subMat.color.setHex(0x064e3b); };
      document.getElementById("btnColorBlack").onclick = function() { subMat.color.setHex(0x09090b); };
      document.getElementById("btnColorBlue").onclick = function() { subMat.color.setHex(0x1e3a8a); };
      document.getElementById("btnReset").onclick = function() {
        camera.position.set(0, -dist * 0.8, dist * 1.1);
        controls.target.set(0, 0, 0);
      };
    }

    window.onload = init3D;
  </script>
</body>
</html>"""


def generate_3d_viewer(
    design_or_path: Design | str | Path,
    output_dir: str | Path = "build/viewer3d",
) -> ThreeDeeBundle:
    """Generate self-contained 3D WebGL board viewer HTML bundle."""
    design = parse_file(Path(design_or_path)) if isinstance(design_or_path, (str, Path)) else design_or_path

    bd = canonical_board_definition(design)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    comps_data = []
    positions = design.placement or {}
    for ref, c in sorted(design.components.items()):
        pos = positions.get(ref)
        if pos:
            comps_data.append({
                "ref": ref,
                "value": c.value,
                "footprint": c.footprint,
                "x": pos[0],
                "y": pos[1],
                "height": _estimate_height(c.footprint),
            })

    data_payload = {
        "design_name": design.meta.name,
        "board": {"width": bd.width, "height": bd.height, "layers": bd.layers},
        "components": comps_data,
    }

    html_content = (
        _3D_TEMPLATE.replace("%DESIGN_NAME%", html.escape(design.meta.name))
        .replace("%WIDTH%", f"{bd.width:.1f}")
        .replace("%HEIGHT%", f"{bd.height:.1f}")
        .replace("%COMP_COUNT%", str(len(comps_data)))
        .replace("%DATA_JSON%", json.dumps(data_payload))
    )

    index_file = out / "index.html"
    index_file.write_text(html_content, encoding="utf-8")

    return ThreeDeeBundle(
        index_path=str(index_file),
        design_name=design.meta.name,
        board_width_mm=bd.width,
        board_height_mm=bd.height,
        component_count=len(comps_data),
    )
