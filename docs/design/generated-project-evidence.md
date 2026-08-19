# Generated Project Evidence Bundle

M7 generated-project evidence wraps the board generation pipeline into a single strict bundle.

The workflow writes:

- `board-generation-intent.json`
- `<design_name>.design_ir_compilation.json`
- `<design_name>.kicad_pro`
- `<design_name>.kicad_sch`
- `<design_name>.kicad_schematic_generation.json`
- `<design_name>.kicad_pcb`
- `<design_name>.kicad_pcb_generation.json`
- `exports/manifest.json`
- `review/handoff.json`
- `<design_name>.generated_project_evidence.json`

## Example

```python
from zaptrace.generation import (
    compile_intent_to_design_ir,
    generate_project_evidence_bundle,
    minimal_board_generation_intent_example,
    validate_board_generation_intent,
)

intent = validate_board_generation_intent(minimal_board_generation_intent_example())
compiled = compile_intent_to_design_ir(intent)
result = generate_project_evidence_bundle(intent, compiled, "generated/esp32_usb_sensor")
```

## Strict pass criteria

The aggregate evidence bundle passes only when:

- every required generated artifact exists;
- schematic generation report passes;
- PCB generation report passes;
- manufacturing export manifest is present;
- review handoff is present;
- generated artifacts retain explicit non-claims.

## Non-claims

The generated-project evidence bundle is review evidence only. It is not fabrication approval, not manufacturer approval, not certification, and not production readiness. KiCad oracle checks, proof-pack sign-off, manufacturing export validation, and qualified human engineering review remain required before fabrication decisions.
