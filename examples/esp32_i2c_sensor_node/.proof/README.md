# ESP32 sensor-node Proof Pack

The policy in [proof.yaml](proof.yaml) checks eight facts about
`../design.yaml`. Five currently pass; **DRC, copper clearance and physical pad mapping fail**
with incomplete physical geometry (27/31 mapped) and genuine routing violations. This is an **expected blocked-design
demonstration**, not JLCPCB sign-off or a clean PCB reference.

Run from the repository root:

```bash
uv run --no-sync zaptrace proof run examples/esp32_i2c_sensor_node/.proof --verbose
```

Important distinction: the proof policy is evaluated on the source design,
not the exported KiCad copper. A source net-list completeness pass does **not**
mean the obstacle-aware router produced electrically connected traces. The
current KiCad PCB intentionally omits unsafe fallback copper and has zero
generated trace segments, 27 unconnected findings, and independently
failing DRC/ERC acceptance.

The **nonzero exit code is expected**. A source ERC pass or manufacturing export
must not be used to override the three physical verification blockers. Refer to the
[example walkthrough](../README.md) for generated KiCad files and HTML review.
