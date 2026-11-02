# Issue #91 — physical DFM decision record (ESP32-WROOM-32 / USB4105)

**Record date:** 2026-10-11. **Disposition:** BLOCKED — engineering options only;
**no fabricator DFM acceptance, board release, or production authorization.**
**Owner direction (2026-11-02): internal engineering only.** No supplier
inquiry, external contact, fabrication quote, or order is part of this work.
The engineering path is to repair the default routing/export pipeline and
investigate geometry-correct, independently verifiable footprint/component
and board-layout alternatives without weakening native DRC or source proofs.
An internal clean DRC is necessary engineering evidence, not fabrication or
RF/electrical sign-off.

## New independent routing evidence — 2026-11-02

System KiCad **10.0.8** reproduced the existing 25-link / 61-segment
partial review, then independently checked an additional genuine
**U1.36 → U2.4 I2C_SCL** connection. The single-layer proposal failed
tracks_crossing and was rejected. A two-layer alternative with
**two 0.30 mm-drilled, 0.70 mm-diameter through-vias** and five segments
passed the independent native KiCad DRC comparison: **26 actual
connections, 66 tracks, 2 vias, 37 → 11 unconnected**, with the same
16 manufacturability defects by exact rule, object and position.
The original D1/D2 geometry, constraints, engineering/DFM hold and
no-fabrication decision are **unchanged**.
A second independent native two-layer R1.1→R2.1 VCC_3V3 review route
was verified on the same source, adding 3 tracks and two vias: **27
connections, 69 tracks, 4 vias and 37→10 unconnected**. The 16 defects
are still identical by native DRC signature. Rejected J1 VBUS attempts
introduced a short or new pad/hole/soldermask DRC errors and are excluded.
A third independently native DRC-checked C2.1→U2.8 VCC_3V3 route
adds 3 copper segments and two vias: the combined review now has **28
connections, 72 segments, 6 vias and 37→9 unconnected**, preserving
the original 16 manufacturing DRC signatures. There is no production
permission or copper completion.

An additional independently checked C1.2→U1.15 GND 2-layer route adds
three copper segments and two vias: the combined review has **29
connections, 75 tracks, 8 vias, 37→8 unconnected**, preserving all sixteen
individual physical DRC defect signatures without introducing new errors.
No manufacturing approval is implied.

Further real KiCad 10.0.8 native acceptance for U2.2→U2.8
VCC_3V3 with two vias and three tracks brings the opt-in review
to **30 authentic pad/net connections, 78 tracks, 10 vias and
37→7 unconnected**, without changing any of the original sixteen
physical DRC defects. Both full continuity and fab approval stay open.

A subsequent KiCad 10.0.8 verified B.Cu stitch connects two
already verified VCC_3V3 net/via terminals, without a new via:
**30 pad-connected routes plus one via stitch, 79 copper segments,
10 vias and 37→6 unconnected**. All original sixteen physical DRC
findings remain unchanged; this is not full PCB continuity or
manufacturing approval.

A further KiCad 10.0.8 verified U3.2 VCC_3V3 pad-to-existing-via
link requires one new drilled via and two segments. The opt-in review
now contains **30 pad-to-pad routes + one via stitch + one pad-to-via
connection, 81 copper segments, 11 vias and 37→5 unconnected**.
The same 16 native DRC defects remain; manufacturing approval is
still blocked.

Another independent KiCad 10.0.8 DRC acceptance links the two
real USB-C J1 VCC_5V contacts A4→B4 through three lower two-layer
tracks and two vias. Combined review: **31 pad-to-pad routes,
one via stitch, one pad-to-via connection, 84 tracks, 13 vias
and 37→4 unconnected**. Original sixteen manufacturability
violations persist identically, especially all four J1 NPTH
clearances; no production sign-off or copper completeness.

Four more system KiCad 10.0.8 verified lower-connector/ground/
I2C routes (VCC_5V source track→J1 via; J1 GND A1→B1;
J1 GND→board ground track; R2.2 I2C_SCL→existing back
track) complete the opt-in native net connectivity:
**37 physical copper joins, 92 segments, 18 vias and
37→0 KiCad unconnected items**, while the exact sixteen
original DRC defects remain **unchanged**. No electrical
measurement, qualified RF/thermal/ESD validation, official
manufacturer exception or fabrication authorization was obtained.
The *default* PCB export is still an intentionally unrouted
zero-copper design and source Proof Pack remains blocked.

