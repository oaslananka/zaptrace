# Current density and copper width evidence

ZapTrace emits a machine-readable current-density report for high-current nets and power rails. The report compares routed trace widths against explicit net constraints or IPC-2221 trace-width estimates.

## Inputs

The report consumes:

```text
Net.type == power
Net.constraints.is_high_current
Net.constraints.min_trace_width_mm
rail-current-budget total load current
Design.routing.traces[].width
```

## Report

`build_current_density_report(design)` returns:

```text
schema_version
high_current_net_count
trace_count
violation_count
missing_route_count
blocked
human_review_required
traces[]
missing_route_nets[]
assumptions[]
```

Each trace entry records net id/name, layer, actual width, current, required width, margin, status, and message.

## Policy

- Trace width below the required current-carrying width blocks autonomous sign-off.
- High-current nets without routed trace evidence require human review.
- Rail currents come from rail-current-budget evidence when available.
- High-current non-rail nets without richer current metadata use a conservative 1A default and record that assumption.

## Proof-pack sign-off

Proof manifests can attach `current_density` evidence:

```text
blocked=true                    -> current-density blocks autonomous-pass
human_review_required=true      -> current-density requires human review
passed=true with complete data  -> current-density passes
```
