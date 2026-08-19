# Complete Release Evidence

ZapTrace release-export operations fail closed unless the exact current design state has complete verification, fabrication-policy, component, assembly, and approval evidence. The same policy is used by direct Python calls, the tool registry, MCP, REST-backed tool execution, CLI export commands, and generated-board CI gates.

This control governs whether ZapTrace may emit release-class KiCad, Gerber, Excellon, manufacturing-bundle, or pick-and-place artifacts. BOM and assembly coverage inside a manufacturing bundle are part of the gate. Standalone BOM preview endpoints remain inspection-only and must not be interpreted as release approval. This control does not certify the resulting hardware as safe, compliant, production-ready, or fabrication-approved.

## Canonical statuses

Release-critical evidence uses one status vocabulary:

| Status | Meaning | Release allowed? |
|---|---|---:|
| `pass` | The required check ran against the current evidence identity and passed. | Yes |
| `fail` | The required check ran and found a blocking failure. | No |
| `missing-evidence` | Required verification or component/assembly evidence was not produced. | No |
| `skip-approved` | A not-applicable decision has an explicit reason and a separate approval identifier. | Yes, for that skipped policy only |
| `skip-unapproved` | A skip reason exists but has no policy approval identifier. | No |
| `human-review-required` | No current matching engineering review approval is present. | Automated export may proceed only where the underlying gate permits it; fabrication is not human-approved. |
| `human-approved` | A current Review Studio `approve` decision matches the supplied approval ID and design hash. | Yes, as human-review evidence; not a fabrication guarantee. |
| `risk-accepted` | A current Review Studio `accept-risk` decision matches the supplied approval ID and design hash. | Yes, with the recorded waiver and non-claims. |
| `rejected` / `repair-requested` / `rolled-back` | The current state has a blocking terminal human decision. | No |

Unknown, absent, zero-coverage, and partially reconciled states never count as passing.

## Required current evidence

Before a release export, ZapTrace requires:

1. a fresh passing ERC result bound to the current release-relevant design hash;
2. a fresh passing DRC result bound to the same design hash;
3. either a named manufacturer fabrication profile used by DRC, or an explicit not-applicable reason with a separate fabrication-profile skip approval identifier;
4. every populated, non-DNP component accounted for in BOM coverage;
5. every populated, non-DNP component accounted for in pick-and-place coverage through a current placement coordinate;
6. resolvable footprint geometry and proof for every populated component;
7. explicit human review and an approval identifier for risky package families;
8. a non-empty release `approval_id` bound to the complete evidence identity;
9. an explicit `fabrication_status` that remains separate from the automated gate result.

DRC executes against an isolated design copy so validation itself cannot silently change the release identity by adding computed net classes or DRC output.

## Surface parity

The gate is evaluated by the shared tool implementation rather than duplicated at transport boundaries:

- MCP obtains the new inputs from the tool registry schema;
- REST runs current DRC through `POST /api/v1/drc/run/{design_name}` and exposes evidence through `GET /api/v1/drc/result/{design_name}`;
- REST KiCad export accepts the fabrication-profile skip and risky-package review inputs as query parameters;
- CLI `zaptrace kicad export` accepts matching `--fab-profile-skip-*` and `--risky-package-*` options;
- direct Python callers receive the same evidence payload and approval-binding behavior.

Transport authorization remains separate from evidence completeness. A caller must first have `release-export` authority and then satisfy the complete release gate. The REST surface with the complete evidence inputs is `POST /api/v1/release/{design_name}/kicad`; legacy inspection/export routes remain separate and do not weaken this gate.

## Evidence identity

Two identities are intentionally distinct. The design release identity below binds ERC/DRC, component coverage, fabrication policy, and approvals to one hardware-design state. The shared [Evidence Source Identity](evidence-identity.md) binds the report itself to package version, Git commit/ref, dirty state, lock hash, source inputs, and toolchain. A release decision is auditable only when both are present.

The release evidence identity is a canonical SHA-256 digest over:

