# Dependency Policy

ZapTrace uses standard package-manager metadata, lockfiles, and automated dependency review to select, obtain, and track dependencies.

## Dependency sources

| Ecosystem | Source files |
|-----------|--------------|
| Python | `pyproject.toml`, `uv.lock` |
| Rust | `zaptrace_core/Cargo.toml`, `zaptrace_core/Cargo.lock` |
| Containers | `Dockerfile`, `docker-compose.yml`, `requirements/container-runtime.txt`, `requirements/container-apk.txt` |
| GitHub Actions | `.github/workflows/*.yml` |

## Selection principles

New dependencies should be:

- necessary for a clear feature, security, or maintainability goal;
- actively maintained;
- compatible with the current PolyForm Noncommercial distribution model and any separately licensed third-party content;
- available from standard package indexes or trusted upstreams;
- pinned or locked where practical;
- reviewed with extra caution when they affect parsing, export, MCP/API, plugin execution, CI, or release workflows.

## Tracking and update automation

- `uv.lock` tracks resolved Python dependencies.
- `requirements/container-runtime.txt` is a hash-complete export of the container runtime subset; CI rejects drift from `uv.lock`.
- `requirements/container-apk.txt` records exact Alpine runtime package versions for the pinned base image.
- `Cargo.lock` tracks resolved Rust dependencies.
- Renovate produces dependency update and vulnerability-remediation pull requests.
- GitHub Dependabot alerts and dependency review remain enabled; routine Dependabot version-update PRs are not generated.
- Low-risk Renovate updates labeled `automerge:enabled` join the protected Mergify queue only after all required checks succeed. Major, native, runtime-sensitive, security-labeled, CI and container changes require manual review.
- Security scan workflows run dependency audit and static-analysis jobs.
- The locked Renovate configuration validator under `.github/renovate-validation/` is a **development/CI-only** copy of the CLI, not the hosted Renovate bot. Its npm `global-agent` 4.x override replaces the legacy `global-agent` 3 -> `roarr` -> unpatched `sprintf-js` chain; the override must be revalidated when Renovate changes its proxy APIs. Renovate 44.148.4 also includes the patched Handlebars 4.7.10 release. The validator runs with `npm ci --ignore-scripts`, then `renovate-config-validator --strict` from the repository root.
- Remaining upstream `braces` <=3.0.3 recursive-pattern DoS risk in Renovate's validation-only dependency graph has **no upstream patched release** as of 2026-10-09; do not treat a clean GitHub Dependabot alert list as a comprehensive npm audit. Do not force an unreviewed third-party fork or downgrade Renovate to evade the advisory.

## Review policy

Dependency update pull requests should include CI results and, for major/runtime-sensitive updates, release note review. Updates that touch parser, plugin, MCP/API, release, or CI behavior should be treated as security-sensitive until reviewed.

## Release evidence

Official release workflows produce checksums and SBOM evidence and verify container build provenance that binds the source commit, pinned base digest, built wheel digest, and dependency-manifest digest. See [Release Verification Guide](../security/release-verification.md).
