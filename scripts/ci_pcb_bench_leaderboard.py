#!/usr/bin/env python3
"""CI gate: run the PCB-bench leaderboard workflow and validate outputs.

Exit codes:
    0 — all tasks generated valid reports
    1 — at least one report failed or could not be scored
    2 — usage error
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    benchmarks_dir = repo_root / "benchmarks"
    reports_dir = repo_root / "docs" / "reports" / "pcb-bench"
    reports_dir.mkdir(parents=True, exist_ok=True)

    from pcb_bench import load_task, score_submission
    from pcb_bench.leaderboard import generate_leaderboard
    from pcb_bench.participant import run_zaptrace_submission

    task_files = list(benchmarks_dir.rglob("task.yaml"))
    if not task_files:
        print("No task.yaml files found under benchmarks/", file=sys.stderr)
        return 2

    all_passed = True
    for task_file in sorted(task_files):
        try:
            task = load_task(task_file)
            print(f"[pcb-bench] task: {task.task_id}")

            # Use the first KiCad corpus fixture as input (if available)
            kicad_corpus = repo_root / "tests" / "corpus" / "kicad"
            if kicad_corpus.is_dir():
                input_dirs = [d for d in kicad_corpus.iterdir() if d.is_dir()]
                input_path = input_dirs[0] if input_dirs else kicad_corpus
            else:
                input_path = kicad_corpus  # will produce skipped evidence

            sub = run_zaptrace_submission(task, input_path=input_path)
            report = score_submission(sub, task)

            # Write report
            report_file = reports_dir / f"{task.task_id}.json"
            report_file.write_text(json.dumps(report.to_dict(), indent=2))
            print(f"  status={report.overall_status} mean_score={report.mean_score:.4f}")
            print(f"  report: {report_file.relative_to(repo_root)}")

            if report.overall_status == "failed":
                all_passed = False

        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}", file=sys.stderr)
            all_passed = False

    # Generate leaderboard
    try:
        board = generate_leaderboard(reports_dir)
        board_file = reports_dir / "leaderboard.json"
        board_file.write_text(json.dumps(board.to_dict(), indent=2))
        md_file = reports_dir / "leaderboard.md"
        md_file.write_text(board.to_markdown())
        print(f"[pcb-bench] leaderboard: {board_file.relative_to(repo_root)} ({len(board.entries)} entries)")
    except Exception as exc:  # noqa: BLE001
        print(f"[pcb-bench] leaderboard generation failed: {exc}", file=sys.stderr)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
