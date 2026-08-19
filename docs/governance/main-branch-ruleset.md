# Main branch ruleset

ZapTrace protects `main` with the repository ruleset defined in
`config/github-main-ruleset.json`. The live GitHub configuration is checked by
`scripts/ci_repository_ruleset.py`; a static documentation statement is not
accepted as protection evidence.

## Required check contract

The ruleset requires six stable contexts on every pull request:

| Context | Responsibility |
|---|---|
| `Release gate summary` | Aggregates the Python, Rust, package, documentation, KiCad, Docker, benchmark, and release-evidence gates. |
| `Security gate` | Aggregates dependency audit, Cargo advisory audit, Semgrep, and CodeQL. |
| `Repository hooks` | Runs pre-commit, actionlint, and zizmor. |
| `Repository hygiene` | Verifies repository policy, pinned REUSE/SPDX compliance, and the live ruleset against the committed contract. |
| `Dependency review` | Blocks newly introduced critical dependency risk. |
| `Container security gate` | Runs the exact-image scan when container/runtime inputs change and emits an explicit non-applicable success otherwise. |

These contexts are intentionally aggregate or always-present jobs. A path-filtered
job must not be added directly to the required-check list because an absent check
can deadlock a merge.

## Solo-maintainer policy

The current repository has zero required approvals because one maintainer cannot
provide independent review of their own change. This does not weaken CI
enforcement: changes still require a pull request, passing required checks,
linear history, and resolved review conversations. Issue #269 owns the future
independent review requirement and backup-maintainer transition.

## Direct pushes and emergency changes

The ruleset has no standing bypass actor. Direct updates, force pushes, and branch
deletion are blocked. A genuine emergency requires the administrator to record an
incident or issue, capture the current ruleset and rule suite evidence, temporarily
change the ruleset through GitHub's audited administration surface, perform the
smallest reviewed repair, restore the active policy, and attach the before/after
rule suite evidence. Disabling a check because it is inconvenient is not an
emergency procedure.

## Verification

Repository CI writes `repository-ruleset-evidence.json` from the live GitHub API.
The evidence records the active ruleset ID, enforcement state, required contexts,
comparison errors, and any visibility warning caused by token scope. GitHub rule
suite records are the negative evidence that a direct or failing update was
blocked.
