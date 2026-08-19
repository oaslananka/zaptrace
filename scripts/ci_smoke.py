from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import yaml

from zaptrace.algo.placer import place_components
from zaptrace.algo.router import route_design_smart
from zaptrace.core.models import BoardConfig, Component, Design, DesignMeta, Net, NetNode
from zaptrace.ee.classifier import classify_design
from zaptrace.export.excellon import generate_excellon
from zaptrace.export.gerber import generate_gerber
from zaptrace.proof import run_proof


def gerber_smoke() -> None:
    design = Design(meta=DesignMeta(name="SmokeTest"), board=BoardConfig(width_mm=50, height_mm=40, layers=2))
    design.components["u1"] = Component(id="u1", ref="U1", type="mcu", value="TestMCU", footprint="QFN-32")
    design.components["r1"] = Component(id="r1", ref="R1", type="resistor", value="10k", footprint="0805")
    design.components["c1"] = Component(id="c1", ref="C1", type="capacitor", value="100n", footprint="0603")
    design.nets["n1"] = Net(
        id="n1",
        name="VCC",
        nodes=[NetNode(component_ref="U1", pin_name="VCC"), NetNode(component_ref="R1", pin_name="p1")],
    )
    design.nets["n2"] = Net(
        id="n2",
        name="GND",
        nodes=[NetNode(component_ref="U1", pin_name="GND"), NetNode(component_ref="C1", pin_name="p2")],
    )
    classify_design(design)
    positions = place_components(design)
    _, design.routing, _sc = route_design_smart(design, positions)

    with tempfile.TemporaryDirectory() as directory:
        output_dir = Path(directory)
        files = generate_gerber(design, output_dir=output_dir)
        assert len(files) >= 4, f"Expected at least four Gerber layers, got {len(files)}"
        for name, path in files.items():
            artifact = Path(path)
            assert artifact.exists(), f"Gerber file missing: {path}"
            assert artifact.stat().st_size > 0, f"Gerber file empty: {path}"
            assert "FSLAX36Y36" in artifact.read_text(), f"Missing RS-274X header in {name}"
        drill_files = generate_excellon(design, output_dir=output_dir)
        print(f"OK: {len(files)} Gerber layers and {len(drill_files)} drill files")


def proof_smoke() -> None:
    design = {
        "meta": {"name": "SmokeTest", "author": "ci"},
        "components": {
            "r1": {"ref": "R1", "type": "resistor", "value": "10k", "footprint": "0805"},
            "c1": {"ref": "C1", "type": "capacitor", "value": "100n", "footprint": "0603"},
        },
        "nets": {
            "vcc": {"name": "VCC", "nodes": ["R1.p1", "C1.p1"]},
            "gnd": {"name": "GND", "nodes": ["R1.p2", "C1.p2"]},
        },
        "board": {"width_mm": 50.0, "height_mm": 40.0, "layers": 2},
    }
    proof = {
        "version": "1.0",
        "name": "CI Smoke Test",
        "design_path": "design.yaml",
        "checks": [
            {"name": "footprints_exist", "type": "footprint_exists", "severity": "error"},
            {"name": "all_routed", "type": "routed", "severity": "warning"},
        ],
        "model": {"min_clearance_mm": 0.15, "min_trace_width_mm": 0.15},
    }

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "design.yaml").write_text(yaml.safe_dump(design), encoding="utf-8")
        (root / "proof.yaml").write_text(yaml.safe_dump(proof), encoding="utf-8")
        pack = run_proof(root)
        assert pack.results, "No checks ran"
        errors = [result for result in pack.results if result.status.value == "error"]
        assert not errors, f"Checks raised errors: {errors}"
        print("OK: Proof pack smoke test passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=["gerber", "proof"])
    args = parser.parse_args()
    {"gerber": gerber_smoke, "proof": proof_smoke}[args.target]()


if __name__ == "__main__":
    main()
