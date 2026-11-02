# ESP32 + GCT USB4105 manufacturability and partial routed PCB review

Status: **BLOCKED / NOT FABRICATION APPROVED**. This is a measured engineering
assessment, not a supplier order approval. The sample board outline and
component placement are provisional; no PCB stackup, copper weight, thermal
performance or order options have been signed off.

**Technical decision record:** [DFM_DECISION_91.md](DFM_DECISION_91.md)
records the exact sixteen native KiCad DRC findings and the internal-only
routing, footprint and geometry remediation path. No external outreach or
manufacturing work is in scope. Do not weaken the native checks or treat
the review-only copper overlay as verified source routing.

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
| Copper width / spacing | Review-only thirty-two pad-to-pad routes, one via stitch, one pad-to-via link, two track-to-via links and one pad-to-existing-track link use 0.20 mm F.Cu/B.Cu tracks, including eighteen 0.70 mm / 0.30 mm through-vias | JLCPCB advertises 0.10/0.10 mm min width/spacing for 2-layer 1 oz | Potentially viable in a **1 oz** process, but DRC and physical electrical performance still need a complete routed PCB and DFM. |
| Complete interconnect and RF | Native KiCad current source: 37 unconnected / 16 manufacturing DRC; optional 37-link review board: **0 unconnected / 16 manufacturing DRC** | No manufacturer approval or qualified electrical/RF assessment is implied by zero KiCad unconnected items | **BLOCKED despite zero native unconnected.** No copper plane/antenna ground fill was invented; U1 RF keepout is retained. TVS on USB 5 V, AMS1117 stability/thermal and connector-shell EMI require separate evidence. |

**Important:** A supplier's generalized capability table does not constitute an
approval for this particular board, copper stack, assembly profile or connector.
A genuine zero-DRC, zero-unconnected board is **not attainable responsibly with
the current unchanged footprint/DRC constraints**. The four J1 peg-to-copper
violations require a qualified connector/land-pattern or geometry decision;
they must not be suppressed locally. The twelve ESP32 0.20 mm drill findings
likewise require a defensible design/footprint revision before the present
0.30 mm design restriction could be changed. These are internal engineering
tasks, not reasons to initiate manufacturer contact.

## Thirty-two pad routes plus five verified native copper island connections (review-only, not production pipeline)

The 2026-11-02 KiCad 10.0.8 addition connects U1.36 to U2.4 on
I2C_SCL using one F.Cu–B.Cu–F.Cu route with **two 0.30 mm drilled
through-vias**, 0.70 mm copper diameters and five new track segments.
The prior single-layer trial was rejected by the native tracks_crossing
rule. The accepted review-only path decreases 12 to **11** real missing
connections without creating any new KiCad DRC findings; all original
twelve U1 drill and four J1 hole-clearance findings remain **identical**.
Via and pad geometry still require real manufacturing review.

Also independently verified on 2026-11-02: R1.1 to R2.1 VCC_3V3
across F.Cu–B.Cu–F.Cu with **two more controlled 0.30 mm drill vias**
and three track segments. Actual native KiCad copper connectivity decreases
11 to **10** open items with the exact original sixteen DRC finding signatures
intact. Two alternative USB-C VBUS candidates were **rejected**: shorting
USB_CC1 or introducing new clearance/hole/solder-mask errors.

A third genuine 2026-11-02 KiCad 10.0.8 candidate joins **C2.1 to U2.8**
on VCC_3V3 with 3 segments across F.Cu/B.Cu/F.Cu and two additional
0.30 mm drilled / 0.70 mm copper through-vias. Its exact net/pad
center contract and unchanged sixteen individual native DRC blockers were
verified on the combined board, reducing open connections **10 → 9**.
Shorts, crossings and clearance failures in alternative trial routes were
not incorporated. All copper remains partial review evidence only.

A fourth independent KiCad 10.0.8 review path joins **C1.2 to U1.15
GND** over F.Cu/B.Cu/F.Cu, three 0.20 mm traces and two additional
0.30 mm drilled / 0.70 mm diameter through-vias. All original sixteen
physical DRC signatures remain exactly unchanged and the true unconnected
count drops **9 → 8**. Alternative routes near the USB-C connector and
VCC_3V3/I2C traces introduced shorts, crossings or clearance findings and
were excluded.

A fifth independent system KiCad 10.0.8 partial review connection joins
**U2 pin 2 to pin 8** on VCC_3V3 using a short F.Cu/B.Cu/F.Cu
detour, three segments and two 0.30 mm drill / 0.70 mm copper
through-vias. The exact net/pad physical connection decreases
**8 → 7** missing nets, with the same sixteen original
manufacturing DRC findings and no new short/crossing/clearance error.
Alternative front-layer-only crossings and unsafe via positions
were rejected. No physical DFM or fab acceptance is implied.

The next independent KiCad 10.0.8 review joins two **already placed
VCC_3V3 B.Cu via terminals**, at (45.1, 61.6) and (53.1, 58.8) mm,
using a single 0.20 mm track and **no new vias**. Both terminals belong
to verified same-net pad-backed route islands. This is separately
validated, not a fabricated pad-to-pad path; it decreases open copper
**7 → 6** without changing any of the original 16 DRC defect identities.
Alternative back-layer geometries that created shorts or clearance
errors were excluded.

