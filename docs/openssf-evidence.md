# OpenSSF Evidence

This file maps repository artifacts to OpenSSF Best Practices and Baseline-style evidence. It is evidence support, not a self-certification result.

## Project metadata

| Field | Evidence |
|-------|----------|
| Project name | ZapTrace |
| Repository | `https://github.com/oaslananka/zaptrace` |
| License | `LICENSE`, MIT |
| Languages | Python, Rust, Dockerfile |
| Status | Pre-1.0, human-review-required EDA kernel |

## Passing readiness evidence

| Criterion family | Status | Evidence |
|------------------|--------|----------|
| Project description | Passed | `README.md` explains what ZapTrace is and is not. |
| Obtain software | Passed | README quickstart and source install instructions. |
| Provide feedback | Passed | GitHub issue templates and support policy. |
| Contribute | Passed | `CONTRIBUTING.md`, PR template, issue templates. |
| Contribution requirements | Passed | Coding standards, test policy, DCO-style assertion, CI requirements. |
| FLOSS license | Passed | MIT license in top-level `LICENSE`. |
| Basic documentation | Passed | README, docs site, getting started, CLI/SDK/MCP docs. |
| Interface documentation | Passed | CLI examples, REST/API docs, MCP tools reference, and docs site navigation provide external interface documentation. |
| HTTPS project sites | Passed | GitHub and docs URLs use HTTPS. |
| Discussion | Passed | GitHub issues and pull requests are URL-addressable and searchable. |
| Maintained | Passed | Recent releases, CI, and active dependency maintenance. |

## Silver readiness evidence

| Criterion family | Status | Evidence / gap |
|------------------|--------|----------------|
| Passing prerequisite | Partial | Requires BadgeApp completion. |
| DCO/legal contribution mechanism | Passed | DCO-style assertion documented in `CONTRIBUTING.md`. |
| Governance | Passed | `GOVERNANCE.md`. |
| Code of conduct | Passed | `CODE_OF_CONDUCT.md`. |
| Roles/responsibilities | Passed | `GOVERNANCE.md`, `MAINTAINERS.md`. |
| Access continuity | Partial | Documented, but real continuity requires another trusted maintainer. |
| Roadmap | Passed | `ROADMAP.md`, `docs/ROADMAP.md`. |
| Architecture | Passed | `docs/ARCHITECTURE.md`, `docs/explanation/architecture.md`. |
| Security requirements | Passed | `SECURITY.md`, `docs/security/threat-model.md`, `docs/security/assurance-case.md`. |
| Quick start | Passed | README and `docs/tutorials/getting-started.md`. |
| Current docs | Passed | Docs-status-sync checks MCP/rule-count drift and stale status claims; ongoing review remains required. |
| Achievements | Partial | README includes current CI/security/docs/Scorecard/Best Practices evidence; badge status should only be upgraded after BadgeApp recognition. |
| Password storage for project site | Not applicable | GitHub-hosted repository; no project-operated password store identified. |

## Gold feasibility evidence

| Criterion | Status | Evidence / gap |
|-----------|--------|----------------|
| Bus factor >= 2 | Missing | Solo maintainer. |
| Two unassociated significant contributors | Missing | Not demonstrated. |
| Non-author human review | Missing | Review required is not enabled because the project is solo-maintainer. |
| Tracked-file copyright/license metadata | Passed | Pinned REUSE 6.2.0 lint covers tracked files; vendored footprints override the project license with CC-BY-SA-4.0 attribution. |
| Cryptographic 2FA | Needs human confirmation | GitHub supports passkeys/TOTP; exact maintainer method is account-level. |

## Baseline evidence highlights

| Baseline area | Status | Evidence / gap |
|---------------|--------|----------------|
| MFA for repository changes | Passed | GitHub requires 2FA; maintainers should use passkeys/TOTP. |
| Lowest collaborator privileges | Needs human confirmation | Repository settings must be verified when adding collaborators. |
| Main-branch ruleset | Passed | `config/github-main-ruleset.json` requires PRs, stable aggregate checks, linear history, and blocks deletion/non-fast-forward updates; live state is recorded in `repository-ruleset-evidence.json`. |
| CI permissions | Passed | Workflows use explicit minimum permissions. |
| Untrusted metadata/code in CI | Partial | No `pull_request_target` workflow observed; workflow inputs should continue to be validated. |
| Secret prevention | Passed | Secret scanning/push protection should be kept enabled; gitleaks workflow added. |
| Release identifiers | Passed | SemVer-style tags and package version checks. |
| Release logs | Passed | `CHANGELOG.md` and GitHub Releases. |
| Dependency tracking | Passed | `pyproject.toml`, `uv.lock`, `Cargo.lock`, Dockerfile, Renovate, Dependabot. |
| Signed/attested release assets | Passed | Release workflow uses GitHub artifact attestations. |
| Build instructions | Passed | README, CONTRIBUTING, release process docs. |
| Member list and roles | Passed | `MAINTAINERS.md`, `GOVERNANCE.md`. |
| Vulnerability disclosure | Passed | `SECURITY.md`; private vulnerability reporting must be enabled in settings. |

## Detailed evidence map

See [OpenSSF Evidence Map](openssf-evidence-map.md) for an expanded mapping of Passing, Baseline Level 1, and Baseline Level 2 criteria to repository evidence.
