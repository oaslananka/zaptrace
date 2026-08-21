# Bounded test lanes

ZapTrace classifies every collected pytest item into exactly one primary lane. The committed policy is `config/test-lanes.json`; tests not listed by an explicit rule enter the `unit` lane. This keeps new tests visible without silently dropping them from CI.

| Lane | Purpose | Pull-request budget |
|---|---|---:|
| `unit` | Pure, fast behavior and calculation tests | 600 s |
| `integration` | Cross-module, API, MCP, policy, and service contracts | 900 s |
| `benchmark` | Deterministic benchmark, convergence, and performance evidence | 900 s |
| `hardware` | EDA formats, generated boards, corpus conversion, and manufacturing evidence | 900 s |
| `external_tool` | Docker, KiCad, ngspice, and other delegated executables | 600 s |
| `native` | Rust extension and native-boundary verification | 600 s |

The coverage-enabled `unit` lane and the heavy `benchmark` and `hardware` lanes are split by whole test module. `config/test-duration-baseline.json` stores measured module durations; the greedy allocator assigns the longest modules first to the currently lightest shard. A module never moves between shards because of collection order. Python 3.12 CI uses three unit shards, while benchmark and hardware use two shards each.

## Local commands

```bash
task test-lane-policy
task test-unit
task test-integration
task test-benchmark
task test-hardware
task test-external-tool
task test-native
```

A direct shard run uses one-based indexes:

```bash
uv run pytest -p tests.lane_policy \
  --lane "benchmark" \
  --lane-shard-index 1 \
  --lane-shard-count 2 \
  --require-lane-execution \
  --lane-report test-lane-benchmark-1.json
```

Each CI lane publishes JUnit XML and a JSON report containing the selected modules, collected inventory, pass/fail/skip counts, elapsed time, runtime budget, projected historical duration, and shard identity. Required heavy lanes fail when empty or entirely skipped. External prerequisite confidence is reinforced by the dedicated KiCad oracle, container, Rust build, and validation-environment gates; a skip is evidence, never a pass claim.

## Refreshing duration weights and detecting drift

`scripts/ci_profile_test_lanes.py` automates timing collection, shard balance simulation, and baseline re-profiling.

### 1. Diagnostic drift check (non-mutating)

Inspect observed timing evidence against the checked-in baseline without modifying files:

```bash
# Profile using CI JUnit XML artifacts:
uv run python scripts/ci_profile_test_lanes.py --junit "junit-lane-*.xml"

# Or profile on-demand by executing pytest:
uv run python scripts/ci_profile_test_lanes.py --run --run-lane "unit"

# Or run via task:
task test-lane-profile
```

The check evaluates per-shard projected vs observed duration, highlights drifting modules (`warning` or `critical`), and writes a deterministic report to `test-lane-profiling-report.json`.

### 2. Updating duration baselines (explicit rebaseline mode)

When test execution durations shift materially or new test modules are added, refresh `config/test-duration-baseline.json` explicitly:

```bash
# Re-profile lane and update checked-in weights:
uv run python scripts/ci_profile_test_lanes.py \
  --junit "junit-lane-*.xml" \
  --update \
  --source "Observed JUnit aggregation from CI run <ID> on ubuntu-latest" \
  --measured-at "YYYY-MM-DD"
```

To update all modules or prune deleted test modules:

```bash
uv run python scripts/ci_profile_test_lanes.py \
  --junit "junit-lane-*.xml" \
  --update \
  --update-all \
  --prune-missing
```

Do not use random or hash-only sharding for bounded lanes because it ignores observed cost and recreates long-tail jobs.

## Dated migration evidence

The baseline inventory, measured shard runs, runtime budgets, and measurement limitations are retained in [`docs/reports/test-lane-evidence-2026-07-27.json`](../reports/test-lane-evidence-2026-07-27.json). The report is dated development evidence, not a cross-machine performance guarantee; GitHub Actions job conclusions remain authoritative.

## Release policy

Tagged releases execute all six lanes explicitly with cumulative coverage, using the same committed three-way unit and two-way benchmark/hardware shard boundaries as pull-request CI. The release job then emits `coverage.json` and applies the critical-runtime coverage policy. No primary lane or configured shard may be removed from the release command list without failing the repository policy tests.
