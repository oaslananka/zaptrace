from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

PLAN = Path("benchmarks/esp32_usb_sensor/physical-validation-plan.json")


def _api():
    from scripts.ci_physical_validation_plan import evaluate_plan, main

    return evaluate_plan, main


def _copy_plan(tmp_path: Path) -> Path:
    target = tmp_path / "physical-validation-plan.json"
    shutil.copyfile(PLAN, target)
    return target


def test_committed_physical_validation_plan_is_valid_but_not_fabrication_eligible() -> None:
    evaluate_plan, _ = _api()
    report = evaluate_plan(PLAN, trusted_root=Path("."))

    assert report["passed"] is True
    assert report["family_id"] == "esp32_usb_sensor"
    assert report["status"] == "pre-fabrication-candidate"
    assert report["human_review"]["status"] == "pending"
    assert report["fabrication"]["eligible"] is False
    assert report["fabrication"]["ordered_bundle_sha256"] is None
    assert report["blocking_reasons"]
    assert "starter fixture" in " ".join(report["non_claims"]).lower()


def test_plan_rejects_starter_fixture_as_fabrication_source(tmp_path: Path) -> None:
    path = _copy_plan(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["fabrication"]["eligible"] = True
    payload["fabrication"]["source_path"] = "benchmarks/esp32_usb_sensor/golden/esp32_usb_sensor.kicad_pcb"
    payload["fabrication"]["ordered_bundle_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    evaluate_plan, _ = _api()
    report = evaluate_plan(path, trusted_root=tmp_path)

    assert report["passed"] is False
    assert any("starter fixture" in reason.lower() for reason in report["violations"])


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("power_scope", "supply_current_limit_a"),
        ("power_scope", "stop_conditions"),
        ("measurement_program", "required_measurements"),
        ("measurement_program", "instrument_metadata_required"),
        ("correlation_report", "required_fields"),
    ],
)
def test_plan_requires_pre_fabrication_safety_and_measurement_contract(
    tmp_path: Path, section: str, field: str
) -> None:
    path = _copy_plan(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload[section][field]
    path.write_text(json.dumps(payload), encoding="utf-8")

    evaluate_plan, _ = _api()
    report = evaluate_plan(path, trusted_root=tmp_path)

    assert report["passed"] is False
    assert any(f"{section}.{field}" in reason for reason in report["violations"])


def test_plan_requires_core_measurement_kinds(tmp_path: Path) -> None:
    path = _copy_plan(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["measurement_program"]["required_measurements"] = ["vbus_voltage", "rail_3v3_voltage"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    evaluate_plan, _ = _api()
    report = evaluate_plan(path, trusted_root=tmp_path)

    assert report["passed"] is False
    assert any("required measurement" in reason.lower() for reason in report["violations"])


def test_cli_writes_machine_and_human_readable_evidence(tmp_path: Path) -> None:
    output = tmp_path / "plan-gate.json"
    markdown = tmp_path / "plan-gate.md"

    _, main = _api()
    assert main(["--plan", str(PLAN), "--output", str(output), "--markdown", str(markdown), "--strict"]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    text = markdown.read_text(encoding="utf-8")

    assert payload["schema_version"] == "2.0"
    assert payload["passed"] is True
    assert payload["fabrication"]["eligible"] is False
    assert len(payload["evidence_identity"]["source_commit"]) == 40
    assert len(payload["evidence_identity"]["identity_sha256"]) == 64
    assert "Physical Validation Plan Gate" in text
    assert "Fabrication eligible: `false`" in text


def test_cli_bootstraps_repository_imports_without_installed_project(tmp_path: Path) -> None:
    output = tmp_path / "isolated.json"
    purelib = sysconfig.get_paths()["purelib"]
    root = str(Path.cwd())
    runner = (
        "import runpy,sys; "
        f"sys.path=[p for p in sys.path if p not in ('', {root!r})]; "
        f"sys.path.append({purelib!r}); "
        "sys.argv=['scripts/ci_physical_validation_plan.py','--plan',"
        f"{str(PLAN)!r},'--output',{str(output)!r},'--strict']; "
        "runpy.run_path('scripts/ci_physical_validation_plan.py', run_name='__main__')"
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", runner],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is True


def _function_node(name: str) -> ast.FunctionDef:
    tree = ast.parse(Path("scripts/ci_physical_validation_plan.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function not found: {name}")


def test_evaluate_plan_remains_a_low_complexity_orchestrator() -> None:
    node = _function_node("evaluate_plan")
    decision_nodes = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.Match,
        ast.IfExp,
        ast.BoolOp,
    )
    decision_count = sum(isinstance(child, decision_nodes) for child in ast.walk(node))

    assert decision_count <= 6


def test_cli_exception_handler_does_not_repeat_value_error_subclasses() -> None:
    node = _function_node("main")
    caught_names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.ExceptHandler) or child.type is None:
            continue
        types = child.type.elts if isinstance(child.type, ast.Tuple) else [child.type]
        for caught in types:
            if isinstance(caught, ast.Name):
                caught_names.add(caught.id)
            elif isinstance(caught, ast.Attribute):
                caught_names.add(caught.attr)

    assert not ({"ValueError", "JSONDecodeError"} <= caught_names)


def test_board_selection_decision_is_approved_without_granting_engineering_review() -> None:
    evaluate_plan, _ = _api()
    report = evaluate_plan(PLAN, trusted_root=Path("."))

    decision = report.get("selection_decision", {})
    assert decision.get("status") == "approved"
    assert decision.get("scope") == "board-selection-only"
    assert decision.get("decided_by") == "oaslananka"
    assert decision.get("decided_at")
    assert report["human_review"]["status"] == "pending"
    assert report["fabrication"]["eligible"] is False


def test_blocked_design_readiness_prevents_fabrication_eligibility(tmp_path: Path) -> None:
    path = _copy_plan(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["selection_decision"] = {
        "status": "approved",
        "scope": "board-selection-only",
        "decided_by": "oaslananka",
        "decided_at": "2026-08-19T03:18:09Z",
        "selected_family": "esp32_usb_sensor",
        "non_claim": "Board selection only; not fabrication approval.",
    }
    payload["design_readiness"] = {
        "status": "blocked",
        "required_checks": [
            "exact_component_identity",
            "usb_c_sink_cc_termination",
            "footprint_resolution_complete",
            "placement_complete",
            "internal_erc_clean",
            "internal_drc_clean",
            "kicad_erc_clean",
            "kicad_drc_clean",
            "profile_bound_dfm_non_hard_fail",
        ],
        "blocking_reasons": ["official KiCad ERC/DRC and profile-bound DFM are not yet clean"],
    }
    payload["human_review"] = {
        "status": "approved",
        "reviewer": "qualified-reviewer",
        "reviewed_at": "2026-08-19T03:18:09Z",
        "required_scopes": ["schematic", "layout", "component-and-footprint", "manufacturing"],
    }
    payload["fabrication"]["eligible"] = True
    payload["fabrication"]["source_path"] = "physical-validation/esp32-usb-sensor/rev-a/board.kicad_pcb"
    payload["fabrication"]["ordered_bundle_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    evaluate_plan, _ = _api()
    report = evaluate_plan(path, trusted_root=tmp_path)

    assert report["passed"] is False
    assert any("design readiness" in reason.lower() for reason in report["violations"])


def test_plan_blockers_reflect_routing_recovery_without_pour_overclaim() -> None:
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    blockers = "\n".join(payload["design_readiness"]["blocking_reasons"])

    assert "all six non-ground nets" in blockers
    assert "GND pour connectivity" in blockers
    assert "passes ZapTrace internal physical DRC" not in blockers
