# Rail current budget evidence

ZapTrace emits a machine-readable rail current budget report for power rails. The report is deterministic and conservative: missing source/load current metadata requires human review, and rail overload blocks autonomous sign-off.

## Inputs

The report consumes:

```text
regulator output pins
component.current_rating
component.properties.current_a
component.properties.operating_current_a
component.properties.load_current_a
component.value strings such as 50mA or 0.2A
power rail net membership
```

## Report

`build_rail_current_budget_report(design)` returns:

```text
schema_version
rail_count
failure_count
missing_metadata_count
blocked
human_review_required
rails[]
```

Each rail includes source refs, source current rating, loads, missing-current refs, total load current, current margin, and status.

## Policy

- Total load above source current rating blocks autonomous sign-off.
- Missing source or load current metadata requires human review.
- Passing rails still report source, load, total current, and margin.

## Proof-pack sign-off

Proof manifests can attach `rail_current_budget` evidence:

```text
blocked=true                   -> rail-current-budget blocks autonomous-pass
human_review_required=true      -> rail-current-budget requires human review
passed=true with complete data  -> rail-current-budget passes
```
