# Historical Sonar Debt Budget

ZapTrace keeps the SonarQube Cloud new-code gate strict while reducing older findings through bounded, reviewable batches. The historical-debt program is governed by `.github/sonar-debt-policy.json`, the revision-bound baseline report, and the `Sonar Historical Debt` workflow. The policy uses `tracking_issue: null` when no active issue exists and retains closed issue #338 only as the implementation record. The program does not suppress findings or redefine them as new-code success.

## Committed contracts

The implementation has four repository-owned contracts:

- `.github/sonar-debt-policy.json` — project, branch, ownership mapping, baseline identity, current budgets, release targets, and prohibited suppression strategies;
- `docs/reports/sonar-historical-debt-baseline.json` — redacted, revision-bound finding inventory and aggregates;
- `schemas/sonar-debt-report-v1.schema.json` — machine-readable report contract;
- `.github/workflows/sonar-debt.yml` — capture and non-regression automation.

The policy and baseline are bound by analysis revision, embedded report SHA-256, total findings, BLOCKER count, and critical security/reliability count. Changing only one file fails validation.

## Current reviewed baseline

The committed baseline was captured on 2026-08-17 from the Sonar analysis of main revision `8a3b21dca3dcb163a2a9dae2dfd3546a5dd70587`.

| Dimension | Count |
|---|---:|
| Total unresolved findings | 27 |
| BLOCKER | 0 |
| CRITICAL | 25 |
| MAJOR | 2 |
| MINOR | 0 |
| Vulnerabilities | 0 |
| Bugs | 0 |
| Code smells | 27 |
| Critical security/reliability findings | 0 |
| Cognitive-complexity findings (`python:S3776`) | 25 |
| General maintainability findings (`python:S5778`) | 2 |

The quality gate was `OK`. The optional measures endpoint returned HTTP 404 for the authenticated project context, so the report records that limitation in `api_warnings` rather than inventing metric values. Issue inventory, latest-analysis identity, and quality-gate evidence were still captured successfully.

Compared with the previous committed 49-finding baseline, the exact analysis contains 27 unresolved findings: 25 cognitive-complexity findings and 2 general maintainability findings. BLOCKER and critical security/reliability counts remain zero. This 22-finding reduction is now locked into the ratchet. Static-analysis count changes are aggregate evidence and are not attributed mechanically to any single changed line.

The committed report intentionally omits Sonar messages, exact line locations, and raw issue keys. It retains the minimum data required for triage and budgeting: a one-way SHA-256 finding identifier derived from the Sonar issue key, rule, component, severity, type, status, timestamps, age bucket, owner, remediation class, and effort. The hashed identifier supports deterministic comparison without publishing the source key.

## Non-regression budget

The current ratchet permits no growth above the reviewed baseline:

| Budget | Maximum |
|---|---:|
| Total unresolved findings | 27 |
| BLOCKER findings | 0 |
| Critical security/reliability findings | 0 |

A main-branch report fails when the quality gate is not `OK` or any reviewed budget increases.

Release reduction targets are:

| Release | Maximum total | Minimum reduction from current baseline |
|---|---:|---:|
| 0.4.0 | 27 | 0% |
| 0.5.0 | 25 | 6.5% |

The 0.4.0 target is tightened to the current 27-finding baseline so the ratchet cannot give back the reduction already achieved. The 0.5.0 ceiling is 25, preserving the approved 6.5% reduction commitment against the new baseline using the policy contract's integer-floor calculation. These targets are planning and CI contracts. They do not prove runtime safety, reliability, security, or fabrication readiness.

## Workflow behavior

`Sonar Historical Debt` runs in three modes:

- on pushes to `main`, it waits boundedly for Sonar to expose the exact `GITHUB_SHA`, then runs the ratchet;
- weekly, it checks the latest main analysis;
- by manual dispatch, maintainers can choose `capture` or `check`.

The workflow uses `SONAR_TOKEN` only from GitHub Actions secrets, installs locked project dependencies, writes JSON and Markdown under `artifacts/sonar-debt/`, and retains those artifacts for 30 days. The token is sent only in the bearer header and is never written to reports.

## Reproducing the contract locally

The model, policy, schema, and report can be validated without Sonar credentials:

```bash
uv run pytest tests/test_sonar_debt.py tests/test_ci_sonar_debt.py
uv run pyright zaptrace/evidence/sonar_debt.py
uv run ruff check zaptrace/evidence/sonar_debt.py scripts/ci_sonar_debt.py
```

Authenticated capture is performed through GitHub Actions after the workflow is present on the default branch:

```bash
gh workflow run sonar-debt.yml --repo oaslananka/zaptrace -f mode=capture
```

## Updating the baseline

A baseline update must be a focused pull request:

1. Run `capture` and download the retained JSON/Markdown artifact.
2. Confirm the analysis revision, report self-hash, schema validity, redaction, and quality-gate state.
3. Reproduce and triage any new BLOCKER or critical security/reliability finding before changing budgets.
4. Replace the committed baseline and update the policy revision, hash, and counts together.
5. Keep release targets measurable and no weaker than the approved reduction plan.
6. Run tests, schema parity, repository hooks, and the strict new-code gate.

Blanket `NOSONAR`, file-wide exclusions, quality-profile weakening, or bulk false-positive closure are prohibited strategies. Rule-specific dispositions require reproduction, tests, and explicit trust-boundary rationale.