All routing remains experimental review-only copper.

The table below is the original dated 2026-10-11 decision baseline.

## Reproduced source baseline — KiCad 10.0.8 (2026-11-02)

The default pipeline was regenerated from the unchanged design.yaml at
PR #119 head 7ec1e8a. The report now exposes **7 unresolved routed nets**:
VCC_5V, VCC_3V3, GND, USB_CC1, USB_CC2, I2C_SDA and
I2C_SCL. Ground is intentionally not poured (copper_pour_gnd=false), so
GND is not eligible to disappear from the routing-completeness denominator.

System KiCad 10.0.8 independently reproduced the source board baseline:

| Native check | Result |
|---|---:|
| Schematic ERC | **0 violations** |
| PCB DRC | **16 errors** |
| PCB unconnected items | **37** |
| Default exported copper tracks | **0** |
| Physical acceptance | **BLOCKED** |

The 16 DRC findings are exactly 12 drill_out_of_range violations on
U1 pad 39 PTH drills (0.2000 mm actual vs 0.3000 mm board minimum) and
four hole_clearance violations between J1's two 0.65 mm NPTH locating
holes and duplicated A/B GND contacts (0.1944 mm actual vs 0.2500 mm
board rule). The four entries describe two physical peg locations and
four overlapping contact-pad observations; they are not four separate
mechanical holes. No rule was waived, and no footprint or board geometry
was altered during this baseline reproduction.

This verifies the current blocker identity; it does not make the board
production-ready or qualify assembly, thermal, RF, ESD or USB behavior.

## Opt-in geometric pad-fanout candidate — native KiCad 10.0.8 (2026-11-02)

The pad-aware GridRouter review candidate now has a real geometric pad-exit
path for the two-terminal USB-C CC nets. Each pad-centre-to-grid stub is
checked against actual rotated pad shapes, unassigned connector contacts,
NPTH holes, board hard obstacles and the route width/clearance. The unassigned
J1 B7/B8/A8/A9 contacts remain physical obstacles. No endpoint cells are
opened and no width reduction is applied.

On the unchanged ESP32 source, the opt-in router proposes **3 of 7 nets**:
USB_CC1, USB_CC2 and I2C_SCL; **27 copper segments, 0 vias**. The default
source pipeline/export contract is unchanged: **0 accepted source tracks**,
seven unresolved nets, and physical preflight still fails. This candidate
is not a complete board route.

For an independent native check, the 27 tracks were added to a temporary
copy of the regenerated default KiCad PCB using KiCad 10.0.8 Python
bindings. Native result:

| Native check | Source baseline | Pad-fanout candidate |
|---|---:|---:|
| Schematic ERC | 0 | 0 |
| PCB DRC violation records | 16 | **16 (exact same 16 records)** |
| New DRC records | — | **0** |
| Unconnected items | 37 | **32** |

The candidate removes five native unconnected relations while preserving
the two physical DRC groups exactly: twelve U1.39 drill-size errors and
four J1 NPTH-to-GND clearance observations. No electrical/physical rule was
waived and no DRC was hidden. The remaining routing nets and U1/J1 DRC
blocks remain unresolved; this is a review-only candidate, not fabrication
acceptance or permission to release the source PCB.

The route candidate and temporary KiCad copy are not the default pipeline
output. Strict source physical preflight remains false and fabApproved
remains false.

## Exact evidence and applicability

