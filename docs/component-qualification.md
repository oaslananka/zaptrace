# Verified component qualification

ZapTrace qualifies component trust in bounded cohorts. Qualification is evidence-first and deliberately separates machine-verifiable readiness from human engineering review, trust-tier promotion, and release/fabrication approval.

A component can be **review-ready** while still remaining `heuristic`, `release_eligible=false`, and `human_review_required=true`.

## Cohort A

The first qualification cohort is committed in `data/qualification/verified-core-cohort-a.yaml`:

- `esp32-c3-mini-1`
- `usb-c-16p` (GCT USB4105-15-A-120)
- `ap2112k-3.3`
- `bme280`
- `atecc608b`

The cohort snapshot is evaluated as of `2026-09-05` with a 90-day freshness horizon for lifecycle and sourcing evidence.

## Machine readiness

The gate checks every critical component field for:

- authoritative manufacturer or authorized-distributor source type;
- source locator and identity;
- exact source identity via raw `source_sha256`, or a digest-bound repository capture for mutable lifecycle/sourcing web claims;
- source version/capture identity;
- extraction method and date;
- lifecycle/sourcing freshness;
- exact physical package pin map;
- committed footprint proof identity and source digest;
- footprint pad/pin/courtyard consistency.

Footprint proofs are committed under `data/library/evidence/footprints/` and bind the reviewed component footprint name to the exact vendored KiCad source file SHA-256.

Machine blockers are separate from human blockers. A missing or unstable source identity cannot be hidden by a reviewer approval. For mutable manufacturer/distributor pages, ZapTrace does **not** pretend that a CDN/anti-bot HTML response is a durable manufacturer document. Instead, lifecycle/sourcing evidence may bind to a committed JSON claim capture using `source_capture_path` plus `source_capture_sha256`. The capture must match component ID, source type, locator, identity, source version, capture date, critical field, and the committed component field value. This fallback is limited to lifecycle/sourcing; it does not replace raw document hashes for immutable manufacturer documents.

## Human review boundary

The gate reports but never invents:

- field reviewer identity and review date;
- high-confidence reviewer judgment;
- risky-package review approval;
- release and fabrication review scopes.

Those are explicit human actions. The gate does not set `trust_tier=verified`, does not create `reviewed_by` metadata, and does not make a component release eligible.

## Current Cohort A snapshot

`docs/reports/component-qualification-cohort-a-2026-09-05.json` is the committed deterministic snapshot.

Current result:

- review-ready: 5 / 5;
- machine-blocked: 0 / 5;
- human-review-required: 5 / 5;
- release-eligible: 0 / 5;
- report SHA-256: `4db763b3fd1ce9fca5db69d78f3fb7578807afa39da6ae9a5152724ee963ada2`.

The former machine blockers are now bound to reproducible authoritative evidence:

- `usb-c-16p`: a SHA-bound GCT USB4105 mutable-web capture for lifecycle and manufacturer-catalog sourcing claims;
- `ap2112k-3.3`: raw Diodes `GL-106 Rev 249` Master CoC PDF bytes, SHA-bound to the current manufacturer document that lists the orderable SOT25 part as active;
- `atecc608b`: a SHA-bound Microchip ATECC608B mutable-web capture for the lifecycle claim (`not-recommended-for-new-designs`).

These evidence bindings make the three records machine-review-ready; they do **not** promote trust, invent reviewer identity, approve procurement, or override the underlying manufacturer status. All five cohort records still require explicit engineering review before any verified/release/fabrication claim.

## Run the gate

Strict mode fails when any machine blocker remains; the current Cohort A snapshot passes this machine-only gate:

```bash
uv run python scripts/ci_component_qualification_gate.py \
  --output component-qualification.json
```

To write the same evidence snapshot without making strict-mode exit status part of the caller contract:

```bash
uv run python scripts/ci_component_qualification_gate.py \
  --report-only \
  --output component-qualification.json
```

The report schema is committed at `schemas/component-qualification-report-v1.schema.json`.

## Non-claims

Review readiness does not prove manufacturer approval, component authenticity, physical hardware behavior, thermal adequacy, EMC/SI/PI performance, assembly success, fabrication correctness, regulatory compliance, or production suitability. Physical and qualified engineering review remain separate gates.
