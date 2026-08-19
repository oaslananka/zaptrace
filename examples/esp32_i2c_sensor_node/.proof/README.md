# Proof Pack: ESP32 Sensor Node Validation

Validates the ESP32 I2C sensor node design against manufacturing constraints.

```yaml
# proof.yaml
version: "1.0"
name: "esp32-sensor-node"
description: "Validates ESP32 sensor node is ready for JLCPCB manufacturing"

design_path: "../examples/esp32_i2c_sensor_node/design.yaml"

model:
  min_clearance_mm: 0.15
  min_trace_width_mm: 0.15
  min_annular_ring_mm: 0.05
  max_layer_count: 2
  allowed_layer_counts: [2]

checks:
  - name: "drc-clean"
    description: "Zero DRC violations"
    category: drc
    type: drc
    severity: critical
    expected_count: 0

  - name: "erc-clean"
    description: "Zero ERC violations"
    category: erc
    type: erc
    severity: critical
    expected_count: 0

  - name: "all-nets-routed"
    description: "All nets fully routed"
    category: routing
    type: routed
    severity: critical

  - name: "min-clearance"
    description: "Verify minimum 0.15mm clearance"
    category: routing
    type: clearance
    severity: error
    params:
      min_clearance_mm: 0.15

  - name: "footprints-complete"
    description: "All components have footprints assigned"
    category: footprint
    type: footprint_exists
    severity: error

  - name: "power-nets-connected"
    description: "Power nets have expected connections"
    category: custom
    type: net_connected
    severity: critical
    params:
      net_name: "VCC"
      expected_pins: ["U1-1", "C1-1", "J1-1"]

  - name: "gnd-connected"
    description: "GND net has expected connections"
    category: custom
    type: net_connected
    severity: critical
    params:
      net_name: "GND"
      expected_pins: ["U1-8", "C1-2", "J1-2", "R1-2", "LED1-2"]

  - name: "i2c-pullups"
    description: "I2C lines have pullup resistors"
    category: custom
    type: custom
    severity: warning
    params:
      script: "checks/i2c_pullups.py"

author: "ZapTrace Core Team"
tags: ["esp32", "sensor", "jlcpcb", "example"]
requires: ["zaptrace>=0.2.0"]
```

## Running

```bash
# From the proof directory
zaptrace proof run .

# With verbose output
zaptrace proof run . --verbose

# JSON report
zaptrace proof run . --format json

# List checks without running
zaptrace proof list .
```
