# Simulation Sign-off Evidence

ZapTrace combines existing DC, transient, AC, power-integrity, signal-integrity, thermal, and current-density producers into one state-bound simulation sign-off report. The report does not replace the underlying analyzers. It records which producer ran, which model it used, what the producer reported, and whether that evidence is strong enough for autonomous sign-off.

## Evidence status is not engine status

Every check retains both the producer's `engine_status` and ZapTrace's normalized `status`:

| Evidence method | Engine result | Normalized sign-off status |
|---|---|---|
| Non-degraded `ngspice` model | pass | `pass` |
| Degraded or low-confidence `ngspice` model | pass | `human-review-required` |
| `hybrid`, `analytical`, or `heuristic` | pass | `human-review-required` |
| Any method | skipped, missing, unsupported, or no reference | `skipped`, high risk, release blocking |
| Any method | fail or error | `fail`, release blocking, repair hint required |

A successful calculation is therefore not automatically an autonomous engineering approval. Analytical evidence can show a useful margin while still requiring a qualified reviewer. Missing models and unsupported analyses are preserved as explicit risk rather than converted into pass results.

## Model and report identity

`SimulationModelEvidence` records:

- model source, version, and SHA-256 identity;
- `ngspice`, `hybrid`, `analytical`, or `heuristic` method;
- family-fixture or other model binding;
- degraded status and confidence;
- assumptions and limitations;
- retained model/netlist artifact paths and netlist SHA-256;
- detected solver version for `ngspice` and hybrid producer results.

`SimulationFamilyReport` binds the resulting checks to the canonical design-state SHA-256. It retains model inputs, assumptions, metrics, raw producer results, repair hints, block/review decisions, live-simulation pass count, and its own report SHA-256. A changed report no longer matches its embedded digest and cannot be attached to a Proof Pack.

## Four-family evidence corpus

The committed corpus covers four representative board families:

| Family | Evidence domains | Primary gate |
|---|---|---|
| `switching_regulator_module` | transient, power integrity, thermal, current density | strict buck transient gate through `ngspice` |
| `usb_c_power_sink` | transient/inrush, power integrity, current density | USB-C inrush hybrid or analytical gate |
| `lipo_charger_node` | AC stability, thermal margin | governed analytical AC stability fixture |
| `esp32_usb_sensor` | SI/PI risk | analytical impedance, return-path, and decoupling evidence |

The aggregate report carries the committed corpus version and policy SHA-256. The Quality workflow installs `ngspice` and requires at least one live solver-backed pass. The remaining analytical or degraded-family evidence stays visible as human-review-required. The corpus checks evidence production and policy behavior; it does not claim that every family is autonomously release-ready.

## Proof Pack integration

`attach_simulation_signoff_evidence()` adds a hash-valid family report reference to `ProofManifest.simulation_signoff`. The Proof Pack records the report and design identity, model/check counts, live pass count, failures, skips, and review state.

- A blocked family creates blocking `simulation-signoff` evidence.
- A non-blocking analytical or low-confidence result creates warning evidence and a human-review requirement.
- Only non-degraded, solver-backed passing evidence can map to an autonomous pass.

The complete input models, assumptions, detailed results, pass/fail states, and repair hints remain in the referenced `simulation-signoff.json` artifact rather than being flattened into the manifest. For SPICE-backed families, the retained `input-model.spice` is the exact deterministic netlist passed to the gate and is bundled alongside its governed model JSON.

## Reproduce the corpus

Run the evidence corpus without requiring a local solver:

```bash
.venv/bin/python scripts/ci_simulation_signoff.py \
  --artifact-dir simulation-signoff-artifacts \
  --output simulation-signoff-report.json \
  --markdown simulation-signoff-report.md \
  --strict
```

Run the same gate used in CI when `ngspice` is installed:

```bash
.venv/bin/python scripts/ci_simulation_signoff.py \
  --artifact-dir simulation-signoff-artifacts \
  --output simulation-signoff-report.json \
  --markdown simulation-signoff-report.md \
  --require-live-simulation \
  --strict
```

All output paths must remain inside `--trusted-output-root` (the current directory by default). Existing artifact directories are cleaned only when they contain the ZapTrace ownership marker.

## Non-claims

A passing corpus run is not electrical correctness, device-model accuracy, field-solver SI/PI validation, fabrication readiness, EMC or safety compliance, manufacturer approval, physical bring-up, or qualified human engineering approval. Family fixtures are governed regression models; they are not automatically selected-device, board-extracted, or lab-correlated models.
