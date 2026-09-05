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
- SHA-256 source binding;
- source version/capture identity;
- extraction method and date;
- lifecycle/sourcing freshness;
- exact physical package pin map;
- committed footprint proof identity and source digest;
- footprint pad/pin/courtyard consistency.

Footprint proofs are committed under `data/library/evidence/footprints/` and bind the reviewed component footprint name to the exact vendored KiCad source file SHA-256.

Machine blockers are separate from human blockers. A missing or unstable source digest cannot be hidden by a reviewer approval.

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

- review-ready: 2 / 5 (`esp32-c3-mini-1`, `bme280`);
- machine-blocked: 3 / 5;
- human-review-required: 5 / 5;
- release-eligible: 0 / 5.

The remaining machine blockers are intentionally fail-closed:

- `usb-c-16p`: lifecycle and sourcing manufacturer-web evidence is not bound to a stable source SHA-256;
- `ap2112k-3.3`: lifecycle and sourcing manufacturer-web evidence is not bound to a stable source SHA-256;
- `atecc608b`: lifecycle manufacturer-web evidence is not bound to a stable source SHA-256.

The authoritative datasheet/drawing sources and vendored footprint sources for the five parts are SHA-bound. The mutable product-page blockers above must be resolved with reproducible evidence before those records can become review-ready.

## Run the gate

Strict mode fails when any machine blocker remains:

```bash
uv run python scripts/ci_component_qualification_gate.py \
  --output component-qualification.json
```

To reproduce the current evidence snapshot without converting known blockers into a passing strict gate:

```bash
uv run python scripts/ci_component_qualification_gate.py \
  --report-only \
  --output component-qualification.json
```

The report schema is committed at `schemas/component-qualification-report-v1.schema.json`.

## Non-claims

Review readiness does not prove manufacturer approval, component authenticity, physical hardware behavior, thermal adequacy, EMC/SI/PI performance, assembly success, fabrication correctness, regulatory compliance, or production suitability. Physical and qualified engineering review remain separate gates.
