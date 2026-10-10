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

| Physical feature | Board / KiCad 10.0.6 evidence | Published capability | Decision |
|---|---|---|---|
| ESP32 U1 thermal pad-39 drilled vias | Twelve 0.20 mm PTH; KiCad minimum 0.30 mm; 0.60 mm annular pads | JLCPCB supports 0.15 mm drilling on 2-layer boards, **prefers 0.20 mm** minimum vias; 0.20 mm small-via options may have additional cost. PCBWay publishes 0.15 mm mechanical capability with extra charges below 0.20 mm. | **Conditional only.** 0.20 mm is in published capacity, but our conservative 0.30 mm rule is unchanged until stackup, via plugging/tenting and supplier DFM are explicitly agreed. A 0.60 mm / 0.20 mm PTH has a 0.20 mm nominal annular ring, meeting JLCPCB's quoted absolute 0.18 mm minimum for 2-layer 1 oz but below the 0.25 mm recommendation. |
| GCT J1 four plated S1 oval slots | Width 0.60 mm; two length 1.40 mm, two length 1.70 mm; Excellon G85 and native KiCad plated-slot geometry verified | JLCPCB's published 2-layer minimum plated slot width is 0.50 mm and slot length must be at least 2× width; advertised slot tolerance +0.13/-0.08 mm | **Plausible**, not ordered/approved. All four slots pass the published width and 2× width length limits; specific tolerance/connector stake fit still require a supplier check. |
| J1 two nonplated locating pegs | Two 0.65 mm NPTH; adjacent GND pad gap is **0.1944 mm**, native KiCad rule **0.25 mm** | JLCPCB advertises 0.50 mm minimum NPTH diameter and 0.20 mm NPTH-to-track clearance; pad-to-NPTH acceptance is **not** guaranteed by the track limit | **BLOCKED.** 0.1944 mm is even 0.0056 mm below the published NPTH-to-track minimum and 0.0556 mm below our 0.25 mm rule. The footprint is constrained by the actual connector locating peg and contact layout. Do not shift pegs, shrink solder contacts, delete holes or change clearance rules merely to get a green DRC. |
| Copper width / spacing | Review-only six connection paths use 0.20 mm F.Cu tracks | JLCPCB advertises 0.10/0.10 mm min width/spacing for 2-layer 1 oz | Potentially viable in a **1 oz** process, but DRC and physical electrical performance still need a complete routed PCB and DFM. |
| Complete interconnect and RF | Native KiCad current source: 37 unconnected / 16 manufacturing DRC; optional six-link review board: **31 unconnected / 16 manufacturing DRC** | No manufacturer publishes acceptance of incomplete nets or an unqualified ESP32 antenna layout | **BLOCKED.** No copper plane/antenna ground fill was invented; U1 RF keepout is retained. TVS on USB 5 V, AMS1117 stability/thermal and connector-shell EMI require separate evidence. |

**Important:** A supplier's generalized capability table does not constitute an
approval for this particular board, copper stack, assembly profile or connector.
A genuine zero-DRC, zero-unconnected board is **not attainable responsibly with
the current unchanged footprint/DRC constraints**. The four J1 peg-to-copper
violations require a supplier-specific written DFM exception supported by
engineering evidence or a qualified different connector/land-pattern decision;
they must not be suppressed locally. The 12 ESP32 0.20 mm drill findings likewise
need a documented selected-process profile before the 0.30 mm design restriction
can be changed.

## Six real physical copper links (review-only, not production pipeline)

Run the usual demo pipeline, then apply a separately audited, **opt-in**
native KiCad route overlay. The default pipeline intentionally continues
to export no tracks rather than pretending to complete all nets.

```bash
zaptrace pipeline --source examples/esp32_i2c_sensor_node/design.yaml --output build/esp32-review
/usr/bin/python3 scripts/issue91_native_copper_review.py \
  build/esp32-review/kicad/ESP32_I2C_Sensor_Board.kicad_pcb \
  build/esp32-review/kicad/ESP32_I2C_Sensor_Board_partial_review.kicad_pcb
```

The opt-in review emits 14 real 0.20 mm F.Cu segments joining 6 pairs of
actual, pinned physical pad centers: J1 A5→R3.1, J1 B5→R4.1, U1.2→U1.3,
U2.5→U2.7, U2.6→U2.8, U2.1→U2.7. Every path is checked against **actual KiCad
net/pad positions and layers** and accepted only if native KiCad DRC has **no
additional violations** and native connectivity finds exactly **six fewer**
unconnected items. The full DRC reports and a JSON evidence record are placed
alongside the generated board. Any change to the source layout or footprint
geometry causes the review script to fail closed until physically revalidated.

Independent native **KiCad 10.0.6 on 2026-10-11** at source commit `462f7e0`:

| Physical check | Default (0 tracks) | Opt-in routed evidence |
|---|---:|---:|
| PCB DRC violations | 16 | **16** |
| Physically unconnected items | 37 | **31** |
| Footprint library mismatches | 0 | **0** |
| Real copper segments | 0 | **14** |
| Schematic ERC | 0 | Source unchanged |

**Do not generate production Gerbers from the partial-review file.**
Proof Pack source remains DRC/clearance blocked; neither the remaining
unrouted nets nor the antenna/EMI, USB power and thermal qualification is
finished. The next engineering gate is a fully connected, independently
KiCad-DRC-clean physical PCB **and** written fabricator acceptance.
