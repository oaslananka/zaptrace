# Requirements Schema v1

ZapTrace requirements schema v1 is the explicit pre-synthesis contract used before an autonomous or assisted electronics design run. It records the product class, environmental assumptions, power requirements, interfaces, safety domain, manufacturing limits, and compliance targets.

This file is evidence, not a fabrication-readiness claim. Missing or invalid required fields must be resolved before synthesis can claim complete requirements coverage.

## Minimal valid example

```yaml
schema_version: "1.0"
product_class: iot_sensor_node
environment:
  temperature_c: [0.0, 50.0]
  ingress_rating: null
  enclosure: plastic
power:
  inputs: [usb_c_5v]
  rails_v: [3.3]
  max_current_a: 0.5
interfaces: [usb, i2c]
safety:
  mains: false
  battery: false
  isolation_required: false
  safety_critical: false
manufacturing:
  fab_profile: jlcpcb-2layer
  layers: 2
  min_trace_width_mm: 0.15
  min_clearance_mm: 0.15
  assembly: smt
compliance_targets: [RoHS]
```

## Required top-level fields

- `product_class`
- `environment`
- `power`
- `interfaces`
- `safety`
- `manufacturing`
- `compliance_targets`

Unknown fields are rejected so silent assumptions cannot enter the design contract.
