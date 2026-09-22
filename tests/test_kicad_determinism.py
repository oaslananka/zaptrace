from __future__ import annotations

from pathlib import Path

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode
from zaptrace.export.kicad import export_kicad_pcb


def test_kicad_export_is_deterministic(tmp_path: Path) -> None:
    design = Design(name="test_kicad", meta=DesignMeta(name="test_kicad"))
    design.components["R1"] = Component(id="R1", value="10k", ref="R1", footprint="R0805", type="resistor")
    design.components["U1"] = Component(id="U1", value="MCU", ref="U1", footprint="QFN32", type="ic")
    design.nets["N1"] = Net(
        id="N1",
        name="VDD",
        nodes=[
            NetNode(component_ref="R1", pin_number="1", pin_name="VCC"),
            NetNode(component_ref="U1", pin_number="1", pin_name="VDD"),
        ],
    )

    dir1 = tmp_path / "run1"
    dir2 = tmp_path / "run2"

    res1 = export_kicad_pcb(design, dir1)
    res2 = export_kicad_pcb(design, dir2)

    content1 = res1["pcb"].read_text(encoding="utf-8")
    content2 = res2["pcb"].read_text(encoding="utf-8")

    assert content1 == content2, "KiCad PCB export must produce byte-identical S-expressions"
