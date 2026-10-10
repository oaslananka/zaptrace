# ESP32 I²C Sensor Node — generated design and real validation failures

This example is the existing ESP32-WROOM-32 + BME280 sensor-node source design.
It is a **working generation-and-inspection demo**, **not a passed release
candidate**. ZapTrace can generate placement, routing, KiCad project files,
reviewable SVG/HTML, Gerber layers, and a manufacturing bundle. With
verified physical copper pads, the obstacle-aware router currently cannot
legally route this placement, so the PCB **intentionally contains no generated
trace segments** instead of quietly falling back to unsafe straight-line
copper. The bundled Gerbers are incomplete and must not be fabricated. **Generating
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
Keep its `ZapTrace.kicad_sym`, `sym-lib-table`, `fp-lib-table` and
`ZapTrace.pretty/` files **together** with the schematic and PCB when moving
the project. The symbol library contains generated *connectivity-only*
symbols, not supplier-qualified electrical symbol definitions. Only exact
SHA-256-verified KiCad footprint files are bundled. The byte-pinned GCT USB4105
J1 land pattern retains four plated oval shell-stake slots and two nonplated
alignment holes, in addition to 16 USB contacts. D1 is a provisional,
byte-verified Nexperia SOD-323 candidate, not an approved VBUS protection design.

The reference input now uses a **provisional 100 × 75 mm layout** with
14 explicit, complete footprint positions and zero overlapping conservative
courtyards; the previous 50 × 40 mm source could not contain the official
ESP32 RF/antenna courtyard (48 × 41.25 mm). This is a review-only
placement, not an approved board outline, antenna layout, USB enclosure fit,
or qualified RF layout. The pipeline **refuses** to silently override partial,
off-board, or conflicting explicit positions.

The grid router can misleadingly report 6/6 graph-connected nets while
native KiCad sees dangling traces, shorts, and more missing connections.
For verified physical footprints the pipeline now rejects candidate copper
when actual pad-endpoint coverage or source DRC fails. Consequently this
demo intentionally exports **zero traces, zero vias and zero GND zones**
rather than apparently complete but invalid copper. The earlier hand-drawn
GND polygon was also removed because its antenna/keepout clearance was not
qualified. This fail-closed result is **not** a successful physical route.

The CLI pipeline returning success means the generation stages ran; it is
**not** a manufacturing sign-off. The program does not submit boards to a
fabricator or certify their safety.

## Run the strict Proof Pack — expected to block

```bash
uv run --no-sync zaptrace proof run \
  examples/esp32_i2c_sensor_node/.proof --verbose
```

**The nonzero exit code is intentional for the present design.** The eight
checks report six passes (including full physical pad identity mapping) and
two blockers: source DRC and copper clearance. The result is **still a fail**.
The source-only routing-completeness check is **not proof that KiCad PCB traces
were generated or all physical pads are electrically joined**. The pipeline
refuses to export the current grid-router trace candidate:

- `drc-clean`: copper clearance error between `VCC_3V3` and `I2C_SCL`
  plus right-angle routing warnings on `I2C_SDA`.
- `min-clearance`: additional intersections violating the configured
  0.15 mm copper clearance.
- Physical pad identity coverage: all **37/37** source net nodes now resolve
  to actual footprint contacts, including J1 USB4105 A5=CC1, B5=CC2,
  four VBUS and four GND USB contacts; the four plated S1 shell stakes
  are deliberately not assigned to GND pending shield/EMI policy review.
  This is **not** evidence of physical routing or ESD qualification.

Those are **design/routing defects**, even with complete pad identity mapping, not configuration issues to silence
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

