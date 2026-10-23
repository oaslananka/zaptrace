# Issue #91 — physical DFM decision record (ESP32-WROOM-32 / USB4105)

**Record date:** 2026-10-11. **Disposition:** BLOCKED — engineering options only;
**no fabricator DFM acceptance, board release, or production authorization.**
The decision is to **prepare a revision-specific written DFM inquiry first**,
without ordering boards or changing the geometry or DRC rules. If the supplier
cannot explicitly support both problem classes for the actual board/process,
select a controlled footprint/component and board-layout revision instead.
Neither path, by itself, establishes finished routing, RF performance, or
fabrication readiness.

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

## Two controlled resolution paths

| Decision dimension | Path A — written, revision-bound fabricator DFM | Path B — qualified footprint / component redesign |
|---|---|---|
| Scope | Retain exact supplier footprints and conservative design rules while gathering explicit exceptions/process capability for **both D1 and D2** | Choose a verified manufacturer land pattern or mechanically/electrically qualified alternate part, update actual board geometry and routing |
| Benefit | Potentially avoids altering module/connector and existing pad provenance | Can eliminate geometric conflicts at source and target unwaived, clean DRC |
| Main risk | Published minimums or a vague support reply are insufficient; small copper/NPTH margin may not be acceptable on the quoted panel, finish or assembly line | May require new connector envelope, pin maps, shell/EMI policy, paste, antenna keepout, placement and RF/electrical requalification |
| Required proof | Written supplier response bound to exact board revision, layer count, stackup, copper weight, finished drill and tolerance, via fill/tent/paste, J1 NPTH-to-*pad* gap and registration, plated-slot/assembly and process limits | Datasheets/drawings for exact orderable variants; provenance-locked footprint/3D geometry; fresh schematic/ERC, net/pad mapping, complete copper routing, native DRC and production DFM |
| Current decision | **Prepare inquiry only — not accepted or ordered** | **Fallback if A is rejected, ambiguous or unreproducible; not yet implemented** |

**Recommended sequence:** keep both paths open while obtaining a *non-ordering*
DFM feasibility answer for the measured revision. Prefer a geometry-correct,
independently DRC-clean redesign when a supplier cannot explicitly accept the
**0.1944 mm NPTH-to-pad** case or the twelve thermal via structures. A
supplier-specific exception, if one is ever signed, needs a separately reviewed
controlled process-profile decision and traceable evidence; it is **not**
authorization to suppress a native DRC or overwrite the strict Proof Pack.

**Supplier-ready, unsent engineering questionnaire:**
[DFM_SUPPLIER_INQUIRY_91.md](DFM_SUPPLIER_INQUIRY_91.md) includes all sixteen
native KiCad finding coordinates, a copyable English feasibility request,
JLCPCB/PCBWay-specific clarifications, response log and controlled disclosure
gates. It has not been sent to any manufacturer.

## Precise non-production DFM questions (not sent)

1. For **the stated 2-layer board revision**, what stackup, copper weight,
   surface finish, plating and hole-tolerance options apply? Is the thermal
   **0.20 mm drill / 0.60 mm pad** configuration manufacturable at all
   twelve U1 locations? Distinguish nominal drill versus **finished hole**,
   annular ring after registration tolerance, solder wicking, and any
   thermal-pad via tenting, filling or plugging requirement.
2. Can the quoted production **and assembly** process explicitly accept
   two 0.65 mm J1 **NPTH locating holes**, with minimum measured
   **0.1944 mm NPTH-to-GND pad clearance**, including hole-position
   tolerance, soldermask and copper proximity? Do *not* substitute the
   unrelated NPTH-to-track design limit as the answer. If not, what exact
   geometry/process constraint must change?
3. Are the four J1 **plated** oval S1 mounting slots (0.60 mm width,
   1.40/1.70 mm lengths) supported with the connector's actual plated-stake
   dimensions, thickness, finished-slot tolerance and assembly process?
   Confirm which fabrication versus assembly operations apply.
4. What written exceptions, cost/lead-time assumptions, failure risks,
   yield or coupon/test requirements apply to each nonstandard feature?
   Can the manufacturer issue a revision/stackup/part-specific DFM report
   citing **each of the sixteen KiCad findings** without silently modifying
   source geometry or drill tables?
5. If *any* answer is negative or qualified, request the **required geometry
   envelope** for a redesign; do not request a fabrication order or treat a
   general capabilities page as written approval.

Before sharing source artifacts outside the project, a human must confirm the
recipient, disclosure scope and non-production purpose. No DFM inquiry or
manufacturer submission was sent as part of this record; never represent the
review-only PCB or its Gerbers as a manufacturing release.

## Sign-off gates and current owner/action

| Gate | Required evidence | Current disposition |
|---|---|---|
| Manufacturing process choice | Named supplier and approved stackup/copper/finish and written DFM answer explicitly covering D1 **and** D2 | **OPEN** — no supplier acceptance |
| BOM / footprint design choice | Exact orderable ESP32-WROOM-32 lifecycle decision and USB4105 variant or qualified substitutions; digest-pinned 3D, slots, NPTH, pinout and paste geometry | **OPEN** — no redesign or variant approval |
| Copper connectivity | Full routed native KiCad PCB with zero real unresolved connectivity breaks, all nets/layers correctly owned; RF keepout preserved | **OPEN** — opt-in board still 12 unconnected; default 37 |
| PCB/assembly electrical assurance | Independent ERC/DRC plus honest strict Proof Pack results; RF antenna/ground return, USB-C CC/shell/ESD/VBUS and LDO power/thermal validation | **OPEN** — ERC 0 but DRC 16, strict Proof 6/2 |
| Production handoff | Approved final BOM/stackup/DFM, controlled fabrication drill/Gerber package, independent qualified hardware sign-off | **BLOCKED** — no fabrication authorization |

**Next engineering action:** prepare a supplier-question packet keyed to the
measured D1/D2 findings; independently derive a geometry-correct redesign
variant *only if* the supplier does not explicitly accept the precise
features. Neither action should mutate the protected `main` branch, waive
constraints, start a fab order or mark Draft PR #119 / issue #91 complete.
