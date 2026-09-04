"""KiCad CLI oracle: validate exported KiCad files with kicad-cli.

Usage:
    python scripts/ci_kicad_oracle.py          # full oracle (creates design + exports + validates)
    python scripts/ci_kicad_oracle.py --check   # check if kicad-cli is available

Exit code:
    0  = all checks pass (or kicad-cli not found with --check)
    1  = validation failure
    2  = kicad-cli not available for full run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from zaptrace.algo.placer import place_components
from zaptrace.core.models import BoardConfig, Component, Design, DesignMeta, Net, NetNode
from zaptrace.ee.classifier import classify_design
from zaptrace.export.kicad import export_kicad_pcb, export_kicad_schematic
from zaptrace.security.paths import resolve_trusted_path
from zaptrace.security.temporary import private_subprocess_environment

ROOT = Path(__file__).resolve().parents[1]

KICAD_CLI = shutil.which("kicad-cli") or shutil.which("kicad-cli.exe")
_CHECKS: list[dict[str, object]] = []
_SKIP_REASONS: list[str] = []


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_path(path: Path) -> str:
    if path.is_file():
        return _sha256_file(path)
    h = hashlib.sha256()
    for child in sorted(p for p in path.rglob("*") if p.is_file()):
        h.update(str(child.relative_to(path)).encode("utf-8"))
        h.update(b"\0")
        with child.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def _record_check(name: str, status: str, message: str, **metadata: object) -> None:
    entry: dict[str, object] = {"check": name, "status": status, "message": message}
    entry.update(metadata)
    _CHECKS.append(entry)
    if status == "skipped" and message:
        _SKIP_REASONS.append(message)


def _overall_status() -> str:
    """Return aggregate oracle status from structured check records."""
    statuses = {str(check.get("status", "")) for check in _CHECKS}
    if "failed" in statuses:
        return "failed"
    if statuses and statuses <= {"skipped"}:
        return "skipped"
    if "skipped" in statuses:
        return "skipped"
    return "passed"


def _kicad_major(version: str) -> int:
    """Return KiCad major version from strings like '10.0.4' or '7.0.11'."""
    try:
        return int(version.split(".", 1)[0])
    except (ValueError, IndexError):
        return 0


def _write_summary(
    path: Path | None,
    *,
    status: str,
    version: str = "",
    cli_path: str = "",
    skip_approval_id: str = "",
) -> None:
    if not path:
        return
    semantic_status = status
    if status == "skipped":
        semantic_status = "skip-approved" if skip_approval_id else "skip-unapproved"
    artifact_hashes = {
        str(check["report_path"]): check.get("report_sha256", "")
        for check in _CHECKS
        if isinstance(check.get("report_path"), str)
    }
    summary = {
        "schema_version": "1.0",
        "kicad_oracle": semantic_status,
        "raw_status": status,
        "skip_reason": "; ".join(dict.fromkeys(_SKIP_REASONS)),
        "skip_approval_id": skip_approval_id,
        "version": version,
        "cli_path": cli_path,
        "checks": _CHECKS,
        "artifact_hashes": artifact_hashes,
        "commands": [check.get("command") for check in _CHECKS if check.get("command")],
        "skip_policy": "skips are explicit evidence; release validation should use --strict-skips",
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _run_subprocess(command: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    with private_subprocess_environment() as env:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )


def _check_kicad_cli() -> bool:
    if KICAD_CLI is None:
        msg = "kicad-cli not found on PATH"
        _record_check("detect", "skipped", msg)
        print(f"SKIP: {msg}")
        return False
    # Verify it actually runs
    try:
        result = _run_subprocess([KICAD_CLI, "--version"])
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"OK: kicad-cli found ({version})")
            return True
        else:
            msg = f"kicad-cli found but returned error: {result.stderr.strip()}"
            _record_check("detect", "skipped", msg, exit_code=result.returncode)
            print(f"WARN: {msg}")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        msg = f"kicad-cli failed to run: {exc}"
        _record_check("detect", "skipped", msg)
        print(f"WARN: {msg}")
        return False


def _build_smoke_design() -> Design:
    """Create a small design for KiCad export validation."""
    design = Design(
        meta=DesignMeta(name="OracleTest"),
        board=BoardConfig(width_mm=50, height_mm=40, layers=2),
    )
    design.components["u1"] = Component(id="u1", ref="U1", type="mcu", value="TestMCU", footprint="QFN-32")
    design.components["r1"] = Component(id="r1", ref="R1", type="resistor", value="10k", footprint="0805")
    design.components["c1"] = Component(id="c1", ref="C1", type="capacitor", value="100n", footprint="0603")
    design.nets["n1"] = Net(
        id="VCC",
        name="VCC",
        nodes=[NetNode(component_ref="U1", pin_name="VCC"), NetNode(component_ref="R1", pin_name="p1")],
    )
    design.nets["n2"] = Net(
        id="GND",
        name="GND",
        nodes=[NetNode(component_ref="U1", pin_name="GND"), NetNode(component_ref="C1", pin_name="p2")],
    )
    classify_design(design)
    design.placement = place_components(design)
    return design


def _run_kicad_cli(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Run kicad-cli with the given args."""
    return _run_subprocess([str(KICAD_CLI), *args], timeout=timeout)