Independent KiCad **10.0.6** on the preceding PR head (2026-10-10) found
**82 PCB DRC violations, 37 unconnected items, and ZERO schematic ERC
violations**. In an isolated native layout experiment, enlarging the board
to 100 × 75 mm and separating every courtyard reduced the *unrouted*
board to **36 PCB DRC violations, still 37 unconnected items** (without
fixing footprint or manufacturing limits). The final exact-branch oracle
must be run again after these new layout and fail-closed checks land. The prior main baseline before J1 physical binding
had 78 DRC findings, 31 unconnected items, and one J1 footprint-link ERC
warning. J1 now references the byte-pinned USB4105 footprint; ERC is clean
because this *metadata link* is resolved, **not** because physical copper is
routed or fabrication accepted. DRC details include 20 clearance, 15 solder-mask
bridge, 14 verified-library footprint graphic mismatch, 12 real 0.20 mm ESP32
drills below the configured 0.30 mm board minimum, 13 silk-over-copper,
6 hole-clearance, and 2 physical shorting findings. The ESP32 pad/drill source
is not falsified, and the board manufacturing rule is not reduced to hide
these authentic failures. Additional historical ERC warnings arose from
missing project-local KiCad symbol/footprint library links; they are now
resolved by generated local libraries, **not** by suppressing KiCad checks.
Independent PCB `lib_footprint_mismatch` findings remain visible
because generated PCB footprint graphics differ from the verified KiCad
library definitions; exact pad geometry alone does not establish footprint
equivalence. The reduced trace-related violation count came from discarding
78 unsafe fallback segments, **not** successful routing. In particular, no
physical continuity has been verified. These results may change with KiCad version, configuration,
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
rather than silently absent from the source schematic. Additional exact
KiCad 10.0.6 geometries are bound to R1/R2/R3/R4, C1/C2/C3, TP1/TP2 and
U3 (AMS1117 SOT-223) using digest-pinned package data and explicit
logical-to-physical pin maps. The AMS1117's middle leg and thermal tab
are both physical pad **2**, connected to VCC_3V3 (never GND). See the
[manufacturer pinout](https://www.datasheets.com/advanced-monolithic-systems/ams1117-3.3/datasheet.pdf).
A provisional Nexperia PESD5V0S1BA SOD323 **bidirectional** ESD candidate
now supplies D1's two source pad identities. Per the
[manufacturer's 2024-04-26 datasheet](https://assets.nexperia.com/documents/data-sheet/PESD5V0S1BA.pdf),
pin 1 is K1 and pin 2 is K2, both cathode identifiers of the bidirectional
device; we map pad 1 to VCC_5V and pad 2 to GND for this *reference example*.
Its **5 V maximum reverse standoff rating** is not proof of adequate
protection across the full USB-C VBUS voltage envelope; sustained voltage,
surge/current/thermal derating and short return-loop placement must be
reviewed by a qualified hardware engineer before selecting production parts.
This is **not** a complete board: the four J1 logical nets now map to
actual verified USB4105 pads (A5/B5 for CC1/CC2, four USB VBUS and four USB
GND). R3 and R4 provide separate 5.1 kΩ Rd terminations to GND. The importer
retains four plated 0.6 × 1.7/1.4 mm oval shell stakes (S1) and two NPTH
0.65 mm alignment holes, and the Excellon exporter emits G85 routed slots,
not zero/round replacement holes. The S1 shell metal is deliberately unassigned
pending shield/EMI review; actual routed copper continuity, drill/manufacturer
acceptance, connector orientation, native KiCad DRC, LDO capacitor stability
and thermal performance, and protection qualification still require evidence.
This is a 5 V fixed-sink reference, not a USB Power Delivery implementation.

- [GCT USB4105 manufacturer drawing (pin assignment)](https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/5492/USB4105.pdf)
- [ST AN5225 USB Type-C application note](https://www.st.com/content/ccc/resource/technical/document/application_note/group1/38/94/1d/41/0e/ba/49/21/DM00536349/files/DM00536349.pdf/jcr%3Acontent/translations/en.DM00536349.pdf)

The `power-nets-connected` and `gnd-connected` checks use the actual
`VCC_3V3`/`GND` net names and component-qualified pin identities such as
`U1.VCC` and `U2.GND`; unlike obsolete unqualified pin expectations,
they cannot pass merely because a different component has a same-named pin.

**Physical pad identity evidence is complete, not fabrication-ready:** the
source schematic covers 37/37 net nodes and all 37 have actual footprint pad
identities, including J1. This is only logical-to-physical pad-identity
evidence, not routed continuity, a manufacturing drill acceptance, or a
full native KiCad ERC/DRC pass. Binding
actual pad geometries exposes copper-level clearance, pad-mask and routing
problems which were invisible while the exported footprints had no pads. `pipeline`
producing a `.kicad_pcb` file does **not** make its footprints real or
its missing routed copper electrically connected. See
[issue #91](https://github.com/oaslananka/zaptrace/issues/91).

Passing source ERC or an automatically generated manufacturing ZIP is **not**
equivalent to KiCad ERC/DRC acceptance, datasheet-verified footprints,
electrical simulation, physical testing, or manufacturer approval.

## Source files

- `design.yaml` — canonical input design
- `.proof/proof.yaml` — strict validation policy and evidence contract

The repository's separate `scripts/ci_examples.py` checks generation/export
ability; it does not certify this example's strict Proof Pack.
