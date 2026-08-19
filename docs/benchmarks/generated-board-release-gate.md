# Generated Board Release Gate

The generated-board release gate promotes the M7 generated-board pipeline from acceptance coverage into a strict release-quality report.

The gate runs the ESP32 USB sensor pipeline end to end:

```text
BoardGenerationIntent
-> Design IR compilation
-> KiCad schematic generation
-> KiCad PCB generation
-> generated-project evidence bundle
-> manufacturing export manifest
-> review handoff
```

## Command

```bash
python scripts/ci_generated_board_release_gate.py \
  --output generated-board-release-gate.json \
  --markdown generated-board-release-gate.md \
  --strict
```

## Current committed result

- Gate: `generated-board-release-gate-v1`
- Family: `esp32_usb_sensor`
- Design: `esp32_usb_sensor_generated_v1`
- Required artifacts: 9
- Missing required artifacts: 0
- Passed: `true`

## What it proves

- The supported generated-board pipeline can produce a reviewable KiCad project.
- The generated project includes schematic and PCB artifacts.
- The aggregate evidence bundle records stable SHA-256 hashes.
- Manufacturing export and review handoff placeholders are present.
- Non-claims remain visible.

## CI integration

The `Quality` workflow runs this gate as `Generated board release gate`. The final release-gate summary depends on that job and treats it as a blocking gate.

## Artifact regression checks

The current JSON report is a CI artifact, not a committed file. Each run records the exact source commit/ref, package version, dirty state, lock hash, source-input hash, generation time, toolchain, and deterministic identity hash. This avoids publishing a stale file that appears current and avoids the self-referential impossibility of embedding a commit hash in the same commit that contains the report.

Regression tests keep deterministic artifact kinds, relative paths, SHA-256 values, coverage counts, blocking behavior, and non-claims as code-level snapshots. The `generated-board-release-gate` artifact from the Quality workflow is the authoritative report for that exact revision.

## Physical reference-board pre-fabrication plan

The same `esp32_usb_sensor` family now has a committed machine-readable pre-fabrication plan at `benchmarks/esp32_usb_sensor/physical-validation-plan.json`. Quality validates that record with `scripts/ci_physical_validation_plan.py` and retains the JSON/Markdown gate output as `physical-validation-plan-gate` evidence.

The plan is deliberately **not** fabrication approval. Its committed state is `pre-fabrication-candidate`, human engineering review remains `pending`, and `fabrication.eligible` remains `false`. It defines the bounded extra-low-voltage/current-limited scope, stop conditions, required functional/rail/current/temperature measurements, instrument identity and uncertainty fields, and the prediction-versus-measurement correlation shape that must be used if a real board is later approved and built.

The benchmark `golden/` KiCad files remain starter fixtures for coverage/hash regression and are explicitly forbidden as fabrication sources. Before fabrication, a separate exact manufacturing bundle must be hash-bound to a released source revision and a real human schematic/layout/component/manufacturing approval record.

## Non-claims

The gate is release evidence for a reviewable generated board project. It is not fabrication approval, not electrical correctness, not DRC/ERC approval, not manufacturer approval, not certification, and not production readiness.
