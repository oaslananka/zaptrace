# Maintainers

## Current maintainers

| GitHub handle | Role | Responsibilities |
|---------------|------|------------------|
| `@oaslananka` | Lead maintainer | Repository administration, roadmap, releases, security triage, merge decisions |

## Sensitive access

Sensitive access includes repository administration, branch/ruleset changes, repository configuration, release creation, private vulnerability reports, and package publishing credentials.

At the time of this document, ZapTrace should be treated as a solo-maintainer project. This is acceptable for Professional OSS maturity when documented, but it is not sufficient for OpenSSF Gold or foundation-grade claims.

## Access review policy

New collaborators should receive the lowest practical permissions by default. Escalated permissions should be granted only after reviewing the contributor's history, need for access, security posture, and expected responsibilities.

## Continuity plan

The current continuity risk is the single-maintainer bus factor. Recommended next steps:

1. Add at least one trusted backup maintainer for issue triage and emergency release support.
2. Document package registry ownership and recovery steps outside the public repository.
3. Require 2FA/passkeys for all maintainers.
4. Keep release and CI processes reproducible from public workflow definitions.

## Gold/foundation-grade gap

Gold/foundation-grade maturity requires at least two active, significant, and preferably unassociated contributors or maintainers, plus regular non-author human review.

## Related policies

- [Governance](GOVERNANCE.md)
- [Maintainer Access Policy](docs/governance/maintainer-access.md)
- [Access Continuity Plan](docs/governance/access-continuity.md)
- [Security Policy](SECURITY.md)
- [Support Policy](SUPPORT.md)
