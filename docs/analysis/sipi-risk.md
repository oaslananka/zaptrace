# SI/PI risk proof-pack evidence

ZapTrace emits an aggregate SI/PI risk report for proof packs. The report summarizes high-speed/RF support, impedance assumptions, return-path diagnostics, and decoupling coverage. It is heuristic evidence, not solver-grade SI/PI sign-off.

## Inputs

The report consumes:

```text
high-speed/RF net names and net types
Net.constraints.impedance_target
Net.constraints.length_match_group
Net.constraints.return_path_net
power rails and capacitor/decoupling evidence
```

## Report

`build_sipi_risk_report(design)` returns:

```text
schema_version
high_speed_net_count
impedance_assumption_count
return_path_diagnostic_count
decoupling_issue_count
unsupported_high_speed_count
blocked
human_review_required
findings[]
non_claims[]
```

## Policy

- High-speed/RF nets without explicit impedance target evidence require human review.
- Missing return-path evidence from controlled/high-speed nets requires human review.
- Power rails without decoupling evidence require human review.
- Blocking SI/PI findings can be attached as proof-pack `sipi_risk.blocked=true`.

## Proof-pack sign-off

Proof manifests can attach `sipi_risk` evidence:

```text
blocked=true                    -> sipi-risk blocks autonomous-pass
human_review_required=true      -> sipi-risk requires human review
passed=true with complete data  -> sipi-risk passes
```
