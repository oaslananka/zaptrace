# Known-failure mutation corpus

ZapTrace benchmarks include a known-failure mutation corpus. The corpus proves that checks catch realistic negative cases instead of only proving that clean examples pass.

## Mutation classes

The initial corpus implements three mutation classes:

```text
remove-decoupling
narrow-high-current-trace
remove-return-path
```

## API

```python
from zaptrace.benchmark.mutations import run_known_failure_mutation_corpus

report = run_known_failure_mutation_corpus(design)
```

The report includes:

```text
schema_version
mutation_count
caught_count
missed_count
passed
results[]
```

Each result records:

```text
mutation_id
mutation_class
expected_detector
caught
detail
```

## Expected detectors

```text
remove-decoupling          -> sipi-risk.decoupling
narrow-high-current-trace  -> current-density.violation
remove-return-path         -> sipi-risk.return-path
```

## Release policy

Known-failure benchmark reports should fail when `missed_count > 0`. A missed known-failure means the engine produced or accepted a realistic bad design without the expected evidence gate firing.

## Non-claims

Mutation corpus pass is regression evidence only. It does not replace full ERC, DRC, KiCad oracle checks, manufacturing export checks, or human review.
