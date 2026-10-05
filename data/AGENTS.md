# AGENTS.md

## Scope

This file applies to `data/**` and supplements the repository-root `AGENTS.md`.

Files under `data/library/**/*.yaml` are governed engineering records, not ordinary fixture data. Read `docs/component-library-governance-schema-v2.md` and the relevant library-governance tests before modifying component records, generators, provenance, trust tiers, or evidence bindings.

## Schema boundary

Every committed component YAML must conform to component schema v2.

- Unknown structural keys are rejected.
- Domain-specific extension attributes belong in the documented `properties` map until promoted into the governed schema.
- Critical fields require machine-readable provenance.
- Missing evidence must be represented honestly as missing/low-confidence evidence, not replaced with invented metadata.

Do not bypass the schema loader or validation path to make a record load.

## Evidence and provenance

Never invent or infer authoritative evidence merely because a value appears plausible.

Do not fabricate:

- manufacturer or authorized-distributor claims;
- MPNs or source identities;
- datasheet identities or hashes;
- pin mappings or package mappings;
- footprint provenance;
- voltage/current/electrical limits;
- lifecycle or sourcing status;
- reviewer identity or review dates;
- source-capture hashes;
- approval IDs or approval scopes.

When evidence is unavailable, preserve the honest lower-confidence state.

## Trust tiers

The governed trust tiers are:

- `verified` — exact reviewed part-level engineering data with authoritative evidence;
- `curated` — part-specific traceable reviewed data below verified strength;
- `heuristic` — bounded synthesis/search/template data with explicit provenance;
- `placeholder` — deliberately incomplete stand-in.

A populated field does not raise its trust level. Trust follows the evidence contract.

Do not promote a component to `verified` or `curated` simply because values look correct or tests pass. Stronger claims require the evidence, review metadata, confidence, and policy scopes defined by schema v2.

A `placeholder` is never release/fabrication eligible. Do not add an approval object to bypass that restriction.

## Verified-component contract

A component declared `verified` must have a valid matching entry in `config/component-evidence-manifest.json`.

The evidence entry must remain bound to the exact component/source/footprint identities required by repository policy. Do not:

- create placeholder evidence merely to satisfy CI;
- copy evidence from a different component or source identity;
- reuse stale hashes after source bytes change;
- weaken exact package/footprint/pin-map agreement;
- treat the evidence manifest as authority to upgrade the component record by itself.

The component record owns the trust claim; the evidence manifest binds that claim to repository-verifiable evidence.

## Physical pin and footprint mappings

Keep logical and physical identities distinct.

- `pins` is the logical pin/function surface.
- `package_pin_map` binds physical package pin/pad IDs to declared logical pins.
- Repeated logical functions are valid when a package exposes them on multiple physical pads.
- For verified claims, the physical mapping and footprint proof must satisfy the complete repository contract.

Do not collapse package pin IDs into logical names in a way that loses repeated-pad information or breaks schematic-to-PCB/netlist parity.

## Trust monotonicity

The committed baseline in `config/component-trust-baseline.json` prevents silent component disappearance or trust downgrade, while stronger claims must pass the evidence validators.

Do not modify the baseline as a shortcut around a failing component record. A baseline update must reflect an intentional, reviewable change in governed state.

## Required component gates

For governed component changes, run the metadata gate:

```bash
uv run python scripts/ci_component_metadata_gate.py \
  --max-errors 0 \
  --max-warnings 0 \
  --trust-baseline config/component-trust-baseline.json \
  --strict \
  --output component-metadata-gate.json
```

When verified-component evidence is present or affected, also run:

```bash
uv run python scripts/ci_component_evidence_gate.py \
  --manifest config/component-evidence-manifest.json \
  --strict \
  --output component-evidence-gate.json
```

Run focused library/schema tests appropriate to the change. The canonical migration and validation examples are maintained in `docs/component-library-governance-schema-v2.md`.

## Generated/migrated records

Use repository-owned generators and migrations rather than bulk hand-editing governed records.

After generation or migration:

- validate schema v2;
- verify the operation is deterministic/idempotent when that is part of the generator contract;
- inspect trust/provenance changes explicitly;
- do not let regeneration silently reintroduce legacy schema or stronger unsupported claims.

## Non-claims

Schema validity and component-level evidence do not prove complete-board electrical correctness, fabrication readiness, manufacturer approval, regulatory compliance, lifecycle availability, procurement authorization, or physical operation.

Do not convert component-level evidence into a broader product or board-level claim.

## Definition of done

A component-data change is complete only when the relevant schema, provenance, trust, evidence, and focused library tests pass and the resulting trust declarations accurately match the evidence actually present.
