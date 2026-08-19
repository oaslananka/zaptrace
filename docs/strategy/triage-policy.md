# GitHub triage policy

This policy keeps issue metadata consistent with ZapTrace milestones and machine-checkable release evidence.

## Required issue structure

Every non-trivial issue records: problem, scope, acceptance criteria, evidence required, dependencies or blockers, and non-goals. Release-blocking work also defines explicit pass/fail/skip policy and retained artifacts.

## Label taxonomy

Use exactly one work-shape label such as `type/feature`, `type/hardening`, `type/test`, `type/refactor`, `type/docs`, `type/ci`, `type/research`, or `type/epic`. Add one priority label (`priority/P0`, `priority/P1`, or `priority/P2`), one or more active `area/...` labels, exactly one lifecycle status, and one size label from `size/XS` through `size/XXL`.

Priority belongs in labels, not issue titles. Issue titles identify the problem or capability and may use only a neutral form prefix such as `[Bug]` or `[Feature]`.

## Lifecycle

The normal lifecycle is:

1. `status/needs-design` — scope, dependencies, and evidence are incomplete.
2. `status/ready` — acceptance criteria and implementation boundary are reviewable.
3. `status/in-progress` — an owner is actively implementing the issue.
4. `status/needs-review` — a PR and evidence are ready for independent review.
5. closed — merged, verified, or explicitly declined with rationale.

`status/blocked` is an exception state used only when a named dependency prevents progress. Restore the previous lifecycle state when the dependency clears. Do not create ad-hoc status labels.

## Priority and size rules

- P0: release, security, evidence-integrity, or foundational blocker.
- P1: required by the next milestone exit criteria.
- P2: valuable but not blocking the current or next release.
- XS/S: one focused policy, test, documentation, or local implementation change.
- M/L: multiple related modules or a new bounded workflow.
- XL/XXL: architecture work that should be decomposed into child issues before implementation.

## Milestone policy

Assign work to the earliest milestone whose published exit criteria require it. Do not place operational host names, private paths, tokens, or temporary VPS details in public issue text. Epics own cross-issue outcomes; implementation issues own independently testable deliverables. A milestone is releasable only when its P0 issues are closed or explicitly deferred with a risk owner and expiry, and required evidence is PASS or SKIP-APPROVED.

## Pull request policy

Every PR links its issues, describes behavior and claim changes, lists verification commands and evidence artifacts, identifies intentional skips, and states whether manufacturing/fabrication claims are affected. Reviewers and maintainers must inspect automated agent and bot comments, validate technically correct findings, and resolve blocking threads before merge.
