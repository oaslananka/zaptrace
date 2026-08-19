---
name: zaptrace-design-validation
description: Validate a local ZapTrace design with requirements review, ERC/DRC evidence, and bounded engineering risk reports without claiming fabrication approval.
---

# ZapTrace Design Validation

Use this skill to inspect and validate an existing local ZapTrace design through the public MCP contract.

## When to use

Use this skill for:

- Parsing and inspecting a local design file
- Requirements and assumption review
- ERC and DRC execution
- Electrical, mechanical, security, and testability evidence
- Comparing two design revisions
- Producing an engineering findings report before any export decision

Do not use this skill to approve fabrication, silently waive violations, expose an MCP/REST service to an untrusted network, or treat generated evidence as a substitute for qualified human review.

## Required inputs

Collect:

- Local design file or committed project path
- Intended operating conditions and requirements
- Applicable board, electrical, and manufacturing constraints
- Expected validation scope
- Existing waivers, assumptions, and known unsupported domains

## MCP workflow

1. Parse the local design with `design_parse_file`.
2. Inspect the normalized design with `design_inspect` and `design_list_nets`.
3. Review requirements and assumptions with `requirements_parse` and `requirements_review` when requirements are available.
4. Run `erc_validate`; read the retained result with `erc_get_result`.
5. Run `drc_run`; read the retained result with `drc_get_result`.
6. Add bounded domain evidence with `electrical_analysis`, `mechanical_review`, `security_review`, and `testability_report` as applicable.
7. Use `design_diff` when a before/after comparison is required.
8. Keep unsupported, skipped, warning, and human-review-required states explicit.

## Quality checks

A complete response must include:

- Source design identity and revision where available
- Requirements and assumptions
- ERC and DRC summaries
- Findings grouped by severity and domain
- Unsupported or skipped checks
- Recommended repairs or next validation steps
- Explicit human-review boundary

## Failure modes

Stop and report clearly when:

- The design path is missing, ambiguous, or outside the approved local project
- Parsing fails or the normalized design cannot be identified
- ERC/DRC results are unavailable
- Required constraints are missing
- A requested domain is unsupported or only heuristic
- The user asks to suppress findings without an engineering rationale

## Output format

Return:

- Design context
- Requirements and assumptions
- ERC summary
- DRC summary
- Domain findings
- Blockers and warnings
- Unsupported checks
- Recommended next actions
- Human-review note
