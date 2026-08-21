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


def save_duration_baseline(
    baseline: DurationBaseline,
    path: Path = DURATION_BASELINE_PATH,
) -> None:
    """Serialize duration baseline to disk with deterministic key ordering."""
    payload = {
        "default_module_seconds": baseline.default_module_seconds,
        "measured_at": baseline.measured_at,
        "module_seconds": {k: baseline.module_seconds[k] for k in sorted(baseline.module_seconds)},
        "schema_version": baseline.schema_version,
        "source": baseline.source,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class DriftThresholds(BaseModel):
    """Configurable thresholds for classifying timing drift and shard imbalance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    module_warning_seconds: float = 2.0
    module_warning_ratio: float = 0.30
    module_critical_seconds: float = 10.0
    module_critical_ratio: float = 0.50
    shard_imbalance_warning_seconds: float = 20.0
    shard_imbalance_critical_seconds: float = 60.0
    lane_budget_warning_ratio: float = 0.80


def _normalize_test_path(raw_path: str, root: Path = ROOT) -> str:
    """Normalize a path or classname to repo-relative POSIX format."""
    normalized = raw_path.replace("\\", "/").strip()
    if not normalized:
        return ""
    try:
        p = Path(normalized)
        if p.is_absolute():
            normalized = str(p.relative_to(root)).replace("\\", "/")
    except ValueError:
        pass

    if normalized.endswith(".py"):
        return normalized

    if "::" in normalized:
        normalized = normalized.split("::")[0]
        if normalized.endswith(".py"):
            return normalized

    parts = normalized.split(".")
    for i in range(len(parts), 0, -1):
        candidate_rel = "/".join(parts[:i]) + ".py"
        if candidate_rel.startswith("tests/") and (root / candidate_rel).is_file():
            return candidate_rel
        if not candidate_rel.startswith("tests/") and (root / "tests" / candidate_rel).is_file():
            return f"tests/{candidate_rel}"

    if len(parts) > 1 and parts[0] == "tests" and parts[1].startswith("test_"):
        return f"tests/{parts[1]}.py"
    if parts[0].startswith("test_"):
        return f"tests/{parts[0]}.py"

    return normalized


def parse_junit_durations(
    source: str | Path | list[str | Path],
    root: Path = ROOT,
) -> tuple[dict[str, float], list[str]]:
    """Parse test module durations from one or more JUnit XML files."""
    import glob
    import xml.etree.ElementTree as ET

    sources: list[Path] = []
    if isinstance(source, (str, Path)):
        s_str = str(source)
        p = Path(source)
        if "*" in s_str or "?" in s_str:
            sources = [Path(match) for match in sorted(glob.glob(s_str, recursive=True))]
        elif p.is_dir():
            sources = sorted(p.glob("*.xml"))
        else:
            sources = [p]
    else:
        for s in source:
            s_str = str(s)
            p = Path(s)
            if "*" in s_str or "?" in s_str:
                sources.extend(Path(match) for match in sorted(glob.glob(s_str, recursive=True)))
            else:
                sources.append(p)

    module_seconds: dict[str, float] = {}
    errors: list[str] = []

    for path in sources:
        if not path.is_file():
            errors.append(f"JUnit file not found: {path}")
            continue
        try:
            tree = ET.parse(path)
            root_elem = tree.getroot()
        except Exception as exc:
            errors.append(f"Failed to parse JUnit XML {path}: {exc}")
            continue

        for testcase in root_elem.iter("testcase"):
            file_attr = testcase.get("file")
            classname_attr = testcase.get("classname")
            raw_path = file_attr or classname_attr or ""
            module = _normalize_test_path(raw_path, root=root)
            if not module or not module.endswith(".py"):
                continue

            time_raw = testcase.get("time")
            try:
                duration = float(time_raw) if time_raw is not None else 0.0
            except ValueError:
                duration = 0.0

            if duration > 0:
                module_seconds[module] = round(module_seconds.get(module, 0.0) + duration, 6)

    cleaned = {k: round(v, 3) for k, v in sorted(module_seconds.items())}
    return cleaned, errors


def parse_durations_log(
    text_or_path: str | Path,
    root: Path = ROOT,
) -> tuple[dict[str, float], list[str]]:
    """Parse test module durations from pytest --durations=0 text output or log file."""
    import re

    errors: list[str] = []
    if isinstance(text_or_path, Path) or (
        isinstance(text_or_path, str)
        and (Path(text_or_path).is_file() or ("\n" not in text_or_path and text_or_path.endswith(".log")))
    ):
        p = Path(text_or_path)
        if not p.is_file():
            errors.append(f"Durations log file not found: {p}")
            return {}, errors
        try:
            content = p.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append(f"Failed to read durations log {p}: {exc}")
            return {}, errors
    else:
        content = str(text_or_path)

    module_seconds: dict[str, float] = {}
    pattern = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*s\s+(?:call|setup|teardown)\s+([^\s:]+)", re.MULTILINE)

    for match in pattern.finditer(content):
        duration_str, raw_path = match.group(1), match.group(2)
        module = _normalize_test_path(raw_path, root=root)
        if not module or not module.endswith(".py"):
            continue
        try:
            duration = float(duration_str)
        except ValueError:
            duration = 0.0
        if duration > 0:
            module_seconds[module] = round(module_seconds.get(module, 0.0) + duration, 6)

    cleaned = {k: round(v, 3) for k, v in sorted(module_seconds.items())}
    return cleaned, errors


def calculate_lane_shard_profile(
    *,
    policy: TestLanePolicy,
    baseline: DurationBaseline,
    observed_durations: dict[str, float],
    thresholds: DriftThresholds | None = None,
    target_lane: PrimaryLane | Literal["all"] = "all",
    root: Path = ROOT,
) -> dict[str, Any]:
    """Aggregate per-lane/shard observed vs baseline timings and analyze drift."""
    if thresholds is None:
        thresholds = DriftThresholds()

    all_test_files = sorted((root / "tests").glob("test_*.py"))
    lanes_modules: dict[PrimaryLane, list[str]] = {lane: [] for lane in PRIMARY_LANES}
    classification_errors: list[str] = []

    for file_path in all_test_files:
        rel_path = str(file_path.relative_to(root)).replace("\\", "/")
        try:
            lane = classify_test_path(rel_path, policy)
            lanes_modules[lane].append(rel_path)
        except ValueError as exc:
            classification_errors.append(str(exc))

    lanes_to_process = PRIMARY_LANES if target_lane == "all" else (cast(PrimaryLane, target_lane),)

    lane_profiles: dict[str, Any] = {}
    all_module_drifts: list[dict[str, Any]] = []
    critical_drift_count = 0
    warning_drift_count = 0
    imbalanced_lanes: list[str] = []
    warnings: list[str] = []

    total_observed_seconds = 0.0
    total_baseline_seconds = 0.0
    observed_modules_count = 0
    unbaselined_modules_count = 0

    for lane in lanes_to_process:
        modules = lanes_modules[lane]
        shard_count = policy.shard_counts.get(lane, 1)
        budget = policy.runtime_budgets_seconds.get(lane, 600)

        baseline_weights = {m: module_weight(m, baseline) for m in modules}
        observed_weights = {m: observed_durations[m] for m in modules if m in observed_durations}
        effective_weights = {m: observed_durations.get(m, baseline_weights[m]) for m in modules}

        lane_baseline_total = sum(baseline_weights.values())
        lane_effective_total = sum(effective_weights.values())
        lane_observed_total = sum(observed_weights.values())

        total_baseline_seconds += lane_baseline_total
        total_observed_seconds += lane_observed_total
        observed_modules_count += len(observed_weights)

        # Baseline assignment
        baseline_assignments = assign_module_shards(baseline_weights, shard_count=shard_count)
        # Rebalanced simulation
        rebalanced_assignments = assign_module_shards(effective_weights, shard_count=shard_count)

        current_shards: list[dict[str, Any]] = []
        for idx in range(shard_count):
            shard_mods = sorted(m for m, s in baseline_assignments.items() if s == idx)
            proj_base = round(sum(baseline_weights[m] for m in shard_mods), 3)
            eff_proj = round(sum(effective_weights[m] for m in shard_mods), 3)
            obs_actual = round(sum(observed_weights.get(m, 0.0) for m in shard_mods), 3)
            drift = round(eff_proj - proj_base, 3)
            current_shards.append(
                {
                    "index": idx + 1,
                    "module_count": len(shard_mods),
                    "projected_baseline_seconds": proj_base,
                    "effective_projected_seconds": eff_proj,
                    "observed_actual_seconds": obs_actual,
                    "drift_seconds": drift,
                    "modules": shard_mods,
                }
            )

        rebalanced_shards: list[dict[str, Any]] = []
        for idx in range(shard_count):
            shard_mods = sorted(m for m, s in rebalanced_assignments.items() if s == idx)
            eff_proj = round(sum(effective_weights[m] for m in shard_mods), 3)
            rebalanced_shards.append(
                {
                    "index": idx + 1,
                    "module_count": len(shard_mods),
                    "effective_projected_seconds": eff_proj,
                    "modules": shard_mods,
                }
            )

        eff_shard_totals = [s["effective_projected_seconds"] for s in current_shards]

        imbalance_seconds = round(max(eff_shard_totals) - min(eff_shard_totals), 3) if eff_shard_totals else 0.0
        imbalance_ratio = (
            round(max(eff_shard_totals) / min(eff_shard_totals), 4)
            if eff_shard_totals and min(eff_shard_totals) > 0
            else 1.0
        )

        lane_severity = "ok"
        if shard_count > 1:
            max_shard = max(eff_shard_totals)
            min_shard = min(eff_shard_totals)
            if imbalance_seconds >= thresholds.shard_imbalance_critical_seconds:
                lane_severity = "critical"
                critical_drift_count += 1
                imbalanced_lanes.append(lane)
                warnings.append(
                    f"Lane '{lane}' shard imbalance is CRITICAL: {imbalance_seconds}s "
                    f"(max: {max_shard}s, min: {min_shard}s)"
                )
            elif imbalance_seconds >= thresholds.shard_imbalance_warning_seconds:
                lane_severity = "warning"
                warning_drift_count += 1
                imbalanced_lanes.append(lane)
                warnings.append(
                    f"Lane '{lane}' shard imbalance warning: {imbalance_seconds}s "
                    f"(max: {max_shard}s, min: {min_shard}s)"
                )

        lane_profiles[lane] = {
            "module_count": len(modules),
            "observed_module_count": len(observed_weights),
            "shard_count": shard_count,
            "runtime_budget_seconds": budget,
            "projected_baseline_seconds": round(lane_baseline_total, 3),
            "effective_projected_seconds": round(lane_effective_total, 3),
            "observed_actual_seconds": round(lane_observed_total, 3),
            "imbalance_seconds": imbalance_seconds,
            "imbalance_ratio": imbalance_ratio,
            "severity": lane_severity,
            "current_shards": current_shards,
            "rebalanced_shards": rebalanced_shards,
        }

        # Module-level drift
        for m in modules:
            is_new = m not in baseline.module_seconds
            if is_new:
                unbaselined_modules_count += 1
            if m in observed_durations:
                obs = observed_durations[m]
                base_w = baseline_weights[m]
                drift = round(obs - base_w, 3)
                drift_ratio = round((obs - base_w) / base_w, 4) if base_w > 0 else 0.0

                mod_sev = "info"
                if is_new:
                    if obs >= thresholds.module_critical_seconds:
                        mod_sev = "critical"
                        critical_drift_count += 1
                    elif obs >= thresholds.module_warning_seconds:
                        mod_sev = "warning"
                        warning_drift_count += 1
                else:
                    if (
                        abs(drift) >= thresholds.module_critical_seconds
                        and abs(drift_ratio) >= thresholds.module_critical_ratio
                    ):
                        mod_sev = "critical"
                        critical_drift_count += 1
                    elif (
                        abs(drift) >= thresholds.module_warning_seconds
                        and abs(drift_ratio) >= thresholds.module_warning_ratio
                    ):
                        mod_sev = "warning"
                        warning_drift_count += 1

                all_module_drifts.append(
                    {
                        "module": m,
                        "lane": lane,
                        "baseline_seconds": round(base_w, 3),
                        "observed_seconds": round(obs, 3),
                        "drift_seconds": drift,
                        "drift_ratio": drift_ratio,
                        "is_new_module": is_new,
                        "severity": mod_sev,
                    }
                )

    all_module_drifts.sort(key=lambda d: (-abs(d["drift_seconds"]), d["module"]))

    missing_in_repo = sorted(path for path in baseline.module_seconds if not (root / path).is_file())
    if missing_in_repo:
        warnings.extend(f"Baseline contains missing test module: {p}" for p in missing_in_repo)

    overall_status = (
        "drift_critical"
        if critical_drift_count > 0 or classification_errors
        else "drift_warning"
        if warning_drift_count > 0 or bool(warnings)
        else "ok"
    )

    total_modules = sum(len(lanes_modules[lane_name]) for lane_name in lanes_to_process)

    return {
        "schema_version": "1.0",
        "gate_id": "test-lane-profiling-v1",
        "status": overall_status,
        "passed": overall_status != "drift_critical" and not classification_errors,
        "summary": {
            "target_lane": target_lane,
            "total_modules": total_modules,
            "observed_modules": observed_modules_count,
            "unobserved_modules": total_modules - observed_modules_count,
            "unbaselined_modules": unbaselined_modules_count,
            "total_baseline_seconds": round(total_baseline_seconds, 3),
            "total_observed_seconds": round(total_observed_seconds, 3),
            "critical_drift_count": critical_drift_count,
            "warning_drift_count": warning_drift_count,
            "imbalanced_lanes": imbalanced_lanes,
            "missing_baseline_modules": missing_in_repo,
        },
        "thresholds": thresholds.model_dump(),
        "lanes": lane_profiles,
        "module_drifts": all_module_drifts,
        "warnings": warnings,
        "errors": classification_errors,
    }


def update_duration_baseline_data(
    baseline: DurationBaseline,
    observed_durations: dict[str, float],
    *,
    measured_at: str | None = None,
    source: str | None = None,
    update_all: bool = False,
    prune_missing: bool = False,
    root: Path = ROOT,
) -> DurationBaseline:
    """Produce an updated DurationBaseline model with new observed timings."""
    import datetime

    date_str = measured_at or datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    source_str = source or f"Observed pytest module durations re-profiled on {date_str}"

    new_module_seconds = dict(baseline.module_seconds)

    if update_all:
        all_modules = sorted((root / "tests").glob("test_*.py"))
        for mod in all_modules:
            rel = str(mod.relative_to(root)).replace("\\", "/")
            if rel in observed_durations and observed_durations[rel] > 0:
                new_module_seconds[rel] = round(observed_durations[rel], 3)
            elif rel not in new_module_seconds:
                new_module_seconds[rel] = baseline.default_module_seconds
    else:
        for path, dur in observed_durations.items():
            if dur > 0:
                new_module_seconds[path] = round(dur, 3)

    if prune_missing:
        new_module_seconds = {path: dur for path, dur in new_module_seconds.items() if (root / path).is_file()}

    return DurationBaseline(
        schema_version="1.0",
        measured_at=date_str,
        source=source_str,
        default_module_seconds=baseline.default_module_seconds,
        module_seconds={k: round(new_module_seconds[k], 3) for k in sorted(new_module_seconds)},
    )


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
