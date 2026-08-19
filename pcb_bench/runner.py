"""PCB-bench submission scorer — deterministic, tool-neutral.

Scores a :class:`~pcb_bench.schema.Submission` against a
:class:`~pcb_bench.schema.TaskSpec`.  ZapTrace is treated as one participant;
no ZapTrace internals are privileged here.

Sandbox policy
--------------
- Submissions are never exec()ed or eval()ed.
- Resource limits (``max_runtime_seconds``, ``max_memory_mb``) are read
  from the task ``limits`` block; external tool execution is not performed
  by this module (that belongs in the CI runner).
- All scoring is deterministic given the same evidence input.
"""

from __future__ import annotations

import time
from typing import Any

from pcb_bench.schema import GraderEvidence, ScoreReport, Submission, TaskSpec

# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------


def _score_evidence(evidence: GraderEvidence, threshold: dict[str, Any]) -> dict[str, Any]:
    """Score one grader's evidence against the task threshold."""
    result: dict[str, Any] = {
        "grader_id": evidence.grader_id,
        "status": evidence.status,
        "score": evidence.score,
        "passed": False,
        "detail": "",
    }

    if evidence.status == "skipped":
        result["passed"] = True  # skipped counts as pass (not a false failure)
        result["detail"] = f"skipped: {evidence.skip_reason}"
        return result

    if evidence.status == "failed":
        result["passed"] = False
        result["detail"] = "grader reported failure"
        return result

    # status == "passed" — check threshold
    if "min_score" in threshold:
        min_score = float(threshold["min_score"])
        result["passed"] = evidence.score >= min_score
        result["detail"] = (
            f"score {evidence.score:.4f} >= {min_score}"
            if result["passed"]
            else f"score {evidence.score:.4f} < {min_score}"
        )
    elif "max_errors" in threshold:
        max_errors = int(threshold["max_errors"])
        errors = int(evidence.details.get("errors", 0))
        result["passed"] = errors <= max_errors
        result["detail"] = f"{errors} errors vs max {max_errors}"
    else:
        # No threshold — pass/fail based on status alone
        result["passed"] = evidence.status == "passed"
        result["detail"] = evidence.status

    return result


def score_submission(submission: Submission, task: TaskSpec) -> ScoreReport:
    """Score a submission against a task and return a deterministic ScoreReport.

    Parameters
    ----------
    submission:
        The tool's submission to score.
    task:
        The task definition (from ``load_task()``).

    Returns
    -------
    ScoreReport
        Deterministic scoring report with per-grader results and summary.
    """
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Build a lookup: grader_id → evidence
    evidence_by_id = {e.grader_id: e for e in submission.evidence}

    grader_results: list[dict[str, Any]] = []
    scores: list[float] = []
    passed = skipped = failed = 0

    for grader in task.graders:
        threshold = task.thresholds.get(grader.grader_id, {})
        ev = evidence_by_id.get(grader.grader_id)

        if ev is None:
            # Missing evidence → implicit skip
            ev = GraderEvidence(
                grader_id=grader.grader_id,
                status="skipped",
                skip_reason="no evidence provided",
            )

        result = _score_evidence(ev, threshold)
        grader_results.append(result)

        if result["status"] == "skipped":
            skipped += 1
        elif result["passed"]:
            passed += 1
            scores.append(ev.score)
        else:
            failed += 1

    mean_score = sum(scores) / len(scores) if scores else 0.0
    overall: str
    if failed > 0:
        overall = "failed"
    elif skipped > 0 and passed == 0:
        overall = "partial"
    else:
        overall = "passed"

    return ScoreReport(
        task_id=task.task_id,
        tool_name=submission.tool_name,
        tool_version=submission.tool_version,
        overall_status=overall,
        grader_results=grader_results,
        mean_score=mean_score,
        skipped_count=skipped,
        failed_count=failed,
        passed_count=passed,
        canonical_hash=submission.canonical_hash or submission.compute_hash(),
        generated_at=generated_at,
    )
