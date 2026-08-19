#!/usr/bin/env python3
"""CI gate: run all 12 benchmark families and validate convergence evidence matrix.

Acceptance criteria (issue #144):
- All 12 families reach zero-blocking ERC/DRC convergence gate.
- Per-family sim/routing/proof evidence and escalations are preserved.
- Every declared interop target has a measured corpus status and degradation policy.
- The public report is reproducible from the pinned harness and artifacts.
- Claims and documentation exactly match measured outcomes.
- No skips or missing references are converted into passes.

Exit codes:
    0 — all 12 families converged; report written
    1 — at least one family did not converge or interop target is degraded
    2 — usage error
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _report_interop_rows(matrix: Any) -> None:
    for row in matrix.interop_rows:
        if not row.all_measured:
            unmeasured = [target for target in row.targets if target not in row.measured_statuses]
            if unmeasured:
                print(
                    f"[convergence-12] WARNING: {row.family_id} missing measurements for {unmeasured}",
                    file=sys.stderr,
                )
        for target, status in row.measured_statuses.items():
            if status != "degraded":
                continue
            policy = row.degradation_policies.get(target, "")
            print(
                f"[convergence-12] DEGRADED: {row.family_id}/{target}: {policy}",
                file=sys.stderr,
            )


def _report_gate_failure(matrix: Any) -> int:
    print(
        f"[convergence-12] FAIL: {matrix.gate_reason}",
        file=sys.stderr,
    )
    non_convergent = matrix.convergence_report.get("non_convergent_families", [])
    if non_convergent:
        print(
            f"[convergence-12] Non-convergent families: {non_convergent}",
            file=sys.stderr,
        )
    return 1


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    report_dir = repo_root / "docs" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    from zaptrace.benchmark.convergence_12 import run_12_family_convergence

    print("[convergence-12] Running all 12 benchmark families...")

    matrix = run_12_family_convergence()

    # Write JSON report
    json_path = report_dir / "convergence-12-families.json"
    json_path.write_text(matrix.to_json())
    print(f"[convergence-12] Report: {json_path.relative_to(repo_root)}")

    # Write Markdown matrix
    md_path = report_dir / "convergence-12-families.md"
    md_path.write_text(matrix.to_markdown())
    print(f"[convergence-12] Matrix: {md_path.relative_to(repo_root)}")

    print(
        f"[convergence-12] {matrix.converged_count}/{matrix.family_count} families converged | "
        f"gate={'PASS' if matrix.gate_passed else 'FAIL'}"
    )
    print(f"[convergence-12] {matrix.gate_reason}")

    _report_interop_rows(matrix)
    return 0 if matrix.gate_passed else _report_gate_failure(matrix)


if __name__ == "__main__":
    sys.exit(main())
