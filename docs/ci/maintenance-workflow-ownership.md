# CI maintenance and assurance ownership

This page records the operational boundary between **merge-blocking PR admission**, **default-branch regression controls**, and **scheduled/advisory security telemetry**. It implements the maintenance-ownership part of [CI cleanup issue #59](https://github.com/oaslananka/zaptrace/issues/59). Historical Sonar debt moved from repeated `main` push runs to weekly/manual checks; the required status contexts, token permissions, and Scorecard triggers are unchanged. The executable configuration, not this page, determines what actually runs.

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
| Historical Sonar debt | [Sonar Historical Debt](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/sonar-debt.yml) | Sunday schedule, manual (optional exact-revision mode) | Enforce historical-debt ratchet and retain revision-identified reports/artifacts; exact current commit only with explicit manual verification | **No**; a failed weekly/manual check requires repair, not unrelated PR blockage |
| Sonar baseline administration | [Sonar New Code Baseline](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/sonar-baseline.yml) | Manual dispatch only | Apply and verify an explicitly reviewed committed new-code baseline | **No** |
| OpenSSF Scorecard | [OpenSSF Scorecard](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/scorecard.yml) | Main push, weekly schedule, manual | Produce Code Scanning SARIF and retained Scorecard artifact | **No** |
| Renovate configuration validation | [Renovate Config](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/renovate-config.yml) | Selected PR/branch paths; manual | Validate committed Renovate configuration using a locked CLI | **No** (not one of the six committed branch-required contexts) |

The authoritative [main branch ruleset](../governance/main-branch-ruleset.md) names the six required check contexts. There are **no standing bypass actors**. A missing or stale required result cannot be treated as passing; a check may report non-applicability only via its designed, verified gate logic. External review services may add separate checks and comments, which should be resolved rather than silently ignored.

## Quality coverage reusable boundary

The top-level `Quality` workflow retains logical job ID `coverage` and `needs: [changes, test]`. That job calls the local [Quality Coverage Aggregation workflow](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/quality-coverage.yml) using `workflow_call` with a single required `test_mode` input from the existing change classifier. The called workflow runs with `contents: read` and no passed secrets. It downloads the same `test-lane-results-*` artifacts from the calling run, enforces the existing critical-runtime floors, and uploads the unchanged `critical-runtime-coverage` artifact. The docs-only path retains an explicit successful skip, while the caller's unchanged `Release gate summary` still evaluates `needs.coverage.result`.

**Check-label migration:** GitHub may display the non-required coverage check as `Combined Python coverage / Aggregate and enforce` instead of the previous `Combined Python coverage`. This is not one of the six branch-required contexts; the branch ruleset, `Release gate summary` identity, coverage thresholds, and artifact names are unchanged. If a separate downstream policy consumes the coverage display label, it must be updated explicitly rather than treating a missing check as successful.

## Native Rust reusable boundary

The top-level `Quality` workflow retains logical job ID `rust`, `needs: changes`, and the release gate dependency on `needs.rust.result`. It now calls [Quality Native Rust](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/quality-native.yml) with the single required `heavy_ci` input from the existing change classifier. The called workflow has read-only `contents` permission, receives no secrets, explicitly succeeds with a skip summary on non-heavy PRs, and runs the same locked Python setup, Rust formatting, all-target Clippy, Rust tests, wheel build, hash-verified clean wheel installation, and mandatory native-boundary verification on heavy CI. The unchanged `native-boundary-evidence` artifact retains strict `if-no-files-found: error` and upload-on-success behavior.

**Check-label migration:** GitHub may show the non-required nested Rust job as `Build Rust extension / Build, test and verify native wheel` instead of `Build Rust extension`. The six required branch checks, `Release gate summary`, release dependency, evidence identity, gate conditions, and Rust toolchain contract remain unchanged. Consumers of the former non-required label must migrate explicitly.

## Distribution clean-install reusable boundary

The top-level `Quality` job `distribution-clean-install` retains `needs: changes` and calls [Quality Distribution Clean Install](https://github.com/oaslananka/zaptrace/blob/main/.github/workflows/quality-distribution.yml) with only the existing required `heavy_ci` classifier input. The called workflow has read-only `contents` permission, receives no secrets, has the same 20-minute inner job timeout, and retains a successful explicit skip on non-heavy PRs. On heavy CI it builds the exact sdist, locks and clean-installs a hash-verified copy, runs the strict external-source distribution smoke, and uploads the same `distribution-smoke-sdist-linux-x86_64-cp313` evidence using `always()` and `if-no-files-found: error`. The upstream Quality classification is unchanged. The required `Release gate summary` now explicitly depends on `distribution-clean-install` and feeds its result to the strict `ci_release_gate.py` evaluator; failed sdist smoke therefore blocks the aggregate required context, while the existing explicit non-heavy skip remains successful. Previously this job ran but was omitted from the aggregate gate DAG.

**Check-label migration:** The non-required distribution check may display as `Distribution clean-install / Build and verify clean source distribution` instead of `Distribution clean-install`. The six branch-required check contexts do not change; any external consumer of this non-required check label must deliberately migrate.

## Docker Hub pull-limit isolation

The Quality Docker image smoke job uses a digest-pinned BuildKit container and Google's documented mirror.gcr.io cache for heavy CI. The immutable BuildKit index digest and the canonical Python base digest remain unchanged; the Compose REST/MCP probes and strict compose-runtime-smoke evidence upload still execute and feed the required Release gate summary. This avoids anonymous pull quotas on shared runners without adding secrets, weakening tests or changing the production Dockerfile. If the mirror cannot supply the pinned digest, CI must fail instead of skipping evidence.

## Shared KiCad oracle steps

The three KiCad/Hardware owners — the `Quality` `kicad-oracle` job,
standalone `KiCad Oracle` and the `Hardware` `kicad` job — now invoke the
same local read-only composite
[`kicad-oracle` action](../../.github/actions/kicad-oracle/action.yml).
It owns the bounded KiCad 10 install helper and strict oracle invocation.
Explicit inputs preserve the prior differences: Quality runs strict oracle
and source-identified jobset without an availability probe; standalone runs
both probes and jobset; Hardware runs availability and strict oracle, but
not the jobset. The Quality step retains its prior `heavy_ci` selector and
the exact PR head `ZAPTRACE_SOURCE_COMMIT`.

No workflow trigger, job ID, aggregate release-gate dependency, artifact
name, non-applicable skip or retention policy changed. `Hardware` still
executes its extra design export regression; Quality still executes the
KiCad benchmark corpus and physical candidate readiness. The separate
standalone oracle's evidence upload remains strict on missing files. CI
contract tests validate the shared steps, callers and their distinct
required evidence.

## Maintenance ownership and failure response

- **PR author / maintainer:** Fix source failures on the PR's exact head SHA, respond to review threads, and verify all six required checks plus relevant external reviews before a normal protected squash merge. Preserve package/artifact identities when moving jobs into reusable workflows.
- **Quality / Security workflow maintainers:** Keep the aggregate status check names, DAG, test matrices, risk classification, artifact uploads, and release dependencies stable. Changes to path filters must not make required contexts disappear. Security and container scans retain their existing risk-scoped and scheduled full-scan behavior.
- **Sonar maintainer:** Treat PR new-code analysis and scheduled historical-debt ratchet as distinct. On a debt failure, inspect the revision-identified [Sonar debt report](../quality/sonar-historical-debt.md), analyzed revision and budget. When exact-current-main assurance is required (for example before release), manually dispatch `mode=check` and `verify_revision=true` to require the checked-out commit. Fix the code or follow the documented reviewed baseline-change procedure; never raise budgets, add broad exclusions, or dismiss issues simply to make a red run green. Optional Sonar measures API errors are recorded as warnings **only** when the authoritative quality-gate and issue evidence remain available.
- **Security / supply-chain maintainer:** Review Code Scanning and Dependabot alerts separately from the six gate results. Scorecard findings are advisory evidence; they do not certify an exploit or automatically veto unrelated PRs. Preserve SARIF and review recurring High/Critical alerts; apply real upstream fixes or record the unpatched residual risk.
- **Release maintainer:** Do not infer that successful PR/main maintenance checks prove a tagged version was published. Tagged release verification, registry artifact identity, container-security gates and GitHub Release must be checked end-to-end on a real release.

## Safe workflow cleanup

For issue #59, prefer a repository-owned **composite action** when several steps need to be shared inside existing jobs, because the existing job/check identity remains visible. A reusable workflow is suitable only when an entire job domain can move without changing required-context names or losing artifact ownership, matrix semantics, permissions, skip behavior, and failure propagation. The source branch should document any intentional status context migration *before* changing branch protection.

Validate workflow migrations using the repository's actionlint/zizmor hooks, CI contract tests, exact PR check contexts and a post-merge default-branch run. Keep maintenance-only Scorecard/Sonar policy bookkeeping from becoming an accidental unrelated PR merge dependency, without weakening security/quality gates.
