"""Tests for PCB-bench package (issue #142).

Validates the submission schema, task loader, scorer, and leaderboard generator.
All tests pass without KiCad installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcb_bench.leaderboard import generate_leaderboard
from pcb_bench.loader import load_task
from pcb_bench.participant import run_zaptrace_submission
from pcb_bench.runner import score_submission
from pcb_bench.schema import (
    GraderEvidence,
    GraderSpec,
    Submission,
    TaskSpec,
)

# ---------------------------------------------------------------------------
# TaskSpec and GraderSpec
# ---------------------------------------------------------------------------


class TestTaskSpec:
    def test_to_dict_has_all_fields(self):
        task = TaskSpec(task_id="test-001")
        d = task.to_dict()
        for key in [
            "task_schema_version",
            "task_id",
            "name",
            "track",
            "description",
            "graders",
            "thresholds",
            "allowed_inputs",
            "limits",
        ]:
            assert key in d

    def test_grader_spec_to_dict(self):
        g = GraderSpec(grader_id="file_inventory", tool="builtin")
        d = g.to_dict()
        assert d["grader_id"] == "file_inventory"
        assert d["tool"] == "builtin"


# ---------------------------------------------------------------------------
# Submission schema
# ---------------------------------------------------------------------------


class TestSubmission:
    def test_from_dict_roundtrip(self):
        data = {
            "task_id": "kicad-rt-001",
            "tool_name": "my-tool",
            "tool_version": "1.0",
            "submitted_at": "2024-01-01T00:00:00Z",
            "evidence": [
                {
                    "grader_id": "file_inventory",
                    "status": "passed",
                    "score": 1.0,
                    "skip_reason": "",
                    "tool_version": "1.0",
                    "runtime_ms": 10.0,
                    "output_hash": "",
                    "details": {},
                }
            ],
            "canonical_hash": "",
            "run_id": "run-1",
            "sandbox_limits": {},
        }
        sub = Submission.from_dict(data)
        assert sub.task_id == "kicad-rt-001"
        assert len(sub.evidence) == 1
        assert sub.evidence[0].grader_id == "file_inventory"

    def test_to_dict_schema_label(self):
        sub = Submission(task_id="t1", tool_name="tool")
        d = sub.to_dict()
        assert d["schema"] == "submission-v1"

    def test_compute_hash_deterministic(self):
        sub = Submission(
            task_id="t1",
            tool_name="tool",
            evidence=[GraderEvidence(grader_id="g1", status="passed", score=1.0)],
        )
        h1 = sub.compute_hash()
        h2 = sub.compute_hash()
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_sign_sets_hash(self):
        sub = Submission(task_id="t1", tool_name="tool")
        assert sub.canonical_hash == ""
        sub.sign()
        assert len(sub.canonical_hash) == 64

    def test_from_file(self, tmp_path: Path):
        sub = Submission(task_id="t1", tool_name="tool")
        sub.sign()
        f = tmp_path / "submission.json"
        f.write_text(json.dumps(sub.to_dict()))
        loaded = Submission.from_file(f)
        assert loaded.task_id == "t1"
        assert loaded.canonical_hash == sub.canonical_hash

    def test_from_dir(self, tmp_path: Path):
        sub = Submission(task_id="t1", tool_name="tool")
        sub.sign()
        (tmp_path / "submission.json").write_text(json.dumps(sub.to_dict()))
        loaded = Submission.from_dir(tmp_path)
        assert loaded.task_id == "t1"


# ---------------------------------------------------------------------------
# Task loader
# ---------------------------------------------------------------------------


class TestLoadTask:
    def test_loads_existing_task(self):
        task_file = Path("benchmarks/kicad-task-v1/task.yaml")
        if not task_file.is_file():
            pytest.skip("task.yaml not found")
        task = load_task(task_file)
        assert task.task_id == "kicad-rt-001"
        assert len(task.graders) >= 3

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_task("/nonexistent/task.yaml")

    def test_missing_task_id_raises(self, tmp_path: Path):
        f = tmp_path / "task.yaml"
        f.write_text("graders: []\n")
        with pytest.raises(ValueError):
            load_task(f)

    def test_minimal_task(self, tmp_path: Path):
        f = tmp_path / "task.yaml"
        f.write_text("task_id: test-minimal\nname: Minimal Test\n")
        task = load_task(f)
        assert task.task_id == "test-minimal"
        assert task.graders == []


# ---------------------------------------------------------------------------
# ZapTrace participant
# ---------------------------------------------------------------------------


class TestZapTraceParticipant:
    def test_dispatch_uses_grader_id_not_tool_metadata(self, tmp_path: Path):
        (tmp_path / "board.kicad_pro").write_text("")
        (tmp_path / "board.kicad_sch").write_text("")
        task = TaskSpec(
            task_id="participant-dispatch",
            graders=[GraderSpec(grader_id="file_inventory", tool="external-tool-label")],
        )

        submission = run_zaptrace_submission(task, tmp_path)

        assert len(submission.evidence) == 1
        assert submission.evidence[0].grader_id == "file_inventory"
        assert submission.evidence[0].status == "passed"
        assert submission.evidence[0].score == 1.0


# ---------------------------------------------------------------------------
# Submission scorer
# ---------------------------------------------------------------------------


class TestScoreSubmission:
    def _make_task(self) -> TaskSpec:
        return TaskSpec(
            task_id="test-001",
            graders=[
                GraderSpec(grader_id="file_inventory", tool="builtin"),
                GraderSpec(grader_id="net_parity", tool="builtin"),
            ],
            thresholds={"file_inventory": {}, "net_parity": {"min_score": 0.0}},
        )

    def test_all_passed(self):
        task = self._make_task()
        sub = Submission(
            task_id="test-001",
            tool_name="test-tool",
            evidence=[
                GraderEvidence(grader_id="file_inventory", status="passed", score=1.0),
                GraderEvidence(grader_id="net_parity", status="passed", score=0.8),
            ],
        )
        report = score_submission(sub, task)
        assert report.overall_status == "passed"
        assert report.passed_count == 2
        assert report.failed_count == 0

    def test_one_failed(self):
        task = self._make_task()
        sub = Submission(
            task_id="test-001",
            tool_name="test-tool",
            evidence=[
                GraderEvidence(grader_id="file_inventory", status="failed", score=0.0),
                GraderEvidence(grader_id="net_parity", status="passed", score=0.8),
            ],
        )
        report = score_submission(sub, task)
        assert report.overall_status == "failed"
        assert report.failed_count == 1

    def test_all_skipped(self):
        task = self._make_task()
        sub = Submission(
            task_id="test-001",
            tool_name="test-tool",
            evidence=[
                GraderEvidence(grader_id="file_inventory", status="skipped", skip_reason="tool unavailable"),
                GraderEvidence(grader_id="net_parity", status="skipped", skip_reason="no input"),
            ],
        )
        report = score_submission(sub, task)
        assert report.skipped_count == 2
        assert report.overall_status == "partial"

    def test_missing_evidence_is_implicit_skip(self):
        task = self._make_task()
        sub = Submission(task_id="test-001", tool_name="test-tool", evidence=[])
        report = score_submission(sub, task)
        assert report.skipped_count == 2

    def test_score_report_schema(self):
        task = self._make_task()
        sub = Submission(task_id="test-001", tool_name="test-tool")
        report = score_submission(sub, task)
        d = report.to_dict()
        assert d["schema"] == "score-report-v1"
        for key in ["task_id", "tool_name", "overall_status", "mean_score", "grader_results"]:
            assert key in d

    def test_min_score_threshold(self):
        task = TaskSpec(
            task_id="t1",
            graders=[GraderSpec(grader_id="net_parity")],
            thresholds={"net_parity": {"min_score": 0.9}},
        )
        sub = Submission(
            task_id="t1",
            tool_name="tool",
            evidence=[GraderEvidence(grader_id="net_parity", status="passed", score=0.5)],
        )
        report = score_submission(sub, task)
        assert report.overall_status == "failed"

    def test_summary_string(self):
        task = self._make_task()
        sub = Submission(task_id="test-001", tool_name="test-tool")
        report = score_submission(sub, task)
        summary = report.summary()
        assert "test-001" in summary
        assert "test-tool" in summary


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


class TestLeaderboard:
    def _make_report(self, tmp_path: Path, tool: str, score: float, failed: int = 0) -> None:
        report = {
            "schema": "score-report-v1",
            "task_id": "test-001",
            "tool_name": tool,
            "tool_version": "1.0",
            "overall_status": "failed" if failed > 0 else "passed",
            "grader_results": [],
            "mean_score": score,
            "skipped_count": 0,
            "failed_count": failed,
            "passed_count": 2 - failed,
            "canonical_hash": "abc123",
            "generated_at": "2024-01-01T00:00:00Z",
        }
        (tmp_path / f"{tool}.json").write_text(json.dumps(report))

    def test_generates_from_reports(self, tmp_path: Path):
        self._make_report(tmp_path, "tool-a", 0.9)
        self._make_report(tmp_path, "tool-b", 0.7)
        board = generate_leaderboard(tmp_path)
        assert board.task_id == "test-001"
        assert len(board.entries) == 2

    def test_ranking_by_score(self, tmp_path: Path):
        self._make_report(tmp_path, "low-scorer", 0.3)
        self._make_report(tmp_path, "high-scorer", 0.95)
        board = generate_leaderboard(tmp_path)
        assert board.entries[0].tool_name == "high-scorer"
        assert board.entries[0].rank == 1

    def test_failures_rank_last(self, tmp_path: Path):
        self._make_report(tmp_path, "failing-tool", 0.9, failed=1)
        self._make_report(tmp_path, "passing-tool", 0.5, failed=0)
        board = generate_leaderboard(tmp_path)
        assert board.entries[0].tool_name == "passing-tool"

    def test_empty_dir(self, tmp_path: Path):
        board = generate_leaderboard(tmp_path)
        assert board.entries == []

    def test_schema_label(self, tmp_path: Path):
        board = generate_leaderboard(tmp_path)
        d = board.to_dict()
        assert d["schema"] == "leaderboard-v1"

    def test_markdown_output(self, tmp_path: Path):
        self._make_report(tmp_path, "zaptrace", 0.85)
        board = generate_leaderboard(tmp_path)
        md = board.to_markdown()
        assert "Leaderboard" in md
        assert "zaptrace" in md

    def test_task_id_filter(self, tmp_path: Path):
        self._make_report(tmp_path, "tool-a", 0.9)
        board = generate_leaderboard(tmp_path, task_id="other-task")
        assert board.entries == []

    def test_deduplication_keeps_best(self, tmp_path: Path):
        # Two reports for same tool — lower score first, then higher
        self._make_report(tmp_path, "tool-x", 0.4)
        # Overwrite with higher score
        report_high = json.loads((tmp_path / "tool-x.json").read_text())
        report_high["mean_score"] = 0.9
        (tmp_path / "tool-x-v2.json").write_text(json.dumps(report_high))
        board = generate_leaderboard(tmp_path)
        assert len(board.entries) == 1
        assert board.entries[0].mean_score == pytest.approx(0.9)
