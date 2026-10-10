# ESP32 sensor-node Proof Pack

The policy in [proof.yaml](proof.yaml) checks seven facts about
`../design.yaml`. Five currently pass; **DRC and copper clearance fail**
with genuine routing violations. This is an **expected blocked-design
demonstration**, not JLCPCB sign-off or a clean PCB reference.

Run from the repository root:

```bash
uv run --no-sync zaptrace proof run examples/esp32_i2c_sensor_node/.proof --verbose
```

The **nonzero exit code is expected**. A source ERC pass or manufacturing export
must not be used to override the two route-safety blockers. Refer to the
[example walkthrough](../README.md) for generated KiCad files and HTML review.