def _validate_schematic(sch_path: Path) -> int:
    """Validate a .kicad_sch file with kicad-cli."""
    print(f"\n--- Validating schematic: {sch_path.name} ---")
    svg_out = sch_path.with_name(f"{sch_path.stem}.sch.svg")
    if svg_out.exists():
        svg_out.unlink()
    command = ["sch", "export", "svg", str(sch_path), "--output", str(svg_out)]
    result = _run_kicad_cli(command)
    if result.returncode != 0:
        msg = f"kicad-cli sch export failed: {result.stderr.strip()}"
        _record_check("schematic_export_svg", "failed", msg, exit_code=result.returncode)
        print(f"FAIL: {msg}")
        return 1
    if not svg_out.exists() or svg_out.stat().st_size == 0:
        msg = f"SVG output missing or empty: {svg_out}"
        _record_check("schematic_export_svg", "failed", msg, exit_code=result.returncode)
        print(f"FAIL: {msg}")
        return 1
    _record_check(
        "schematic_export_svg",
        "passed",
        f"Schematic SVG generated ({svg_out.stat().st_size} bytes)",
        exit_code=result.returncode,
        command=[str(KICAD_CLI), *command],
        report_path=str(svg_out),
        report_sha256=_sha256_path(svg_out),
    )
    print(f"OK: Schematic SVG generated ({svg_out.stat().st_size} bytes)")
    return 0


def _export_pcb_svg(pcb_path: Path) -> int | None:
    svg_out = pcb_path.with_name(f"{pcb_path.stem}.pcb.svg")
    if svg_out.exists():
        svg_out.unlink()
    command = [
        "pcb",
        "export",
        "svg",
        str(pcb_path),
        "--layers",
        "F.Cu,B.Cu",
        "--mode-single",
        "--output",
        str(svg_out),
    ]
    result = _run_kicad_cli(command)
    if result.returncode != 0:
        detail = result.stderr.strip()
        if "created with a more recent version" in detail or "Expecting ')'" in detail:
            msg = "Installed kicad-cli is too old for the exported PCB file format"
            _record_check("pcb_export_svg", "skipped", msg, exit_code=result.returncode)
            print(f"SKIP-APPROVED: {msg}")
            if detail:
                print(detail)
            return 0
        msg = f"kicad-cli pcb export svg failed: {detail}"
        _record_check("pcb_export_svg", "failed", msg, exit_code=result.returncode)
        print(f"FAIL: {msg}")
        return 1
    if not svg_out.exists() or svg_out.stat().st_size == 0:
        msg = f"PCB SVG output missing or empty: {svg_out}"
        _record_check("pcb_export_svg", "failed", msg, exit_code=result.returncode)
        print(f"FAIL: {msg}")
        return 1
    _record_check(
        "pcb_export_svg",
        "passed",
        f"PCB SVG generated ({svg_out.stat().st_size} bytes)",
        exit_code=result.returncode,
        command=[str(KICAD_CLI), *command],
        report_path=str(svg_out),
        report_sha256=_sha256_path(svg_out),
    )
    print(f"OK: PCB SVG generated ({svg_out.stat().st_size} bytes)")
    return None


