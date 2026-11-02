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


## Qualified reviewer acceptance protocol (not yet executed)

This protocol is an invitation to a **future real human evaluation**, not a
claim that an automated browser or an assistant is a qualified hardware reviewer.
Use one externally observed task sheet per participant and do not capture private
identifiers, employer data or hardware project secrets.

- **Participants:** aim for at least five genuinely qualified PCB/schematic
  reviewers, independently recruited and observed. Record qualifications as
  role/experience category, not identity. Count actual participation, not
  simulated runs.
- **Case A — existing native DRC:** a real KiCad board with a reproducible
  track_dangling warning. Ask for the exact rule/severity, whether the
  proposed action introduced the warning, the evidence reference and a
  justified *defer/repair/reject* decision. Do not credit "ready to fabricate".
- **Case B — missing evidence:** a PCB-only comparison without an associated
  verified schematic. Ask whether cross-surface electrical parity was checked
  and what further evidence would be required. The correct answer must state
  NOT CHECKED for the absent schematic and no production authority.
- **Case C — paired schematic and PCB:** real paired KiCad review with an
  R1 value change, native ERC findings and scoped pin/net mismatches. Ask the
  reviewer to select the changed component, locate an unrelated ERC finding,
  return to the exact evidence ID, and identify why a matching reference label
  is *not* proof of electrical parity.
- **Observation:** an independent facilitator starts a monotonic external
  stopwatch at the task disclosure and stops when the reviewer gives their
  final evidence-backed decision. Record completion, source-state SHA,
  task ID, correct changed object, rule/severity, blocking/missing evidence,
  outcome/rationale, unsupported claims, misnavigation and elapsed time.
  For the threshold to qualify as *trustworthy*, both the task answer and
  its evidence link must be correct; a fast but incorrect answer is a failure,
  not a trustworthy time measurement.
- **Accessibility:** exercise keyboard-only navigation and at least one
  screen-reader-supported path; record whether focus, status text and
  source-bound navigation remain understandable. Do not count automated DOM
  checks as proof of human accessibility.
- **Reporting:** publish actual per-task success/error rates and externally
  measured median/p90 time only after real participants finish; report
  failures separately. Report not measured when samples, observation or
  correctness evidence are missing. The offline v2 audit's browser-local
  elapsed_ms remains self-declared and its
  time_to_trustworthy_decision_ms remains null.

No manufacturing, independent DFM approval, supplier outreach, release or
remote AI-provider invocation follows from completing these tasks.
