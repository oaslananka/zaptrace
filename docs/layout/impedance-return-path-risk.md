# Impedance and return-path risk evidence

ZapTrace emits explicit impedance assumptions and return-path diagnostics as machine-readable evidence. This is a heuristic pre-check, not a field solver and not fabricator stackup approval.

## Inputs

The report consumes:

```text
Net.constraints.impedance_target
Net.constraints.return_path_net
Net.constraints.is_high_current
```

## Report

`build_impedance_return_path_report(design)` returns assumption counts, diagnostic counts, human-review status, blocking status, assumptions, diagnostics, and limitations.

Each impedance assumption records net id/name, target impedance, assumed Er, copper thickness, dielectric height, and method.

## Policy

- Explicit impedance assumptions are recorded for controlled-impedance nets.
- Nets that need a return path but have no `return_path_net` become human-review-required.
- Future plane-geometry gates can mark actual discontinuities as `blocked=true`.

## Proof-pack sign-off

```text
human_review_required=true and blocked=false -> impedance-return-path requires human review
blocked=true                                -> impedance-return-path blocks autonomous-pass
passed=true with no diagnostics             -> impedance-return-path passes
```
