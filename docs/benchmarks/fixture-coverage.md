# Benchmark Fixture Coverage

ZapTrace 0.3.0 introduced a 12-family benchmark manifest. The next benchmark-depth step is tracking which families have committed fixture artifacts, not merely target definitions.

`zaptrace.benchmark.fixtures` evaluates each family from `zaptrace/benchmark/manifests/board-families-v1.json` against the required artifact patterns declared in the manifest:

- `requirements.json`
- `proof-pack/manifest.json`
- `golden/*.kicad_*`
- `exports/*`

The coverage report is intentionally a repository completeness gate. It does not claim that a fixture is electrically correct, manufacturable, certified, or production-ready.

## Current fixture baseline

The first complete committed family fixtures are:

```text
benchmarks/esp32_usb_sensor/
benchmarks/stm32_rs485_industrial/
benchmarks/nrf52_ble_multisensor/
benchmarks/rp2040_can_node/
benchmarks/usb_c_power_sink/
benchmarks/lipo_charger_node/
benchmarks/poe_ethernet_controller/
benchmarks/motor_driver_hbridge/
benchmarks/switching_regulator_module/
benchmarks/high_current_led_driver/
benchmarks/mcu_sd_datalogger/
benchmarks/lora_gateway_node/
```

Each fixture contains:

```text
requirements.json
proof-pack/manifest.json
golden/<family_id>.kicad_pro
golden/<family_id>.kicad_sch
golden/<family_id>.kicad_pcb
golden/fixture.json
exports/manifest.json
```

The current coverage report now shows all 12 manifest families as complete at the starter-fixture level. Future work can raise the bar from starter fixtures to richer board-specific proof packs and generated manufacturing bundles.

## Generate the report

```bash
python scripts/ci_benchmark_fixture_coverage.py \
  --output benchmark-fixture-coverage.json \
  --markdown benchmark-fixture-coverage.md \
  --strict \
  --min-complete-families 12
```

Raising `--min-complete-families` is the intended ratchet as more families gain real fixtures. The Quality workflow publishes the current identity-bound result in the `benchmark-evidence` artifact; no committed JSON or Markdown file is presented as current evidence.

## Non-claims

A complete fixture means the required files exist and are machine-checkable. It does not mean:

- the board is fabrication-ready;
- the board is manufacturer-approved;
- the circuit is electrically correct;
- the proof pack is sufficient for no-human-review sign-off;
- the generated artifacts are certified or production-ready.
