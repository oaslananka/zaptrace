# OpenSSF Gap Analysis

> **Evidence date:** 2026-08-04

## Recommended target

- Immediate: OpenSSF Passing readiness and Baseline Level 1.
- Professional target: OpenSSF Silver readiness and Baseline Level 2.
- Do not claim Gold or foundation-grade maturity until independent maintainers, regular non-author review, and stronger legal/continuity evidence exist.

## Passing and Baseline status

| Area | Classification | Action |
|---|---|---|
| Project and contribution documentation | Passed | Keep interface and contributor documentation synchronized through CI. |
| Maintained evidence | Passed | Continue revision-bound release, CI, dependency, and roadmap evidence. |
| Main-branch integrity | Passed | The active committed ruleset requires stable aggregate quality/security checks and blocks deletion/non-fast-forward updates. |
| Security automation | Passed with bounded scope | Preserve dependency, SAST, secret, fuzz, and exact-image container gates without presenting them as formal correctness. |
| Release integrity | Passed | Preserve SBOM, checksums, attestations, source identity, and verification instructions. |
| Documentation currency | Partial | Finish the machine-derived public-claim inventory and continue negative drift tests. |
| SPDX/REUSE | Passed for tracked-file metadata | Locked `reuse lint` runs in CI with explicit third-party overrides and retained evidence. |

## Silver gaps

| Gap | Classification | Required evidence |
|---|---|---|
| Access continuity | Partial | A trusted backup maintainer or tested emergency steward process. Closed issue #269 documented the policy work, but no backup maintainer is currently listed. |
| Independent review | Missing | Regular non-author review and ruleset approval requirement after reviewer capacity exists. |
| Legal file coverage | Passed for source metadata | Tracked files pass REUSE; dependency-license interpretation and legal review remain separate. |
| Accessibility and internationalization | Partial | Scope-appropriate review for the documentation and Review Studio surfaces. |
| Historical static-analysis debt | Partial | The revision-bound ratchet is active at 49 findings; `.github/sonar-debt-policy.json` targets at most 45 for version 0.5.0. |

## Gold/foundation-grade blockers

| Blocker | Classification | Why not claim |
|---|---|---|
| Bus factor at least two | Missing | The documented active maintainer count is one. |
| Two unassociated significant contributors | Missing | Not demonstrated by repository evidence. |
| Non-author human review | Missing | The active ruleset enforces CI but intentionally requires zero approvals in the solo-maintainer state. |
| Required CODEOWNERS review | Missing | It should be enabled only after an independent reviewer can satisfy it reliably. |
| Complete tracked-file licensing metadata | Passed | Project files and vendored footprint overrides are covered by enforced REUSE metadata. |
| Physical product validation | Outside repository maturity | Software evidence cannot establish general fabrication or product certification. |

## Current follow-up

At the evidence date, the repository had no open issues. The remaining maturity limits are operational goals rather than open-issue claims:

1. Recruit and test a trusted backup maintainer or emergency steward before increasing the continuity claim.
2. Reduce the Sonar debt baseline from 49 to at most 45 for version 0.5.0 without weakening the quality profile.
3. Continue scope-appropriate accessibility and internationalization review.
4. Measure contributor concentration, issue/PR age, first-response time, and release cadence without representing best-effort support as an SLA.

Closed issues [#269](https://github.com/oaslananka/zaptrace/issues/269) and [#305](https://github.com/oaslananka/zaptrace/issues/305) retain the completed governance-policy and distribution-support implementation records. Closing those issues does not establish backup-maintainer capacity or a higher maturity tier.
