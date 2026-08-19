# Intent to Design IR Compiler

The first M7 compiler converts a validated `BoardGenerationIntent` into the existing ZapTrace `Design` IR.

This first compiler is deliberately bounded. It supports `esp32_usb_sensor` and maps that family to the existing `esp32_i2c_sensor` synthesis template. The compiler records this as deterministic template selection, not from-scratch circuit synthesis.

## Public API

```python
from zaptrace.generation import compile_intent_to_design_ir, minimal_board_generation_intent_example, validate_board_generation_intent

intent = validate_board_generation_intent(minimal_board_generation_intent_example())
compiled = compile_intent_to_design_ir(intent)
design = compiled.design
report = compiled.report
```

## What the compiler adds to Design IR

- generated design metadata and family tags;
- voltage-domain constraints from the intent power section;
- routing constraints from interface nets;
- manufacturing intent marked as `reviewable-generated-board`;
- provenance record with a stable hash of the board generation intent;
- machine-readable compilation report with requirement traces and non-claims.

## Non-claims

The compiler does not create a production-ready PCB. It selects and annotates a bounded template to produce a reviewable Design IR. KiCad generation, proof-pack evidence, ERC/DRC/parity checks, and qualified human review are still required before any fabrication decision.
