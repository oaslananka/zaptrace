# Governance

ZapTrace currently uses a solo-maintainer governance model.

## Decision model

The project owner and lead maintainer makes final decisions about scope, release timing, roadmap priority, repository settings, and merge policy. Decisions should be documented through issues, pull requests, roadmap updates, or design notes when they affect users or contributors.

## Current maturity claim

ZapTrace targets **Professional OSS / Mature OSS** practices. It does not claim OpenSSF Gold, foundation-grade governance, or regular independent human review until the project has multiple active maintainers and independent contributors.

## Roles

| Role | Responsibility | Current holder |
|------|----------------|----------------|
| Lead maintainer | Final technical and release decisions, security triage, repository settings | `@oaslananka` |
| Contributor | Submit issues, pull requests, docs, tests, examples, fixtures, and review comments | Community contributors |
| Security reporter | Report suspected vulnerabilities privately and coordinate disclosure | External reporters |

See `MAINTAINERS.md`, [Access Continuity Plan](docs/governance/access-continuity.md), and [Maintainer Access Policy](docs/governance/maintainer-access.md) for access and continuity details.

## Change acceptance process

Changes should be proposed by pull request unless they are emergency administrative changes. The pull request template defines expected evidence, safety checks, and release-gate impact. For public behavior changes, documentation and changelog entries are expected.

## Review policy

The repository is configured for required CI checks. Human review is desirable for all non-trivial changes, but the current solo-maintainer model means independent review cannot be guaranteed. Gold/foundation-grade maturity requires enabling required non-author PR review and adding independent maintainers or reviewers.

## Conflict resolution

The lead maintainer resolves disputes after considering project safety, evidence quality, maintainability, roadmap fit, and user impact. If the project gains multiple maintainers, this document should be updated with an escalation process and voting/consensus policy.

## Access continuity

Solo-maintainer projects have inherent bus-factor risk. The current mitigation is documented public process, public CI/release automation, explicit governance, and issue-based tracking. Full continuity requires at least one additional trusted maintainer or emergency steward with documented release and repository administration capability. Until that exists, access-continuity and bus-factor criteria should remain partial/unmet rather than overstated.

## Non-goals

Governance does not claim manufacturer approval, regulatory certification, automatic fabrication sign-off, or production readiness for generated boards.
