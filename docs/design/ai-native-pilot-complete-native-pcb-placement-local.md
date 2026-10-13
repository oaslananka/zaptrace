# AI-native #33 → #35: first complete native PCB placement baseline

**MSI local only. Source-only engineering experiment, not completed routing, DRC acceptance, independent human signoff or a fabrication release.** No GitHub writes or changes to the user's open KiCad GUI.

The exact source candidate is generated from the USB-C-powered 3.3 V / 100 mA STM32F103C8T6 + I²C temperature-sensor request. Unlike the earlier USB-C connector-only experiment, this produces one **complete 12-component, 8-net native KiCad schematic + PCB** with a real Edge.Cuts 100×80 mm outline.

## Source, placement and identity

- Original source candidate remains unchanged: `build/qa-038-physical-pin-source/candidate/`.
- `scripts/ai_native_pilot_pcb_baseline.py` verifies the frozen candidate manifest and actual SHA values, expected references, **pinned GCT USB4105 physical geometry** and all 12 resolved pad footprints. It runs the repository's existing deterministic `place_components` algorithm on an **in-memory copy**. No netlist, footprints or source-design file is modified.
- The local-only portable `ZapTracePilot.pretty`, schematic symbol library, project and `fp-lib-table` are exported for the **same placed design**. The system KiCad 10 `pcbnew` loader normalizes each synthetic footprint's library nickname without changing pad geometry or symbol/footprint UUID linkage, saves and reopens the actual .kicad_pcb.
- The independent audit demands **12 distinct physical footprint UUIDs**, **100 distinct physical pad UUIDs**, an exact pad ID count and **pad/net correspondence on every physical pad** (including unconnected pads and the two NPTH mechanical holes). Genuine KiCad XML cross-probe requires all 12 schematic↔PCB UUID paths and critical reference/value/pin-net associations to match. The GCT four individually UUID-identified `S1` pads remain on GND, but **copper connectivity is not inferred**.
- `placement-evidence.json` stores the source candidate ID and original SHA values, complete native coordinate/net/UUID inventory, the placement algorithm, *all generated files including portable library assets with SHA values*, actual KiCad DRC JSON digest, limitations and explicitly false fabrication authorization. A new directory is compulsory; no overwriting existing packages or accepted artifacts.
- Repeat runs preserve **placed-design.json and native schematic source bytes**, placement coordinates and stable footprint/pad UUID identities. KiCad's loader generates new UUIDs for some previously absent optional PCB property objects; therefore the normalized **.kicad_pcb file SHA is not byte-for-byte repeatable** across independent runs. Each particular artifact remains SHA-bound to its own evidence manifest. This is not a cryptographically signed approval.

## Actual KiCad 10.0.7 baseline measurement

| Property | Independent result |
| --- | --- |
| Real native PCB footprints | 12/12 |
| Physical pads | 100 |
| Nets | 8 |
| Source-linked pads with assigned nets | 55 (52 logical schematic nodes, plus repeated physical S1 instances) |
| Track segments / zones | 0 / 0 |
| Unconnected items in actual native KiCad PCB | **42** |
| Other native PCB DRC findings | **445** |
| DRC rule checks ignored | 5 (retained as limitations, NOT waived) |
| Schematic-to-PCB UUID reference paths | 12/12 verified |
| GCT S1 physical pads | Four unique pad UUIDs; all tagged GND; **still unrouted** |

Typical native PCB findings include 277 clearance, 131 solder-mask bridges, 12 footprint-library mismatches, 12 silk-over-copper, nine shorting-items, four hole-clearance findings. This proves the **seeded placement is not a professionally routable/qualified design yet**. The existing footprint models and physical clearances require actual remediation before accepting any routing, DFM or multi-EDA transfer. The board outline is a provisional 100×80 mm design envelope, **not a fabricator-approved mechanical drawing or verified USB-C edge placement**.

## Run on MSI

From the repository root, with the already installed `.venv` and native KiCad 10 (no new installations):

```bash
.venv/bin/python -m scripts.ai_native_pilot_pcb_baseline \
  --candidate-dir build/qa-038-physical-pin-source/candidate \
  --output-dir build/qa-040-native-placement/new-unique-placement
```

Open the resulting `SynthesizedBoard.kicad_pcb` using KiCad PCB Editor on MSI **only when you choose to inspect it**; the agent does not change the live GUI. The same directory also contains `SynthesizedBoard.kicad_sch`, `SynthesizedBoard.kicad_pro`, portable KiCad libraries and `placement-evidence.json` / `native-pcb-drc.json`.

## Open engineering work

Investigate clearance/mask/library/short findings at their physical source and actual part geometry; fix placement constraints, qualify USB-C edge/connector mounting, then connect the four physical S1 shield lands through explicitly reviewed, real PCB copper. After each change rerun actual KiCad native DRC, unconnected checks, source-bound schematic↔PCB linkage and relevant negative tests. SPICE remains **not checked**, KiCad/EasyEDA Standard roundtrip and Proof Pack gates remain open. The official #33 GitHub issue is deliberately untouched.
