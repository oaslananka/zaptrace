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
- compatible with the MIT license and distribution model;
- available from standard package indexes or trusted upstreams;
- pinned or locked where practical;
- reviewed with extra caution when they affect parsing, export, MCP/API, plugin execution, CI, or release workflows.

## Tracking and update automation

- `uv.lock` tracks resolved Python dependencies.
- `requirements/container-runtime.txt` is a hash-complete export of the container runtime subset; CI rejects drift from `uv.lock`.
- `requirements/container-apk.txt` records exact Alpine runtime package versions for the pinned base image.
- `Cargo.lock` tracks resolved Rust dependencies.
- Renovate handles normal dependency updates.
- Dependabot remains enabled for GitHub-native security alerts and dependency review.
- Security scan workflows run dependency audit and static-analysis jobs.

## Review policy

Dependency update pull requests should include CI results and, for major/runtime-sensitive updates, release note review. Updates that touch parser, plugin, MCP/API, release, or CI behavior should be treated as security-sensitive until reviewed.

## Release evidence

Official release workflows produce checksums and SBOM evidence and verify container build provenance that binds the source commit, pinned base digest, built wheel digest, and dependency-manifest digest. See [Release Verification Guide](../security/release-verification.md).
