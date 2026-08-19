# Auto-repair proposal evidence

ZapTrace auto-repair must be auditable. A repair is not treated as invisible mutation: every selected change should have a proposal, alternatives, selected change, and verification result.

## Report

`build_repair_proposal_report(repair)` emits:

```text
schema_version
proposal_count
verified_count
silent_repair_count
human_review_required
blocked
proposals[]
remaining[]
```

Each proposal includes:

```text
problem
alternatives[]
selected_change
confidence
verification
human_review_required
```

## Policy

- A patch attached to a repair iteration becomes a repair proposal.
- A patch not attached to iteration evidence is counted as silent repair and blocks autonomous sign-off.
- Low-confidence default choices or remaining violations require human review.
- A proposal whose verification does not improve ERC evidence blocks autonomous sign-off.

## Proof-pack sign-off

Proof manifests can attach `repair_proposals` evidence:

```text
silent_repair_count > 0 or blocked=true -> repair-proposals blocks autonomous-pass
human_review_required=true              -> repair-proposals requires human review
passed=true with verified proposals      -> repair-proposals passes
```
