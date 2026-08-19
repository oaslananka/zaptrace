# Design Note — Autonomous Synthesis & the Verification Loop

Status: design / forward-looking. This note describes how ZapTrace moves from a
broad-but-shallow pipeline to an engine that completes a professional board end
to end. It is the technical backing for milestones M1–M2 in
[ROADMAP.md](../ROADMAP.md). Nothing here is a fabrication-readiness claim.

## Problem statement

Today an agent can call dozens of tools, but the core creative step — *deciding
the circuit* — is template selection. `synthesize_with_provenance()` keyword-scores
the YAML templates in `zaptrace/synthesis/templates/` and loads the closest
match (`zaptrace/synthesis/engine.py`, `method="template_selection"`). The only
genuinely synthesized path is the power tree
(`zaptrace/synthesis/power_tree.py` → `build_power_tree_design()`), which
composes parametric blocks for sources, regulators, and pull-ups.

The vision needs the opposite default: an intent that does not match a template
must still yield a *complete, justified* design. That requires three things to
work together — composition, simulation, and a correction loop.

## 1. From-scratch synthesis by block composition

The realistic path to "from scratch" is **not** free-form LLM netlist
generation (unverifiable, non-deterministic). It is requirement-driven
composition of small, parametric, individually-correct blocks — the approach
already proven for the power tree, generalized to the rest of the board.

### Existing primitives to build on

- `zaptrace/synthesis/requirements.py` — parses intent into structured
  `Requirements` (rails, current, interfaces, MCU, USB-C, battery), with an
  assumption register, conflict detector, and a content-addressed freeze gate.
- `zaptrace/synthesis/blocks/builtin.py` — parametric block instantiation
  (e.g. `instantiate_ldo`, USB-C CC termination, I2C pull-ups).
- `zaptrace/synthesis/calculators.py`, `analog.py`, `rf.py` — value sizing
  (buck L/C, LDO selection, SOA, Sallen-Key, L-network match, microstrip width).
- `zaptrace/synthesis/power_tree.py` — the reference example of plan → justify →
  emit, with every stage citing the calculator that sizes it.

### The generalization

```
Requirements ──▶ Architecture Planner ──▶ Block Graph ──▶ Netlist Emit
   (freeze        (which functional        (typed blocks   (Design: components
    hash)          blocks + how they        + required      + nets, every value
                   connect, justified)      interfaces)      traced to a calc)
```

- **Architecture Planner** extends the power-tree planner from "what power
  stages" to "what functional blocks": MCU support (decoupling, crystal/load
  caps, boot/reset straps, programming header), each declared interface (I2C
  pull-ups, USB-C CC/ESD, RS-485 transceiver + termination, SPI), sensors, and
  protection. It decides blocks and their connections *and records why* — the
  same provenance discipline already in `power_tree.py`.
- **Block contracts.** Each block is a typed unit declaring the nets/pins it
  provides and requires (`provides: I2C{SDA,SCL}`, `requires: rail 3V3`). The
  planner composes by satisfying requires-with-provides, so a bare intent
  invents nothing it was not asked for — the freeze-gate invariant.
- **Value sizing stays deterministic** and calculator-backed; every emitted
  component carries the calculator + inputs that produced it, surfaced through
  the existing `SynthesisDecisionLog` (`zaptrace/synthesis/explain.py`).

Determinism is the point: same frozen requirements ⇒ same block graph ⇒ same
netlist, so a result is reproducible and a diff is meaningful.

## 2. Simulation as a blocking gate

Today `zaptrace/analysis/spice_orchestrator.py` runs **DC operating-point only**,
is **skip-aware** (returns `skipped` when ngspice is absent), and is not part of
any gate. "Flawless" cannot rest on a check that silently disappears.

Plan:

- **Bundle the simulator.** Ship ngspice in the container image so the runner is
  always available in CI; a missing binary is an environment error, not a free
  pass. Mirror the KiCad-oracle "explicit skip is recorded evidence" rule.
- **Add the missing models.** The orchestrator notes transient/AC need device
  models that are absent. Curate a model set (regulators, common ICs, passives
  with parasitics) keyed to the library so synthesized blocks are simulatable.
- **Promote to a gate.** DC operating-point (rail voltages within tolerance) and
  a transient bring-up check (no rail collapse at load step) become **blocking**
  evidence in the proof pack, alongside ERC/DRC — not advisory.

## 3. The convergent self-correction loop

The architecture diagram already shows ERC-fail → patch → re-verify. The
`synthesize_and_check` MCP tool closes intent → netlist → ERC in one call. What
is missing is *convergence*: a measured, bounded loop rather than a hopeful one.

```
synthesize ─▶ ERC ─▶ sim ─▶ DRC ──┬─ all pass ─▶ candidate + proof pack
     ▲                            │
     └──────── patch ◀── diagnose ┘   (bounded iterations, then escalate)
```

- **Diagnose → patch** maps each failure class to a concrete edit: ERC008
  missing current-limit → insert a sized series resistor; rail out of tolerance
  → re-size the regulator block; DRC clearance → re-route or widen spacing. Each
  patch is a typed transform on the `Design`, snapshotted via the existing
  transaction-safe state (`design_snapshot`/`rollback`/`commit`).
- **Convergence is measured.** The loop has a hard iteration cap and tracks
  whether the violation count is monotonically decreasing. Non-convergence
  escalates to a human with the decision log — it never loops forever or claims
  success on a partial fix.
- **No silent success.** A passing run reports its scope (`coverage_summary()`
  already does this for ERC): N checks run, K known gaps — never an unqualified
  "passed."

## 4. Removing the KiCad dependency

KiCad is currently the external oracle. To make ZapTrace GUI- and EDA-independent
*as a runtime*, the internal engines must be the authority:

- Internal ERC (29 rules), DRC (16 rules), and the bundled SPICE gate are the
  primary verdict.
- KiCad Oracle is reframed as an **optional cross-check** that produces a
  fidelity scorecard ("internal and KiCad agree within tolerance X"), not a
  required step. Its absence degrades evidence richness, not the ability to run.

## 5. Proving it: the benchmark harness

None of the above is creditable without measurement. A release-blocking
benchmark (building on `zaptrace/benchmark/corpus.py` and the
`benchmarks/` specs) scores *complete* synthesized designs against fabricable
reference projects:

- Inputs: an intent and a contract (expected rails, interfaces, constraints).
- Score: did synthesis produce a complete netlist? Did it pass internal ERC,
  DC + transient sim, and DRC without human edits? Does the BOM resolve to real,
  in-stock parts?
- The harness runs in CI as a gate; a regression in synthesis, routing, or
  verification quality blocks the release.

This is what turns "flawless" from a claim into a number.

## Sequencing

1. Block contracts + architecture planner generalization (composition).
2. Bundled simulator + device models + DC/transient gate.
3. Convergent correction loop wiring the two together.
4. Benchmark harness to lock in quality, then routing fidelity (M2).

Each step is independently shippable and independently verifiable, consistent
with the verification-first principle: never add autonomy faster than the
evidence that can check it.
