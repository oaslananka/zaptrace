# KiCad Round-trip Scorecard

The KiCad round-trip scorecard is a contract for measuring `KiCad -> ZapTrace -> KiCad` fidelity. It is intentionally split into categories so unsupported areas are visible:

| Category | Meaning |
|---|---|
| schematic | symbols, references, fields, schematic structure |
| net | net names and pin connectivity |
| footprint | footprint identity and placement-relevant metadata |
| constraint | board/fab/electrical constraints that survive import/export |
| board | board outline, layer count, placements, routing geometry where available |
| manufacturing | generated/exported manufacturing artifacts and evidence |

A case fails release-gate regression if its overall score or any configured category score falls below threshold. Unsupported features are allowed only when they are reported as explicit degradation entries with severity and explanation.
