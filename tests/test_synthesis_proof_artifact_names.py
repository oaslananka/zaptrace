"""Regression coverage for stable synthesis proof-pack artifact names."""

from zaptrace.synthesis import proof


def test_synthesis_proof_artifact_names_remain_stable() -> None:
    assert proof._DESIGN_ARTIFACT_NAME == "design.yaml"
    assert proof._KICAD_SCHEMATIC_PARITY_NAME == "kicad_schematic_parity.json"
    assert proof._KICAD_PCB_PARITY_NAME == "kicad_pcb_parity.json"
    assert proof._IPC_D356_PARITY_NAME == "ipc_d356_parity.json"
    assert proof._REQUIREMENTS_COVERAGE_NAME == "requirements_coverage.json"
