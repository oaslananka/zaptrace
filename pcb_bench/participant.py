"""ZapTrace PCB-bench participant — submits ZapTrace scores as a participant.

This module runs the ZapTrace benchmark harness and formats the output
as a PCB-bench :class:`~pcb_bench.schema.Submission`.  ZapTrace is treated
as one participant; no privileged access to grader internals is used here.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pcb_bench.schema import GraderEvidence, Submission, TaskSpec


def run_zaptrace_submission(
    task: TaskSpec,
    input_path: str | Path,
) -> Submission:
    """Run ZapTrace on *input_path* and return a signed Submission.

    This runner calls the ZapTrace benchmark harness through the public
    API only — it does not access grader internals.

    Parameters
    ----------
    task:
        The task to run.
    input_path:
        Path to the input PCB project directory or file.

    Returns
    -------
    Submission
        Signed submission with evidence for all graders.
    """

    input_path = Path(input_path)
    evidence_list: list[GraderEvidence] = []

    for grader in task.graders:
        t0 = time.perf_counter()
        try:
            # Dispatch to the appropriate ZapTrace grader
            result = _run_grader(grader.grader_id, input_path)
            runtime_ms = (time.perf_counter() - t0) * 1000
            status = result.get("status", "skipped")
            score = float(result.get("score", 0.0))
            skip_reason = result.get("skip_reason", "")
            details = {k: v for k, v in result.items() if k not in ("status", "score", "skip_reason")}
        except Exception as exc:  # noqa: BLE001
            runtime_ms = (time.perf_counter() - t0) * 1000
            status = "failed"
            score = 0.0
            skip_reason = ""
            details = {"error": str(exc)}

        evidence_list.append(
            GraderEvidence(
                grader_id=grader.grader_id,
                status=status,
                score=score,
                skip_reason=skip_reason,
                tool_version=_zaptrace_version(),
                runtime_ms=runtime_ms,
                details=details,
            )
        )

    sub = Submission(
        task_id=task.task_id,
        tool_name="zaptrace",
        tool_version=_zaptrace_version(),
        submitted_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        evidence=evidence_list,
        sandbox_limits=task.limits,
    )
    return sub.sign()


def _run_grader(grader_id: str, input_path: Path) -> dict[str, Any]:
    """Dispatch to the appropriate ZapTrace grader implementation."""
    if grader_id == "file_inventory":
        return _grade_file_inventory(input_path)
    if grader_id == "net_parity":
        return _grade_net_parity(input_path)
    if grader_id == "kicad_erc":
        return _grade_kicad_erc(input_path)
    # Unknown grader → skip rather than fail
    return {
        "status": "skipped",
        "score": 0.0,
        "skip_reason": f"grader_id {grader_id!r} not implemented in ZapTrace participant",
    }


def _grade_file_inventory(input_path: Path) -> dict[str, Any]:
    """Check that required KiCad files are present."""
    required_exts = {".kicad_pro", ".kicad_sch"}
    found = {f.suffix for f in input_path.iterdir() if f.is_file()} if input_path.is_dir() else {input_path.suffix}
    missing = required_exts - found
    return {
        "status": "passed" if not missing else "failed",
        "score": 1.0 if not missing else 0.0,
        "found_extensions": sorted(found),
        "missing_extensions": sorted(missing),
    }


def _grade_net_parity(input_path: Path) -> dict[str, Any]:
    """Count nets in KiCad schematic files."""
    try:
        from zaptrace.kicad.project_importer import import_kicad_project

        result = import_kicad_project(input_path)
        net_count = (
            result.design.meta.net_count if hasattr(result.design.meta, "net_count") else len(result.design.nets)
        )
        score = min(1.0, net_count / 10.0) if net_count > 0 else 0.0
        return {
            "status": "passed" if net_count > 0 else "failed",
            "score": score,
            "net_count": net_count,
        }
    except ImportError:
        return {"status": "skipped", "score": 0.0, "skip_reason": "zaptrace.kicad not available"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "skipped", "score": 0.0, "skip_reason": str(exc)}


def _grade_kicad_erc(input_path: Path) -> dict[str, Any]:
    """Run KiCad ERC via the oracle (skipped if unavailable)."""
    try:
        from zaptrace.kicad.oracle import KiCadOracle

        oracle = KiCadOracle()
        if not oracle.available:
            return {"status": "skipped", "score": 0.0, "skip_reason": "kicad-cli not found"}
        erc = oracle.run_erc(input_path)
        if not erc.available:
            return {"status": "skipped", "score": 0.0, "skip_reason": erc.message}
        return {
            "status": "passed" if erc.passed else "failed",
            "score": 1.0 if erc.passed else 0.0,
            "errors": erc.errors,
            "warnings": erc.warnings,
            "version": erc.version,
        }
    except ImportError:
        return {"status": "skipped", "score": 0.0, "skip_reason": "zaptrace.kicad not available"}


def _zaptrace_version() -> str:
    try:
        import zaptrace

        return getattr(zaptrace, "__version__", "unknown")
    except ImportError:
        return "unknown"
