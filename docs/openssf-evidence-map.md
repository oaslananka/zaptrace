# OpenSSF Evidence Map

This page maps high-value OpenSSF Best Practices and OSPS Baseline criteria to ZapTrace repository evidence.

## Passing badge evidence

| Area | Evidence |
|------|----------|
| Project description | `README.md` hero, What ZapTrace Is / Is Not |
| Obtain and use software | README Quickstart, `docs/GETTING_STARTED.md` |
| Feedback and bugs | GitHub Issues, `CONTRIBUTING.md`, `SECURITY.md` |
| Contribution process | `CONTRIBUTING.md`, pull request template, CI checks |
| Contribution requirements | `CONTRIBUTING.md`, `docs/development/coding-standards.md`, `docs/development/testing-policy.md` |
| License | `LICENSE`, SPDX expression `MIT` |
| Interface docs | README CLI examples, REST docs, MCP tools reference |
| Maintained | Recent commits, issues, release workflows, roadmap |
| Release notes | `CHANGELOG.md` |
| Vulnerability process | `SECURITY.md`, `docs/security/vulnerability-response.md` |

## Baseline Level 1 evidence

| Control | Evidence |
|---------|----------|
| MFA for repository modification | GitHub account-level MFA requirement and maintainer policy |
| Lowest collaborator permissions | `docs/governance/maintainer-access.md` |
| Direct commit prevention | Branch protection on `main` |
| Primary branch deletion prevention | Branch protection on `main` |
| CI untrusted input handling | GitHub Actions using controlled scripts and no privileged `pull_request_target` pattern |
| CI credential isolation | Release permissions isolated to trusted release workflow events |
| Secret prevention | `.gitignore`, `.env.example`, GitHub secret scanning, gitleaks workflow |
| User guides | README, docs site, quickstart, examples |
| Defect reporting | GitHub Issues and `SECURITY.md` |
| Public discussions | GitHub Issues and Pull Requests |
| Contribution explanation | `CONTRIBUTING.md` |

## Baseline Level 2 evidence

| Control | Evidence |
|---------|----------|
| Default CI permissions | workflow-level permissions and least-privilege release permissions |
| Unique release identifiers | SemVer-style tags and package versions |
| Changelog | `CHANGELOG.md` |
| Standard dependency tooling | `pyproject.toml`, `uv.lock`, `Cargo.toml`, `Cargo.lock` |
| Signed/hash release manifest | `release.yml`, `scripts/generate_checksum_manifest.py`, GitHub artifact attestations |
| Dependency policy | `docs/supply-chain/dependency-policy.md` |
| Build instructions | README, `CONTRIBUTING.md`, `Taskfile.yml`, validation environment docs |
| Member list and roles | `MAINTAINERS.md`, `GOVERNANCE.md` |
| Contributor requirements | `CONTRIBUTING.md` |
| DCO assertion | `CONTRIBUTING.md`, `scripts/ci_dco_check.py` |
| Required status checks | branch protection and quality workflows |
| Test policy | `docs/quality/testing-policy.md` |
| Vulnerability response | `docs/security/vulnerability-response.md` |

## Deliberately not claimed yet

| Criterion | Reason |
|-----------|--------|
| Full access continuity | Requires a real backup maintainer or emergency steward. |
| Bus factor >= 2 | Current project is solo-maintainer. |
| Regular non-author human review | Requires an independent reviewer and branch protection review enforcement. |
| Gold/foundation-grade maturity | Requires multiple active maintainers/contributors and stronger governance evidence. |
