"""Genuine KiCad 10 model diagnostics on read-only PCB: no CAD signoff."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("native_014_model_checks", SCRIPTS / "review_studio_native_kicad.py")
assert spec and spec.loader
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
SOURCE = SCRIPTS.parent / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"


def test_014_model_file_candidates_never_infer_mechanical_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "3dmodels"
    model = base / "Resistor_SMD.3dshapes" / "example.step"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"local-test-candidate")
    monkeypatch.setenv("KICAD10_3DMODEL_DIR", str(base))
    present, candidate = native._model_file_probe("${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/example.step", tmp_path)
    assert present and not candidate
    present, candidate = native._model_file_probe("${KICAD9_3DMODEL_DIR}/Resistor_SMD.3dshapes/example.wrl", tmp_path)
    assert not present and candidate  # STEP is NOT automatically a qualified mechanical substitute.
    assert native._model_file_probe("${KICAD10_3DMODEL_DIR}/../../secret.step", tmp_path) == (False, False)
    assert native._model_file_probe("${UNTRUSTED}/var/private.step", tmp_path) == (False, False)
    assert native._model_file_probe("${KIPRJMOD}/../../outside.step", tmp_path) == (False, False)
    assert native._model_file_probe("/etc/shadow", tmp_path) == (False, False)
    assert native._model_file_probe("${KIPRJMOD}/missing.step", tmp_path) == (False, False)


def test_014_real_native_model_inventory_preserves_original_board_sha() -> None:
    before = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    code = (
        "import json,sys;"
        f"sys.path.insert(0,{str(SCRIPTS)!r});"
        "from review_studio_native_kicad import _read_kicad;"
        f"print(json.dumps(_read_kicad(__import__('pathlib').Path({str(SOURCE)!r}))['model_assets']))"
    )
    result = subprocess.run(["/usr/bin/python3", "-B", "-c", code], capture_output=True, text=True, timeout=22)
    assert result.returncode == 0, result.stderr
    diag = json.loads(result.stdout)
    assert (diag["footprints"], diag["declared_references"]) == (14, 12)
    # Environment-dependent available file count is deliberately not signoff.
    assert 0 <= diag["present_files"] <= 12
    assert diag["model_geometry_approved"] is False
    assert "NOT verified" in diag["scope"]
    assert {"J1", "U1"} <= set(diag["unresolved_refs"] + diag["same_stem_step_candidates"])
    assert diag["without_model_refs"] == ["TP1", "TP2"]
    assert before == hashlib.sha256(SOURCE.read_bytes()).hexdigest()


def test_014_diagnostics_report_exists_and_does_not_claim_fabrication() -> None:
    template = (SCRIPTS / "review_studio_native_template.html").read_text()
    for marker in (
        'id="render3dModelSummary"',
        'id="render3dModelDetails"',
        'id="render3dModelDiagnostics"',
        "showModelFileDiagnostics()",
        "checked.model_geometry_approved!==false",
        "Same-stem STEP candidates (NOT verified)",
        "NOT FABRICATION APPROVED",
    ):
        assert marker in template
    report = (SCRIPTS / "review_studio_native_kicad.py").read_text()
    assert "3D model file references" in report
    assert "File presence only; fit/assembly NOT qualified." in report
