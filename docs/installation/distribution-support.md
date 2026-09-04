# Distribution Support and Clean-Install Evidence

ZapTrace is pre-1.0. This page is the public support contract for package and container artifacts. The machine-readable source of truth is [`config/distribution-support.json`](https://github.com/oaslananka/zaptrace/blob/main/config/distribution-support.json).

A platform is **supported** only when the exact artifact is continuously built, installed outside the source tree, and exercised through the applicable CLI, SDK, REST API, and MCP entry points. A compatibility test or successful compilation alone does not create a release-support claim.

## Current distribution channels

- **GitHub Releases** is the authoritative channel for source distributions, supported native wheels, checksums, SBOMs, attestations, and clean-install evidence.
- **PyPI end-user installation is enabled** for the verified `v0.3.3` release as `zaptrace-eda==0.3.3`; the import package and CLI remain `zaptrace`. Production publication uses the environment-scoped GitHub OIDC Trusted Publisher and is downstream of TestPyPI artifact/hash and clean-install verification. GitHub Releases remains the authoritative evidence bundle for checksums, SBOMs, attestations, and per-target clean-install reports.
- **GHCR publication is not enabled.** The pinned Dockerfile is continuously built and verified, but no official registry image is currently claimed.
- A source checkout remains available for contributors and for explicitly best-effort or unsupported combinations.

### Registry identity and staged publishing

`zaptrace-eda` is the distribution name used by Python registries and artifact metadata. Installing that distribution continues to provide `import zaptrace` and the `zaptrace`, `zaptrace-mcp`, `zaptrace-mcp-http`, and `zaptrace-api` console commands.

### Name normalization and abuse-risk review

The registry identity is deliberately `zaptrace-eda`, not `zaptrace`. The `-eda` suffix makes the distribution identity specific to the electronics-design-automation project while preserving the established Python import and CLI surface. This avoids a registry-name collision with the separate `zaptrace` distribution namespace without forcing application code or shell integrations to migrate.

Python package indexes normalize case and runs of `.`, `-`, and `_` for project-name comparison. Consequently, `zaptrace-eda`, `zaptrace_eda`, and `zaptrace.eda` are normalization-equivalent spellings of the same registry identity, not independent names that can be reserved as defensive packages. Release metadata and user-facing installation guidance therefore use the canonical spelling `zaptrace-eda`; built wheel and source-distribution filenames use the packaging filename form `zaptrace_eda-*`.

That normalization blocks separator-only collision variants but does not eliminate typosquatting by genuinely different names. The project does not publish look-alike defensive packages. Maintainer guidance, release evidence, and PyPI installation instructions must name `zaptrace-eda` exactly and bind it to `oaslananka/zaptrace` plus the environment-scoped Trusted Publisher. A future distribution rename would require an explicit migration plan; changing the registry name silently while keeping the same import surface is not an accepted compatibility strategy.

The release workflow uses GitHub OIDC Trusted Publishing; no PyPI or TestPyPI API token is stored in the repository. A manual `release.yml` dispatch on `main` may publish the current development identity to the `testpypi` environment for staging only. Tagged releases publish the exact already-built source distribution and native wheels to TestPyPI first, compare registry filenames and SHA-256 values with the CI artifacts, clean-install the exact registry version, then publish the same artifacts to PyPI and repeat those checks. GitHub Release creation is downstream of successful PyPI verification so a failed registry publication is not presented as a complete multi-channel release.

TestPyPI is a staging channel, not a supported end-user distribution channel.

## Support levels

- `supported`: the named artifact/platform combination is continuously clean-installed and smoke-tested.
- `best-effort`: bounded compatibility or source-build evidence exists, but the combination does not receive the complete tagged-release artifact contract.
- `unsupported`: no artifact is published or continuously verified for that combination. The guidance column gives the safe next step.

## Support matrix

| Target ID | OS | Architecture | Python | Artifact | Native extension | Support level | Channel | Guidance |
|---|---|---|---|---|---|---|---|---|
| `native-linux-x86_64-cp313` | Linux | x86_64 | CPython 3.13 | native wheel (`manylinux_x86_64`) | required | `supported` | GitHub Releases + PyPI | Install `zaptrace-eda` from PyPI, or use the matching Linux x86_64 GitHub Release wheel and evidence bundle. |
| `native-macos-x86_64-cp313` | macOS | x86_64 | CPython 3.13 | native wheel (`macosx_x86_64`) | required | `supported` | GitHub Releases + PyPI | Install `zaptrace-eda` from PyPI, or use the matching macOS Intel GitHub Release wheel and evidence bundle. |
| `native-macos-arm64-cp313` | macOS | arm64 | CPython 3.13 | native wheel (`macosx_arm64`) | required | `supported` | GitHub Releases + PyPI | Install `zaptrace-eda` from PyPI, or use the matching Apple Silicon GitHub Release wheel and evidence bundle. |
| `sdist-linux-x86_64-cp313` | Linux | x86_64 | CPython 3.13 | source distribution | absent | `supported` | GitHub Releases + PyPI | Install `zaptrace-eda` from PyPI or the matching GitHub Release sdist for the verified pure-Python fallback. |
| `source-linux-x86_64-cp312` | Linux | x86_64 | CPython 3.12 | source distribution | absent | `best-effort` | GitHub Releases + PyPI | Install `zaptrace-eda` from PyPI or use the GitHub Release sdist; source compatibility is tested, but tagged registry clean-install evidence is produced on CPython 3.13. |
| `source-linux-x86_64-cp314` | Linux | x86_64 | CPython 3.14 | source distribution | absent | `best-effort` | GitHub Releases + PyPI | Install `zaptrace-eda` from PyPI or use the GitHub Release sdist; compatibility is tested, but tagged registry clean-install evidence is produced on CPython 3.13. |
| `container-linux-x86_64-cp313` | Linux | x86_64 | CPython 3.13 | container image (`linux/amd64`) | required | `best-effort` | source build only | Build the pinned Dockerfile from reviewed release source; GHCR is not enabled. |
| `native-linux-arm64-cp313` | Linux | arm64 | CPython 3.13 | native wheel (`manylinux_aarch64`) | required | `unsupported` | none | No native wheel is published. Use the source distribution as an unverified fallback or build from source until a dedicated runner is added. |
| `native-windows-x86_64-cp313` | Windows | x86_64 | CPython 3.13 | native wheel (`win_amd64`) | required | `unsupported` | none | No native wheel or isolated mutating-agent runtime is supported. Use the source distribution only for unverified read-only SDK/CLI experiments; use WSL or the Linux container for agent mutations. |
| `native-linux-x86_64-cp312` | Linux | x86_64 | CPython 3.12 | native wheel (`manylinux_x86_64`) | required | `unsupported` | none | Use the source distribution pure-Python fallback or CPython 3.13 for a supported native wheel. |
| `native-linux-x86_64-cp314` | Linux | x86_64 | CPython 3.14 | native wheel (`manylinux_x86_64`) | required | `unsupported` | none | Use the source distribution pure-Python fallback or CPython 3.13 for a supported native wheel. |

The JSON policy remains authoritative when prose and policy differ. CI validates unique target IDs, required fields, support levels, verification workflow references, and actionable unsupported-target guidance.

## Installing a GitHub Release artifact

List and download the assets for a tag:

```bash
gh release view <tag> --repo oaslananka/zaptrace
gh release download <tag> --repo oaslananka/zaptrace --dir /tmp/zaptrace-release
```

Create a clean environment and install the artifact that matches the matrix:

```bash
uv venv /tmp/zaptrace-env --python 3.13
uv pip install --python /tmp/zaptrace-env/bin/python /tmp/zaptrace-release/zaptrace_eda-<version>-*.whl
/tmp/zaptrace-env/bin/zaptrace --version
/tmp/zaptrace-env/bin/zaptrace --help
```

For the source distribution fallback, replace the wheel path with `zaptrace_eda-<version>.tar.gz`. A source distribution may build a pure-Python package without `zaptrace._core`; native acceleration is not implied.

## Clean-install evidence

The release workflow retains one report for every claimed package artifact:

- `distribution-smoke-sdist-linux-x86_64-cp313.json` and its Markdown summary;
- `distribution-smoke-<target-id>.json` and its Markdown summary for each native wheel;
- existing `native-boundary-<rust-target>.json` evidence for native behavior and resource limits;
- existing exact-image container provenance, SBOM, vulnerability, and Compose REST/MCP smoke evidence.

Each distribution report records:

- artifact filename, size, and SHA-256;
- exact source commit and `uv.lock` SHA-256;
- Python implementation/version, operating system, and architecture;
- installed package path and source-tree isolation result;
- `zaptrace --version` and `zaptrace --help`;
- SDK import and minimal public-model construction;
- required, optional, or absent native-extension state;
- loopback REST health/authentication checks;
- loopback MCP HTTP authentication, `2026-07-28` `server/discover` identity, and stateless transport evidence;
- deterministic evidence digest and explicit non-claims.

The JSON/Markdown evidence is downloaded into the release aggregation job before the release SBOM and `SHA256SUMS` are generated. Missing evidence blocks release creation.

## Unsupported combinations

Unsupported does not mean a platform can never run ZapTrace. It means the project does not publish and continuously verify the named artifact. For Linux arm64, Windows x86_64, CPython 3.12 native, and CPython 3.14 native combinations:

1. prefer the source distribution pure-Python fallback;
2. treat local native builds as unverified local artifacts;
3. do not report a local successful build as project-supported;
4. retain the build logs, artifact hash, interpreter identity, and smoke results when proposing a new supported target.

A target becomes supported only after a dedicated CI runner builds the exact artifact, installs it in a clean environment, exercises the public entry points, and retains evidence on every tagged release.

### Windows agent-runtime boundary

The isolated mutating-agent worker relies on POSIX process groups, private mode bits, and directory-relative IPC operations. Native Windows execution therefore rejects mutating agent and MCP tools before a worker starts, with the stable `UNSUPPORTED_PLATFORM` error. Read-only SDK/CLI experiments remain unverified; use WSL or the verified Linux container when agent mutations are required.

## Container boundary

The Dockerfile produces a Linux x86_64 image with a locally built native wheel, hash-complete Python dependencies, exact Alpine packages, embedded source/base/dependency provenance, SBOM generation, vulnerability policy, and Compose REST/MCP smoke tests. This is strong source-build evidence, but it is `best-effort` distribution support because GHCR publication is not enabled.

## Non-claims

Passing clean-install checks proves only the named artifact, interpreter, runner, and bounded entrypoint checks. It does not establish universal platform support, formal verification, production qualification, fabrication readiness, manufacturer approval, regulatory compliance, or immunity from platform-specific defects. Unsupported and best-effort targets remain outside the supported release contract until continuous evidence exists.
