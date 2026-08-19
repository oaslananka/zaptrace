# Repository Maturity Report

> **Evidence date:** 2026-08-04
> **Source revision:** use the revision recorded in `repository-ruleset-evidence.json`, CI artifacts, and release evidence generated for the evaluated commit.

## Executive summary

ZapTrace is a mature pre-1.0 open-source engineering project with strong automated quality, security, release, and evidence controls. It has structured governance and contribution policies, pinned GitHub Actions, locked Python and Rust dependencies, deterministic release evidence, an external KiCad oracle, bounded fuzzing, exact-image vulnerability scanning, SBOMs, checksums, and artifact attestations.

The project remains a **Professional OSS candidate**, not a foundation-grade or fabrication-ready system. It has one active maintainer, no regular independent non-author review, enforced REUSE/SPDX file coverage, and no general physical-validation claim. All generated hardware outputs require qualified human engineering review.

## Current classification

| Area | Classification | Evidence / limitation |
|---|---|---|
| Repository hygiene | Passed | Community files, issue forms, artifact policy, and repository-policy evidence are present. |
| Quality automation | Passed | Ruff, Pyright, Python matrix tests, Rust checks, package build, documentation build, benchmarks, KiCad, Docker, and release summary gates run in CI. |
| Security automation | Passed with bounded scope | Dependency audit, Cargo audit, Semgrep, CodeQL, secret scanning, fuzzing, and exact-image Trivy scanning are active. Scanner success is not a proof of runtime safety. |
| Release integrity | Passed for GitHub Releases | Version consistency, source identity, SBOM, `SHA256SUMS`, attestations, and release verification guidance are implemented. External registry publishing remains intentionally disabled. |
| Main-branch integrity | Passed | The active `main-branch-integrity` ruleset is defined in `config/github-main-ruleset.json` and verified from the live GitHub API into `repository-ruleset-evidence.json`. |
| Governance | Partial | Roles and continuity policy are documented, but the bus factor is one and independent review is not yet enforceable. |
| License hygiene | Passed for tracked-file metadata | Pinned REUSE 6.2.0 verification covers project-owned and vendored files; dependency-license compatibility and legal review remain separate concerns. |
| Engineering validation | Partial | ERC/DRC, KiCad, simulation/analysis, DFM, and proof evidence are substantial but do not replace physical validation or engineering judgment. |
| Component evidence | Partial with strict controls | All 504 records pass strict schema v2 and declare per-field provenance, but the 2026-08-04 audit classifies every record as heuristic and release-blocked pending policy-scoped review. Record completeness is not treated as manufacturer verification. |

## GitHub community standards

| Criterion | Status | Evidence |
|---|---|---|
| README | Passed | Scope, quick start, interfaces, safety boundaries, roadmap, and limitations. |
| LICENSE | Passed | Top-level MIT license. |
| CONTRIBUTING | Passed | Setup, workflow, tests, DCO, review, and security-sensitive contribution rules. |
| CODE_OF_CONDUCT | Passed | Contributor Covenant policy. |
| SECURITY | Passed | Private-reporting instructions, supported versions, scope, and coordinated disclosure expectations. |
| SUPPORT | Passed | Supported release lines, channels, best-effort expectations, and non-claims. |
| Issue and PR templates | Passed | Structured issue forms and PR evidence checklist. |
| Governance and maintainers | Passed as documentation | `GOVERNANCE.md`, `MAINTAINERS.md`, CODEOWNERS, and continuity documents. Actual continuity remains partial until another trusted maintainer exists. |

## OpenSSF and Scorecard readiness

| Check area | Status | Evidence / gap |
|---|---|---|
| Maintained | Passed | Active release, CI, dependency, roadmap, and issue activity. |
| Branch protection | Passed | Active repository ruleset blocks deletion and non-fast-forward updates, requires PRs, linear history, resolved conversations, and six stable aggregate checks. |
| Code review | Partial | PR workflow and CODEOWNERS exist; required independent approval remains unavailable in the solo-maintainer model. |
| Security policy | Passed | `SECURITY.md` and security assurance documentation. |
| Dependency updates | Passed | Renovate plus GitHub-native Dependabot security updates. |
| Pinned CI dependencies | Passed | GitHub Actions are pinned to commit SHAs and workflow security is checked by actionlint/zizmor. |
| Token permissions | Passed | Explicit least-privilege workflow permissions; SARIF jobs receive only the required write scope. |
| SAST | Passed with tool limitations | Semgrep and CodeQL run; findings still require reachability and engineering-context review. |
| Fuzzing | Passed for bounded campaigns | Deterministic CI corpus and scheduled deeper campaigns exist. This is not a claim of exhaustive or formal input safety. |
| Container scanning | Passed | The exact built image is scanned with Trivy; policy, SBOM, SARIF, digest, and provenance evidence are retained. |
| Release checksums | Passed | Release assets include and verify `SHA256SUMS`. |
| SBOM and provenance | Passed | SPDX SBOM and GitHub artifact attestations are generated for release artifacts. |
| Bus factor | Missing | One active maintainer. |
| SPDX/REUSE tracked-file coverage | Passed | `reuse lint` is enforced in repository hygiene and retains machine-readable evidence. |

