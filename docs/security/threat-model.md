# Threat Model

This document summarizes security assumptions for repository maturity evidence. For the agent runtime-specific model, see `docs/security/agent-runtime-threat-model.md`.

## Assets

- Source code and release workflows.
- Generated design artifacts and proof packs.
- Release assets, SBOMs, and attestations.
- Repository settings, branch protection, confidential reports, and package publishing access.
- User-provided design files and prompts.

## Trust boundaries

- User design files and prompts are untrusted input.
- Pull requests from contributors are untrusted code until reviewed and tested.
- Plugins are untrusted unless explicitly reviewed, signed, and sandboxed.
- External EDA tools such as KiCad/ngspice are separate trust domains.
- Release artifacts are trusted only when verified through GitHub release metadata, attestations, and hashes.

## Primary risks

| Risk | Mitigation |
|------|------------|
| Malicious design input causes unsafe file access | Path validation, safe YAML parsing, tests, SAST. |
| Workflow privilege exposure from untrusted PRs | Avoid `pull_request_target`, minimal permissions, no privileged data in PR jobs. |
| Dependency compromise | Lockfiles, Renovate, Dependabot alerts, uv audit, dependency review. |
| Accidental private value disclosure | GitHub scanning and Gitleaks workflow. |
| Overclaiming generated hardware correctness | README/SECURITY/docs non-claims and human-review requirement. |
| Release tampering | GitHub release workflow, SBOM, artifact attestations, verification docs. |

## Residual risks

- Solo-maintainer bus factor.
- No formal verification or regulatory certification.
- External EDA oracle coverage depends on installed tool versions.
- Plugin sandboxing is not yet sufficient for arbitrary untrusted plugins.
