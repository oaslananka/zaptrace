---
name: zaptrace-benchmark-evaluation
description: Run and interpret bounded ZapTrace benchmark evidence while preserving fixture, grader, source, and environment identities.
---

# ZapTrace Benchmark Evaluation

Use this skill for deterministic ZapTrace benchmark and agent-evaluation workflows against local, committed fixtures.

## When to use

Use this skill for:

- Running the public synthesis benchmark contract
- Evaluating a bounded agent scenario corpus
- Reviewing benchmark scorecards and convergence evidence
- Comparing results across source revisions
- Preparing machine-readable benchmark evidence for review

Do not use benchmark success to claim general EDA superiority, fabrication readiness, physical correctness, or independent third-party reproduction.

## Required inputs

Collect:

- Benchmark or scenario identifier
- Committed fixture/corpus path
- Source revision
- Grader and tool versions
- Expected output and policy files
- Requested comparison baseline, if any

## Workflow

1. Confirm the fixture and policy are committed and integrity-checked.
2. Use `synthesis_benchmark` for the public MCP benchmark surface when it matches the requested task.
3. Use `synthesize_board_score` only for a bounded preview score; do not commit or export generated state implicitly.
4. For the twelve-scenario agent corpus, run `python scripts/ci_agent_evaluation.py` with explicit corpus, policy, JSON output, Markdown output, and artifacts directory arguments.
5. Preserve raw and normalized evidence, source revision, environment identity, fixture hashes, and grader versions.
6. Compare only compatible benchmark versions and normalized fields.
7. Report blocked, skipped, unsupported, and human-review-required outcomes without converting them to passes.

## Quality checks

A valid benchmark report must include:

- Benchmark/corpus identity
- Source revision
- Fixture and policy hashes
- Tool and grader versions
- Scenario/task results
- Generated artifact hashes
- Stop reasons and skipped checks
- Comparison limitations
- Independent-reproduction status

## Failure modes

Stop and report clearly when:

- Fixtures or policies are dirty, missing, or unpinned
- The requested score lacks source or grader identity
- Results come from incompatible benchmark versions
- External tools are unavailable and the check cannot be reproduced
- A repository-controlled rerun is presented as independent third-party evidence

## Output format

Return:

- Benchmark identity
- Environment and revision
- Result summary
- Per-task findings
- Artifact and hash summary
- Reproduction status
- Limitations and non-claims
