# Support Policy

ZapTrace is a pre-1.0 open-source project maintained on a best-effort basis.

## Supported versions

| Version line | Support status | Notes |
|--------------|----------------|-------|
| `0.3.x` | Supported | Current evidence-hardening line. Security fixes and critical correctness fixes are prioritized. |
| `0.2.x` | Limited | Security fixes may be backported where practical. |
| `<0.2` | Unsupported | Upgrade to a supported version line. |

## Support channels

- Bugs and feature requests: GitHub Issues.
- Security vulnerabilities: follow `SECURITY.md`; do not open a public issue.
- Questions and design discussion: GitHub Discussions when enabled, or issues labeled as documentation/support.

## Response expectations

The project does not provide commercial service-level agreements. The maintainer aims to triage significant bugs, security reports, and release blockers before routine feature requests.

## Scope of support

ZapTrace can help with project usage, examples, generated evidence, and reproducible bug reports. It cannot certify that a generated circuit is safe, manufacturable, compliant, or production-ready. All generated hardware outputs require qualified human engineering review before fabrication or use.

## End-of-life policy

A release line may be marked unsupported when the current architecture has moved on, security fixes cannot be backported safely, or maintainer capacity is unavailable. Unsupported versions should not be used for new work.

## Release verification

Users can verify release asset checksums, GitHub artifact attestations, expected repository identity, and release tags using [Release Verification Guide](docs/security/release-verification.md).

## Dependency and build support

Dependency selection and tracking are documented in [Dependency Policy](docs/supply-chain/dependency-policy.md). Build and validation prerequisites are documented in [Validation Environment](docs/development/validation-environment.md).
