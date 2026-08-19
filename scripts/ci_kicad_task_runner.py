"""CI gate: runner-neutral KiCad benchmark task (issue #131).

Loads every ``task.yaml`` found under ``benchmarks/kicad-task-v1/``, runs all
graders against the corpus fixtures in ``tests/corpus/kicad/``, and exits
non-zero if any grader returns ``fail`` or ``error``.  ``skip`` results are
reported but do not fail the gate.

Usage:
    python scripts/ci_kicad_task_runner.py [--task-dir TASK_DIR] [--project-dir PROJECT_DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from zaptrace.benchmark.kicad_task import TaskRunResult, load_task, run_task


def _project_directories(project_dir: Path) -> list[Path]:
    projects = sorted(path for path in project_dir.iterdir() if path.is_dir()) if project_dir.is_dir() else []
    if projects:
        return projects
    print(f"WARNING: no subdirectories found in {project_dir}; running against parent")
    return [project_dir]


def _print_task_header(spec: Any) -> None:
    print(f"\n=== Task: {spec.task_id} ({spec.name}) ===")
    print(f"    Track: {spec.track} | Graders: {len(spec.graders)}")


def _print_run(project: Path, result: TaskRunResult) -> None:
    icon = {"pass": "✓", "fail": "✗", "skip": "⊘", "error": "!"}.get(result.status, "?")
    print(f"  [{icon}] {project.name}: {result.status.upper()} (hash={result.run_hash[:12]})")
    grader_icons = {"pass": " ✓", "fail": " ✗", "skip": " ⊘", "error": " !"}
    for grader in result.grader_results:
        print(f"      {grader_icons.get(grader.status, ' ?')} {grader.grader_id}: {grader.detail[:80]}")
    for violation in result.threshold_violations:
        print(f"      VIOLATION: {violation}")


def _print_summary(results: list[TaskRunResult]) -> None:
    print(f"\n{'=' * 60}")
    print(f"Total task runs: {len(results)}")
    for status in ("pass", "fail", "skip", "error"):
        print(f"  {status}={sum(1 for result in results if result.status == status)}")


def _run_gate(task_dir: Path, project_dir: Path) -> tuple[int, list[dict[str, Any]]]:
    """Run the gate and return its exit code plus per-project evidence."""
    task_files = sorted(task_dir.glob("task.yaml"))
    if not task_files:
        print(f"ERROR: no task.yaml found under {task_dir}", file=sys.stderr)
        return 1, []

    results: list[TaskRunResult] = []
    evidence_rows: list[dict[str, Any]] = []
    for task_path in task_files:
        spec = load_task(task_path)
        _print_task_header(spec)
        for project in _project_directories(project_dir):
            result = run_task(spec, project)
            results.append(result)
            evidence_rows.append({"project": project.name, "result": result.to_dict()})
            _print_run(project, result)

    _print_summary(results)
    failed = any(result.status in {"fail", "error"} for result in results)
    return (1 if failed else 0), evidence_rows


def main() -> None:
    repo_root = Path(__file__).parent.parent
    parser = argparse.ArgumentParser(description="KiCad benchmark task runner CI gate")
    parser.add_argument(
        "--task-dir",
        type=Path,
        default=repo_root / "benchmarks" / "kicad-task-v1",
        help="Directory containing task.yaml files",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=repo_root / "tests" / "corpus" / "kicad",
        help="Directory containing KiCad project subdirectories",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write JSON results",
    )
    args = parser.parse_args()

    rc, evidence_rows = _run_gate(args.task_dir, args.project_dir)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        statuses = [str(row["result"]["status"]) for row in evidence_rows]
        report = {
            "schema_version": "1.0",
            "gate_id": "kicad-benchmark-corpus-v1",
            "task_dir": str(args.task_dir),
            "project_dir": str(args.project_dir),
            "exit_code": rc,
            "counts": {
                "runs": len(evidence_rows),
                "pass": statuses.count("pass"),
                "fail": statuses.count("fail"),
                "skip": statuses.count("skip"),
                "error": statuses.count("error"),
            },
            "results": evidence_rows,
        }
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    sys.exit(rc)


if __name__ == "__main__":
    main()