Evidence baseline: Draft [PR #119](https://github.com/oaslananka/zaptrace/pull/119)
source commit `89e0328263e2e907a690e09f1ba8e7819b42b1e4`,
provisional 100 × 75 mm, 2-layer ESP32 I²C sensor reference. System KiCad
**10.0.7** was run independently on a newly generated schematic and default
PCB, and against the separately opted-in native copper review. No physical
footprint or rule was modified to obtain the evidence below.

| Evidence | Default exported PCB | Separate opt-in review PCB |
|---|---:|---:|
| Native schematic ERC | 0 | Same unchanged source |
| Native PCB manufacturability DRC | **16 errors** | **16, identical individual defects** |
| Native physical `unconnected_items` | **37** | **12** |
| Routed F.Cu segments | 0 | 61, representing 25 net/pad-matched links |
| Strict source Proof Pack | **6 PASS / 2 FAIL** | Not a separate production Proof Pack |

The two Proof Pack failures are `drc-clean` and `min-clearance`; the source
verdict is `blocked-insufficient-evidence`. The optional review manifest
records `fabApproved=false` and `physicalContinuityComplete=false`.
The 16 defects were compared by complete native KiCad rule, severity,
offending object and location signatures, not merely by category count.
**CI and successful partial copper routing do not waive these defects.**

### Blocker D1 — ESP32 module thermal ground vias (12 native errors)

- KiCad rule: `drill_out_of_range`; twelve genuine U1 pad-39 plated holes.
  **Measured drill 0.2000 mm; project minimum 0.3000 mm** (0.1000 mm short).
  Existing nominal via copper diameter is **0.60 mm**, giving a nominal
  radial annular ring of `(0.60 - 0.20)/2 = 0.20 mm` before production
  tolerances. The pad geometry and solder/thermal behavior require review.
- [JLCPCB's published 2-layer capabilities](https://jlcpcb.com/capabilities/pcb-capabilities/)
  list 0.15 mm minimum drilling, 0.20 mm preferred minimum via drill, and
  a **0.18 mm absolute / 0.25 mm recommended** PTH annular-ring width for
  2-layer, 1 oz copper. [PCBWay capabilities](https://www.pcbway.com/capabilities.html)
  list 0.15 mm minimum mechanical drilling and added charges for sizes below
  0.20 mm. These are generic process ranges, **not board-specific DFM approval**.
- **Unsafe shortcut:** increasing the hole to 0.30 mm *without changing the
  0.60 mm pad* reduces the calculated radial annular ring to **0.15 mm**,
  below JLCPCB's cited absolute 0.18 mm 2-layer/1 oz figure. Enlarging pads,
  changing a via count, or removing thermal vias may also invalidate module
  footprint clearances, paste deposition, heat flow and supplier pin/pad
  provenance. None may be done as a blind DRC fix.
- The design specifically uses **ESP32-WROOM-32**, not ESP32-C3-MINI-1 or
  another WROOM variant. [Espressif's ESP32-WROOM-32 datasheet](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html)
  contains the recommended land pattern with thermal-pad vias and labels
  this original module **NRND (Not Recommended For New Designs)**.
  Any replacement module requires its **own** verified land pattern, pad/pin
  mapping, RF/antenna layout, availability and electrical qualification;
  a similarly named module cannot be silently substituted.

### Independent D1 what-if board trials — 2026-11-02 (NOT approved)

On the **same exact PCB source** at Draft PR #119 head
ea8549c65d25467e12c16ba3ad7f825dd0005c84, system
**KiCad 10.0.8** validated the opt-in, completely routed reference
PCB at **0 native unconnected / 16 original manufacturing DRC**.
In isolated temporary copies, *only* the twelve U1/39 plated-drill
diameters, and where noted their copper pad diameters, were changed.
These were **not** modifications to the tracked vendor footprint,
default design, manufacturing outputs or PR routing contract.

| Temporary what-if, all 12 U1/39 vias | Nominal annular ring | Neighboring via-pad edge gap (0.7625 mm center pitch) | Native KiCad result | Qualification |
|---|---:|---:|---|---|
| Original 0.20 mm drill / 0.60 mm land | 0.200 mm | 0.1625 mm | 16 original errors | Source remains blocked by 0.30 mm minimum drill |
| 0.30 / 0.60 mm | **0.150 mm** | 0.1625 mm | 4 J1 errors + 1 footprint-library mismatch | **Reject**: below vendor-published 0.18 mm absolute annular ring |
| 0.30 / 0.65 mm | **0.175 mm** | 0.1125 mm | 4 J1 errors + 1 footprint-library mismatch | **Reject**: still below 0.18 mm absolute annular ring |
| 0.30 / 0.75 mm | 0.225 mm | **0.0125 mm** | 4 J1 errors + 1 footprint-library mismatch | **Unqualified**: below 0.25 mm recommended ring and very tight same-net pad spacing |
| 0.30 / 0.80 mm | 0.250 mm | **−0.0375 mm** (overlap) | 4 J1 errors + 1 footprint-library mismatch | **Unqualified**: adjacent copper pads overlap; paste, assembly and thermal behavior not approved |

The ring values are **nominal geometric calculations**, not measured
finished hole sizes. DRC does not certify process capability,
registration tolerance, solder wicking, via filling, thermal-pad paste
deposition, assembly, current/heat flow or RF performance. The
footprint-library mismatch occurs because these temporary board pad
edits do not match the unchanged original source footprint; removing
that warning by editing both files would **not** prove manufacturability.
No tested option changes the four J1 peg-to-pad clearance violations.

These results are **feasibility evidence**, not a selected
replacement footprint. An exact manufacturer land pattern and a
qualified process/assembly decision are required before updating
U1 geometry. The project's native DRC minimum drill remains
0.30 mm and no physical violations were waived. JLCPCB's
[2-layer capabilities](https://jlcpcb.com/capabilities/pcb-capabilities/)
publish a 0.18 mm absolute and 0.25 mm recommended 1 oz
PTH annular ring, not a board-specific authorization.

### Independent manufacturer source cross-check — 2026-11-02

The selected **GCT USB4105** manufacturer's [product page and
drawing](https://gct.co/connector/usb4105) identify two Ø0.65 mm
locating holes **5.78 mm center-to-center**, and a recommended
component-side land pattern using **0.60 × 1.15 mm** outer
ground-contact lands. Independent KiCad 10.0.8 extraction of
the **unchanged J1 footprint**, relative to its board origin
(80.0, 67.0) mm, shows:

| Item | Actual local footprint coordinates (mm) | Dimensions |
|---|---|---|
| Two mechanical NPTH locating pegs | (−2.89, −2.605), (+2.89, −2.605) | Ø0.65, centers 5.78 apart |
| A1/B12 shared ground contact | (−3.20, −3.68) | 0.60 × 1.15 copper |
| A12/B1 shared ground contact | (+3.20, −3.68) | 0.60 × 1.15 copper |

These dimensions agree with the listed **GCT recommended
land pattern**; the two real Ø0.65 pegs must not be shifted
just to suppress four duplicated-pad KiCad findings. The
native hole-clearance result is **0.1944 mm** versus the
unchanged 0.2500 mm board rule. Matching a drawing proves
dimensional consistency, **not** assembly, manufacturing
tolerance or supplier process acceptance. The exact
USB4105-15-A-120 shell stake and assembly fit still require
qualification.

The current official [Espressif ESP32-WROOM-32 datasheet,
Section 10.1](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html)
depicts copper vias beneath the thermal pad, but does
**not** by itself qualify the local twelve 0.20-mm drilled
/ 0.60-mm land structures or a 0.30-mm drill replacement.
The original module remains **NRND**. Any changes require
pad/paste/thermal, manufacturer land-pattern and
board-process verification, not an assumed DRC-only fix.

### Blocker D2 — USB-C J1 locating peg / GND land clearance (4 native errors)

- KiCad rule: `hole_clearance`; J1 **NPTH** locating holes at
  `(77.1100,64.3950)` and `(82.8900,64.3950)` mm. The four GND pad
  observations correspond to physically overlapping A/B contact numbers at
  `(76.8000,63.3200)` and `(83.2000,63.3200)` mm, **not four distinct pegs**.
- Actual clearance **0.1944 mm**, required **0.2500 mm**; nominal shortfall
  **0.0556 mm**. JLCPCB's generic **0.20 mm NPTH-to-track** figure does
  **not** qualify NPTH-to-*pad* proximity; indeed the measured gap is below
  even that distinct track figure. Board-house process, hole-registration
  tolerance, soldermask and exposed copper require specific review.
- [GCT USB4105 product and source drawing](https://gct.co/connector/usb4105)
  govern its 16 contact lands, two locating pegs and four plated S1 oval
  shell stakes. The existing S1 slots are 0.60 mm wide with lengths 1.40/
  1.70 mm; their plausibility under generic plated-slot capabilities does
  **not** cure the NPTH-to-GND clearance issue or certify assembly fit.
- **Unsafe shortcut:** moving the pegs, shrinking/removing GND contact lands,
  renumbering A/B contacts, treating shell stakes as net-connected copper,
  removing locating holes or relaxing clearance globally. Each would change
  actual connector fit, soldering or electrical/EMI behavior without evidence.

## Engineering-only remediation (owner direction: no external outreach)

The objective is an honest and reproducible **default** pipeline, not a
fabrication order. The historical published capability figures above provide
design constraints only; they do not authorize changing a rule or calling
the unchanged board production-ready.

| Work item | Existing evidence | Internal acceptance target |
|---|---|---|
| D1: twelve U1 thermal vias | 0.20 mm drills, 0.60 mm pads, 0.30 mm project drill minimum; isolated drill/pad trials exposed annular-ring and adjacent-pad constraints | Choose a physically defensible module land pattern and drill/pad arrangement backed by exact component drawings; independent KiCad DRC without rule suppression or new footprint mismatches |
| D2: four J1 contact/locating-peg findings | 0.1944 mm NPTH-to-GND pad clearance vs 0.25 mm board rule; actual footprint matches the selected connector drawing | Evaluate exact part/footprint compatibility and revised layout/connector options; preserve peg fit, pad pinout, shell slots and electrical constraints; independent KiCad DRC without waivers |
| Default routing | Source exports zero accepted copper and reports **seven unresolved nets** (six signal/power nets plus GND because copper_pour_gnd=false); separate opt-in review overlay has 37 genuine joins / 92 tracks / 18 vias / 0 native unconnected, but still D1/D2 | Integrate valid geometry/routing behavior through the owned deterministic pipeline; independently reproduce complete pad/net continuity in generated output with zero critical shorts/clearance defects |
| Proof/electrical evidence | Source strict Proof Pack 6 PASS / 2 FAIL and native PCB DRC 16; real RF, ESD, power and thermal qualification not established | Preserve fail-closed checks and negative regression tests; demonstrate independent native ERC/DRC and strict Proof Pack outcomes without misrepresenting hardware approval |

### Execution order

1. Characterize why the ordinary grid router reports graph-connected nets
   yet rejects actual exported traces. Use the real ESP32 input and preserve
   provenance-locked footprint/pad identities; translate the already verified
   review-only routes into algorithmic regression expectations, not an
   unvalidated static default copper overlay.
2. Investigate D1 and D2 as *source geometry and placement* constraints.
   Validate any potential replacement part and land pattern internally
   against exact public drawings and native KiCad DRC. Rejected experimental
   variants remain rejected; do not silently change the project design
   rules, pad/pin mapping, antenna keepout or shell-stake handling.
3. Re-run source-generation end to end, native schematic ERC, PCB DRC,
   complete actual pad/net connectivity, strict Proof Pack and targeted
   negative fixtures. Distinguish software verification from unperformed
   RF, ESD, thermal, USB power and assembly qualification.

**Stop rule:** if a physical geometry change cannot be independently
justified without compromising the chosen part's mechanical/electrical
requirements, keep it as an honest unresolved finding. Do not create
speculative design variants merely to reach zero warnings.

## Current engineering gates

| Gate | Required evidence | Current disposition |
|---|---|---|
| Source routing | Deterministic default copper with zero real unconnected items and no new shorts | **OPEN** — default copper zero; separate review-only PCB 0 unconnected |
| Source geometry | Exact component/footprint compatibility and independent justified KiCad DRC | **OPEN** — D1 12 + D2 4 violations |
| Strict proof | All applicable unwaived checks and regression fixtures pass | **OPEN** — source 6 PASS / 2 FAIL |
| Electrical/RF behavior | Ground return, RF keepout, USB-C CC/shell/ESD/VBUS, regulator thermal and qualified evidence | **OPEN** — not hardware-qualified |
| Fabrication release | Separate professional review and final physical evidence | **BLOCKED** — no authorization; not part of this work |

**Next:** work within #91 and #35 on genuine default copper and physical
geometry/footprint correctness; preserve the Draft PR and all fail-closed
checks while the above gates are unresolved. No external communications.
