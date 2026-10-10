# ESP32 I²C Sensor Node — generated design and real validation failures

This example is the existing ESP32-WROOM-32 + BME280 sensor-node source design.
It is a **working generation-and-inspection demo**, **not a passed release
candidate**. ZapTrace can generate placement, routing, KiCad project files,
reviewable SVG/HTML, Gerber layers, and a manufacturing bundle. **Generating
files is not evidence that the board is safe to build.**

## Run from the repository root

After installing the project's locked Python environment (see the repository
Quickstart), run:

```bash
uv run --no-sync zaptrace parse examples/esp32_i2c_sensor_node/design.yaml
uv run --no-sync zaptrace pipeline \
  --source examples/esp32_i2c_sensor_node/design.yaml \
  --output build/esp32-demo
uv run --no-sync zaptrace view \
  examples/esp32_i2c_sensor_node/design.yaml \
  --proof examples/esp32_i2c_sensor_node/.proof/proof.yaml \
  --output build/esp32-review
```

Open `build/esp32-review/index.html` to inspect the generated design.
The interactive viewer displays the **declared Proof Pack policy**;
providing `--proof` does **not run** that policy. Execute the separate
`proof run` command below for authoritative pass/fail results.
The pipeline generates a KiCad schematic and PCB under `build/esp32-demo/kicad/`.
The CLI pipeline returning success means the generation stages ran; it is
**not** a manufacturing sign-off. The program does not submit boards to a
fabricator or certify their safety.

## Run the strict Proof Pack — expected to block

```bash
uv run --no-sync zaptrace proof run \
  examples/esp32_i2c_sensor_node/.proof --verbose
```

**The nonzero exit code is intentional for the present design.** The seven
checks report five passes (ERC, routing-completeness, footprint presence,
3.3 V connections, and ground connections) and two blockers:

- `drc-clean`: copper clearance error between `VCC_3V3` and `I2C_SCL`
  plus right-angle routing warnings on `I2C_SDA`.
- `min-clearance`: additional intersections violating the configured
  0.15 mm copper clearance.

Those are **design/routing defects**, not configuration issues to silence
or an invitation to reduce clearance thresholds. The template is a useful
demonstration of ZapTrace **catching** unsuitable generated geometry.
Its Proof Pack must remain **blocked** until the generated copper geometry
is genuinely corrected and rechecked by the KiCad oracle and a qualified
hardware engineer. Do not fabricate from this example.
The tracked engineering follow-up is
[issue #91](https://github.com/oaslananka/zaptrace/issues/91).

### Independent KiCad checks (when KiCad 10 is installed)

```bash
kicad-cli pcb drc --exit-code-violations \
  --output build/esp32-demo/kicad/board-drc.rpt \
  build/esp32-demo/kicad/ESP32_I2C_Sensor_Board.kicad_pcb

kicad-cli sch erc --exit-code-violations \
  --output build/esp32-demo/kicad/schematic-erc.rpt \
  build/esp32-demo/kicad/ESP32_I2C_Sensor_Board.kicad_sch
```

Both commands currently **exit nonzero** because the generated KiCad
project has additional errors. Independently tested with KiCad 10.0.6:
**22 PCB DRC violations, 3 unconnected items, and 24 schematic ERC
violations**. These results may change with KiCad version, configuration,
or routing changes. They are *not* the same rule set as the in-process
ZapTrace ERC/DRC checks. A clean ZapTrace source ERC result must never
be substituted for KiCad CLI acceptance.

## What's verified and what isn't

The demo now explicitly maps ESP32-WROOM-32 module pads (including GPIO21
physical pad 33 and GPIO22 physical pad 36) and the Bosch BME280 LGA-8 pads
to their **logical** pin names, based on their respective official datasheets:
[Espressif ESP32-WROOM-32](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html)
and [Bosch BME280](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf).
BME280 VDDIO (physical pad 6) is now explicitly on the 3.3 V supply,
rather than silently absent from the source schematic. This represents
*logical mapping intent only*: manufacturer pad geometry, net continuity,
complete USB-C CC handling, routing and vendor qualification still need
professional review and KiCad evidence.

The `power-nets-connected` and `gnd-connected` checks use the actual
`VCC_3V3`/`GND` net names and component-qualified pin identities such as
`U1.VCC` and `U2.GND`; unlike obsolete unqualified pin expectations,
they cannot pass merely because a different component has a same-named pin.

**Critical missing physical footprint evidence:** the source demo's 31
logical net nodes have **0 resolved physical pad geometries** in its
current KiCad netlist evidence. The source schematic connectivity covers 31/31
logical nodes, but PCB pad mapping covers **0/31**. That is a genuine unresolved
footprint/package mapping deficiency, not a KiCad DRC pass. `pipeline`
producing a `.kicad_pcb` file does **not** make its footprints real or
its routed copper electrically connected. See
[issue #91](https://github.com/oaslananka/zaptrace/issues/91).

Passing source ERC or an automatically generated manufacturing ZIP is **not**
equivalent to KiCad ERC/DRC acceptance, datasheet-verified footprints,
electrical simulation, physical testing, or manufacturer approval.

## Source files

- `design.yaml` — canonical input design
- `.proof/proof.yaml` — strict validation policy and evidence contract

The repository's separate `scripts/ci_examples.py` checks generation/export
ability; it does not certify this example's strict Proof Pack.
