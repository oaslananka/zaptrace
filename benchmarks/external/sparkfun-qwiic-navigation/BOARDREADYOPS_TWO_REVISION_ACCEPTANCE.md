# BoardReadyOps two-revision visual acceptance fixture

**Source baseline:** `oaslananka/zaptrace@884485d7395f611257a7b496355f731dfd746f15`,
SparkFun Qwiic Navigation benchmark, originally from SparkFun.

This separate test branch adds exactly one **synthetic front-silkscreen line**
to exercise a real KiCad PCB SVG change between two Git commits. It does not
change copper routing, the main branch, or customer files. It does **not**
represent a validated electrical, manufacturing, or fabrication change.

The `F.Cu` exported PCB view includes its front-silkscreen overlay. Compare
this branch's head against the exact baseline SHA and independently verify
that both SVGs are real native KiCad exports. Do not create inferred
component/finding coordinates from this visual change.

## Source-object anchor acceptance

A second publication of this isolated fixture validates that real KiCad 10
DRC JSON source-object UUIDs and millimeter positions reach the native SVG
Review Canvas. These markers identify referenced KiCad source objects,
**not the exact physical centers of rule violations**. Fabrication approval
is not part of this fixture. The previous SVG source files are unchanged.

## Controlled source-marker positive fixture (2026-10-20)

**Test-only intentional defect.** To exercise native KiCad UUID-to-visual-marker
mapping under the same zone-refill policy as the live CLI, a synthetic 0.25 mm
F.Cu track (net SW_Left) was added between SW2 pad 1 (SW_Left) and SW2
pad 2 (GND). This deliberately **shorts two different nets**. KiCad DRC
with zone refilling verifies shorting_items, tracks_crossing, and
solder_mask_bridge on F.Cu, with actual source-object UUID/positions.

This is a test fixture ONLY: **never manufacture, approve, fabricate, or
merge it to Zaptrace main**. No changes to the BoardReadyOps production
readiness decision are implied. Inspect real source-object positions rather
than asserting the exact short-circuit geometry from any anchor.
