# Benchmark board-family manifest

ZapTrace defines a versioned benchmark board-family manifest for the professional autonomous electronics roadmap. The manifest records the target board families that future benchmark fixtures, golden KiCad projects, mutation tests, and Review Studio summaries should cover.

## Version

```text
schema_version: 1.0
manifest_version: 2026.06
```

The committed machine-readable manifest is:

```text
zaptrace/benchmark/manifests/board-families-v1.json
```

## API

```python
from zaptrace.benchmark.families import builtin_board_family_manifest, validate_board_family_manifest

manifest = builtin_board_family_manifest()
errors = validate_board_family_manifest(manifest)
```

Helper APIs:

```text
builtin_board_family_manifest()
list_board_families(domain=None, tags=None)
get_board_family(family_id)
validate_board_family_manifest(manifest)
manifest_json(manifest=None)
load_board_family_manifest(path)
```

## Required coverage

The v1 manifest contains 12 board families:

```text
esp32_usb_sensor
stm32_rs485_industrial
nrf52_ble_multisensor
rp2040_can_node
usb_c_power_sink
lipo_charger_node
poe_ethernet_controller
motor_driver_hbridge
switching_regulator_module
high_current_led_driver
mcu_sd_datalogger
lora_gateway_node
```

## Required artifacts per family

Each family defines required artifact categories:

```text
requirements-json
proof-pack
kicad-project
manufacturing-bundle
```

These are path-pattern targets for later benchmark fixture work. Missing release-blocking evidence should fail the relevant benchmark gate.

## Acceptance thresholds

Each family defines release-blocking thresholds for:

```text
scorecard.score
proof_pack.autonomous_status
release_blocking_evidence.missing
```

A benchmark pass is regression evidence only. It does not imply fabrication approval; the proof-pack and human-review policy still decide whether a generated design can advance.
