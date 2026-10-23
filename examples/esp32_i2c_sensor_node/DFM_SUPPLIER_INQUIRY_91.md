# Issue #91 — pre-submission supplier DFM feasibility inquiry

**Status: PREPARED, NOT SENT.** This is a draft engineering inquiry for a
qualified human owner to review, select a recipient and explicitly authorize
external disclosure. It is **not a production order, order quote, waiver,
request to fabricate, release package or manufacturing approval**. The
candidate PCB is unfinished; **do not transmit its Gerbers/drill outputs to an
ordering portal or place any order**.

## 1. Identify the candidate precisely

| Field | Engineering source / status |
|---|---|
| Reference | ZapTrace Issue #91, Draft [PR #119](https://github.com/oaslananka/zaptrace/pull/119) |
| Physical board source | Commit `89e0328263e2e907a690e09f1ba8e7819b42b1e4` (same board/footprints/DRC preserved by later documentation-only commits) |
| Reference design | `examples/esp32_i2c_sensor_node/design.yaml` |
| Board | Provisional **100 × 75 mm**, **2 copper layers**; *stackup, actual board thickness, copper weight, mask, surface finish and supplier are NOT chosen* |
| Parts affecting question | **Espressif ESP32-WROOM-32**, U1; **GCT USB4105 series**, J1 (exact orderable connector suffix must be confirmed before assembly/fit acceptance) |
| Test tool | Independently regenerated **KiCad 10.0.7** schematic/PCB and native ERC/DRC; baseline **ERC 0**, **16 physical PCB DRC violations**, **37 physical unconnected items** |
| Review-only overlay | **25 pad/net-matched links / 61 F.Cu segments / 12 still unconnected**; original **16 DRC findings unchanged**; `fabApproved=false`, `physicalContinuityComplete=false` |
| Strict source Proof Pack | **6 PASS / 2 FAIL** (`drc-clean`, `min-clearance`), `blocked-insufficient-evidence` |
| Design authority | [DFM decision record](DFM_DECISION_91.md) and [manufacturing review](MANUFACTURING_REVIEW.md); pending qualified human owner approval |

**Question scope is manufacturing *feasibility*** of the two measured feature
classes on a hypothetical, explicitly stated process stackup, not whether the
unrouted PCB can be manufactured as submitted. A favorable answer **cannot**
resolve the unfinished copper connectivity, RF/antenna, USB power/EMI,
regulator-thermal or final electrical verification requirements.

## 2. Reproduced KiCad findings to be answered explicitly

- **D1 — U1 pad 39 thermal vias (12 errors):** all have a nominal **0.2000 mm
  plated drill**, versus the current project's **0.3000 mm minimum**. Nominal
  copper land diameter **0.60 mm** yields `(0.60 − 0.20) / 2 = 0.20 mm`
  radial annular ring *before* hole/registration/etch tolerance. Simply
  increasing the drill to **0.30 mm** while holding the pad diameter would
  give only **0.15 mm** nominal ring; do not propose that as an unqualified fix.
- **D2 — J1 USB-C NPTH locating pegs (4 errors across 2 holes):** the actual
  closest *NPTH-to-GND-pad* clearance is **0.1944 mm**, versus the unchanged
  KiCad project rule **0.2500 mm** (shortfall **0.0556 mm**). The four
  findings arise from two overlapping A/B GND pad IDs at the two physical
  locating holes; do not misinterpret them as four separate holes. The two
  **NPTH diameters are 0.65 mm**. Four separate **plated** S1 shell slots
  are 0.60 mm wide and 1.40/1.70 mm long; their acceptance is a **different**
  fabrication/assembly decision from the locating pegs.

The following **16 original physical findings** were extracted from native
KiCad 10.0.7 on the immutable referenced physical source, rather than
inferred from a vendor capability chart. All positions are **board-local mm**.

<!-- Native DRC 10.0.7 exact-head findings; updated only after rerunning the external oracle. -->

