# Issue #31 — KiCad schematic pin ↔ PCB pad/net crossprobe (source-only)

## Scope

Actual KiCad 10 native kicadxml schematic netlist exports from original and proposal are compared with native pcbnew pad inventories from original and proposed PCB copies, for MOVED FOOTPRINT REFERENCES ONLY. Exact pin and pad number plus named KiCad net must agree. Duplicate component/pin/pad identities or ambiguous net membership are refused. Existing native PCB DRC/ERC, PCB source/proposal SHA and project/custom-rule sidecar equality checks remain mandatory. PCB project/custom rule SHA also must match original/proposed schematic project rules for scoped consistency. The native KiCad XML netlist exports are SHA rechecked before and after the crossprobe.

Each pin maps to matched, mismatch (missing pin/pad or net-name conflict), or unverifiable (unnamed/unconnected net). Missing schematic inputs give not-checked; legacy PCB-only decision-state hash remains unchanged.

Scoped verification is NOT whole-project PCB-to-schematic parity, routed copper/physical connectivity proof, qualified symbol pin function/footprint identity, ERC/DRC waiver, signed approval or fabrication permission. All production approval flags remain false.

## Real local KiCad QA (MSI)

Ignored evidence: build/qa-034-pin-net/.

- MISMATCH_REVIEW.html: actual R1/R2 source board has pad IDs 1/2 and unnamed nets, while real schematic has P1/P2 pins with named nets: 16 mismatches across original and candidate, cross-project rule link unavailable; no approval.
- MATCHED_LINKED_REVIEW.html: separate disposable KiCad source PCB has pad IDs P1/P2 and nets /VCC_3V3, /I2C_SDA, /I2C_SCL; a verified two-footprint native ECO moves R1/R2. Original/proposed schematics use matching project/custom rule SHA. Native KiCad export verifies 8/8 scoped pin/net pairs, but whole-project parity remains false. KiCad DRC 0→0 violations, one unrouted connection remains 1→1.
- Real Chrome at 320/390/1440px: accessible keyboard Enter navigation to exact native pin/net detail, visible mismatch/scoped-match statuses, genuine KiCad graphics, zero horizontal overflow and JavaScript exceptions.
- Python regression checks named matches, invalid net, missing pins/pads, duplicate/ambiguous netlist entities, named-net gaps and missing project association.
- Legacy PCB-only state hash recheck passed unchanged: 954649b7a5d9dceecd1c2554c7e272faf4339679f937d1bea5f2f67bcf03cc5a.

## Outstanding

This is not the actual ESP32 board qualification. Actual ESP32 has 16 unresolved native DRC violations and missing routed copper/physical 3D STEP/supplier/assembly signoff. Full-project electrical parity, pin-function/footprint equivalence, authenticated signatures, independent hardware engineer UAT, live GUI connection and new immutable Debian/Ubuntu acceptance have not occurred.
