# 2026-06-19 Status Reconciliation

This document records the governance reconciliation performed across the README, ROADMAP, CHANGELOG, and audit docs.

## Baseline

- Current package/release baseline: `0.2.2`.
- Next stabilization milestone: `M0 / v0.2.3 - Verification Gate Stabilization`.
- The project is pre-1.0 and must not claim fabrication-ready, production-ready, manufacturer-approved, or no-review autonomy.

## Reconciled Documents

| File | Reconciled Item |
|------|-----------------|
| `README.md` | Feature matrix distinguishes implemented foundations from experimental evidence and planned gates. Roadmap references M0/M1/M2/M3. |
| `docs/ROADMAP.md` | Replaced generic v0.3/v0.4 future roadmap with issue-backed M0/M1/M2/M3 roadmap and exit criteria. |
| `docs/FAQ.md` | Updated alpha baseline from v0.2.1 to v0.2.2. |
| `docs/strategy/current-state-audit.md` | Updated refresh date, version, DFM/proof-pack/plugin status, testing gaps, and 2026-06-19 reconciliation notes. |
| `CHANGELOG.md` | Added Unreleased governance/release-readiness section. |

## Status Rules

Use these status meanings consistently in docs, issues, and releases:

| Term | Meaning |
|------|---------|
| Implemented foundation | Code or workflow exists and is covered by at least basic tests, but may not yet be release-blocking or externally validated. |
| Experimental | Available for review and internal use; format, API, or evidence semantics may change. |
| Release-blocking | Required for a release gate; failure or non-approved skip blocks release. |
| Evidence | A generated artifact showing what was checked. Evidence is not a guarantee of correctness. |
| Human-reviewed | Output may be used only after qualified engineering review. |

## Closed-Issue Audit Policy

Closed issues can stay closed when the original implementation exists, but they must not imply stronger claims than the current evidence supports.

| Historical issue class | Policy |
|------------------------|--------|
| Core implementation closed issues | Keep closed, label `status:validated` when covered by tests or release notes. |
| Proof/manufacturing/benchmark closed issues | Keep closed but attach `status:needs-audit` until release-gate evidence confirms the stronger claim. |
| SPICE or advanced analysis closed issues | Keep closed only if the implemented scope is clearly documented; otherwise open a follow-up issue. |

## Product Positioning Guardrail

Preferred sentence:

> Agent generates design candidates, ZapTrace records verification evidence, and a human engineer approves fabrication decisions.

Avoid:

- "fully autonomous production signoff"
- implicit fabrication readiness claims
- "manufacturer approved"
- "no human review required"