| # | KiCad finding | Original offending object(s) and location(s) |
|---:|---|---|
| 1 | `drill_out_of_range` | `PTH pad 39 [GND] of U1` @ `27.7950 mm, 32.3275 mm` |
| 2 | `drill_out_of_range` | `PTH pad 39 [GND] of U1` @ `27.7950 mm, 33.8525 mm` |
| 3 | `drill_out_of_range` | `PTH pad 39 [GND] of U1` @ `28.5575 mm, 31.5650 mm` |
| 4 | `drill_out_of_range` | `PTH pad 39 [GND] of U1` @ `28.5575 mm, 33.0900 mm` |
| 5 | `drill_out_of_range` | `PTH pad 39 [GND] of U1` @ `28.5575 mm, 34.6150 mm` |
| 6 | `drill_out_of_range` | `PTH pad 39 [GND] of U1` @ `29.3200 mm, 32.3275 mm` |
| 7 | `drill_out_of_range` | `PTH pad 39 [GND] of U1` @ `29.3200 mm, 33.8525 mm` |
| 8 | `drill_out_of_range` | `PTH pad 39 [GND] of U1` @ `30.0825 mm, 31.5650 mm` |
| 9 | `drill_out_of_range` | `PTH pad 39 [GND] of U1` @ `30.0825 mm, 33.0900 mm` |
| 10 | `drill_out_of_range` | `PTH pad 39 [GND] of U1` @ `30.0825 mm, 34.6150 mm` |
| 11 | `drill_out_of_range` | `PTH pad 39 [GND] of U1` @ `30.8450 mm, 32.3275 mm` |
| 12 | `drill_out_of_range` | `PTH pad 39 [GND] of U1` @ `30.8450 mm, 33.8525 mm` |
| 13 | `hole_clearance` | `Pad B12 [GND] of J1 on F.Cu` @ `76.8000 mm, 63.3200 mm`; `NPTH pad of J1` @ `77.1100 mm, 64.3950 mm` |
| 14 | `hole_clearance` | `Pad A1 [GND] of J1 on F.Cu` @ `76.8000 mm, 63.3200 mm`; `NPTH pad of J1` @ `77.1100 mm, 64.3950 mm` |
| 15 | `hole_clearance` | `Pad A12 [GND] of J1 on F.Cu` @ `83.2000 mm, 63.3200 mm`; `NPTH pad of J1` @ `82.8900 mm, 64.3950 mm` |
| 16 | `hole_clearance` | `Pad B1 [GND] of J1 on F.Cu` @ `83.2000 mm, 63.3200 mm`; `NPTH pad of J1` @ `82.8900 mm, 64.3950 mm` |

## 3. Public supplier references (not acceptance)

These pages describe **generic offered processes**, which can differ by
stackup, finished hole definition, copper weight, finish, solder mask, pricing
and order-specific engineering approval. **Neither supplier has reviewed this
reference PCB**, and the figures below are **not a design-rule waiver**.

