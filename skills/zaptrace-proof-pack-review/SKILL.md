---
name: zaptrace-proof-pack-review
description: Create or review ZapTrace proof-pack evidence, verify artifact identities, and separate automated gate results from human engineering approval.
---

# ZapTrace Proof-Pack Review

Use this skill when the user asks to create, inspect, compare, or explain ZapTrace proof-pack evidence for a local design.

## When to use

Use this skill for:

- Listing available proof checks
- Running bounded proof checks for a parsed design
- Reviewing proof artifacts, hashes, assumptions, skips, and gate outcomes
- Comparing proof evidence across revisions
- Preparing a human-review handoff

Do not use a passing proof pack as a fabrication, safety, compliance, or production-readiness guarantee.

## Required inputs

Collect:

- Parsed design identity or local design file
- Proof-pack directory or requested output directory
- Required checks and policy context
- Source revision and environment identity when reproducibility matters
- Known assumptions and approved skips

## MCP and CLI workflow

1. Use `proof_list_checks` to discover the available checks.
2. Parse and inspect the design with `design_parse_file` and `design_inspect` when no design identity exists.
3. Run `proof_run_design` for a design-bound proof result, or `proof_run` for the supported proof workflow.
4. Inspect related lifecycle records with `audit_list_events` when decisions or mutations must be traced.
5. Verify that reported artifacts carry stable hashes or evidence identities and that the source revision is recorded when available.
6. Keep failed, skipped, unsupported, degraded, and human-review-required results distinct from passing results.
7. For command-line reproduction, use the documented `zaptrace proof` commands from the source checkout and retain the machine-readable report.

## Quality checks

The review must verify:

- Design or source revision identity
- Check inventory and policy identity
- Artifact hashes and referenced files
- Assumptions, warnings, skips, and unsupported domains
- Automated gate result
- Human-review or fabrication-review status as a separate field
- Reproduction command or environment notes when requested

## Failure modes

Stop and report clearly when:

- The proof pack is incomplete or its referenced artifacts are missing
- Hashes or source identities do not match
- A result is stale relative to the design revision
- A skipped or unsupported check is represented as passing
- The user asks for an approval that the evidence does not support

## Output format

Return:

- Evidence identity
- Design/source identity
- Check results
- Artifact integrity summary
- Assumptions and skips
- Automated gate status
- Human-review status
- Reproduction notes
- Non-claims
