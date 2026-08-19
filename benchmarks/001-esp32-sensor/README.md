# Benchmark 001 — ESP32 Sensor Board

This benchmark defines the first deterministic release-blocking acceptance harness for a realistic ZapTrace board flow.

Target board:

- ESP32-S3 module
- USB-C 5 V input with CC pull-down resistors
- 1S Li-ion/LiPo battery connector
- Battery charger IC
- 3.3 V regulator
- I2C environmental sensor
- Programming/debug header
- Status LED and boot/user button
- Two-layer JLCPCB-style fabrication profile

Run the deterministic harness:

```bash
uv run python scripts/ci_benchmark_001.py --strict --output benchmark-001-report.json
```

The harness validates that requirements, expected artifacts, thresholds, proof-pack policy, and release-gate metadata are present and machine-readable. It does not claim the board is fabrication-ready; generated schematic/PCB/manufacturing artifacts must still pass ERC/DRC/DFM/BOM/KiCad oracle checks before release acceptance.


## Scoring evidence

The committed deterministic contract includes proof-pack, BOM-risk, and fab-profile evidence inputs:

- proof manifest: `benchmarks/001-esp32-sensor/.proof/proof.yaml`;
- BOM risk sample: `docs/reports/benchmark-001-bom-risk-sample.json`;
- fab profile: `jlcpcb-standard-2layer` with 2 layers and explicit clearance/trace/drill limits.

The CI harness verifies these inputs before reporting benchmark 001 as passing. Future generated artifacts can replace the sample evidence with measured ERC/DRC/DFM/BOM/KiCad oracle results without changing the report contract.
