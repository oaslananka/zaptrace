# CI observability

ZapTrace keeps merge-blocking test and coverage authority inside the repository and GitHub Actions. External analysis services may add maintainability, reliability, or security feedback, but they are not required to accept repository-owned coverage evidence.

## Coverage policy

Python 3.12 lane jobs publish parallel Coverage.py data. The `Combined Python coverage` job merges those fragments, enforces the repository-wide `75%` Coverage.py threshold, emits `coverage.xml` and `coverage.json`, and then applies the committed critical-runtime module floors.

The merged reports and the critical-runtime report are retained as GitHub Actions artifacts. Coverage enforcement therefore does not depend on a third-party upload service, token, dashboard, or API being available.

## Critical runtime coverage evidence

The repository-owned critical-runtime gate enforces exact per-module floors for MCP, transaction-safe isolated execution, REST transport/authentication, object authorization, capability policy, release evidence, and REST release-export code. The combined Python 3.12 lane coverage job publishes the `critical-runtime-coverage` artifact; tagged releases publish `critical-runtime-coverage-release` after executing all approved lanes. Each report is bound to the producing revision through the shared evidence identity.

The repository validator is the merge-blocking authority for committed global and critical-module coverage policy. SonarQube Cloud remains a separate new-code quality/security signal rather than a second coverage authority. See [Critical Runtime Coverage](critical-runtime-coverage.md).

## Test result evidence

Every Python 3.12 lane or shard writes a unique JUnit XML file such as `junit-lane-unit-1.xml`, `junit-lane-benchmark-1.xml`, or `junit-lane-external-tool.xml`. Python 3.13 and 3.14 compatibility jobs emit separate uninstrumented unit and integration reports.

JUnit reports, lane JSON evidence, and per-lane coverage fragments are uploaded directly as GitHub Actions artifacts. Lane JSON evidence records inventory, selected modules, shard identity, duration, runtime budget, pass/fail/skip counts, and whether required execution occurred. A test job's conclusion is determined by the test and repository policy itself, not by an external analytics upload.

## JavaScript Bundle Analysis

External JavaScript bundle analysis is not enabled. ZapTrace is a Python/Rust package and does not emit a Vite, Webpack, or Rollup JavaScript application bundle. If a future web application introduces a supported bundler, bundle analysis should be evaluated in that application-specific workflow rather than added to the Python package CI.

## Workflow security

The required `Repository hooks` check runs actionlint and zizmor across all workflow files. Zizmor findings at Medium severity or higher block the check. Low and informational recommendations remain visible for triage but do not duplicate or replace CodeQL, Semgrep, or the repository's native linters.

## SonarQube Cloud new-code baseline

SonarQube Cloud Automatic Analysis remains ZapTrace's only Sonar scanner. The repository does not run `sonar-scanner` in GitHub Actions and does not commit `sonar-project.properties`, because Automatic Analysis ignores that file and must not be combined with a CI-based scan.

The `main` branch uses an explicit project-level **Specific date** new-code definition. The committed policy is `.github/sonar-new-code-baseline.json`; its initial baseline is `2026-07-21`. This separates the historical issue inventory from changes introduced after the migration checkpoint without resolving, suppressing, or bulk-marking historical findings. Existing findings remain visible in SonarQube Cloud's overall-code issue view and must be triaged independently.

Changing the baseline is an administrative operation, not a routine build step:

1. Update `.github/sonar-new-code-baseline.json` in a reviewed pull request. The date must not be in the future, the project key is fixed, and the historical-backlog policy must remain `visible-and-triaged-separately`.
2. Merge the policy change, then manually run the **Sonar New Code Baseline** workflow from the default branch.
3. Retain the uploaded `sonar-new-code-baseline-*` artifact. It records the exact verified server settings and never contains `SONAR_TOKEN`.
4. Verify both layers: a clean pull request must report zero new Sonar issues, and its merge commit must receive a green `main` quality gate.

Do not advance this date merely to make a quality gate green. Move it only at an intentional release or migration checkpoint after confirmed findings since the current baseline have been remediated or separately accepted through normal issue triage.

### Applied baseline evidence

The initial policy was applied and API-verified on July 21, 2026 by workflow run `29865850166` against merge commit `9739110cf427f0f1ac098d7571a52dadd02eb84a`. The resulting `main` analysis passed the quality gate with zero unresolved new-code issues and zero security hotspots. The overall-code inventory remained visible with 774 unresolved historical findings at the time of verification.

The historical verification snapshot is committed at [`docs/reports/sonar-new-code-baseline.json`](../reports/sonar-new-code-baseline.json). It declares `historical_snapshot: true`, records the analyzed commit and timestamps, and is not current evidence for later revisions. Counts in that report are evidence captured at the stated timestamp, not a permanently expected backlog size.
