"""PCB-bench submission and task schema (tool-neutral).

These dataclasses define the public contract between task definitions and
tool submissions.  No ZapTrace internals are imported here; third-party
tools can vendor this file.

Submission contract
-------------------
A conforming submission consists of:

1. A ``submission.json`` file in the output directory matching
   :class:`Submission` schema.
2. One evidence file per grader listed in the task (or a ``skipped`` entry).
3. All file paths in the submission are relative to the submission directory.

Security
--------
Submissions from untrusted sources are run in isolated subprocesses with
resource limits.  The runner never eval()s submission content.  See
``SECURITY.md`` in the repository root for the full policy.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Task schema
# ---------------------------------------------------------------------------


@dataclass
class GraderSpec:
    """Specification for a single grader step in a task."""

    grader_id: str
    tool: str = "builtin"
    command: list[str] = field(default_factory=list)
    skip_policy: str = "tool_unavailable"
    timeout_seconds: int = 60
    output_schema: str = "generic_v1"
    description: str = ""
    version_min: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "grader_id": self.grader_id,
            "tool": self.tool,
            "command": self.command,
            "skip_policy": self.skip_policy,
            "timeout_seconds": self.timeout_seconds,
            "output_schema": self.output_schema,
            "description": self.description,
            "version_min": self.version_min,
        }


@dataclass
class TaskSpec:
    """A versioned, tool-neutral benchmark task definition."""

    task_id: str
    task_schema_version: str = "1.0"
    name: str = ""
    track: str = ""
    description: str = ""
    graders: list[GraderSpec] = field(default_factory=list)
    thresholds: dict[str, Any] = field(default_factory=dict)
    allowed_inputs: list[str] = field(default_factory=list)
    limits: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_schema_version": self.task_schema_version,
            "task_id": self.task_id,
            "name": self.name,
            "track": self.track,
            "description": self.description,
            "graders": [g.to_dict() for g in self.graders],
            "thresholds": self.thresholds,
            "allowed_inputs": self.allowed_inputs,
            "limits": self.limits,
        }


# ---------------------------------------------------------------------------
# Submission schema
# ---------------------------------------------------------------------------


@dataclass
class GraderEvidence:
    """Evidence record for one grader in a submission."""

    grader_id: str
    status: str  # "passed" | "failed" | "skipped"
    score: float = 0.0
    skip_reason: str = ""
    tool_version: str = ""
    runtime_ms: float = 0.0
    output_hash: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "grader_id": self.grader_id,
            "status": self.status,
            "score": self.score,
            "skip_reason": self.skip_reason,
            "tool_version": self.tool_version,
            "runtime_ms": self.runtime_ms,
            "output_hash": self.output_hash,
            "details": self.details,
        }


@dataclass
class Submission:
    """A tool submission for a PCB-bench task.

    A valid submission:
    - Lists the task_id it responds to.
    - Carries one GraderEvidence per grader in the task (or a skipped entry).
    - Is signed by a canonical_hash for reproducibility verification.
    """

    task_id: str
    tool_name: str
    tool_version: str = ""
    submitted_at: str = ""
    evidence: list[GraderEvidence] = field(default_factory=list)
    canonical_hash: str = ""
    run_id: str = ""
    sandbox_limits: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Submission:
        evidence = [
            GraderEvidence(
                grader_id=e["grader_id"],
                status=e.get("status", "skipped"),
                score=float(e.get("score", 0.0)),
                skip_reason=e.get("skip_reason", ""),
                tool_version=e.get("tool_version", ""),
                runtime_ms=float(e.get("runtime_ms", 0.0)),
                output_hash=e.get("output_hash", ""),
                details=e.get("details", {}),
            )
            for e in data.get("evidence", [])
        ]
        return cls(
            task_id=data.get("task_id", ""),
            tool_name=data.get("tool_name", ""),
            tool_version=data.get("tool_version", ""),
            submitted_at=data.get("submitted_at", ""),
            evidence=evidence,
            canonical_hash=data.get("canonical_hash", ""),
            run_id=data.get("run_id", ""),
            sandbox_limits=data.get("sandbox_limits", {}),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> Submission:
        with open(path) as fh:
            return cls.from_dict(json.load(fh))

    @classmethod
    def from_dir(cls, directory: str | Path, *, task: TaskSpec | None = None) -> Submission:
        """Load a submission from a directory containing submission.json."""
        sub_file = Path(directory) / "submission.json"
        if not sub_file.is_file():
            raise FileNotFoundError(f"submission.json not found in {directory}")
        return cls.from_file(sub_file)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "submission-v1",
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "submitted_at": self.submitted_at,
            "evidence": [e.to_dict() for e in self.evidence],
            "canonical_hash": self.canonical_hash,
            "run_id": self.run_id,
            "sandbox_limits": self.sandbox_limits,
        }

    def compute_hash(self) -> str:
        """Compute a canonical SHA-256 of this submission (without run_id/timestamps)."""
        canonical = {
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "evidence": sorted(
                [
                    {
                        "grader_id": e.grader_id,
                        "status": e.status,
                        "score": round(e.score, 6),
                        "output_hash": e.output_hash,
                    }
                    for e in self.evidence
                ],
                key=lambda x: x["grader_id"],
            ),
        }
        blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    def sign(self) -> Submission:
        """Set canonical_hash from current evidence."""
        self.canonical_hash = self.compute_hash()
        return self


# ---------------------------------------------------------------------------
# Report schema
# ---------------------------------------------------------------------------


@dataclass
class ScoreReport:
    """Scoring report for a single submission against a task."""

    task_id: str
    tool_name: str
    tool_version: str = ""
    overall_status: str = "passed"  # "passed" | "failed" | "partial"
    grader_results: list[dict[str, Any]] = field(default_factory=list)
    mean_score: float = 0.0
    skipped_count: int = 0
    failed_count: int = 0
    passed_count: int = 0
    canonical_hash: str = ""
    generated_at: str = ""

    def summary(self) -> str:
        lines = [
            f"Task: {self.task_id}",
            f"Tool: {self.tool_name} {self.tool_version}",
            f"Status: {self.overall_status}",
            f"Mean score: {self.mean_score:.3f}",
            f"Passed: {self.passed_count}  Failed: {self.failed_count}  Skipped: {self.skipped_count}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "score-report-v1",
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "overall_status": self.overall_status,
            "grader_results": self.grader_results,
            "mean_score": self.mean_score,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "passed_count": self.passed_count,
            "canonical_hash": self.canonical_hash,
            "generated_at": self.generated_at,
        }
