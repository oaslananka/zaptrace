from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from zaptrace.cli.main import cli
from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode
from zaptrace.viewer import generate_static_viewer


def _design() -> Design:
    design = Design(meta=DesignMeta(name="ViewerBoard"))
    design.components = {
        "u1": Component(id="u1", ref="U1", type="mcu", value="ESP32"),
        "r1": Component(id="r1", ref="R1", type="resistor", value="10k", footprint="0603"),
    }
    design.nets = {
        "n1": Net(
            id="n1",
            name="GPIO",
            nodes=[NetNode(component_ref="U1", pin_name="1"), NetNode(component_ref="R1", pin_name="1")],
        )
    }
    design.placement = {"u1": (10.0, 10.0), "r1": (25.0, 18.0)}
    return design


def test_generate_static_viewer_bundle_contains_required_panels(tmp_path: Path) -> None:
    proof = tmp_path / "proof.yaml"
    proof.write_text("name: ViewerProof\nchecks:\n  - name: erc\n", encoding="utf-8")

    bundle = generate_static_viewer(_design(), tmp_path / "viewer", proof_path=proof)

    index = Path(bundle.index_path)
    assert index.exists()
    html = index.read_text(encoding="utf-8")
    assert "Schematic" in html
    assert "PCB Top Copper" in html
    assert "BOM summary" in html
    assert "Proof-pack status" in html
    assert Path(bundle.assets["schematic"]).exists()
    assert Path(bundle.assets["pcb_top"]).exists()
    assert Path(bundle.assets["pcb_bottom"]).exists()

    manifest = json.loads(Path(bundle.data["manifest"]).read_text(encoding="utf-8"))
    assert manifest["design"]["name"] == "ViewerBoard"
    assert {"schematic", "pcb-top", "pcb-bottom", "validation-markers", "bom", "proof-pack"}.issubset(
        set(manifest["panels"])
    )
    assert manifest["proof_pack"]["present"] is True
    assert manifest["bom_summary"]["item_count"] == 2
    assert "cloud upload" in manifest["non_claims"][0]


def test_viewer_cli_writes_browser_bundle(tmp_path: Path) -> None:
    design_path = tmp_path / "design.yaml"
    proof_path = tmp_path / "proof.yaml"
    output = tmp_path / "out"
    design_path.write_text(
        "meta:\n  name: CliViewer\ncomponents:\n  r1:\n    ref: R1\n    type: resistor\n    value: 10k\n",
        encoding="utf-8",
    )
    proof_path.write_text("name: CliProof\nchecks: []\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["viewer", str(design_path), "--proof", str(proof_path), "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert (output / "index.html").exists()
    assert (output / "data" / "viewer-manifest.json").exists()
