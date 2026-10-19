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
