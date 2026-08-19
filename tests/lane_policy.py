"""Central pytest lane policy, sharding, and evidence hooks."""

from __future__ import annotations

import fnmatch
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, ClassVar, Literal, cast

import pytest
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "test-lanes.json"
DURATION_BASELINE_PATH = ROOT / "config" / "test-duration-baseline.json"
PRIMARY_LANES = ("unit", "integration", "benchmark", "hardware", "external_tool", "native")
PrimaryLane = Literal["unit", "integration", "benchmark", "hardware", "external_tool", "native"]


class LaneRule(BaseModel):
    """One ordered group of paths assigned to a primary lane."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lane: PrimaryLane
    patterns: list[str] = Field(min_length=1)


class AuxiliaryRule(BaseModel):
    """Additional non-primary marker applied to matching tests."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    marker: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    patterns: list[str] = Field(min_length=1)


class TestLanePolicy(BaseModel):
    """Versioned test-lane classification and runtime policy."""

    __test__: ClassVar[bool] = False

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    primary_lanes: list[PrimaryLane]
    default_lane: PrimaryLane
    runtime_budgets_seconds: dict[PrimaryLane, int]
    lane_rules: list[LaneRule]
    auxiliary_rules: list[AuxiliaryRule] = Field(default_factory=list)
    required_execution_lanes: list[PrimaryLane] = Field(default_factory=list)
    shard_counts: dict[PrimaryLane, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_policy(self) -> TestLanePolicy:
        if tuple(self.primary_lanes) != PRIMARY_LANES:
            raise ValueError(f"primary_lanes must be exactly {PRIMARY_LANES!r}")
        if set(self.runtime_budgets_seconds) != set(PRIMARY_LANES):
            raise ValueError("runtime budgets must cover every primary lane")
        if any(value <= 0 for value in self.runtime_budgets_seconds.values()):
            raise ValueError("runtime budgets must be positive")
        if len({rule.lane for rule in self.lane_rules}) != len(self.lane_rules):
            raise ValueError("each primary lane may appear in lane_rules at most once")
        if any(count <= 0 for count in self.shard_counts.values()):
            raise ValueError("shard counts must be positive")
        return self


class DurationBaseline(BaseModel):
    """Historical module-duration weights used for deterministic sharding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    measured_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source: str = Field(min_length=10)
    default_module_seconds: float = Field(gt=0)
    module_seconds: dict[str, float]

    @model_validator(mode="after")
    def validate_durations(self) -> DurationBaseline:
        if any(value <= 0 for value in self.module_seconds.values()):
            raise ValueError("duration weights must be positive")
        return self


def load_lane_policy(path: Path = POLICY_PATH) -> TestLanePolicy:
    """Load and validate the committed test-lane policy."""
    return TestLanePolicy.model_validate_json(path.read_text(encoding="utf-8"))


def load_duration_baseline(path: Path = DURATION_BASELINE_PATH) -> DurationBaseline:
    """Load historical module-duration weights."""
    return DurationBaseline.model_validate_json(path.read_text(encoding="utf-8"))


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def classify_test_path(path: str, policy: TestLanePolicy) -> PrimaryLane:
    """Return the one primary lane for a repository-relative test path."""
    normalized = path.replace("\\", "/")
    matches = [rule.lane for rule in policy.lane_rules if _matches(normalized, rule.patterns)]
    if len(matches) > 1:
        raise ValueError(f"{normalized} matches multiple primary lanes: {', '.join(matches)}")
    return cast(PrimaryLane, matches[0] if matches else policy.default_lane)


def auxiliary_markers(path: str, policy: TestLanePolicy) -> tuple[str, ...]:
    """Return deterministic additional markers for a test path."""
    normalized = path.replace("\\", "/")
    return tuple(sorted(rule.marker for rule in policy.auxiliary_rules if _matches(normalized, rule.patterns)))


def assign_module_shards(module_seconds: dict[str, float], *, shard_count: int) -> dict[str, int]:
    """Greedily balance whole test modules by historical duration.

    The return value uses zero-based shard indexes. Sorting by weight and path
    makes the assignment stable regardless of input mapping order.
    """
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    totals = [0.0] * shard_count
    assignments: dict[str, int] = {}
    for path, weight in sorted(module_seconds.items(), key=lambda item: (-item[1], item[0])):
        shard = min(range(shard_count), key=lambda index: (totals[index], index))
        assignments[path] = shard
        totals[shard] += weight
    return assignments


def module_weight(path: str, baseline: DurationBaseline) -> float:
    """Return an explicit historical weight or the documented default."""
    return baseline.module_seconds.get(path, baseline.default_module_seconds)


_RUN_STATE: dict[str, Any] = {}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("zaptrace test lanes")
    group.addoption("--lane", choices=(*PRIMARY_LANES, "all"), help="Run one approved primary test lane")
    group.addoption("--lane-shard-index", type=int, help="One-based shard index for the selected lane")
    group.addoption("--lane-shard-count", type=int, help="Total shards for the selected lane")
    group.addoption("--lane-report", type=Path, help="Write machine-readable lane execution evidence")
    group.addoption(
        "--require-lane-execution",
        action="store_true",
        help="Fail required lanes when empty or entirely skipped",
    )
    group.addoption(
        "--enforce-lane-budget",
        action="store_true",
        help="Fail when the selected lane exceeds its committed runtime budget",
    )


def pytest_configure(config: pytest.Config) -> None:
    policy = load_lane_policy()
    for lane in PRIMARY_LANES:
        config.addinivalue_line("markers", f"{lane}: primary ZapTrace test lane")
    for rule in policy.auxiliary_rules:
        config.addinivalue_line("markers", f"{rule.marker}: auxiliary ZapTrace test classification")
    _RUN_STATE.clear()
    _RUN_STATE.update(
        {
            "policy": policy,
            "baseline": load_duration_baseline(),
            "started_at": time.monotonic(),
            "outcomes": {},
            "inventory": Counter(),
            "selected_modules": [],
            "projected_seconds": 0.0,
        }
    )


def _relative_item_path(item: pytest.Item, rootpath: Path) -> str:
    try:
        path = item.path.relative_to(rootpath)
    except ValueError:
        path = item.path
    return str(path).replace("\\", "/")


def _selected_shard_modules(
    items: list[pytest.Item],
    *,
    rootpath: Path,
    baseline: DurationBaseline,
    shard_index: int,
    shard_count: int,
) -> tuple[set[str], dict[str, int], float]:
    modules = sorted({_relative_item_path(item, rootpath) for item in items})
    weights = {path: module_weight(path, baseline) for path in modules}
    assignments = assign_module_shards(weights, shard_count=shard_count)
    selected = {path for path, assigned in assignments.items() if assigned == shard_index}
    projected = sum(weights[path] for path in selected)
    return selected, assignments, projected


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    policy: TestLanePolicy = _RUN_STATE["policy"]
    baseline: DurationBaseline = _RUN_STATE["baseline"]
    rootpath = ROOT
    lane_by_nodeid: dict[str, PrimaryLane] = {}

    for item in items:
        path = _relative_item_path(item, rootpath)
        lane = classify_test_path(path, policy)
        lane_by_nodeid[item.nodeid] = lane
        item.add_marker(lane)
        item.user_properties.append(("zaptrace_lane", lane))
        for marker in auxiliary_markers(path, policy):
            item.add_marker(marker)
        _RUN_STATE["inventory"][lane] += 1

    selected_lane = config.getoption("--lane")
    selected = list(items)
    deselected: list[pytest.Item] = []
    if selected_lane and selected_lane != "all":
        selected = [item for item in selected if lane_by_nodeid[item.nodeid] == selected_lane]
        deselected = [item for item in items if lane_by_nodeid[item.nodeid] != selected_lane]

    shard_index_raw = config.getoption("--lane-shard-index")
    shard_count = config.getoption("--lane-shard-count")
    if (shard_index_raw is None) != (shard_count is None):
        raise pytest.UsageError("--lane-shard-index and --lane-shard-count must be used together")
    if shard_count is not None:
        if not selected_lane or selected_lane == "all":
            raise pytest.UsageError("sharding requires one explicit --lane")
        if shard_count <= 0 or shard_index_raw is None or not 1 <= shard_index_raw <= shard_count:
            raise pytest.UsageError("lane shard index must be between 1 and lane shard count")
        selected_modules, assignments, projected = _selected_shard_modules(
            selected,
            rootpath=rootpath,
            baseline=baseline,
            shard_index=shard_index_raw - 1,
            shard_count=shard_count,
        )
        shard_deselected = [item for item in selected if _relative_item_path(item, rootpath) not in selected_modules]
        selected = [item for item in selected if _relative_item_path(item, rootpath) in selected_modules]
        deselected.extend(shard_deselected)
        _RUN_STATE["shard_assignments"] = assignments
        _RUN_STATE["projected_seconds"] = projected

    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected
    _RUN_STATE["selected_lane"] = selected_lane or "all"
    _RUN_STATE["selected_count"] = len(selected)
    _RUN_STATE["selected_modules"] = sorted({_relative_item_path(item, rootpath) for item in selected})
    _RUN_STATE["shard_index"] = shard_index_raw
    _RUN_STATE["shard_count"] = shard_count


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    outcomes: dict[str, str] = _RUN_STATE.get("outcomes", {})
    if report.when in {"setup", "teardown"} and report.failed:
        outcomes[report.nodeid] = "failed"
    elif report.when == "setup" and report.skipped:
        outcomes[report.nodeid] = "skipped"
    elif report.when == "call":
        outcomes[report.nodeid] = "skipped" if report.skipped else "failed" if report.failed else "passed"
    _RUN_STATE["outcomes"] = outcomes


def _write_lane_report(
    config: pytest.Config,
    elapsed: float,
    budget_exceeded: bool,
    requirement_failed: bool,
    pytest_exitstatus: int,
) -> None:
    report_path = config.getoption("--lane-report")
    if report_path is None:
        return
    outcomes = Counter(_RUN_STATE.get("outcomes", {}).values())
    inventory = {lane: int(_RUN_STATE["inventory"].get(lane, 0)) for lane in PRIMARY_LANES}
    payload = {
        "schema_version": "1.0",
        "gate_id": "pytest-lanes-v1",
        "lane": _RUN_STATE.get("selected_lane", "all"),
        "shard_index": _RUN_STATE.get("shard_index"),
        "shard_count": _RUN_STATE.get("shard_count"),
        "selected_count": int(_RUN_STATE.get("selected_count", 0)),
        "selected_modules": _RUN_STATE.get("selected_modules", []),
        "inventory": inventory,
        "outcomes": {
            "passed": outcomes.get("passed", 0),
            "failed": outcomes.get("failed", 0),
            "skipped": outcomes.get("skipped", 0),
        },
        "elapsed_seconds": round(elapsed, 3),
        "projected_seconds": round(float(_RUN_STATE.get("projected_seconds", 0.0)), 3),
        "runtime_budget_seconds": _RUN_STATE.get("runtime_budget_seconds"),
        "budget_exceeded": budget_exceeded,
        "required_execution_failed": requirement_failed,
        "pytest_exitstatus": pytest_exitstatus,
        "passed": (
            pytest_exitstatus == 0 and not budget_exceeded and not requirement_failed and outcomes.get("failed", 0) == 0
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _required_execution_failed(*, selected_count: int, outcomes: Counter[str]) -> bool:
    """Return whether a required lane produced no executed pass/fail outcome."""
    return selected_count == 0 or outcomes.get("passed", 0) + outcomes.get("failed", 0) == 0


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    elapsed = time.monotonic() - float(_RUN_STATE.get("started_at", time.monotonic()))
    lane = str(_RUN_STATE.get("selected_lane", "all"))
    policy: TestLanePolicy = _RUN_STATE["policy"]
    outcomes = Counter(_RUN_STATE.get("outcomes", {}).values())
    selected_count = int(_RUN_STATE.get("selected_count", 0))

    requirement_failed = False
    if config.getoption("--require-lane-execution") and lane in policy.required_execution_lanes:
        requirement_failed = _required_execution_failed(selected_count=selected_count, outcomes=outcomes)

    budget_exceeded = False
    if config.getoption("--enforce-lane-budget") and lane in policy.runtime_budgets_seconds:
        budget = policy.runtime_budgets_seconds[lane]  # type: ignore[index]
        _RUN_STATE["runtime_budget_seconds"] = budget
        budget_exceeded = elapsed > budget

    if requirement_failed or budget_exceeded:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    _write_lane_report(config, elapsed, budget_exceeded, requirement_failed, int(session.exitstatus))
