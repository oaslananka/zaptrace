#!/usr/bin/env python3
"""Evaluate a bounded component qualification cohort without trust promotion."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from zaptrace.library.loader import LibraryLoader
from zaptrace.library.qualification import (
    ComponentQualificationReport,
    evaluate_component_qualification_readiness,
    write_component_qualification_report,
)


class CohortConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)

    schema_version: str = "1.0"
    cohort_id: str = Field(min_length=1)
    as_of: date
    freshness_days: int = Field(ge=1)
    component_ids: list[str] = Field(min_length=1)


def _load_cohort(path: Path, *, repository_root: Path) -> CohortConfig:
    root = repository_root.resolve(strict=True)
    if path.is_symlink():
        raise ValueError(f"cohort config must not be a symbolic link: {path}")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError(f"cohort config is outside repository root or not a regular file: {resolved}")
    payload: Any = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    config = CohortConfig.model_validate(payload)
    if config.schema_version != "1.0":
        raise ValueError(f"unsupported cohort schema_version: {config.schema_version}")
    if len(config.component_ids) != len(set(config.component_ids)):
        raise ValueError("duplicate component id in qualification cohort")
    return config


def run_gate(
    *,
    cohort_path: Path,
    repository_root: Path,
    output_path: Path,
    report_only: bool = False,
) -> tuple[int, ComponentQualificationReport]:
    config = _load_cohort(cohort_path, repository_root=repository_root)
    report = evaluate_component_qualification_readiness(
        LibraryLoader().load_all(),
        config.component_ids,
        repository_root=repository_root,
        as_of=config.as_of,
        freshness_days=config.freshness_days,
    )
    write_component_qualification_report(report, output_path)
    return (0 if report_only or report.machine_blocked_count == 0 else 1), report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cohort",
        type=Path,
        default=Path("data/qualification/verified-core-cohort-a.yaml"),
        help="Committed bounded cohort configuration.",
    )
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Write evidence without converting known machine blockers into a passing strict gate.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    code, report = run_gate(
        cohort_path=args.cohort,
        repository_root=args.repository_root,
        output_path=args.output,
        report_only=args.report_only,
    )
    print(
        "component qualification: "
        f"ready={report.review_ready_count}/{report.component_count} "
        f"machine_blocked={report.machine_blocked_count} "
        f"human_review_required={report.human_review_required_count} "
        f"release_eligible={report.release_eligible_count} "
        f"report_sha256={report.report_sha256}"
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
