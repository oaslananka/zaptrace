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

import math
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
        result["detail"] = f"skipped: {evidence.skip_reason}"
        return result

    if evidence.status != "passed":
        result["detail"] = "grader reported failure" if evidence.status == "failed" else "invalid grader status"
        return result

    if not math.isfinite(evidence.score):
        result["detail"] = "non-finite grader score"
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
        errors = evidence.details.get("errors")
        if type(errors) is not int or errors < 0:
            result["detail"] = "missing or invalid native error count"
            return result
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
    if submission.task_id != task.task_id:
        raise ValueError("Submission task_id does not match benchmark task")
    if submission.canonical_hash and submission.canonical_hash != submission.compute_hash():
        raise ValueError("Submission evidence hash mismatch")
    expected_ids = {grader.grader_id for grader in task.graders}
    if len(expected_ids) != len(task.graders):
        raise ValueError("Benchmark task has duplicate grader IDs")
    if len({e.grader_id for e in submission.evidence}) != len(submission.evidence):
        raise ValueError("Submission contains duplicate grader evidence")
    if any(e.grader_id not in expected_ids for e in submission.evidence):
        raise ValueError("Submission contains unknown grader evidence")

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
            # Missing evidence is not proof that an external grader was unavailable.
            result = {
                "grader_id": grader.grader_id,
                "status": "failed",
                "score": 0.0,
                "passed": False,
                "detail": "missing required grader evidence",
            }
        else:
            result = _score_evidence(ev, threshold)
            if ev.status == "skipped" and (
                grader.skip_policy == "never" or not isinstance(ev.skip_reason, str) or not ev.skip_reason.strip()
            ):
                result["status"] = "failed"
                result["detail"] = "skip forbidden or missing a documented reason"
        grader_results.append(result)

        if result["status"] == "skipped":
            skipped += 1
        elif result["passed"]:
            passed += 1
            if ev is not None:
                scores.append(ev.score)
        else:
            failed += 1

    mean_score = sum(scores) / len(scores) if scores else 0.0
    overall: str
    if failed > 0 or not task.graders:
        overall = "failed"
    elif skipped > 0:
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