- [JLCPCB public PCB capability table](https://jlcpcb.com/capabilities/pcb-capabilities/):
  advertises a **0.15 mm** minimum 2-layer drill, **0.20 mm preferred** via
  hole, and for **2-layer/1 oz** a PTH annular ring **0.18 mm absolute minimum,
  0.25 mm recommended**. Its **NPTH-to-track 0.20 mm** figure is about a
  *track*, **not NPTH-to-SMD pad**; it cannot settle J1's 0.1944 mm question.
  Its plated slot width and length specifications are **not** connector
  fit/assembly approval.
- [PCBWay public PCB capability table](https://www.pcbway.com/capabilities.html):
  publishes **0.15 mm** minimum CNC drilling with cost implications below
  0.20 mm, and gives a **0.15 mm nominal minimum annular ring for pads with
  vias** as a general figure. Its advanced-process conditions vary by stackup,
  aspect ratio and tolerance; do not assume these accept this specific U1
  pad/via array or its J1 NPTH-to-contact distance. Obtain a written
  board-specific response.
- [GCT's official USB4105 drawing](https://gct.co/files/drawings/usb4105.pdf):
  identifies 16 signal/contact positions, two **Ø0.65 mm** locating holes,
  separate elongated shell stakes, and its recommended PCB pattern. It
  does **not** replace a board-house hole/copper clearance check.
- [GCT USB4105 product specification](https://gct.co/files/specs/usb4105-spec.pdf)
  and [Espressif ESP32-WROOM-32 datasheet](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html)
  are part-specific engineering sources. The original ESP32-WROOM-32 is
  **NRND (Not Recommended For New Designs)**; a similarly named module is
  **not** automatically pin/footprint/RF compatible.

## 4. Ready-to-copy manufacturer inquiry — UNSENT

**Subject:** Engineering feasibility review only — 2-layer ESP32-WROOM-32 / USB4105, 16 known KiCad DRC findings; no PCB order

Hello PCB fabrication/DFM engineering team,

We are evaluating a **provisional, unrouted** 100 × 75 mm two-layer PCB with
an ESP32-WROOM-32 module and GCT USB4105 connector. **This is a technical
pre-feasibility inquiry only; no production, fabrication, quotation
acceptance, source-file upload or permission to alter geometry is requested.**
Our independent KiCad 10.0.7 review finds sixteen existing geometric
violations detailed in the attached-internal finding matrix above. Please
answer both feature classes for a **specific proposed stackup, copper weight,
finish and fabrication/assembly process**, rather than from general
capabilities alone:

1. **Thermal pad drills:** Can your process support **twelve 0.20 mm plated
   holes with 0.60 mm copper pads** within the ESP32 module's ground/thermal
   land pattern? Are the values quoted drilled or finished sizes? What
   drill/registration tolerance and minimum finished annular ring apply on
   this selected stackup? Is via filling, plugging, tenting or paste control
   required for assembly/reflow or solder-wicking reliability?
2. **USB-C locating holes:** Can your process **explicitly accept two
   Ø0.65 mm NPTH pegs only 0.1944 mm from their neighboring GND contact
   pads**, including hole-registration and solder-mask/copper tolerances?
   This is a **hole-to-pad** gap, **not hole-to-track**. If unacceptable,
   what minimum NPTH-to-pad land-pattern clearance or process change is
   required? Do not propose shifting connector pegs without a revised
   connector drawing and fit qualification.
3. **Other connector features:** Are **four plated shell slots, 0.60 mm
   wide and 1.40/1.70 mm long**, compatible with the stated PCB thickness,
   plated-slot registration and USB4105 assembly/solder-stake specification?
   Distinguish board fabrication from connector assembly acceptance.
4. **Decision and constraints:** Please return an itemized written
   **acceptable / unacceptable / conditional / requires-data** decision for
   **D1 and D2 separately**, identifying the specific process parameters,
   assumed tolerances, necessary evidence, cost/lead-time implications and
   any required geometry changes. A generic capability chart or "should be
   OK" response is not sufficient.
5. **Disclosure/next step:** Please state exactly which **minimum**
   fabrication drawings or geometry excerpts your engineer needs for a
   non-production assessment. We will request internal authorization before
   sharing a controlled design package. **Do not create an order or adjust
   source files on our behalf.**

This is not a released design. The source PCB presently has **37 unrouted
connections** (the optional review demonstrator still has **12**), the
native DRC has **16 physical errors**, and the strict Proof Pack fails its
manufacturability/clearance checks. Any supplier response will be assessed
by a qualified engineer before a separate redesign/DFM acceptance decision.

Thank you.

*Project engineering team — contact identity to be supplied by authorized
owner; this draft has not been sent.*

## 5. Supplier-specific follow-up and response capture

| Requested answer | JLCPCB clarification | PCBWay clarification | Acceptance if documented |
|---|---|---|---|
| U1 thermal via drill/ring | Confirm the **2-layer / 1 oz** recommended **0.25 mm**, absolute **0.18 mm** PTH annular-ring conditions; alternatives if copper/finish differs | Confirm whether the published **0.15 mm annular-ring** figure actually applies to *these twelve* thermal via pads, with specific thickness, finished holes and tolerances | Specific written process/registration/assembly judgment; no silent KiCad rule downgrade |
| J1 NPTH–land | Confirm the minimum **NPTH-to-pad** copper and mask edge distance, explicitly separate from NPTH-to-track | Confirm **NPTH-to-pad** minimum under selected drill-registration and solder-mask process, not a generic drill diameter | Explicitly approves/rejects **0.1944 mm** nominal geometry or specifies revision |
| J1 shell stakes | Confirm 0.60 × 1.40/1.70 mm plated oval slot capability and assembly fit against exact USB4105 variant | Confirm plated slot dimensional tolerance and connector-assembly availability | Written slot and assembly limitations by chosen thickness/variant |
| Part/board assumptions | Name fixed board thickness, finished copper, surface finish, registration tolerances and order options | Name same, including plating, manufacturing class and any special steps | No answer accepted unless **exact board revision + process** is identified |

**Owner response log — currently unanswered:**

| Field | Current value |
|---|---|
| Recipient / authorized disclosure | **NOT SELECTED / NOT APPROVED** |
| Supplier process, thickness, copper, finish | **NOT SELECTED** |
| Response, date, engineer identity | **NO RESPONSE — NOT SENT** |
| U1 thermal-pad D1 determination | **OPEN — 12 findings** |
| J1 NPTH-to-pad D2 determination | **OPEN — 4 findings** |
| Alternate connector/module lifecycle decision | **OPEN — independent qualification required** |
| Remaining 12 native copper connections / RF, ESD, power and thermal | **OPEN** |
| Production sign-off / board order | **BLOCKED — prohibited by current evidence** |

## 6. Controlled disclosure and acceptance gates

1. An authorized human selects recipient(s), verifies the requested orderable
   USB4105 suffix and defines the preliminary stackup/finish assumptions.
   Only then may a **non-ordering inquiry** be sent. This document contains
   no recipient address, credentials or hidden project files.
2. Request engineering-only feasibility **before** offering board assets.
   If more geometry is required, obtain permission to share *specific*
   excerpts, supplier drawings and relevant DRC coordinates. Do not upload
   the **unrouted** PCB or Gerbers as if ready for production.
3. Preserve the supplier's complete written reply, date, part/board revision,
   assumptions and explicit D1/D2 dispositions; cross-link in [Issue #91](https://github.com/oaslananka/zaptrace/issues/91)
   without treating generic or conditional replies as project approval.
4. If rejected or uncertain, revise source using pinned, exact-vendor
   footprints and new independent checks. A credible new layout requires
   **zero actual unresolved copper continuity**, independently justified
   native ERC/DRC, passing strict Proof Pack and qualified RF/electrical
   design review; **fabricator acceptance and human sign-off are separate**.
5. Until all conditions are met, leave [PR #119](https://github.com/oaslananka/zaptrace/pull/119)
   **Draft**, Issue #91 **open**, `fabApproved=false`, and the default
   fail-closed PCB exporter unchanged. **No manufacturing authorization.**
