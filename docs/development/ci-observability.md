# CI observability

ZapTrace uses Codecov for coverage-specific pull-request feedback and SonarQube Cloud for broader maintainability, reliability, and security quality gates. The services have distinct responsibilities; SonarQube Cloud is not configured as a second required coverage gate.

## Coverage policy

Python 3.12 lane jobs publish parallel coverage data that the `Combined Python coverage` job merges into `coverage.xml`. Codecov applies project and patch statuses with an automatic target and a 1% tolerance. This protects the current baseline and new code without introducing a repository-wide fixed percentage that can reward low-value tests or penalize generated and integration-heavy code.

Coverage uploads are explicit, use the committed XML report, and fail trusted CI when the uploader cannot process the report. Line annotations are enabled through GitHub Checks.

## Critical runtime coverage evidence

The repository-owned critical-runtime gate enforces exact per-module floors for MCP, transaction-safe isolated execution, REST transport/authentication, object authorization, capability policy, release evidence, and REST release-export code. The combined Python 3.12 lane coverage job publishes the `critical-runtime-coverage` artifact; tagged releases publish `critical-runtime-coverage-release` after executing all approved lanes. Each report is bound to the producing revision through the shared evidence identity.

This control is intentionally separate from Codecov and SonarQube Cloud. Codecov reports repository/patch trends and annotations. SonarQube Cloud reports new-code quality and security findings. The repository validator is the merge-blocking authority for the committed critical-module floors and reviewed exceptions. See [Critical Runtime Coverage](critical-runtime-coverage.md).

## Test Analytics

Every Python 3.12 lane or shard writes a unique JUnit XML file such as `junit-lane-unit-1.xml`, `junit-lane-benchmark-1.xml`, or `junit-lane-external-tool.xml`. Python 3.13 and 3.14 compatibility jobs emit separate uninstrumented unit and integration reports.

Trusted branch and same-repository pull-request runs upload those reports with the pinned Codecov v7 uploader in test-results mode. Failed tests remain in the JUnit file because the upload step runs when the job has not been cancelled. Fork pull requests do not receive `CODECOV_TOKEN`, so their Test Analytics upload is skipped while their test result still controls the GitHub job conclusion. Lane JSON evidence separately records inventory, selected modules, shard identity, duration, runtime budget, pass/fail/skip counts, and whether required execution occurred.

## JavaScript Bundle Analysis

Codecov Bundle Analysis is not enabled. ZapTrace is a Python/Rust package and does not emit a Vite, Webpack, or Rollup JavaScript application bundle. If a future web application introduces a supported bundler, Bundle Analysis should be evaluated in that application-specific workflow rather than added to the Python package CI.

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
