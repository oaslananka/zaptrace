# Layout quality and placement evidence

ZapTrace exposes two related, machine-readable layout contracts:

- `build_placement_scorecard(design)` scores placement-only observations.
- `build_layout_quality_report(design)` combines placement, routing, SI/PI, current-density, differential-pair, thermal, mechanical, and design-for-test evidence under one versioned policy.

Neither report is fabrication approval or solver-grade sign-off. Missing physical evidence remains explicit and requires human review.

## Placement scorecard

The placement scorecard does not move components. It scores an existing placement and explains what needs review or repair.

`build_placement_scorecard(design)` reports:

```text
block_grouping
connector_constraints
decoupling_proximity
keepouts
thermal_spacing
placement_coverage
```

The scorecard includes:

```text
schema_version
overall_score
status
min_autonomous_score
min_review_score
group_count
component_count
placed_component_count
section_scores[]
observations[]
blocking_observation_count
warning_count
human_review_required
blocked
```

Placement policy:

- `blocked=true` when the score is below `min_autonomous_score` or a blocking observation exists.
- `human_review_required=true` when warnings exist or the score is below `min_review_score` but not blocked.
- Connector edge constraints, decoupling distance, keepout/near constraints, and thermal spacing are scored independently.

## Unified layout-quality policy

`builtin_layout_quality_policy()` returns a deterministic policy with `schema_version`, `policy_version`, canonical SHA-256 identity, explicit evidence sources, and non-claims. The policy covers eight required rule families:

```text
decoupling-loop-area
power-path-current-density
ground-return-split-plane
high-speed-differential
analog-digital-separation
thermal-placement-copper
connector-mechanical
test-debug-access
```

`build_layout_quality_report(design)` binds the policy digest to the canonical design-state hash. The externally consumable schema is committed at `schemas/layout-quality-report-v1.schema.json`; CI compares it byte-for-byte with the Pydantic contract. The report produces:

```text
schema_version
design_name
design_state_hash
policy_version
policy_sha256
overall_score
status
blocked
human_review_required
sections[]
findings[]
constraints[]
repairs[]
non_claims[]
```

Each finding records a stable rule ID, rule family, normalized status, subject, source analysis, metrics, and whether a bounded repair is available.

## Outcome contract

| Status | Meaning |
|---|---|
| `pass` | The modeled rules have no findings. |
| `warning` | Nonblocking heuristic risk is visible; downstream policy may still require review. |
| `human-review-required` | Physical evidence or qualified judgment is missing, but no modeled blocking violation exists. |
| `blocking` | A release-blocking modeled violation exists. |

Missing placement or routed-trace evidence is never represented as a pass. It produces `human-review-required` evidence. High-current trace-width violations and supported differential-pair failures are blocking.

## Bounded repair evidence

`apply_bounded_layout_repairs(design)` deep-copies the design and may apply three deterministic, limited transformations:

1. Move one distant decoupling capacitor near its nearest active IC.
2. Align one connector with an explicitly required board edge.
3. Widen one failing high-current trace to its computed minimum width.

The original design is not mutated. Every repair records the subject, rationale, before/after values, section scores, and score delta. A transformation that does not measurably improve its target family is not evidence of improvement.

## Proof Pack and Review Studio

Synthesis proof generation writes `layout-quality.json`, hashes it as a proof artifact, and stores normalized `layout_quality` evidence in the proof manifest. Autonomous sign-off maps it as follows:

```text
blocked=true                        -> layout-quality blocks autonomous-pass
human_review_required=true         -> layout-quality requires human review
no blocking/review-required finding -> layout-quality passes; warnings remain visible
```

Review Studio exposes a `layout_quality` panel containing policy identity, design-state hash, aggregate score, normalized findings, and bounded repair deltas. The panel is evidence for review; it does not authorize fabrication by itself.

## Regression corpus

The repository includes known-good and known-bad physical-layout fixtures plus CI coverage for five representative synthesis families. The corpus verifies all eight rule families and proves measurable improvement for decoupling placement, connector edge alignment, and high-current routing width without claiming physical manufacturing success.