The next independent KiCad 10.0.8 review routes **U3 pad 2 VCC_3V3**
(61.85, 36.0 mm) through one new 0.30 mm drilled/0.70 mm diameter
via (62.4, 36.4 mm) to the existing same-net back copper via
(57.1, 58.8 mm). The driver separately verifies the physical pad,
previous pad-backed via anchor, via geometry and two F.Cu/B.Cu
segments. This is not a new pad-to-pad route. Native DRC decreases
**6 → 5** missing copper connections, preserves all sixteen
existing physical DRC errors by exact signature and adds no new
short, mask or clearance findings. Unsafe alternative via positions
were rejected.

The next genuine KiCad 10.0.8 review connects both USB-C
**J1 A4 and J1 B4 VCC_5V contacts**, using a lower F.Cu/B.Cu/F.Cu
corridor: (77.6, 63.32) → (78.2, 65.5) → (81.8, 65.5)
→ (82.4, 63.32) mm. The three 0.20 mm segments use two
new 0.30 mm drill/0.70 mm diameter through-vias. Exact source
pad/net, via and all individual original physical DRC identities
are verified. Native copper connectivity improves **5 → 4**
open items, with no new DRC findings. Upper connector escapes
shorting USB_CC1/CC2 and GND alternatives creating new NPTH
clearances were rejected. The original J1 mechanical DFM
violations remain and there is **no fabrication approval**.

Final native KiCad 10.0.8 copper-island review, on the **same
unchanged reference source/footprints/rules**, added four further
validated links: VCC_5V main-board track to existing J1 via
(one new via/one B.Cu track); J1 A1→B1 GND contacts (two vias/three
tracks); that GND island to the existing board ground F.Cu track
(one via/one B.Cu track); and R2.2 I2C_SCL pad to an existing
B.Cu SCL track through a 45-degree-bend F.Cu path (one new via,
three tracks). All routes were tested **together**, yielding **zero
native KiCad unconnected items** while retaining the exact
original sixteen manufacturability DRC signatures. Unsafe
shorts, crossings and new NPTH clearance candidates were rejected.
This is native copper connectivity **only**, not measured
electrical behavior, DFM/fab approval or a change to the default
zero-track PCB pipeline.

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

The opt-in review emits **92 real 0.20 mm F.Cu/B.Cu segments joining 32 pad pairs, one via stitch, one pad-to-via, two track-to-via and one pad-to-existing-track link**,
including eighteen 0.30 mm-drilled, 0.70 mm-diameter through-vias,
of actual, pinned physical pad centers across USB-CC1/CC2, I²C, VCC_3V3,
VCC_5V and GND. These include the two USB-C CC sink lines, internal ESP32
VCC and GND terminals, BME280 supply/GND, R1/R2 I²C pullup-to-testpad,
U2 SDA-to-R1, C3-to-D1 power and GND, R3-to-R4 ground and U3's duplicate
VOUT lead/tab pads. Additional KiCad-verified paths connect C1–C2 GND,
C1–C2 3.3 V, C2 GND–U2 GND, U1.15 GND–U1.39 thermal pad and
U3 VIN–C3 VBUS. The twentieth, native-verified GND path links R3.2
to C3.2 on F.Cu via (72.51, 57.2) and (69.6, 57.2)/(69.6, 66.5),
respecting nearby USB-CC1 and VBUS copper. Two further, independent
KiCad-verified GND paths now connect **U1.38→U3.1** across the top of the
ESP32 design and **D1.2→U2.5** along the bottom, each with three
0.20 mm F.Cu segments; the two paths passed **together** with no changed
physical DRC findings. Three more routes now join **U1.1→U1.39 GND**
(three F.Cu segments), **C1.1→U1.2 VCC_3V3** (three segments along the
left edge) and **U1.33→U2.3 I2C_SDA** (four segments). Native KiCad
10.0.7 independently verified them **all on one combined board**, without
introducing or replacing physical DRC violations. Other candidates near
the USB-C shell, resistor supply pads and I²C crossings were rejected by
native KiCad because they introduced shorts, crossing traces, solder-mask
bridges or clearance violations. An
attempted direct C1–ESP32 ground route was likewise rejected. Every path is checked against **actual KiCad net/pad
positions and layers** and accepted only if native KiCad DRC has **no
additional violations** and native connectivity finds exactly **37 fewer**
unconnected items. The complete DRC reports and a JSON evidence record are
placed alongside the generated board. Any change to the source layout or
footprint geometry causes the review script to fail closed until physically
revalidated.

Independent native **KiCad 10.0.8 on 2026-11-02**, using the same pinned
source with thirty-two pad routes and five separately verified copper island links (the first 25 retain their previous
KiCad 10.0.7 evidence). Earlier native reviews
progressed from **19 links / 41 segments / 18 unconnected**, to **20 / 45 / 17**,
then **22 / 51 / 15**; those are historical evidence, not claims about this
updated route set:

| Physical check | Default (0 tracks) | Opt-in routed evidence |
|---|---:|---:|
| PCB DRC violations | 16 | **16** |
| Physically unconnected items | 37 | **0** |
| Footprint library mismatches | 0 | **0** |
| Real copper segments | 0 | **92** |
| Schematic ERC | 0 | Source unchanged |

**Do not generate production Gerbers from the partial-review file.**
Proof Pack source remains DRC/clearance blocked; neither the remaining
unrouted nets nor the antenna/EMI, USB power and thermal qualification is
finished. The next engineering gate is a fully connected, independently
KiCad-DRC-clean physical PCB **and** written fabricator acceptance.
