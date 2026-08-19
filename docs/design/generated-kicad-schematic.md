# Generated KiCad Schematic Project

M7 schematic generation converts compiled `Design` IR into a reviewable KiCad schematic project.

The first generator emits:

- `<design_name>.kicad_pro`
- `<design_name>.kicad_sch`
- `<design_name>.kicad_schematic_generation.json`

The JSON report records deterministic file hashes, requirement trace count, provenance record count, family ID, and explicit non-claims.

## Example

```python
from zaptrace.generation import (
    compile_intent_to_design_ir,
    generate_kicad_schematic_project,
    minimal_board_generation_intent_example,
    validate_board_generation_intent,
)

intent = validate_board_generation_intent(minimal_board_generation_intent_example())
compiled = compile_intent_to_design_ir(intent)
generated = generate_kicad_schematic_project(compiled, "generated/esp32_usb_sensor")
```

## Non-claims

Generated schematic projects are for engineering review only. They are not fabrication-ready, not manufacturer-approved, not certified, and not production-ready. ERC/oracle evidence, proof-pack review, PCB generation, manufacturing export evidence, and qualified human review are still required before fabrication decisions.
