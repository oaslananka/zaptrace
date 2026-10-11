# ESP32 + GCT USB4105 manufacturability and partial routed PCB review

Status: **BLOCKED / NOT FABRICATION APPROVED**. This is a measured engineering
assessment, not a supplier order approval. The sample board outline and
component placement are provisional; no PCB stackup, copper weight, thermal
performance or order options have been signed off.

## Manufacturer evidence (reviewed 2026-10-11)

Primary sources:

- [JLCPCB PCB manufacturing capabilities](https://jlcpcb.com/capabilities/pcb-capabilities/)
- [PCBWay manufacturing capabilities](https://www.pcbway.com/capabilities.html)
- [GCT USB4105 official product and drawings](https://gct.co/connector/usb4105)
- [GCT USB4105 official product specification](https://gct.co/files/specs/usb4105-spec.pdf)

| Physical feature | Board / independent native KiCad 10.0.7 evidence | Published capability | Decision |
|---|---|---|---|
| ESP32 U1 thermal pad-39 drilled vias | Twelve 0.20 mm PTH; KiCad minimum 0.30 mm; 0.60 mm annular pads | JLCPCB supports 0.15 mm drilling on 2-layer boards, **prefers 0.20 mm** minimum vias; 0.20 mm small-via options may have additional cost. PCBWay publishes 0.15 mm mechanical capability with extra charges below 0.20 mm. | **Conditional only.** 0.20 mm is in published capacity, but our conservative 0.30 mm rule is unchanged until stackup, via plugging/tenting and supplier DFM are explicitly agreed. A 0.60 mm / 0.20 mm PTH has a 0.20 mm nominal annular ring, meeting JLCPCB's quoted absolute 0.18 mm minimum for 2-layer 1 oz but below the 0.25 mm recommendation. |
| GCT J1 four plated S1 oval slots | Width 0.60 mm; two length 1.40 mm, two length 1.70 mm; Excellon G85 and native KiCad plated-slot geometry verified | JLCPCB's published 2-layer minimum plated slot width is 0.50 mm and slot length must be at least 2× width; advertised slot tolerance +0.13/-0.08 mm | **Plausible**, not ordered/approved. All four slots pass the published width and 2× width length limits; specific tolerance/connector stake fit still require a supplier check. |
| J1 two nonplated locating pegs | Two 0.65 mm NPTH; adjacent GND pad gap is **0.1944 mm**, native KiCad rule **0.25 mm** | JLCPCB advertises 0.50 mm minimum NPTH diameter and 0.20 mm NPTH-to-track clearance; pad-to-NPTH acceptance is **not** guaranteed by the track limit | **BLOCKED.** 0.1944 mm is even 0.0056 mm below the published NPTH-to-track minimum and 0.0556 mm below our 0.25 mm rule. The footprint is constrained by the actual connector locating peg and contact layout. Do not shift pegs, shrink solder contacts, delete holes or change clearance rules merely to get a green DRC. |
| Copper width / spacing | Review-only twenty connection paths use 0.20 mm F.Cu tracks | JLCPCB advertises 0.10/0.10 mm min width/spacing for 2-layer 1 oz | Potentially viable in a **1 oz** process, but DRC and physical electrical performance still need a complete routed PCB and DFM. |
| Complete interconnect and RF | Native KiCad current source: 37 unconnected / 16 manufacturing DRC; optional twenty-link review board: **17 unconnected / 16 manufacturing DRC** | No manufacturer publishes acceptance of incomplete nets or an unqualified ESP32 antenna layout | **BLOCKED.** No copper plane/antenna ground fill was invented; U1 RF keepout is retained. TVS on USB 5 V, AMS1117 stability/thermal and connector-shell EMI require separate evidence. |

**Important:** A supplier's generalized capability table does not constitute an
approval for this particular board, copper stack, assembly profile or connector.
A genuine zero-DRC, zero-unconnected board is **not attainable responsibly with
the current unchanged footprint/DRC constraints**. The four J1 peg-to-copper
violations require a supplier-specific written DFM exception supported by
engineering evidence or a qualified different connector/land-pattern decision;
they must not be suppressed locally. The 12 ESP32 0.20 mm drill findings likewise
need a documented selected-process profile before the 0.30 mm design restriction
can be changed.

## Twenty real physical copper links (review-only, not production pipeline)

Run the usual demo pipeline, then apply a separately audited, **opt-in**
native KiCad route overlay. The default pipeline intentionally continues
to export no tracks rather than pretending to complete all nets.

```bash
zaptrace pipeline --source examples/esp32_i2c_sensor_node/design.yaml --output build/esp32-review
bash scripts/issue91_native_copper_review.sh \
  build/esp32-review/kicad/ESP32_I2C_Sensor_Board.kicad_pcb \
  build/esp32-review/kicad/ESP32_I2C_Sensor_Board_partial_review.kicad_pcb
```

The shell driver invokes *only* the system KiCad 10 CLI for independent
DRC before and after Python generates a staged candidate. Python itself
does not spawn processes; a source/candidate SHA-256 manifest, unchanged
physical pad contracts and the two full native DRC reports must validate
before the review PCB is published. In addition to exact DRC finding counts,
the driver compares the unchanged physical blocker **rule, severity, object and
location signatures** before/after; replacing one violation with a new violation
of the same class is rejected even if the category totals stay constant. This
avoids tainted arbitrary subprocess arguments and preserves fail-closed hardware
evidence.

The opt-in review emits **45 real 0.20 mm F.Cu segments joining 20 pairs**
of actual, pinned physical pad centers across USB-CC1/CC2, I²C, VCC_3V3,
VCC_5V and GND. These include the two USB-C CC sink lines, internal ESP32
VCC and GND terminals, BME280 supply/GND, R1/R2 I²C pullup-to-testpad,
U2 SDA-to-R1, C3-to-D1 power and GND, R3-to-R4 ground and U3's duplicate
VOUT lead/tab pads. Additional KiCad-verified paths connect C1–C2 GND,
C1–C2 3.3 V, C2 GND–U2 GND, U1.15 GND–U1.39 thermal pad and
U3 VIN–C3 VBUS. The twentieth, native-verified GND path links R3.2
to C3.2 on F.Cu via (72.51, 57.2) and (69.6, 57.2)/(69.6, 66.5),
respecting nearby USB-CC1 and VBUS copper. An attempted direct C1–ESP32
ground route and an additional I²C SCL route were independently rejected for
copper track crossings. Every path is checked against **actual KiCad net/pad
positions and layers** and accepted only if native KiCad DRC has **no
additional violations** and native connectivity finds exactly **20 fewer**
unconnected items. The complete DRC reports and a JSON evidence record are
placed alongside the generated board. Any change to the source layout or
footprint geometry causes the review script to fail closed until physically
revalidated.

Independent native **KiCad 10.0.7 on 2026-10-11**, using the current draft
source plus the twentieth opt-in GND connection. The original nineteen-link
KiCad 10.0.6 review on historical source commit `b66315c` was **37→18**
unconnected with **41** segments; its evidence remains historical rather
than a claim about this updated route set:

| Physical check | Default (0 tracks) | Opt-in routed evidence |
|---|---:|---:|
| PCB DRC violations | 16 | **16** |
| Physically unconnected items | 37 | **17** |
| Footprint library mismatches | 0 | **0** |
| Real copper segments | 0 | **45** |
| Schematic ERC | 0 | Source unchanged |

**Do not generate production Gerbers from the partial-review file.**
Proof Pack source remains DRC/clearance blocked; neither the remaining
unrouted nets nor the antenna/EMI, USB power and thermal qualification is
finished. The next engineering gate is a fully connected, independently
KiCad-DRC-clean physical PCB **and** written fabricator acceptance.
