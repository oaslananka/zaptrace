# Generated Board Acceptance

The first M7 generated-board acceptance test locks the ESP32 USB sensor pipeline end to end:

```text
BoardGenerationIntent
-> Design IR compilation
-> KiCad schematic project generation
-> KiCad PCB project generation
-> generated-project evidence bundle
-> human-review-required handoff
```

The acceptance test asserts that the generated project emits the expected KiCad and evidence files, keeps artifact hashes stable, preserves non-claims, writes a manufacturing export manifest, and produces a Review Studio handoff requiring qualified engineering review.

## Non-claims

Passing generated-board acceptance means the pipeline produced reviewable artifacts and evidence. It does not mean the board is electrically correct, fabrication-ready, DRC-clean, manufacturer-approved, certified, or production-ready.
