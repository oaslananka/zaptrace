"""Interop track for the runner-neutral benchmark harness (issue #132).

Scores cross-EDA round-trip fidelity across five categories:
  connectivity, components, geometry, metadata, degradation_completeness.

The interop runner never imports ZapTrace internals — it reads the
canonical category scores from an evidence YAML file produced by the
conversion pipeline (or a synthetic fixture for testing), so a third-party
runner can reproduce the score from a clean clone.

Public surface
--------------
InteropCategory     – category identifiers
InteropCategorySpec – per-category threshold in a task YAML
InteropTaskSpec     – full interop-track task loaded from YAML
CategoryScore       – measured score for one category
InteropTrackResult  – aggregated deterministic interop-track result
load_interop_task   – parse an interop-track YAML
run_interop_task    – score a project evidence YAML against thresholds
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INTEROP_SCHEMA_VERSION = "1.0"
_SENTINEL_RUN_ID = "RUN-CANONICAL"

InteropCategory = Literal[
    "connectivity",
    "components",
    "geometry",
    "metadata",
    "degradation_completeness",
]

ALL_CATEGORIES: tuple[InteropCategory, ...] = (
    "connectivity",
    "components",
    "geometry",
    "metadata",
    "degradation_completeness",
)

# ---------------------------------------------------------------------------
# Schema types
# ---------------------------------------------------------------------------


@dataclass
class InteropCategorySpec:
    """Threshold for one interop category."""

    category: str  # one of InteropCategory literals
    min_score: float = 0.75
    required: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> InteropCategorySpec:
        return cls(
            category=d["category"],
            min_score=float(d.get("min_score", 0.75)),
            required=bool(d.get("required", True)),
        )


@dataclass
class InteropTaskSpec:
    """Full interop-track task loaded from YAML."""

    task_schema_version: str
    task_id: str
    name: str
    categories: list[InteropCategorySpec]
    source_format: str  # e.g. "kicad", "easyeda_pro", "altium"
    target_format: str  # e.g. "easyeda_pro", "kicad"
    description: str = ""
    limits: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> InteropTaskSpec:
        return cls(
            task_schema_version=d.get("task_schema_version", INTEROP_SCHEMA_VERSION),
            task_id=d["task_id"],
            name=d["name"],
            description=d.get("description", ""),
            source_format=d.get("source_format", "kicad"),
            target_format=d.get("target_format", "easyeda_pro"),
            categories=[InteropCategorySpec.from_dict(c) for c in d.get("categories", [])],
            limits=d.get("limits", {}),
        )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CategoryScore:
    """Measured score for one interop category."""

    category: str
    score: float  # 0.0–1.0
    threshold: float
    passed: bool
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InteropTrackResult:
    """Aggregated deterministic interop-track result."""

    task_id: str
    run_id: str
    source_format: str
    target_format: str
    category_scores: list[CategoryScore] = field(default_factory=list)
    threshold_violations: list[str] = field(default_factory=list)
    status: Literal["pass", "fail", "skip", "error"] = "pass"
    run_hash: str = ""
    schema_version: str = INTEROP_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def compute_hash(self) -> str:
        canonical = self.to_dict()
        canonical["run_id"] = _SENTINEL_RUN_ID
        canonical.pop("run_hash", None)
        blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    @property
    def mean_score(self) -> float:
        if not self.category_scores:
            return 0.0
        return sum(c.score for c in self.category_scores) / len(self.category_scores)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_interop_task(path: Path) -> InteropTaskSpec:
    """Parse an interop-track YAML file."""
    raw = yaml.safe_load(path.read_text())
    return InteropTaskSpec.from_dict(raw)


# ---------------------------------------------------------------------------
# Evidence file schema
# ---------------------------------------------------------------------------

# Evidence YAML produced by the conversion pipeline has this shape:
#
#   evidence_schema_version: "1.0"
#   source_format: "kicad"
#   target_format: "easyeda_pro"
#   categories:
#     connectivity: 0.92
#     components: 0.85
#     geometry: 0.70
#     metadata: 0.80
#     degradation_completeness: 1.00
#   notes: "..."
#
# A missing category is treated as score=0.0.


def _load_evidence(evidence_path: Path) -> dict[str, float]:
    """Load category scores from an evidence YAML file."""
    raw = yaml.safe_load(evidence_path.read_text())
    cats = raw.get("categories", {})
    return {k: float(v) for k, v in cats.items()}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_interop_task(
    spec: InteropTaskSpec,
    evidence_path: Path,
    *,
    run_id: str = _SENTINEL_RUN_ID,
) -> InteropTrackResult:
    """Score a project evidence YAML against the interop-track thresholds.

    The runner reads the evidence YAML (produced by the conversion pipeline)
    and compares each category score against the configured threshold.  It
    never re-runs the conversion — it only grades the pre-recorded evidence so
    a third-party verifier can reproduce the score without ZapTrace tools.

    If *evidence_path* does not exist the result status is 'skip'.
    """
    if not evidence_path.exists():
        result = InteropTrackResult(
            task_id=spec.task_id,
            run_id=run_id,
            source_format=spec.source_format,
            target_format=spec.target_format,
            status="skip",
            threshold_violations=["Evidence file not found; skipped"],
        )
        result.run_hash = result.compute_hash()
        return result

    measured = _load_evidence(evidence_path)

    category_scores: list[CategoryScore] = []
    violations: list[str] = []

    for cat_spec in spec.categories:
        score = measured.get(cat_spec.category, 0.0)
        passed = score >= cat_spec.min_score
        cs = CategoryScore(
            category=cat_spec.category,
            score=round(score, 4),
            threshold=cat_spec.min_score,
            passed=passed,
            detail=(
                f"score={score:.3f} >= threshold={cat_spec.min_score:.3f}"
                if passed
                else f"score={score:.3f} < threshold={cat_spec.min_score:.3f}"
            ),
            evidence={"measured": score, "threshold": cat_spec.min_score},
        )
        category_scores.append(cs)
        if not passed and cat_spec.required:
            violations.append(f"{cat_spec.category}: {score:.3f} < {cat_spec.min_score:.3f}")

    status: Literal["pass", "fail", "skip", "error"] = "fail" if violations else "pass"

    result = InteropTrackResult(
        task_id=spec.task_id,
        run_id=run_id,
        source_format=spec.source_format,
        target_format=spec.target_format,
        category_scores=category_scores,
        threshold_violations=violations,
        status=status,
    )
    result.run_hash = result.compute_hash()
    return result
