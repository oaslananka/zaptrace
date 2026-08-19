# Board Generation Intent Schema

`BoardGenerationIntent` is the M7 contract between an agent request and the future generated-board pipeline.

It is intentionally narrower than natural language. The agent must express a supported board family, traceable requirements, power and interface constraints, artifact policy, evidence expectations, and explicit non-claims before any KiCad project is generated.

## Scope

The schema supports reviewable generated board projects for built-in benchmark board families. It does not claim arbitrary electronic design, fabrication readiness, manufacturer approval, certification, or production readiness.

## Minimal example

```python
from zaptrace.generation.intent import minimal_board_generation_intent_example, validate_board_generation_intent

intent = validate_board_generation_intent(minimal_board_generation_intent_example())
```

## Key guarantees

- `family_id` must match a built-in board family.
- At least one release-blocking requirement is required.
- `target_output_dir` must be a safe relative path.
- Fabrication-ready claims are blocked by policy.
- Non-claims must include `not fabrication-ready`.
- KiCad project generation requires KiCad project presence evidence.

## Non-claims

A valid board generation intent is only a pre-generation contract. It does not mean the generated board is electrically correct, fabricated, reviewed, manufacturer-approved, certified, or production-ready.