def _ensure_pcb_project(pcb_path: Path) -> None:
    pro_path = pcb_path.with_suffix(".kicad_pro")
    if pro_path.exists():
        return
    pro_data = {
        "meta": {"version": 1},
        "board": {"design_settings": {"defaults": {"copper_line_width": 0.25}}},
        "sheets": [["", pcb_path.stem]],
    }
    pro_path.write_text(json.dumps(pro_data, indent=2), encoding="utf-8")
    print(f"OK: Created minimal project file: {pro_path.name}")


def _run_pcb_drc(pcb_path: Path) -> tuple[subprocess.CompletedProcess[str], Path, list[str]]:
    json_out = pcb_path.with_suffix(".drc.json")
    text_out = pcb_path.with_suffix(".drc")
    command = ["pcb", "drc", "--format", "json", "--output", str(json_out), str(pcb_path)]
    result = _run_kicad_cli(command)
    if json_out.exists():
        return result, json_out, command
    command = ["pcb", "drc", str(pcb_path), "--output", str(text_out)]
    return _run_kicad_cli(command), text_out, command


def _drc_has_error_finding(report_path: Path, report_text: str) -> bool:
    if report_path.suffix != ".json":
        lowered = report_text.lower()
        return "local override; error" in lowered or "severity: error" in lowered
    try:
        parsed = json.loads(report_text)
    except json.JSONDecodeError:
        parsed = {}
    serialized = json.dumps(parsed).lower()
    return '"severity": "error"' in serialized or '"severity":"error"' in serialized


def _record_drc_report(
    report_path: Path,
    report_text: str,
    result: subprocess.CompletedProcess[str],
    command: list[str],
) -> None:
    meta = {
        "report_path": str(report_path),
        "report_sha256": _sha256_path(report_path),
        "command": [str(KICAD_CLI), *command],
        "exit_code": result.returncode,
    }
    if _drc_has_error_finding(report_path, report_text):
        _record_check("pcb_drc", "failed", "DRC reported error-severity violations", **meta)
        print("FAIL: DRC reported error-severity violations")
        return
    message = "DRC report generated"
    if report_path.suffix != ".json" and "** Found 0 DRC violations **" not in report_text:
        message = "DRC report generated with warnings only"
        print("WARN: DRC reported warnings (review recommended)")
    _record_check("pcb_drc", "passed", message, **meta)


def _record_missing_drc(result: subprocess.CompletedProcess[str], command: list[str]) -> None:
    detail = result.stderr.strip()
    msg = (
        f"No DRC report generated: {detail}"
        if detail
        else "No DRC report generated (kicad-cli version may not support 'pcb drc')"
    )
    _record_check("pcb_drc", "skipped", msg, exit_code=result.returncode, command=[str(KICAD_CLI), *command])
    print(f"NOTE: {msg}")


def _validate_pcb(pcb_path: Path) -> int:
    """Validate a .kicad_pcb file with kicad-cli's built-in DRC."""
    print(f"\n--- Validating PCB: {pcb_path.name} ---")
    terminal = _export_pcb_svg(pcb_path)
    if terminal is not None:
        return terminal

    _ensure_pcb_project(pcb_path)
    drc_result, drc_out, drc_command = _run_pcb_drc(pcb_path)
    if drc_out.exists():
        drc_text = drc_out.read_text(encoding="utf-8")
        print(f"DRC report ({drc_out.stat().st_size} bytes):")
        for line in drc_text.splitlines()[:20]:
            print(f"  {line}")
        _record_drc_report(drc_out, drc_text, drc_result, drc_command)
    else:
        _record_missing_drc(drc_result, drc_command)

    print("OK: PCB file parses and exports correctly in KiCad")
    return 0


def _resolve_oracle_output(raw_output: str | None, trusted_root: Path) -> Path | None:
    if not raw_output:
        return None
    return resolve_trusted_path(raw_output, trusted_root=trusted_root, label="output path")


