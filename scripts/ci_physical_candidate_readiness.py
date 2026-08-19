"""Capture fail-closed readiness evidence for the selected physical reference-board candidate."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.ee.drc.engine import DRCEngine  # noqa: E402
from zaptrace.evidence.identity import EvidenceMode, capture_evidence_identity  # noqa: E402
from zaptrace.export.kicad import export_kicad_pcb, export_kicad_schematic  # noqa: E402
from zaptrace.export.manufacturing import generate_manufacturing_bundle  # noqa: E402
from zaptrace.kicad.oracle import detect_kicad  # noqa: E402
from zaptrace.synthesis.fab import route_synthesized_design  # noqa: E402

CANDIDATE_ID = "esp32_usb_sensor_physical_rev_a"
INTENT = "ESP32-C3 USB-C 3.3V board with I2C temperature sensor"
FAB_PROFILE = "jlcpcb-2layer"
EXPECTED_MCU_MPN = "ESP32-C3-MINI-1-N4X"
EXPECTED_MCU_FOOTPRINT = "ESP32-C3-MINI-1"
EXPECTED_USB_C_MPN = "USB4105-15-A-120"
REQUIRED_CHECKS = (
    "exact_component_identity",
    "exact_esp32_c3_identity",
    "exact_usb_c_identity",
    "usb_c_sink_cc_termination",
    "footprint_resolution_complete",
    "placement_complete",
    "internal_erc_clean",
    "internal_drc_clean",
    "kicad_erc_clean",
    "kicad_drc_clean",
    "profile_bound_dfm_non_hard_fail",
)
EVIDENCE_SOURCE_INPUTS = (
    ".github/workflows/quality.yml",
    "benchmarks/esp32_usb_sensor/physical-validation-plan.json",
    "benchmarks/esp32_usb_sensor/requirements.json",
    "data/footprints/vendor/ESP32-C3-MINI-1.kicad_mod",
    "data/footprints/vendor/USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.kicad_mod",
    "data/library/connector/usb-c-16p.yaml",
    "data/library/mcu/esp32-c3-mini-1.yaml",
    "data/library/sensor/sht31-dis.yaml",
    "scripts/ci_physical_candidate_readiness.py",
    "uv.lock",
    "pyproject.toml",
    "zaptrace/algo/grid_router.py",
    "zaptrace/algo/placer.py",
    "zaptrace/ee/drc/engine.py",
    "zaptrace/evidence/identity.py",
    "zaptrace/export/kicad.py",
    "zaptrace/export/manufacturing.py",
    "zaptrace/fab/profile.py",
    "zaptrace/fab/profiles/jlcpcb-2layer.yaml",
    "zaptrace/kicad/oracle.py",
    "zaptrace/synthesis/architecture.py",
    "zaptrace/synthesis/connectors.py",
    "zaptrace/synthesis/fab.py",
    "zaptrace/synthesis/footprint_resolver.py",
    "zaptrace/synthesis/mcu.py",
    "zaptrace/synthesis/repair.py",
)


def _check(passed: bool, summary: str, **details: Any) -> dict[str, Any]:
    return {"passed": passed, "status": "passed" if passed else "failed", "summary": summary, **details}


def _not_run(summary: str) -> dict[str, Any]:
    return {"passed": False, "status": "not-run", "summary": summary}


def _populated_components(design: Any) -> list[Any]:
    return [component for component in design.components.values() if not bool(getattr(component, "dnp", False))]


def _exact_component_identity_check(design: Any) -> dict[str, Any]:
    populated = _populated_components(design)
    missing = sorted(component.ref for component in populated if not str(component.mpn or "").strip())
    return _check(
        not missing,
        "All populated components have exact orderable MPN identity."
        if not missing
        else "Some populated components still use generic identity and cannot be frozen for procurement.",
        populated_count=len(populated),
        exact_identity_count=len(populated) - len(missing),
        missing_identity_refs=missing,
    )


def _single_component(design: Any, component_type: str) -> Any | None:
    matches = [component for component in design.components.values() if component.type == component_type]
    return matches[0] if len(matches) == 1 else None


def _mcu_identity_check(design: Any) -> dict[str, Any]:
    mcu = _single_component(design, "mcu")
    passed = bool(mcu and mcu.mpn == EXPECTED_MCU_MPN and mcu.footprint == EXPECTED_MCU_FOOTPRINT)
    return _check(
        passed,
        "Selected MCU is the exact ESP32-C3-MINI-1-N4X candidate."
        if passed
        else "Selected MCU does not match the exact ESP32-C3 candidate contract.",
        ref=mcu.ref if mcu else "",
        mpn=mcu.mpn if mcu else "",
        footprint=mcu.footprint if mcu else "",
    )


def _usb_c_identity_check(design: Any) -> dict[str, Any]:
    connector = next(
        (component for component in design.components.values() if component.mpn == EXPECTED_USB_C_MPN),
        None,
    )
    return _check(
        connector is not None,
        "USB-C receptacle is bound to the exact GCT USB4105 candidate."
        if connector
        else "Exact USB-C receptacle identity is missing.",
        ref=connector.ref if connector else "",
        mpn=connector.mpn if connector else "",
        footprint=connector.footprint if connector else "",
    )


def _net_refs(design: Any, net_name: str) -> set[tuple[str, str]]:
    net = design.nets.get(net_name)
    if net is None:
        return set()
    return {(node.component_ref, node.pin_name) for node in net.nodes}


def _cc_resistor_is_grounded(design: Any, cc_net: str, connector_ref: str) -> bool:
    cc_nodes = _net_refs(design, cc_net)
    if (connector_ref, cc_net) not in cc_nodes:
        return False
    resistor_refs = {
        ref
        for ref, _pin in cc_nodes
        if ref in design.components
        and design.components[ref].type == "resistor"
        and str(design.components[ref].value).lower() in {"5.1k", "5k1"}
    }
    gnd_refs = {ref for ref, _pin in _net_refs(design, "GND")}
    return bool(resistor_refs & gnd_refs)


def _usb_c_cc_check(design: Any) -> dict[str, Any]:
    connector = next(
        (component for component in design.components.values() if component.mpn == EXPECTED_USB_C_MPN),
        None,
    )
    cc1 = bool(connector and _cc_resistor_is_grounded(design, "CC1", connector.ref))
    cc2 = bool(connector and _cc_resistor_is_grounded(design, "CC2", connector.ref))
    return _check(
        cc1 and cc2,
        "USB-C sink has independent 5.1k Rd termination on CC1 and CC2."
        if cc1 and cc2
        else "USB-C sink CC termination is incomplete.",
        cc1_terminated=cc1,
        cc2_terminated=cc2,
    )


def _footprint_check(synthesis: dict[str, Any]) -> dict[str, Any]:
    resolution = synthesis["footprints"]
    unresolved = [str(item.get("ref", "")) for item in resolution.unresolved]
    return _check(
        resolution.fully_resolved,
        "Every populated component has resolved footprint geometry."
        if resolution.fully_resolved
        else "One or more populated components lack footprint geometry.",
        resolved_count=len(resolution.resolved),
        unresolved_count=len(resolution.unresolved),
        unresolved_refs=sorted(unresolved),
    )


def _placement_check(design: Any) -> dict[str, Any]:
    populated = _populated_components(design)
    missing = sorted(component.ref for component in populated if component.position is None)
    return _check(
        not missing,
        "Every populated component has a physical placement." if not missing else "Physical placement is incomplete.",
        placed_count=len(populated) - len(missing),
        missing_placement_refs=missing,
    )


def _internal_erc_check(synthesis: dict[str, Any]) -> dict[str, Any]:
    remaining = synthesis["repair"].remaining
    return _check(
        not remaining,
        "ZapTrace synthesis ERC/repair converged with no remaining violations."
        if not remaining
        else "ZapTrace synthesis ERC still has remaining violations.",
        remaining_count=len(remaining),
    )


def _internal_drc_check(design: Any) -> dict[str, Any]:
    result = DRCEngine().run(design)
    rule_ids = sorted({violation.rule_id for violation in result.violations})
    return _check(
        result.passed,
        "ZapTrace physical DRC is clean." if result.passed else "ZapTrace physical DRC still has blocking errors.",
        errors=result.errors,
        warnings=result.warnings,
        violations=result.total_violations,
        rule_ids=rule_ids,
    )


def _dfm_check(design: Any, temp_root: Path) -> dict[str, Any]:
    bundle_dir = temp_root / "dfm"
    result = generate_manufacturing_bundle(design, bundle_dir, prefix=CANDIDATE_ID, fab_profile=FAB_PROFILE)
    readiness = json.loads(Path(result["dfm_readiness"]).read_text(encoding="utf-8"))
    violations = readiness.get("violations", [])
    rule_ids = sorted({str(item.get("rule_id", "")) for item in violations if item.get("rule_id")})
    status = str(readiness.get("status", "hard-fail"))
    passed = status != "hard-fail"
    profile = readiness.get("profile", {})
    return _check(
        passed,
        "Profile-bound DFM has no hard-fail condition."
        if passed
        else "Profile-bound DFM still contains hard-fail conditions.",
        readiness_status=status,
        violation_count=len(violations),
        rule_ids=rule_ids,
        profile={
            "name": profile.get("name", FAB_PROFILE),
            "manufacturer": profile.get("manufacturer", ""),
            "version": profile.get("version", ""),
            "sha256": profile.get("sha256", ""),
        },
    )


def _kicad_checks(design: Any, temp_root: Path, *, run_kicad: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    if not run_kicad:
        return _not_run("Official KiCad ERC was not requested."), _not_run("Official KiCad DRC was not requested.")

    oracle = detect_kicad()
    if not oracle.available:
        return _not_run("kicad-cli is unavailable."), _not_run("kicad-cli is unavailable.")

    export_dir = temp_root / "kicad"
    schematic = export_kicad_schematic(design, export_dir)["schematic"]
    pcb = export_kicad_pcb(design, export_dir)["pcb"]
    erc = oracle.run_erc(schematic, output_path=temp_root / "kicad-erc.json")
    drc = oracle.run_drc(pcb, output_path=temp_root / "kicad-drc.json")

    def oracle_check(result: Any, check_name: str) -> dict[str, Any]:
        if result.passed:
            summary = f"Official KiCad {check_name} is clean."
        elif result.errors:
            summary = f"Official KiCad {check_name} reports blocking errors."
        else:
            summary = (
                f"Official KiCad {check_name} execution failed or produced no trustworthy clean result; "
                "the candidate remains blocked."
            )
        return _check(
            result.passed,
            summary,
            available=result.available,
            success=result.success,
            version=result.version,
            exit_code=result.exit_code,
            message=result.message,
            errors=result.errors,
            warnings=result.warnings,
            violation_count=result.violation_count,
            rule_ids=sorted({item.rule for item in result.violations if item.rule}),
            report_sha256=result.report_sha256,
        )

    erc_check = oracle_check(erc, "ERC")
    drc_check = oracle_check(drc, "DRC")
    return erc_check, drc_check


def _blocking_reasons(checks: dict[str, dict[str, Any]]) -> list[str]:
    return [f"{name}: {checks[name]['summary']}" for name in REQUIRED_CHECKS if not checks[name]["passed"]]


def build_candidate_readiness(*, run_kicad: bool = True) -> dict[str, Any]:
    """Generate bounded readiness evidence without granting fabrication eligibility."""
    design, synthesis = route_synthesized_design(INTENT, name=CANDIDATE_ID)
    with tempfile.TemporaryDirectory(prefix="zaptrace-physical-candidate-") as temp_dir:
        temp_root = Path(temp_dir)
        checks = {
            "exact_component_identity": _exact_component_identity_check(design),
            "exact_esp32_c3_identity": _mcu_identity_check(design),
            "exact_usb_c_identity": _usb_c_identity_check(design),
            "usb_c_sink_cc_termination": _usb_c_cc_check(design),
            "footprint_resolution_complete": _footprint_check(synthesis),
            "placement_complete": _placement_check(design),
            "internal_erc_clean": _internal_erc_check(synthesis),
            "internal_drc_clean": _internal_drc_check(design),
        }
        kicad_erc, kicad_drc = _kicad_checks(design, temp_root, run_kicad=run_kicad)
        checks["kicad_erc_clean"] = kicad_erc
        checks["kicad_drc_clean"] = kicad_drc
        checks["profile_bound_dfm_non_hard_fail"] = _dfm_check(design, temp_root)

    identity = capture_evidence_identity(
        root=ROOT,
        mode=EvidenceMode.SNAPSHOT,
        source_inputs=EVIDENCE_SOURCE_INPUTS,
    )
    ready = all(checks[name]["passed"] for name in REQUIRED_CHECKS)
    return {
        "schema_version": "1.0",
        "candidate_id": CANDIDATE_ID,
        "family_id": "esp32_usb_sensor",
        "intent": INTENT,
        "fab_profile": FAB_PROFILE,
        "candidate_ready": ready,
        "fabrication_eligible": False,
        "checks": checks,
        "blocking_reasons": _blocking_reasons(checks),
        "non_claims": [
            "Candidate readiness evidence is not fabrication approval.",
            "A non-hard-fail DFM result is not manufacturer approval or assembly capability confirmation.",
            (
                "This evidence does not replace qualified schematic, layout, component, footprint, "
                "manufacturing, or procurement review."
            ),
            "No physical board operation, EMC, regulatory, safety, thermal, or production-readiness claim is made.",
        ],
        "evidence_identity": identity.model_dump(mode="json"),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Physical Candidate Readiness",
        "",
        f"Candidate: `{report['candidate_id']}`",
        f"Candidate ready: `{str(report['candidate_ready']).lower()}`",
        f"Fabrication eligible: `{str(report['fabrication_eligible']).lower()}`",
        f"Profile: `{report['fab_profile']}`",
        f"Source commit: `{report['evidence_identity']['source_commit']}`",
        "",
        "## Checks",
        "",
    ]
    for name in REQUIRED_CHECKS:
        check = report["checks"][name]
        lines.append(f"- `{name}`: **{check['status']}** — {check['summary']}")
    lines.extend(["", "## Blocking reasons", ""])
    if report["blocking_reasons"]:
        lines.extend(f"- {reason}" for reason in report["blocking_reasons"])
    else:
        lines.append("- None")
    lines.extend(["", "## Non-claims", ""])
    lines.extend(f"- {claim}" for claim in report["non_claims"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--skip-kicad", action="store_true")
    parser.add_argument("--require-kicad", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)

    report = build_candidate_readiness(run_kicad=not args.skip_kicad)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = render_markdown(report)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")

    if args.require_kicad:
        for name in ("kicad_erc_clean", "kicad_drc_clean"):
            if report["checks"][name]["status"] == "not-run":
                return 2
    return 1 if args.require_ready and not report["candidate_ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
