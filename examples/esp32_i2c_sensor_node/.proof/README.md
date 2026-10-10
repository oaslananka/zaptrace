# ESP32 sensor-node Proof Pack

The policy in [proof.yaml](proof.yaml) checks eight facts about
`../design.yaml`. Five currently pass; **DRC, copper clearance and physical pad mapping fail**
with incomplete physical geometry (12/31 mapped) and genuine routing violations. This is an **expected blocked-design
demonstration**, not JLCPCB sign-off or a clean PCB reference.

Run from the repository root:

```bash
uv run --no-sync zaptrace proof run examples/esp32_i2c_sensor_node/.proof --verbose
```

The **nonzero exit code is expected**. A source ERC pass or manufacturing export
must not be used to override the three physical verification blockers. Refer to the
[example walkthrough](../README.md) for generated KiCad files and HTML review.