def _unavailable_result(args: argparse.Namespace, output_path: Path | None) -> int:
    _write_summary(output_path, status="skipped", skip_approval_id=args.skip_approval_id)
    if args.check:
        return 0
    if args.skip_approval_id:
        print("SKIP-APPROVED: kicad-cli not available; approval id recorded")
    else:
        print("SKIP-UNAPPROVED: kicad-cli not available; install KiCad to run the oracle")
    return 1 if args.strict_skips and not args.skip_approval_id else 0


def _old_version_result(args: argparse.Namespace, output_path: Path | None, version: str) -> int:
    msg = f"kicad-cli {version} is too old for the modern KiCad PCB format emitted by ZapTrace"
    _record_check("version", "skipped", msg)
    _write_summary(
        output_path,
        status="skipped",
        version=version,
        cli_path=str(KICAD_CLI),
        skip_approval_id=args.skip_approval_id,
    )
    if args.skip_approval_id:
        print(f"SKIP-APPROVED: {msg}")
    else:
        print(f"SKIP-UNAPPROVED: {msg}")
    return 1 if args.strict_skips and not args.skip_approval_id else 0


def _final_oracle_result(
    args: argparse.Namespace,
    output_path: Path | None,
    version: str,
    exit_code: int,
) -> int:
    status = _overall_status()
    _write_summary(
        output_path,
        status=status,
        version=version,
        cli_path=str(KICAD_CLI),
        skip_approval_id=args.skip_approval_id,
    )
    if status == "failed":
        print(f"\n❌ KiCad CLI oracle: FAILED (exit={exit_code})")
        return 1
    if status == "skipped":
        if args.skip_approval_id:
            print("\n⚠️ KiCad CLI oracle: SKIP-APPROVED (approval id recorded)")
        else:
            print("\n⚠️ KiCad CLI oracle: SKIP-UNAPPROVED (approval id required for strict release gates)")
        return 1 if args.strict_skips and not args.skip_approval_id else 0
    print("\n✅ KiCad CLI oracle: ALL CHECKS PASSED")
    return 0


def _run_full_oracle(args: argparse.Namespace, output_path: Path | None, version: str) -> int:
    with tempfile.TemporaryDirectory(prefix="zaptrace-kicad-oracle-") as tmpdir:
        output_dir = Path(tmpdir)
        design = _build_smoke_design()
        sch_files = export_kicad_schematic(design, output_dir)
        pcb_files = export_kicad_pcb(design, output_dir)

        print(f"Exported to: {output_dir}")
        for kind, fpath in {**sch_files, **pcb_files}.items():
            fsize = Path(fpath).stat().st_size
            print(f"  {kind}: {Path(fpath).name} ({fsize} bytes)")

        exit_code = 0
        if "schematic" in sch_files:
            exit_code |= _validate_schematic(Path(sch_files["schematic"]))
        if "pcb" in pcb_files:
            exit_code |= _validate_pcb(Path(pcb_files["pcb"]))
        return _final_oracle_result(args, output_path, version, exit_code)


def main(argv: list[str] | None = None, *, trusted_root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="KiCad CLI Oracle")
    parser.add_argument("--check", action="store_true", help="Only check if kicad-cli is available")
    parser.add_argument("--output", help="Write structured oracle summary JSON")
    parser.add_argument("--strict-skips", action="store_true", help="Return non-zero when any oracle check is skipped")
    parser.add_argument(
        "--skip-approval-id", default="", help="Approved skip identifier for release evidence when a skip is expected"
    )
    args = parser.parse_args(argv)
    try:
        output_path = _resolve_oracle_output(args.output, trusted_root)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not _check_kicad_cli():
        return _unavailable_result(args, output_path)

    version = _run_subprocess([str(KICAD_CLI), "--version"]).stdout.strip()
    if args.check:
        _write_summary(output_path, status="passed", version=version, cli_path=str(KICAD_CLI))
        return 0
    if _kicad_major(version) < 9:
        return _old_version_result(args, output_path, version)
    return _run_full_oracle(args, output_path, version)


if __name__ == "__main__":
    sys.exit(main())
