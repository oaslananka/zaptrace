"""Benchmark board-family fixture coverage checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.benchmark.families import BenchmarkBoardFamily, BoardFamilyManifest, builtin_board_family_manifest


class BenchmarkArtifactCoverage(BaseModel):
    """Presence record for one required benchmark family artifact."""

    model_config = ConfigDict(strict=False)

    family_id: str
    name: str
    kind: str
    path_pattern: str
    required: bool = True
    present: bool
    matched_paths: list[str] = Field(default_factory=list)
    description: str = ""


class BenchmarkFamilyFixtureCoverage(BaseModel):
    """Coverage summary for one benchmark board family."""

    model_config = ConfigDict(strict=False)

    family_id: str
    title: str
    complete: bool
    artifact_count: int = Field(ge=0)
    present_required_artifact_count: int = Field(ge=0)
    missing_required_artifact_count: int = Field(ge=0)
    artifacts: list[BenchmarkArtifactCoverage]


class BenchmarkFixtureCoverageReport(BaseModel):
    """Repository-level coverage report for benchmark family fixtures."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    family_count: int = Field(ge=0)
    complete_family_count: int = Field(ge=0)
    incomplete_family_count: int = Field(ge=0)
    missing_required_artifact_count: int = Field(ge=0)
    complete: bool
    families: list[BenchmarkFamilyFixtureCoverage]
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "fixture coverage is repository completeness evidence, not fabrication approval",
            "a complete fixture means required files exist; it does not mean the board is electrically correct",
            "benchmark artifacts still require proof-pack gates and qualified human engineering review",
        ]
    )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _normalize(path: Path) -> str:
    return path.as_posix()


def _matched_paths(root: Path, path_pattern: str) -> list[str]:
    """Return files matching a manifest path pattern relative to ``root``."""
    root_resolved = root.resolve(strict=False)
    pattern_path = root_resolved / path_pattern
    if any(token in path_pattern for token in "*?["):
        candidates = sorted(path for path in root_resolved.glob(path_pattern) if path.is_file())
    else:
        candidates = [pattern_path] if pattern_path.is_file() else []
    return [_normalize(path.relative_to(root_resolved)) for path in candidates]


def evaluate_family_fixture_coverage(root: str | Path, family: BenchmarkBoardFamily) -> BenchmarkFamilyFixtureCoverage:
    """Evaluate committed artifact coverage for one board family."""
    root_path = Path(root)
    artifacts: list[BenchmarkArtifactCoverage] = []
    for artifact in family.required_artifacts:
        matched = _matched_paths(root_path, artifact.path_pattern)
        artifacts.append(
            BenchmarkArtifactCoverage(
                family_id=family.family_id,
                name=artifact.name,
                kind=artifact.kind,
                path_pattern=artifact.path_pattern,
                required=artifact.required,
                present=bool(matched),
                matched_paths=matched,
                description=artifact.description,
            )
        )
    missing_required = [artifact for artifact in artifacts if artifact.required and not artifact.present]
    present_required_count = sum(1 for artifact in artifacts if artifact.required and artifact.present)
    return BenchmarkFamilyFixtureCoverage(
        family_id=family.family_id,
        title=family.title,
        complete=not missing_required,
        artifact_count=len(artifacts),
        present_required_artifact_count=present_required_count,
        missing_required_artifact_count=len(missing_required),
        artifacts=artifacts,
    )


def evaluate_fixture_coverage(
    root: str | Path = ".",
    *,
    manifest: BoardFamilyManifest | None = None,
) -> BenchmarkFixtureCoverageReport:
    """Evaluate repository fixture coverage for all benchmark board families."""
    effective_manifest = manifest or builtin_board_family_manifest()
    family_reports = [evaluate_family_fixture_coverage(root, family) for family in effective_manifest.families]
    complete_count = sum(1 for family in family_reports if family.complete)
    missing_required = sum(family.missing_required_artifact_count for family in family_reports)
    return BenchmarkFixtureCoverageReport(
        family_count=len(family_reports),
        complete_family_count=complete_count,
        incomplete_family_count=len(family_reports) - complete_count,
        missing_required_artifact_count=missing_required,
        complete=missing_required == 0,
        families=family_reports,
    )


def fixture_coverage_json(report: BenchmarkFixtureCoverageReport | None = None) -> str:
    """Serialize fixture coverage as stable JSON."""
    payload = (report or evaluate_fixture_coverage()).model_dump(mode="json")
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
