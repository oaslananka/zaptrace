"""PCB-bench leaderboard generator — deterministic, canonical.

Consumes signed/canonical score reports and produces a deterministic leaderboard
that can be published.  ZapTrace is listed only as a participant, not a privileged
grader — all tools are scored on equal footing.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pcb_bench.schema import ScoreReport

# ---------------------------------------------------------------------------
# Leaderboard models
# ---------------------------------------------------------------------------


@dataclass
class LeaderboardEntry:
    """One row in the leaderboard."""

    rank: int
    tool_name: str
    tool_version: str
    task_id: str
    overall_status: str
    mean_score: float
    passed_count: int
    failed_count: int
    skipped_count: int
    canonical_hash: str
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "task_id": self.task_id,
            "overall_status": self.overall_status,
            "mean_score": self.mean_score,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "canonical_hash": self.canonical_hash,
            "generated_at": self.generated_at,
        }


@dataclass
class Leaderboard:
    """A ranked, deterministic leaderboard."""

    task_id: str
    generated_at: str = ""
    entries: list[LeaderboardEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "leaderboard-v1",
            "task_id": self.task_id,
            "generated_at": self.generated_at,
            "entries": [e.to_dict() for e in self.entries],
        }

    def to_markdown(self) -> str:
        """Render a Markdown table of the leaderboard."""
        lines = [
            f"# Leaderboard: {self.task_id}",
            f"_Generated: {self.generated_at}_",
            "",
            "| Rank | Tool | Version | Mean Score | Status | Passed | Failed | Skipped |",
            "| ---: | ---- | ------- | ---------: | ------ | -----: | -----: | ------: |",
        ]
        for e in self.entries:
            lines.append(
                f"| {e.rank} | {e.tool_name} | {e.tool_version or '-'} | "
                f"{e.mean_score:.4f} | {e.overall_status} | "
                f"{e.passed_count} | {e.failed_count} | {e.skipped_count} |"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Leaderboard generation
# ---------------------------------------------------------------------------


def _load_report_file(path: Path) -> ScoreReport | None:
    """Load a ScoreReport from a JSON file; return None on error."""
    try:
        with open(path) as fh:
            data = json.load(fh)
        if data.get("schema") != "score-report-v1":
            return None
        return ScoreReport(
            task_id=data.get("task_id", ""),
            tool_name=data.get("tool_name", ""),
            tool_version=data.get("tool_version", ""),
            overall_status=data.get("overall_status", "failed"),
            grader_results=data.get("grader_results", []),
            mean_score=float(data.get("mean_score", 0.0)),
            skipped_count=int(data.get("skipped_count", 0)),
            failed_count=int(data.get("failed_count", 0)),
            passed_count=int(data.get("passed_count", 0)),
            canonical_hash=data.get("canonical_hash", ""),
            generated_at=data.get("generated_at", ""),
        )
    except (OSError, KeyError, ValueError):
        return None


def generate_leaderboard(
    reports_dir: str | Path,
    *,
    task_id: str | None = None,
) -> Leaderboard:
    """Generate a deterministic leaderboard from signed score reports.

    Parameters
    ----------
    reports_dir:
        Directory containing ``*.json`` score report files.
    task_id:
        Filter to a specific task; if None, all tasks are included (first
        task_id encountered sets the board's task_id).

    Returns
    -------
    Leaderboard
        Ranked by (failed_count ASC, mean_score DESC, tool_name ASC) for
        full determinism.
    """
    reports_path = Path(reports_dir)
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    reports: list[ScoreReport] = []
    for json_file in sorted(reports_path.glob("*.json")):
        report = _load_report_file(json_file)
        if report is None:
            continue
        if task_id and report.task_id != task_id:
            continue
        reports.append(report)

    # Deduplicate by (task_id, tool_name, tool_version) — keep highest mean_score
    best: dict[tuple[str, str, str], ScoreReport] = {}
    for r in reports:
        key = (r.task_id, r.tool_name, r.tool_version)
        if key not in best or r.mean_score > best[key].mean_score:
            best[key] = r

    # Sort: fewer failures first, then higher mean_score, then alphabetical
    sorted_reports = sorted(
        best.values(),
        key=lambda r: (r.failed_count, -r.mean_score, r.tool_name),
    )

    board_task_id = task_id or (sorted_reports[0].task_id if sorted_reports else "unknown")
    entries = [
        LeaderboardEntry(
            rank=i + 1,
            tool_name=r.tool_name,
            tool_version=r.tool_version,
            task_id=r.task_id,
            overall_status=r.overall_status,
            mean_score=r.mean_score,
            passed_count=r.passed_count,
            failed_count=r.failed_count,
            skipped_count=r.skipped_count,
            canonical_hash=r.canonical_hash,
            generated_at=r.generated_at,
        )
        for i, r in enumerate(sorted_reports)
    ]

    return Leaderboard(
        task_id=board_task_id,
        generated_at=generated_at,
        entries=entries,
    )
