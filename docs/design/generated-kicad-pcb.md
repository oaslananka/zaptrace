# Generated KiCad PCB Project

M7 PCB generation converts compiled `Design` IR into a reviewable KiCad PCB artifact.

The first generator emits:

- `<design_name>.kicad_pcb`
- `<design_name>.kicad_pcb_generation.json`

The JSON report records deterministic file hashes, board dimensions, layer count, net/component counts, placement/routing starter evidence, requirement trace count, provenance record count, and explicit non-claims.

## Example

```python
from zaptrace.generation import (
    compile_intent_to_design_ir,
    generate_kicad_pcb_project,
    minimal_board_generation_intent_example,
    validate_board_generation_intent,
)

intent = validate_board_generation_intent(minimal_board_generation_intent_example())
compiled = compile_intent_to_design_ir(intent)
generated = generate_kicad_pcb_project(compiled, "generated/esp32_usb_sensor")
```

## Non-claims

Generated PCB projects are for engineering review only. They are not fabrication-ready, not manufacturer-approved, not certified, not production-ready, and not guaranteed DRC-clean. KiCad oracle checks, proof-pack evidence, manufacturing export evidence, and qualified human review are still required before fabrication decisions.
