from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path("scripts/ci_physical_candidate_readiness.py")


def _api():
    assert SCRIPT.is_file(), "physical candidate readiness CI script is missing"
    spec = importlib.util.spec_from_file_location("ci_physical_candidate_readiness", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_candidate_records_real_readiness_without_fabrication_claim() -> None:
    module = _api()
    report = module.build_candidate_readiness(run_kicad=False)

    assert report["candidate_id"] == "esp32_usb_sensor_physical_rev_a"
    assert report["candidate_ready"] is False
    assert report["fabrication_eligible"] is False
    assert report["checks"]["exact_esp32_c3_identity"]["passed"] is True
    assert report["checks"]["exact_usb_c_identity"]["passed"] is True
    assert report["checks"]["usb_c_sink_cc_termination"]["passed"] is True
    assert report["checks"]["footprint_resolution_complete"]["passed"] is True
    assert report["checks"]["placement_complete"]["passed"] is True
    assert report["checks"]["internal_erc_clean"]["passed"] is True
    assert report["checks"]["exact_component_identity"]["passed"] is False
    assert report["checks"]["internal_drc_clean"]["passed"] is False
    assert report["checks"]["internal_drc_clean"]["errors"] == 1
    assert report["checks"]["internal_drc_clean"]["rule_ids"] == ["DRC-005"]
    assert report["checks"]["profile_bound_dfm_non_hard_fail"]["passed"] is False
    assert report["checks"]["kicad_erc_clean"]["status"] == "not-run"
    assert report["checks"]["kicad_drc_clean"]["status"] == "not-run"
    assert report["blocking_reasons"]
    assert any("not fabrication approval" in item.lower() for item in report["non_claims"])


def test_candidate_markdown_keeps_blockers_and_non_claims_visible() -> None:
    module = _api()
    report = module.build_candidate_readiness(run_kicad=False)
    text = module.render_markdown(report)

    assert "Candidate ready: `false`" in text
    assert "Fabrication eligible: `false`" in text
    assert "## Blocking reasons" in text
    assert "## Non-claims" in text
    assert "exact_component_identity" in text


def test_require_ready_is_fail_closed_for_current_candidate(tmp_path: Path) -> None:
    module = _api()
    output = tmp_path / "readiness.json"
    markdown = tmp_path / "readiness.md"

    code = module.main(
        [
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--skip-kicad",
            "--require-ready",
        ]
    )

    assert code == 1
    assert output.is_file()
    assert markdown.is_file()


def test_quality_kicad_job_captures_candidate_readiness_artifact() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "scripts/ci_physical_candidate_readiness.py" in workflow
    assert "--require-kicad" in workflow
    assert "name: physical-candidate-readiness" in workflow


def test_kicad_operational_failure_preserves_exit_detail(monkeypatch, tmp_path: Path) -> None:
    module = _api()

    class _Result:
        def __init__(self, *, passed: bool, errors: int, message: str, exit_code: int) -> None:
            self.passed = passed
            self.available = True
            self.success = passed
            self.version = "10.0.5"
            self.errors = errors
            self.warnings = 0
            self.violation_count = errors
            self.violations = []
            self.report_sha256 = ""
            self.message = message
            self.exit_code = exit_code

    class _Oracle:
        available = True

        def run_erc(self, *_args, **_kwargs):
            return _Result(passed=False, errors=0, message="ERC failed (exit 5)", exit_code=5)

        def run_drc(self, *_args, **_kwargs):
            return _Result(passed=True, errors=0, message="0 DRC errors, 0 warnings", exit_code=0)

    schematic = tmp_path / "candidate.kicad_sch"
    pcb = tmp_path / "candidate.kicad_pcb"
    schematic.write_text("(kicad_sch)", encoding="utf-8")
    pcb.write_text("(kicad_pcb)", encoding="utf-8")
    monkeypatch.setattr(module, "detect_kicad", lambda: _Oracle())
    monkeypatch.setattr(module, "export_kicad_schematic", lambda *_args, **_kwargs: {"schematic": schematic})
    monkeypatch.setattr(module, "export_kicad_pcb", lambda *_args, **_kwargs: {"pcb": pcb})

    erc, _drc = module._kicad_checks(object(), tmp_path, run_kicad=True)

    assert erc["passed"] is False
    assert erc["exit_code"] == 5
    assert erc["message"] == "ERC failed (exit 5)"
    assert "execution failed" in erc["summary"].lower()


def test_candidate_identity_binds_component_footprint_profile_and_workflow_sources() -> None:
    module = _api()
    report = module.build_candidate_readiness(run_kicad=False)
    sources = set(report["evidence_identity"]["source_inputs"])

    assert {
        ".github/workflows/quality.yml",
        "zaptrace/algo/grid_router.py",
        "zaptrace/algo/placer.py",
        "data/library/mcu/esp32-c3-mini-1.yaml",
        "data/library/connector/usb-c-16p.yaml",
        "data/library/sensor/sht31-dis.yaml",
        "data/footprints/vendor/ESP32-C3-MINI-1.kicad_mod",
        "data/footprints/vendor/USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.kicad_mod",
        "zaptrace/fab/profiles/jlcpcb-2layer.yaml",
    } <= sources
