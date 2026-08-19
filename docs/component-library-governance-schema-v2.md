# Governed Component Schema v2

> **Evidence snapshot:** 2026-07-27
> **Machine-readable audit:** `docs/reports/component-library-audit-2026-07-27.json`

ZapTrace component schema v2 separates **record completeness** from **engineering trust**. A component can be syntactically complete and usable for bounded synthesis without being datasheet-verified, release-eligible, procurement-ready, or fabrication-safe.

## Strict record boundary

Every file under `data/library/**/*.yaml` is validated by `ComponentRecordV2` before a `ComponentSpec` is constructed. The schema uses Pydantic `extra="forbid"` at the top level and in structured nested sections. Unknown keys therefore fail with a field path instead of being silently discarded.

The only intentionally open extension map is `properties`. Domain-specific attributes belong there until they are promoted into a governed field. Pin entries, sourcing, compliance, provenance, review metadata, and electrical-limit sections reject undeclared keys.

Each record must declare:

```yaml
schema_version: '2.0'
trust_tier: heuristic
field_provenance:
  mpn: {...}
  datasheet: {...}
  pin_map: {...}
  package: {...}
  footprint: {...}
  electrical_limits: {...}
  lifecycle: {...}
  sourcing: {...}
```

The eight provenance entries are mandatory even when their confidence is low. Missing evidence must be represented honestly; it must not be replaced by an invented source hash, review, or manufacturer claim.

## Trust tiers

| Tier | Intended use | Evidence requirements | Release/fabrication behavior |
|---|---|---|---|
| `verified` | Exact, reviewed part-level engineering data | Authoritative manufacturer or authorized-distributor sources; source identity, version and SHA-256; extraction date/method; field reviewer/date; high confidence; release and fabrication approval scopes | Eligible when the complete schema and evidence contract pass |
| `curated` | Part-specific data reviewed from traceable sources but below verified strength | Part-specific source type; identity/version; extraction and review metadata; medium or high confidence; human review metadata | Eligible only when policy-scoped review covers both release and fabrication |
| `heuristic` | Bounded synthesis, search, family templates, migrated starter data | All critical fields have machine-readable provenance, commonly low-confidence internal manifests or family templates | Blocked by default; may be used for release only with explicit policy-scoped human approval |
| `placeholder` | Deliberate incomplete stand-in | Explicit provenance and placeholder classification | Never release or fabrication eligible, even with an approval object |

A populated datasheet URL, package string, footprint name, or pin map does not by itself increase the trust tier. Trust follows the evidence attached to each field.

## Human-review approval

A bounded override is represented explicitly:

```yaml
human_review:
  approval_id: COMPONENT-REVIEW-2026-001
  reviewed_by: engineer@example.com
  reviewed_at: 2026-07-27
  scopes: [release, fabrication]
  policy: component-trust-v1
```

The approval does not repair schema errors and cannot unlock a `placeholder`. It records who accepted the residual risk, under which policy, and for which actions.

## Physical package pin map

`pins` remains the logical pin/function surface consumed by synthesis and ERC. `package_pin_map` is a separate physical binding from package pin/pad ID to one declared logical pin key, for example `{"1": "GND", "2": "CSB", "7": "GND"}`. Repeated logical functions are allowed when a package exposes the same function on multiple physical pads.

Heuristic records may carry a `package_pin_map` as review-ready candidate evidence without changing trust tier. When present, every mapped logical name must exist in `pins`. A `verified` claim additionally requires a non-empty map that covers every declared logical pin. This prevents a logical synthesis model from being mistaken for exact package pinout evidence.

The component evidence gate compares the complete physical footprint identity against the package IDs from `package_pin_map`, not against the logical `pins` keys. Signal pads come from `FootprintProof.pin_map` keys and exposed/thermal pad identities come from `FootprintProof.thermal_pads`; their union must exactly match the physical package IDs. Thermal pads remain excluded from the signal-pin count while still being mandatory physical package evidence. The schema relationship and footprint proof therefore form two complementary checks: package pin IDs bind to declared logical functions, and those exact physical IDs bind to committed footprint pads.

When a governed library part is instantiated into a board, synthesis preserves `package_pin_map` on the runtime `Component`. KiCad PCB export resolves each physical pad through that map before assigning nets, so repeated package pads such as multiple grounds inherit the logical pin net. Netlist evidence and schematic-to-PCB parity expand the same mapping and fail closed on missing or partial physical bindings. Components without a package map retain the legacy identity mapping for backwards compatibility.

## Field provenance

Each critical-field record includes:

