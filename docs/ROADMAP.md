# ZapTrace Roadmap

## Current status — 2026-07-01

ZapTrace 0.3.0 is the evidence-hardening baseline. The M0–M4 issue-backed roadmap has been completed in the repository: autonomous sign-off vocabulary, requirements coverage, KiCad oracle evidence, governed component/datasheet/footprint evidence, layout/power/SI/PI reports, benchmark corpus manifest, known-failure mutation corpus, and Review Studio benchmark readiness are implemented.

This does **not** mean ZapTrace is fabrication-ready or production-ready. A passing gate means the configured evidence did not block. Every generated schematic, PCB, export, and proof pack still requires qualified human engineering review before fabrication or use.

## Completed roadmap tracks

| Track | Status | Outcome |
|-------|--------|---------|
| M0 — Autonomous Sign-off Foundation | ✅ Complete | status model, proof-pack summaries, claim guard, requirements coverage, assumptions evidence |
| M1 — Closed-loop KiCad & Manufacturing Oracle | ✅ Complete | KiCad ERC/DRC adapters, missing-oracle evidence, parity/export evidence foundations |
| M2 — Governed Component & Footprint Intelligence | ✅ Complete | component schema/validator, lifecycle/sourcing risk, datasheet provenance, footprint proof, risky-package policy, IPC-7351 skeleton |
| M3 — Constraint-aware Autonomous Layout | ✅ Complete | placement scorecard, diff-pair length evidence, impedance/return-path risk, repair proposals, rail/regulator/current-density/SI/PI reports |
| M4 — Professional Review & v1.0 Release Gate | ✅ Complete | 12-family benchmark manifest, golden KiCad fixture format, known-failure mutation corpus, Review Studio benchmark panel |

## What remains for a v1.0-quality product

The next work is not another broad scaffold milestone; it is depth, fixtures, and external validation.

1. **Expand real benchmark fixtures** — for all 12 board families, add requirements, golden KiCad projects, proof packs, manufacturing exports, and known-failure mutations.
2. **Run real KiCad environments in CI** — add optional or matrix-based KiCad CLI ERC/DRC/parity/export smoke jobs where the toolchain is installed.
3. **Grow the governed component/footprint library** — prioritize module, DFN/LGA/aQFN/RJ45/RF packages with datasheet-backed geometry and provenance.
4. **Improve routing fidelity** — push-and-shove/rip-up routing, pad-aware routing, length tuning, impedance stackup integration, and return-path/plane geometry evidence.
5. **Integrate solver-grade analysis** — external SI/PI/thermal/PDN tools should become evidence producers for production validation workflows.
6. **Harden plugin/runtime security** — enforce signed plugin admission and stronger sandboxing before recommending untrusted extensions.
7. **Release governance** — keep semantic versioning, release notes, security policy, CI evidence, proof-pack non-claims, and benchmark regression results visible.

## Non-goals

ZapTrace does not claim to be:

- a full replacement for an interactive PCB editor;
- a fabrication approval system;
- a no-human-review autonomous production sign-off authority;
- a field solver, compliance lab, or manufacturer DFM approval service;
- a guarantee that a circuit is safe, functional, manufacturable, or certifiable.

## Contribution focus

Good next contributions are narrow, evidence-producing changes: one board family fixture, one footprint proof, one datasheet fact extractor, one KiCad parity check, one mutation test, or one Review Studio panel improvement at a time.
