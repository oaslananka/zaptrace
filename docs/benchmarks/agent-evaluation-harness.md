# End-to-end agent evaluation harness

ZapTrace includes a deterministic scenario harness for measuring whether the agent runtime can carry a project brief through requirements, synthesis, repair, verification, manufacturing gates, proof evidence, and benchmark scorecards.

The harness measures the shared agent-tool contract. Agent steps run through `zaptrace.agent.tool_impls.registry.call_tool`, the same secure dispatcher used by the MCP, REST, and CLI-facing tool surfaces. Proof-pack and engine-scorecard steps use their existing evidence producers and are recorded in the same scenario trace.

## Versioned corpus

The committed corpus is:

```text
zaptrace/benchmark/manifests/agent-evaluation-v1.json
```

It defines at least ten realistic project prompts. Every scenario records:

```text
scenario_id
title
prompt
risk_class
expected_outcome
board_family_id
modes[]
steps[]
outcome_rules[]
expected_artifact_kinds[]
```

The corpus is secret-free and offline. Scenario validation rejects environment-secret placeholders, API-key fields, and network URLs.

## Outcomes

Reports use four explicit outcomes:

| Outcome | Meaning |
|---|---|
| `success` | The bounded tool plan completed and no blocking rule matched. |
| `blocked` | A release, proof, simulation, or artifact gate correctly failed closed. |
| `human-review-required` | Evidence is incomplete or unsupported and cannot be represented as autonomous approval. |
| `stop-condition` | The runtime intentionally stopped, for example on prompt injection or an unsupported project domain. |

A blocked or review-required result can match the scenario contract and therefore count as a successful harness evaluation. The harness fails only when observed behavior differs from the committed expectation or required evidence is missing.

## Evidence

Each scenario writes an isolated directory containing:

```text
scenario-input.json
tool-trace.json
scenario-result.json
```

Relevant scenarios also retain manufacturing files, a real synthesis proof pack, `proof-link.json`, or `benchmark-scorecard.json`. Every retained file has a relative path, kind, byte size, producer step, and SHA-256 digest in the evaluation report.

Tool traces preserve operation, redacted parameter identity, result identity, risk, status, error metadata, and artifact paths. The normalized trace SHA-256 excludes timestamps and durations so identical evidence remains stable across machines and output directories. Wall-clock values remain available as audit metadata.

The report schema is committed at:

```text
schemas/agent-evaluation-report-v1.schema.json
```

## MCP surface metrics

Surface-aware scenarios are evaluated against the committed `inspect`, `design`, `verify`, `repair`, and `release` profiles while the legacy corpus continues to exercise the shared dispatcher independently. The report binds these measurements to MCP protocol `2026-07-28`, a surface contract SHA-256 derived from visible tool names plus capability requirements, and the evidence identity source commit captured by the CI runner.

The machine-readable `surface_metrics` object uses these semantics:

| Metric | Meaning |
|---|---|
| **Invalid-call rate** | Planned agent-tool calls whose tool exists in the registry but is not visible on the selected reduced surface, divided by planned calls for that surface. Invalid surface calls are rejected before dispatch and count as regressions. |
| **Authorization-denial rate** | Capability-policy denials divided by planned agent-tool calls for that surface. Expected and unexpected denials are reported separately so correct deny-by-default behavior is not conflated with runtime failure. |
| **Expected policy denial** | A deny-by-default capability decision that the fixture explicitly expects. It is recorded as authorization evidence and does not count as a runtime failure or product regression. |
| **Unexpected policy denial** | A capability denial that the fixture did not expect. It counts as a surface regression. |
| **Runtime failure** | An exception raised after a valid, authorized call reaches the shared dispatcher. Runtime failures are distinct from correct policy denials and count as surface regressions. |
| **Task completion** | A task-role scenario reached its committed expected outcome. A correct blocked or human-review-required outcome can therefore be a completed contract; this is not the same as claiming engineering success. |
| **Replay equivalence** | A second isolated execution produced the same normalized trace SHA-256 and outcome after volatile timing and workspace/session identities were excluded. Replay equivalence is deterministic software evidence, not physical-state proof. |

`surface_regression_count` is the sum of invalid surface calls, unexpected policy denials, authorization-expectation mismatches, runtime failures, and replay mismatches. `--strict` fails when that count is non-zero or any scenario outcome mismatches its committed contract. The CI command also compares the committed JSON schema with the runtime Pydantic report model before execution, so schema drift fails closed.

## Run locally

Run the complete CI profile:

```bash
python scripts/ci_agent_evaluation.py \
  --mode ci \
  --artifact-dir agent-evaluation-artifacts \
  --output agent-evaluation-report.json \
  --markdown agent-evaluation-report.md \
  --strict
```

Run a single scenario while developing:

```bash
python scripts/ci_agent_evaluation.py \
  --scenario requirements-esp32-sensor \
  --artifact-dir agent-evaluation-artifacts \
  --output agent-evaluation-report.json \
  --markdown agent-evaluation-report.md \
  --strict
```

## CI and nightly mode

The existing `Quality` workflow runs this harness in the benchmark-evidence job. Pull requests and pushes use `ci` mode. The scheduled workflow uses `nightly` mode and uploads the JSON report, Markdown summary, and complete scenario artifact directory. Neither mode requires an external secret or network service.

## Non-claims

A passing report is regression evidence for deterministic orchestration. It does not prove hardware correctness and does not establish language-model quality, electrical correctness, manufacturer approval, fabrication readiness, independent reproduction, EMC compliance, solver-grade SI/PI or thermal sign-off, or physical board operation.