- `source_type`: manufacturer document/web, authorized distributor, internal manifest, family template, or manual entry;
- `source_locator` and `source_identity`;
- `source_sha256` where verified evidence requires exact document identity;
- `source_version`;
- extraction method and date;
- reviewer and review date;
- confidence (`high`, `medium`, or `low`).

`verified` claims fail closed when any critical field lacks the required authoritative identity, SHA-256, extraction metadata, review metadata, or high confidence. `curated` claims likewise reject family-template/internal-manifest evidence and low-confidence fields.

## Part-level evidence manifest

A `verified` component must also be bound by `config/component-evidence-manifest.json`. The manifest does not create or upgrade trust on its own; `ComponentRecordV2` remains the source of the trust-tier claim and human-review metadata. It binds each verified component to exact source artifacts and repository-owned footprint evidence without requiring manufacturer PDFs to be redistributed.

For every manifest entry, Quality CI requires:

- exact component ID, manufacturer, MPN, and `verified` tier agreement with the committed component record;
- bindings for all eight critical fields, with matching source type, locator, identity, version, and SHA-256;
- review metadata identical to the component `human_review` approval;
- lifecycle and sourcing evidence with a current `valid_until` horizon and no future-dated capture;
- a non-empty physical `package_pin_map` whose values reference declared logical `pins`;
- an available, digest-matching footprint-proof file whose signal `pin_map` keys plus `thermal_pads` cover the exact physical package pin IDs, satisfies the `FootprintProof` pin/pad validator, and passes the existing risky-package policy for scoped package families;
- for vendored/imported footprint proofs, a repository-local `source_path` whose current file SHA-256 matches `FootprintProof.source.source_sha256`; and
- exact footprint-proof `package_id` and `footprint_name` agreement with the component package and footprint.

The authoritative `field_provenance.footprint` artifact and the repository land-pattern source are intentionally separate evidence chains. The former identifies the manufacturer/distributor evidence used to justify the package/land-pattern claim; the latter proves which exact vendored/imported geometry file was validated. Their SHA-256 values are not required to be identical.

The committed manifest can be empty while the library contains no verified records. Once any record is upgraded to `verified`, a missing or invalid manifest entry is release-blocking. Adding a manifest entry for a missing, non-verified, or mismatched component is also an error.

Quality CI runs:

```bash
uv run python scripts/ci_component_evidence_gate.py \
  --manifest config/component-evidence-manifest.json \
  --strict \
  --output component-evidence-gate.json
```

The evidence gate does not invent reviewer identity, replace engineering review, or make a complete design fabrication-safe or release-ready.

## Repository migration snapshot

On 2026-07-27 all 504 committed component records were migrated deterministically to schema v2. The migration:

- classified all 504 records as `heuristic`;
- added eight low-confidence provenance entries per record without inventing hashes or reviews;
- corrected the malformed top-level `description"` key in `nrf24l01.yaml`;
- corrected the malformed pin-level `description"` key in `cc1101.yaml`;
- produced zero loader or schema errors;
- was idempotent: a second run changed zero files.

The audit reports 504 schema-valid records, 0 release-eligible records, 504 records requiring human review, and 19 repeated non-passive pin signatures. Repeated signatures are review leads, not automatic proof that records are wrong.

## CI and trust monotonicity

Quality CI runs:

```bash
uv run python scripts/ci_component_metadata_gate.py \
  --max-errors 0 \
  --max-warnings 0 \
  --trust-baseline config/component-trust-baseline.json \
  --strict \
  --output component-metadata-gate.json
```

The committed baseline prevents existing component IDs from disappearing or moving to a weaker tier. Stronger claims must first pass the schema-v2 evidence validators. New records are allowed only when their declared tier is valid.

Repository CI intentionally does **not** require every library record to be release-eligible, because heuristic records remain useful for bounded synthesis. A release or selected-part gate uses `--require-release-eligible`, and proof-pack evidence treats any `blocked_component_count > 0` as a release-blocking failure.

## Migration and validation commands

```bash
uv run python scripts/migrate_component_schema_v2.py --library-root data/library --write
uv run python scripts/migrate_component_schema_v2.py --library-root data/library --check
uv run pytest tests/test_component_schema.py tests/test_component_schema_migration.py -q
uv run pytest tests/test_library.py tests/test_library_governance.py tests/test_library_integrity.py -q
```

The expansion generator emits schema-v2 records directly so regeneration cannot silently reintroduce legacy records.

## Non-claims

Schema validation proves that a record follows the declared contract. It does not prove manufacturer approval, electrical correctness, footprint geometry, regulatory compliance, lifecycle status, availability, procurement authorization, or physical board operation. Qualified engineering review and physical validation remain mandatory for production use.
