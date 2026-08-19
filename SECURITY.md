# ZapTrace Security Policy

## Reporting a Vulnerability

**Do not open public GitHub issues for security vulnerabilities.**

Instead, please report them privately by using GitHub Private Vulnerability Reporting:
https://github.com/oaslananka/zaptrace/security/advisories/new

If that channel is unavailable, contact the maintainer using the public profile
contact information and include enough detail to reproduce the issue privately.

We will acknowledge receipt within 48 hours and provide a timeline for a fix
and disclosure. See [Vulnerability Response Process](docs/security/vulnerability-response.md) for triage targets, reporter credit, and disclosure workflow.

## Scope

The following are in scope:

- Remote code execution in the MCP server or REST API
- Arbitrary file read/write through the design parser or export pipeline
- Injection attacks through YAML/design file parsing
- Authentication/authorization bypass in the API
- Supply chain attacks via the plugin system
- The Rust extension and PyO3 boundary in `zaptrace_core/`, including panic propagation, denial of service, non-finite or degenerate geometry, resource exhaustion, incorrect Python exception conversion, and native-wheel integrity

For Rust/PyO3 reports, include the ZapTrace version, Python version, operating system and architecture, wheel filename and SHA-256, `rustc --version`, `cargo --version`, `cargo audit --version`, the smallest reproducer, and whether the hosting Python process remained usable after the rejected call.

## Out of Scope

- Third-party dependencies reported without a ZapTrace-specific impact path (report upstream first)
- Theoretical vulnerabilities without a demonstrated exploit path

## Safe Usage

1. **Do not run `zaptrace-mcp` or `zaptrace-api` with network exposure** without
   proper authentication and sandboxing in front.
2. **Do not parse untrusted YAML files** without validation. ZapTrace uses
   `yaml.safe_load`, but malicious input could still cause resource exhaustion.
3. **Plugins are untrusted by default**. Only install plugins from sources
   you trust.
4. **Do not automate fabrication orders**. All manufacturing outputs require
   human review before submission to a fab house.

## Security Measures

- `yaml.safe_load` is used for all YAML parsing (no arbitrary code execution)
- Pydantic validation rejects malformed designs
- Gerber output is generated programmatically (no shell injection)
- Plugin system has a permission manifest model
- MCP server runs on stdio by default (no network exposure)
- Mutating MCP tools run in isolated subprocesses with per-session serialization, process-group cancellation, staged output publication, and terminal lifecycle audit evidence; see [cancellation-safe tool execution](docs/security/cancellation-safe-tool-execution.md)
- Native placement/routing wrappers preflight concrete Python-list lengths before PyO3 element extraction; kernels then validate finite values, derived arithmetic, indices, geometry ranges, and explicit resource limits before allocation-heavy work
- Every supported native-wheel target is installed and exercised through mandatory PyO3 boundary verification before release artifacts are accepted
- Cargo dependencies are checked with a pinned `cargo-audit` version and retained as raw plus normalized evidence
- CI utilities that need a fallback `HOME` use an atomically created, process-owned mode-`0700` directory below a validated temporary parent; symlink parents and non-sticky world-writable parents are rejected, and cleanup never follows a replacement symlink

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.3.x   | ✅ Current |
| 0.2.x   | ⚠️ Security fixes where practical |
| < 0.2   | ❌ |

<!-- professional-oss-security-process -->
## Coordinated Vulnerability Disclosure Process

Preferred reporting channel: GitHub Private Vulnerability Reporting for this repository:
https://github.com/oaslananka/zaptrace/security/advisories/new

If private reporting is unavailable to the reporter, contact the maintainer using the public profile contact information and include enough detail to reproduce the issue privately.

Expected response targets:

| Step | Target |
|------|--------|
| Acknowledge report | within 48 hours |
| Initial triage | within 7 calendar days |
| Fix plan for confirmed vulnerabilities | within 14 calendar days where practical |
| Public advisory or release note | after fix availability and coordinated disclosure |

Security advisories should identify affected versions, fixed versions, impact, workarounds, and whether the issue affects generated artifacts, runtime services, MCP tools, REST API, plugins, native wheels/PyO3, or release infrastructure.

## Supported Release Policy

ZapTrace is pre-1.0. The current minor release line receives security fixes where practical. Older release lines may receive fixes only when the patch is low-risk and does not conflict with the current architecture. This policy is also summarized in [SUPPORT.md](SUPPORT.md).

## Supply-Chain Security

- GitHub Actions are pinned by immutable commit SHA where practical.
- Renovate manages normal dependency updates; Dependabot remains enabled for GitHub-native security alerting.
- Release workflows generate SBOM/provenance artifacts where configured.
- Native dependency advisory evidence records the exact Cargo.lock digest and pinned cargo-audit tool version.
- The release process and verification instructions are documented in [release integrity](docs/security/release-integrity.md) and the [release verification guide](docs/security/release-verification.md).
- Dependency selection and tracking are documented in [dependency management](docs/development/dependency-management.md).

## Security Non-Claims

A clean security scan, Rust's memory-safety model, or successful native boundary evidence does not prove that ZapTrace is safe for untrusted multi-tenant execution or that placement/routing algorithms are formally correct. Network-exposed API/MCP deployments and untrusted plugins require additional sandboxing, authentication, resource limits, and operational controls outside this repository.
