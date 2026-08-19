# Component derating policy evidence

ZapTrace includes a deterministic component derating policy engine for early design review. It is a pre-signoff check, not a replacement for datasheet review, SPICE, thermal simulation, or manufacturer approval.

## Policy

`DeratingPolicy` is configurable:

```text
voltage_utilization_max: default 0.8
current_utilization_max: default 0.8
power_utilization_max: default 0.5
require_operating_values: default false
```

## Inputs

The checker uses component ratings and explicit operating values:

- `component.voltage_rating`
- `component.current_rating`
- `component.voltage_supply`
- `component.properties.operating_voltage_v`
- `component.properties.operating_current_a`
- `component.properties.power_w`
- `component.properties.rated_power_w`

Legacy property aliases such as `voltage_rating_v`, `max_voltage_v`, `current_rating_a`, `max_current_a`, and `max_power_w` are also recognized.

## Output

`evaluate_component_derating(design, policy)` returns a machine-readable `DeratingReport` with:

```text
schema_version
policy
component_count
finding_count
blocked
findings[]
message
```

Each finding records component reference, metric, used value, rating, utilization, limit, status, and message.

## Proof-pack sign-off

Proof packs can attach `derating_evidence`. If `passed=false`, autonomous sign-off is blocked by:

```text
component-derating
```
