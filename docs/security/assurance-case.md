# Security and Quality Assurance Case

ZapTrace uses an evidence-based assurance model. The repository does not claim that absence of findings proves security or correctness.

## Claims supported today

| Claim | Evidence |
|-------|----------|
| The project is maintained | Recent CI, releases, dependency updates, roadmap. |
| Basic community health files exist | README, LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, SUPPORT, issue/PR templates. |
| Quality gates run automatically | `quality.yml`, docs workflow, hardware/KiCad/proof workflows. |
| Critical runtime coverage cannot silently regress | Identity-bound per-module floors, owner policy, exact exclusions, and time-bounded reviewed exceptions. |
| Static analysis runs | Semgrep and CodeQL in `security-scan.yml`. |
| Untrusted-input boundaries are exercised | Bounded Hypothesis properties and deterministic child-process campaigns in `fuzz.yml`, with weekly deep evidence artifacts. |
| Dependency security is monitored | Renovate, Dependabot alerts, uv audit, dependency review, and pinned Cargo advisory evidence bound to Cargo.lock. |
| The Rust/PyO3 boundary is tested fail-closed | Direct Rust negative/invariant tests, panic containment, explicit resource limits, mandatory installed-wheel verification, and per-target JSON/Markdown evidence. |
| Published native wheels were exercised after installation | Every release wheel target installs its exact wheel in a clean environment and runs the mandatory boundary verifier before wheel upload. |
| Release artifacts have provenance support | Release workflow uses SBOM and artifact attestation. |

## Claims not supported today

| Claim | Reason |
|-------|--------|
| Gold/foundation-grade governance | Solo maintainer; no regular independent human review. |
| Generated hardware is safe/fabrication-ready | Requires qualified human engineering review and manufacturer validation. |
| Plugins are safe for arbitrary untrusted execution | Stronger sandboxing and signed admission are still roadmap items. |
| All vulnerabilities will be found by scanners | SAST/SCA are partial evidence only. |
| Rust/PyO3 behavior is formally verified or denial-of-service-proof | Tests cover defined invariants and limits, not all algorithms, workloads, platforms, or toolchains. |

## Native evidence interpretation

A PASS native-boundary report means the named wheel digest was installed outside the source tree and completed the defined deterministic, invalid-input, limit, and same-process checks. It does not mean that untested inputs or platforms are safe. A clean Cargo advisory report means no known matching advisory was reported for the exact Cargo.lock digest at scan time; it is not a guarantee against unknown or application-specific vulnerabilities.

## Assurance maintenance

Update this file when adding or removing material security, release, or quality controls.
