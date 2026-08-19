# ZapTrace Product Manifesto

## The Problem

Hardware engineers spend more time managing tools than thinking about circuits.
The state-of-the-art design flow is a spreadsheet-orchestrated patchwork:
schematic capture in one tool, layout in a second, BOM in a third, simulation in
a fourth, compliance pre-check in email threads, and sign-off in PDFs. Every
hand-off is lossy. Every revision cycle adds manual reconciliation. Mistakes
reach fabrication.

## The Bet

AI agents can automate the boring parts of hardware design — constraint
extraction, rule checking, BOM sourcing, simulation orchestration, evidence
packaging — without replacing the engineer. The engineer decides. The agent
verifies, traces, and documents.

## What ZapTrace Is

ZapTrace is an **agent-native, verified hardware design platform**. It provides:

1. **A canonical hardware IR** — a typed, diffable in-memory model of a design
   that agents can read, mutate, and reason over.
2. **A rule engine** — ERC, DRC, DFM, SI/PI, compliance, and domain-specific
   checks that run deterministically on the IR.
3. **A proof system** — every agent decision is recorded with evidence, waivers
   are tracked, and the full audit trail is packaged for sign-off.
4. **An agent SDK** — tool primitives that give AI models the right verbs
   (synthesize, place, route, check, export) and deny-by-default capability
   gates that prevent unreviewed mutations.

## Design Principles

### Verifiability over convenience

Every output includes a proof pack: what was checked, what was flagged, who
waived what, and with what evidence. Outputs that cannot be traced are not
outputs.

### Deny-by-default capability model

Read is always allowed. Write requires explicit capability grants. Exports
require release-level grants. No tool escalates its own privilege.

### Non-claims are first-class

The system explicitly states what it does not verify. Stock data may be stale.
3-D heights are not checked. Simulation results are best-effort without lab
validation. These caveats ship with every artefact.

### Agent-first, EDA-second

ZapTrace is not a PCB editor. It does not replace KiCad, Altium, or Cadence.
It sits alongside them as an agent-orchestrated verification and intelligence
layer. Round-trip fidelity with existing EDA formats is a goal; replacing them
is not.

## What ZapTrace Is Not

- A full schematic capture or layout editor (no manual routing environment)
- A simulation engine (it orchestrates ngspice; it does not implement SPICE)
- A distributor (BOM intelligence is evidence, not procurement approval)
- A compliance authority (pre-checks flag risks; certification is a human process)

## The Vision

A hardware team commits a design change. Within seconds:

1. An agent runs ERC, DRC, DFM, SI/PI, and compliance checks.
2. BOM risks are scored against live distributor data.
3. SPICE simulations run automatically and annotate nodes with DC bias.
4. A proof pack is assembled and submitted for review.
5. The review team sees a unified cockpit — violations, waivers, evidence — and
   approves or rejects with a signed decision record.
6. The release gate passes and Gerbers are exported with a locked audit trail.

The engineer reviews the decision. The agent does the work.

## Roadmap Commitments

| Priority | Area | Commitment |
|----------|------|------------|
| P0 | IR + ERC + DRC | Canonical hardware IR; professional ERC/DRC rule packs |
| P1 | Simulation | SPICE orchestration, SI/PI checks, proof pack v2 |
| P1 | Manufacturing | IPC-2581 / DFM depth, BOM supply-chain intelligence |
| P2 | Domain | RF/wireless, analog, power electronics, high-speed, DFT |
| P2 | Interop | Cross-EDA round-trips, benchmark corpus |
| P3 | Enterprise | RBAC, audit trail, plugin ecosystem |
