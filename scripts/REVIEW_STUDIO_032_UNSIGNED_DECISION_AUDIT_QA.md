# Review Studio #31 — local unsigned evidence/decision study

Source-only feature, not a signed release, engineering approval, identity provider or manufacturing authorization.

## Design

Existing legacy v1 decision import remains available. Optional v2 exports a self-declared reviewer label, the existing source-bound decision status and rationale, inspected native KiCad evidence IDs, and untrusted monotonic browser timings. All records explicitly deny verified identity, cryptographic signing, electrical/fabrication approval and source modification.

Run strict offline validation:

```sh
python3 scripts/review_studio_decision_audit.py --state review.state.json --audit exported-v2.json
```

The validator rejects a wrong hash, missing native reference, invented reviewer authority, fictitious trustworthy-decision timing, extra keys and altered state catalog. It does **not** establish who the reviewer was, that they viewed or understood the evidence, that their machine clock is trustworthy, or that a mutable local JSON file is authentic. No service, account, key or new dependency was added.

## Native local QA

Ignored local evidence in `build/qa-032-decision-audit/`: genuine KiCad 10 schematic/PCB review, browser-run v2 export JSON, source state, Chrome results/screenshots. The source fixture R1 changes 4.7k → 10k and ERC reports 0 errors, 28 warnings; it is **not** the actual ESP32 board acceptance. Negative regression tests exercise spoofed identity/signature, stale state, extra authority fields, invalid timing and invented evidence.

## Future qualified UX timing

Time-to-trustworthy-decision is **not measured** by this build. Chrome automated timing is only browser-local interaction latency, never independent engineering UAT. A qualified study needs recruited hardware engineers, externally observed task starts/ends, correct identification of changed objects and blockers, evidence-backed next decisions, keyboard/screen-reader acceptance, and medians plus error/unsupported conclusions. At least five real participants are a proposed evaluation protocol, not completed evidence.

Open: authenticated/signed human accountable approval design, independent hardware UAT, real multi-footprint ECO, schematic↔PCB pin/net parity, physical DRC/copper/STEP/supplier proof, and exact-source immutable package/Ubuntu acceptance.
