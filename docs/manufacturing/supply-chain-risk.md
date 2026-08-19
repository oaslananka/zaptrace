# Supply-chain and lifecycle risk evidence

ZapTrace models sourcing and lifecycle risk as evidence, not procurement approval. The risk report is deterministic when backed by fixture providers and records provider/cache provenance for every BOM line.

## Risk inputs

Each `BomLineRisk` records:

```text
ref
mpn
manufacturer
provider
distributor_part_number
stock
lifecycle
risk_score
risk_level
flags
alternates
cache
dnp
```

Lifecycle status is part of the serialized evidence and can be one of:

```text
active
nrnd
obsolete
unknown
```

## Risk flags

The scorer raises risk for:

- `provider-miss` / `unresolved-required-part`: required part not resolved by the provider.
- `unavailable`: provider stock is zero.
- `low-availability`: provider stock is non-zero but below the availability threshold.
- `obsolete`: lifecycle is obsolete.
- `nrnd`: lifecycle is not recommended for new designs.
- `lifecycle-unknown`: lifecycle data is missing.
- `single-source`: no alternates are known.
- `cache-stale`: provider cache is older than policy.
- `footprint-mismatch`: provider footprint conflicts with the design footprint.

DNP parts are recorded but do not block on sourcing availability.

## Proof-pack sign-off

`ProofManifest.bom_provenance[]` can attach a BOM risk report. If `blocked=true`, autonomous sign-off is blocked by:

```text
supply-chain-risk
```

This ensures lifecycle, single-source, low-availability, obsolete, and unresolved required parts remain visible in proof-pack evidence.
