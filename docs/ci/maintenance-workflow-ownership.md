# CI maintenance and assurance ownership

This page records the operational boundary between **merge-blocking PR admission**, **default-branch regression controls**, and **scheduled/advisory security telemetry**. It implements the maintenance-ownership part of [CI cleanup issue #59](https://github.com/oaslananka/zaptrace/issues/59) without changing triggers, status check names, or permissions. The executable configuration, not this page, determines what actually runs.

## Check authority

| Surface | Source or provider | Trigger | Responsibility | Required on PR? |
| --- | --- | --- | --- | --- |
| Release gate summary | [Quality](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/quality.yml) | PR, main push, dispatch, schedule | Aggregate Python, Rust, packaging, KiCad, benchmark, docs and release-readiness checks | **Yes** |
| Security gate | [Security](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/security-scan.yml) | PR, main push, dispatch, weekly schedule | Aggregate risk-classified dependency audit, CodeQL, Semgrep and Cargo checks | **Yes** |
| Repository hooks | [Pre-commit](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/pre-commit.yml) | Repository workflow contract | Verify lint and workflow security/policy hooks | **Yes** |
| Repository hygiene | [CI](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/ci.yml) | Repository workflow contract | Enforce repository contracts and ruleset parity | **Yes** |
| Dependency review | GitHub Dependency Review | PR | Reject newly introduced dependency risk according to its configured policy | **Yes** |
| Container security gate | [Container Security](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/container-security.yml) | PR, main push, release paths | Enforce exact-image scans when applicable; retain an explicit non-applicable result otherwise | **Yes** |
| SonarCloud new-code quality | SonarCloud PR integration | PR | Review new-code maintainability/security gates without relaxing historical-debt policy | **No** (not one of the six committed branch-required contexts) |
| Historical Sonar debt | [Sonar Historical Debt](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/sonar-debt.yml) | Main push, Sunday schedule, manual | Enforce exact-main historical-debt ratchet, record revision-bound report and artifacts | **No**; failure is a default-branch maintenance defect requiring repair |
| Sonar baseline administration | [Sonar New Code Baseline](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/sonar-baseline.yml) | Manual dispatch only | Apply and verify an explicitly reviewed committed new-code baseline | **No** |
| OpenSSF Scorecard | [OpenSSF Scorecard](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/scorecard.yml) | Main push, weekly schedule, manual | Produce Code Scanning SARIF and retained Scorecard artifact | **No** |
| Renovate configuration validation | [Renovate Config](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/renovate-config.yml) | Selected PR/branch paths; manual | Validate committed Renovate configuration using a locked CLI | **No** (not one of the six committed branch-required contexts) |

The authoritative [main branch ruleset](../governance/main-branch-ruleset.md) names the six required check contexts. There are **no standing bypass actors**. A missing or stale required result cannot be treated as passing; a check may report non-applicability only via its designed, verified gate logic. External review services may add separate checks and comments, which should be resolved rather than silently ignored.

## Quality coverage reusable boundary

The top-level `Quality` workflow retains logical job ID `coverage` and `needs: [changes, test]`. That job calls the local [Quality Coverage Aggregation workflow](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/quality-coverage.yml) using `workflow_call` with a single required `test_mode` input from the existing change classifier. The called workflow runs with `contents: read` and no passed secrets. It downloads the same `test-lane-results-*` artifacts from the calling run, enforces the existing critical-runtime floors, and uploads the unchanged `critical-runtime-coverage` artifact. The docs-only path retains an explicit successful skip, while the caller's unchanged `Release gate summary` still evaluates `needs.coverage.result`.

**Check-label migration:** GitHub may display the non-required coverage check as `Combined Python coverage / Aggregate and enforce` instead of the previous `Combined Python coverage`. This is not one of the six branch-required contexts; the branch ruleset, `Release gate summary` identity, coverage thresholds, and artifact names are unchanged. If a separate downstream policy consumes the coverage display label, it must be updated explicitly rather than treating a missing check as successful.

## Maintenance ownership and failure response

- **PR author / maintainer:** Fix source failures on the PR's exact head SHA, respond to review threads, and verify all six required checks plus relevant external reviews before a normal protected squash merge. Preserve package/artifact identities when moving jobs into reusable workflows.
- **Quality / Security workflow maintainers:** Keep the aggregate status check names, DAG, test matrices, risk classification, artifact uploads, and release dependencies stable. Changes to path filters must not make required contexts disappear. Security and container scans retain their existing risk-scoped and scheduled full-scan behavior.
- **Sonar maintainer:** Treat PR new-code analysis and main-branch historical-debt ratchet as distinct. On a debt failure, inspect the exact-main [Sonar debt report](../quality/sonar-historical-debt.md) and its analysis revision and budget. Fix the code or follow the documented reviewed baseline-change procedure; never raise budgets, add broad exclusions, or dismiss issues simply to make a red run green. Optional Sonar measures API errors are recorded as warnings **only** when the authoritative quality-gate and issue evidence remain available.
- **Security / supply-chain maintainer:** Review Code Scanning and Dependabot alerts separately from the six gate results. Scorecard findings are advisory evidence; they do not certify an exploit or automatically veto unrelated PRs. Preserve SARIF and review recurring High/Critical alerts; apply real upstream fixes or record the unpatched residual risk.
- **Release maintainer:** Do not infer that successful PR/main maintenance checks prove a tagged version was published. Tagged release verification, registry artifact identity, container-security gates and GitHub Release must be checked end-to-end on a real release.

## Safe workflow cleanup

For issue #59, prefer a repository-owned **composite action** when several steps need to be shared inside existing jobs, because the existing job/check identity remains visible. A reusable workflow is suitable only when an entire job domain can move without changing required-context names or losing artifact ownership, matrix semantics, permissions, skip behavior, and failure propagation. The source branch should document any intentional status context migration *before* changing branch protection.

Validate workflow migrations using the repository's actionlint/zizmor hooks, CI contract tests, exact PR check contexts and a post-merge default-branch run. Keep maintenance-only Scorecard/Sonar policy bookkeeping from becoming an accidental unrelated PR merge dependency, without weakening security/quality gates.