## Test and validation maturity

| Criterion | Status | Evidence / gap |
|---|---|---|
| Lint and formatting | Passed | Ruff checks and format verification. |
| Type checking | Passed | Pyright. |
| Python compatibility | Passed for the declared CI matrix | Python 3.12, 3.13, and 3.14 jobs with risk-based collection. |
| Rust boundary | Passed for supported CI targets | Formatting, Clippy, tests, native wheel build, installation, and Python-boundary evidence. |
| Coverage | Passed with protected critical-module floors | Global coverage threshold plus explicit critical runtime coverage policy. |
| External KiCad oracle | Passed for generated oracle fixtures | Supported KiCad CLI validation produces revision-bound evidence. The corpus ERC repair and subprocess-diagnostics work recorded in closed issue #274 is implemented. |
| Fuzz/property testing | Passed for the committed bounded target inventory | Deeper coverage-guided/native campaigns remain a possible future extension. |
| Test-lane efficiency | Passed with measured budgets | Every test has one primary lane; coverage-enabled unit plus benchmark/hardware work is duration-sharded, required heavy lanes fail on empty/all-skip execution, and per-shard evidence is retained. Host-specific timings remain non-portable. |
| Component trust validation | Passed for schema and downgrade controls | Strict unknown-key rejection, explicit trust tiers, eight critical-field provenance records, monotonic trust baseline, release eligibility, and proof-pack blocking are automated. The current library remains heuristic rather than verified. |
| Physical validation | Missing as a general claim | Planned reference-board fabrication evidence is tracked separately; software gates do not prove a board works physically. |

## Documentation maturity

The documentation follows a mixed Diátaxis-style structure with tutorials, how-to guides, reference material, explanations, security assurance, governance, design notes, and benchmark evidence. Every public Markdown page is intentionally listed in `mkdocs.yml`; the strict documentation build is the publication gate.

Current-state documents must include an evidence date or point to revision-bound generated evidence. Historical strategy documents are retained only when explicitly labeled as dated planning or snapshot material.

## Governance maturity

The active ruleset requires these stable contexts on every pull request:

- `Release gate summary`
- `Security gate`
- `Repository hooks`
- `Repository hygiene`
- `Dependency review`
- `Container security gate`

The ruleset has no standing bypass actor. It currently requires zero approving reviews because one maintainer cannot independently approve their own change. This limitation is documented rather than represented as independent review. Closed issue #269 records the continuity-policy implementation, but the repository still lists one active maintainer and cannot yet enforce non-author approval.

## Release maturity

GitHub Releases are the authoritative publication channel for the current pre-1.0 line. Release evidence includes:

- synchronized Python, Rust, runtime, and tag versions;
- source commit/ref, dirty state, lock hash, and toolchain identity;
- Python source distributions and supported native wheels;
- machine-readable support levels with actionable unsupported-target guidance;
- clean-install CLI, SDK, REST API, MCP HTTP, and native-state evidence for every claimed package artifact;
- exact-image container security evidence;
- SPDX SBOM;
- `SHA256SUMS` and checksum verification;
- GitHub artifact attestations;
- generated release notes and changelog context.

PyPI and GHCR publication are not claimed until naming, credentials, support matrix, and package-policy work are explicitly completed.

## Current maturity limitations

At the evidence date, the repository had no open issues. The principal limitations are still visible in repository evidence:

1. The active maintainer count is one; backup-maintainer and emergency-steward capacity has not been demonstrated.
2. Independent non-author approval is not enforced in the solo-maintainer ruleset.
3. The Sonar debt ratchet permits 49 historical findings and targets at most 45 for version 0.5.0.
4. Physical reference-board validation and broader accessibility/internationalization evidence remain outside the current maturity claim.

Persistent, versioned local state for controlled deployments was implemented through closed issue [#153](https://github.com/oaslananka/zaptrace/issues/153), with restart, migration, backup, recovery, ACL, audit, and protected-artifact evidence. This does not create a multi-tenant SaaS claim.

## Non-claims

This report does not claim OpenSSF Gold, foundation governance, regulatory certification, manufacturer approval, production readiness, universal plugin safety, multi-tenant SaaS safety, or fabrication correctness. Repository automation and passing evidence reduce risk; they do not replace qualified electronics engineering review or physical testing.
