# Differential-pair length/skew evidence

ZapTrace emits a machine-readable report for differential-pair and length-match constraints. The report is based on routed trace segment lengths and is conservative: missing route evidence blocks supported high-speed profiles.

## Inputs

The report consumes:

```text
Net.constraints.length_match_group
Net.constraints.diff_pair_partner
RoutingIntent.differential_pair
RoutingIntent.length_match_mm
Design.routing.traces
```

## Report

`build_diffpair_length_report(design)` returns:

```text
schema_version
pair_count
violation_count
missing_route_count
blocked
entries[]
```

Each entry records:

```text
group_name
net_ids
net_names
lengths_mm
delta_mm
tolerance_mm
supported_profile
status
blocking
message
```

## Policy

- If a supported differential/high-speed profile exceeds its length-match tolerance, the entry is blocking.
- If a supported profile has no routed trace evidence, the entry is blocking.
- Unrouted or partial route data is treated as insufficient evidence, not a pass.

## Proof-pack sign-off

Proof manifests can attach `diffpair_length` evidence. It maps to autonomous sign-off as:

```text
passed=false -> diff-pair-length blocks autonomous-pass
passed=true  -> diff-pair-length passes
```