- release-gate version;
- release-relevant design state hash;
- ERC evidence and its design hash;
- DRC evidence, design hash, and fabrication profile;
- full component, BOM, pick-and-place, footprint, and risky-package coverage;
- fabrication-profile policy status, reason, and skip approval identifier;
- normalized engineering-review status, reviewer identity, decision timestamp, rationale, checklist results, approval match, and reviewed design hash.

The identity intentionally excludes the computed DRC result embedded in a design object. Validation output is represented separately in the evidence payload and therefore cannot recursively change the design identity it is meant to verify.

Proof packs can attach the exact decision through `ProofManifest.release_evidence`. `ReleaseGateProofEvidence.from_release_gate(...)` preserves `automated_gate_status`, `fabrication_status`, the complete evidence identity, approval binding, and normalized `engineering_review` metadata. `ProofManifest.engineering_review` may also expose that record directly. Neither field reconstructs a weaker post-hoc summary, and neither changes `autonomous_signoff` into human approval.

## Approval binding

A release `approval_id` is bound to exactly one evidence identity. Repeating the same approval for the same identity is idempotent. Reusing it after a design, footprint, placement, ERC, DRC, fabrication-profile, skip-reason, or reviewed-evidence change fails with an approval-binding error.

A release approval, a Review Studio decision approval, and a fabrication-profile skip approval are distinct. A generic external release approval is never treated as human review unless it exactly matches a current state-bound Review Studio decision:

- `approval_id` authorizes the complete release evidence identity;
- `fab_profile_skip_approval_id` authorizes only the explicit decision not to use a manufacturer profile;
- `risky_package_approval_id` records the explicit review decision for risky package evidence;
- a Review Studio `approval_id` belongs to an immutable `approve` or `accept-risk` decision bound to the reviewed design hash.

This separation prevents a generic release approval from silently approving an unrelated verification skip.

## Component and assembly reconciliation

DNP components remain visible in total counts but are excluded from populated fabrication and assembly denominators. For every populated component, the gate records:

- component ID and reference;
- footprint name;
- pad and pin counts;
- footprint proof diagnostics;
- risky-package family and diagnostics;
- BOM accounting;
- pick-and-place accounting;
- unresolved or blocked reason.

A populated design with zero checked components is `missing-evidence`, not a vacuous pass. Missing placement coordinates also produce `missing-evidence` because a partial centroid file is not complete assembly evidence.

Vendored footprints are resolved only through the explicit trusted-name registry. Every checked component records a SHA-256 digest over the complete footprint proof, including pad geometry, pin mapping, courtyard, and source provenance. Vendored source paths and upstream file SHA-256 digests are included separately. Unknown package names remain unresolved; ZapTrace never invents pad geometry to satisfy the gate.

## Generated-board CI baseline

The generated-board release gate applies deterministic placement, generates the reviewable project, reconciles every populated component, and evaluates risky packages. The CI run carries an explicit fixture review identifier and a shared source/toolchain identity. Removing review evidence, introducing unresolved geometry, losing placement coverage, changing an approved risky footprint, or changing identity-bound source inputs causes the strict gate or evidence verification to fail.

Current generated-board evidence is uploaded as the `generated-board-release-gate` CI artifact. It is intentionally not committed as a “current” JSON report because a file cannot truthfully embed the hash of the same Git commit that contains it. Deterministic artifact hashes and structural expectations remain protected by regression tests.

The generated project retains its existing non-claims, including `not fabrication-ready`. Passing this CI gate means the expected review artifacts and evidence are complete and internally consistent; it does not convert the generated project into fabrication approval.

## Limitations

- Persistent review, validation, release, ACL, and design state are available only when `ZAPTRACE_SESSION_STORE_ROOT` is configured; the default remains process-local for compatibility.
- SQLite persistence provides restart-safe local/controlled-service state, not distributed consensus or arbitrary untrusted multi-tenant isolation.
- Evidence identity proves consistency of the recorded inputs and checks, not physical correctness of a datasheet, land pattern, model, or board.
- Manufacturer DFM submission, simulation signoff, independent engineering review, fabrication feedback, bring-up, thermal testing, and EMC evidence remain separate release requirements.
