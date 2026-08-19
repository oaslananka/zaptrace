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

A passing report is regression evidence for deterministic orchestration. It does not establish language-model quality, electrical correctness, manufacturer approval, fabrication readiness, independent reproduction, EMC compliance, solver-grade SI/PI or thermal sign-off, or physical board operation.
