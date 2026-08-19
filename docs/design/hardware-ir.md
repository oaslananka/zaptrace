# Canonical Hardware IR v1

ZapTrace's Canonical Hardware IR is the shared contract between agents, parsers, importers, exporters, validators, proof packs, and future review surfaces. It is not a KiCad clone and it is not a transient API response shape. It is the loss-accounting model that every EDA adapter targets before ZapTrace makes routing, validation, manufacturing, or release decisions.

The versioned schema contract is `docs/schemas/hardware-ir-v1.json`. `zaptrace/core/models.py` remains the current runtime model for v0.x, while the IR contract defines the stable migration target and adapter boundary.

## IR boundaries

The IR owns normalized hardware intent and evidence. It must be deterministic, serializable, versioned, and suitable for proof-pack inclusion.

The IR does not own renderer-specific geometry caches, GUI layout preferences, process-local sessions, network credentials, manufacturer approval claims, or opaque third-party files unless they are represented as unsupported-data records with hashes and provenance.

## Top-level invariants

1. Every IR document declares `ir_version` and `design_id`.
2. IDs are stable within a document and references must resolve inside the same document unless they are explicitly external provenance links.
3. Units are metric unless a field states otherwise. Coordinates, lengths, drills, and clearances are millimetres; copper thickness is millimetres; impedance is ohms.
4. Importers must never silently discard source data. They must preserve, warn, degrade, or reject through `unsupported_data` records.
5. Exporters must declare which IR domains they consumed and which records were degraded or omitted.
6. Validation and signoff decisions belong in the evidence graph and must include tool versions, artifact hashes, and approval identifiers when available.
7. Older proof packs remain readable. Minor IR versions may add optional fields; breaking changes require a new major version.

## Domain model

### 1. Electrical graph

Owned data: components, symbols, pins, nets, buses, hierarchy, and power/ground domains.

Required invariants:

- `component.ref` values are unique.
- Each net node references a component and pin.
- Power domains explicitly list source nets and return nets.
- Bus members reference concrete nets.
- Hierarchy nodes preserve imported page/sheet/block ownership.

### 2. Physical graph

Owned data: footprints, pads, placements, board outline, layers, vias, traces, zones, and keepouts.

Required invariants:

- Placement component references resolve to electrical components.
- Trace, via, zone, and keepout nets resolve to electrical nets unless intentionally unconnected.
- Board outlines are closed polygons or importer-preserved unsupported records.
- Layer names are canonicalized but source layer names are retained in provenance when they differ.

### 3. Constraint graph

Owned data: net classes, impedance targets, differential pairs, length-match groups, max lengths, high-current regions, decoupling ownership, return-path hints, and keepout/region hints.

Minimum v1 support:

- Controlled-impedance target (`impedance_targets`).
- Differential pair membership and gap/length constraints (`differential_pairs`).
- Length-match groups (`length_match_groups`).
- Per-net max length (`max_lengths`).
- High-current nets or board regions (`high_current_regions`).
- Decoupling capacitor ownership (`decoupling_relations`).
- Keepout and region hints (`keepout_regions`, `return_path_hints`).

### 4. Manufacturing graph

Owned data: fab profile, stackup, drill rules, assembly variants, BOM population/DNP state, and export targets.

Required invariants:

- Stackup layers map to physical layers.
- Drill rules are measurable and unit-explicit.
- Assembly variants encode populated and DNP state independently from the base component list.
- Export targets declare format, version/profile, and generation intent.

### 5. Supply-chain graph

Owned data: MPNs, distributor IDs, lifecycle, stock, price, substitutes, and provenance.

Required invariants:

- Supply-chain records reference electrical components.
- Provider data includes source, fetched timestamp, and confidence/freshness metadata when available.
- Substitutes declare compatibility notes instead of implying automatic interchangeability.

### 6. Evidence graph

Owned data: validation results, oracle reports, proof-pack artifacts, artifact hashes, tool versions, agent decisions, and human approvals.

Required invariants:

- Every artifact reference includes a content hash when the artifact is available.
- Validation results include status, severity counts, and tool/version metadata.
- Agent decisions include actor, timestamp, input state hash, output state hash when applicable, and rationale summary.
- Human approvals include approval ID, approver or approval authority, timestamp, and scope.

## Current model mapping

| Current model field/class | IR domain | v1 mapping | Gap / migration step |
|---|---|---|---|
| `Design.meta` | document metadata | `design_id`, `source`, title/description fields | Add stable `source_fingerprint` for imports. |
| `Component` | electrical + supply-chain | `electrical.components[]`, `supply_chain.parts[]` | Split logical component, placed instance, and sourcing record. |
| `Pin`, `SymbolDef`, `SymbolPin` | electrical | component pins and symbols | Add explicit imported symbol library provenance. |
| `Net`, `NetNode`, `NetType` | electrical + constraints | `electrical.nets[]`, `constraints.net_classes[]` | Add buses, hierarchy, and power-domain objects. |
| `NetConstraints.impedance_target` | constraints | `impedance_targets[]` | Add layer reference, tolerance, and solved geometry. |
| `NetConstraints.length_match_group` | constraints | `length_match_groups[]` | Add target/tolerance and member role. |
| `NetConstraints.max_length_mm` | constraints | `max_lengths[]` | Add per-source provenance and severity policy. |
| `BoardConfig` | manufacturing + physical | legacy board dimensions and defaults | Migrate to `BoardDefinition` as canonical board object. |
| `BoardDefinition`, `LayerSpec`, `MountingHole` | physical + manufacturing | outline, layers, stackup, drill constraints | Add rigid/flex and material stack details later. |
| `FootprintDef`, `Pad`, `DrawCommand` | physical | footprints, pads, outlines | Add pad-to-pin mapping and source-footprint preservation. |
| `Component.position`, `Design.placement` | physical | placements | Resolve duplicate placement sources with explicit precedence. |
| `RouteResult`, `TraceSegment`, `Via` | physical | traces and vias | Replace tuple vias with object records and stable IDs. |
| `CopperPourArea`, `ThermalRelief` | physical + constraints | zones, return path and thermal hints | Add zone priority/isolation and fabrication intent. |
| `BoardConstraints` | manufacturing + constraints | drill rules, clearance rules, default widths | Link constraints to fab profile version. |
| `DRCResult`, `DRCViolation` | evidence | validation_results | Add ERC/proof/oracle results under one evidence envelope. |
| `Lifecycle`, `mpn`, `lcsc_id`, `stock`, `basic_part` | supply-chain | parts, distributor_ids, lifecycle | Add price, alternates, fetched timestamp, and provider provenance. |
| proof-pack manifests | evidence | proof_pack_artifacts, artifact_hashes | Reference IR state hash and domain coverage. |

## Unsupported-data behavior

Adapters must choose one behavior per unsupported construct:

| Behavior | Meaning | Required record fields |
|---|---|---|
| `preserve` | Raw data is kept for round-trip but not interpreted. | source path/location, format, raw payload hash. |
| `warn` | Data is interpreted enough to continue but requires review. | severity, message, affected references. |
| `degrade` | Data is approximated in the IR. | original semantics, approximation, risk note. |
| `reject` | Import/export must stop. | blocking reason, source location, remediation hint. |

Silent loss is never valid. Unsupported records are part of the evidence graph when they affect validation, export, or signoff.

## Import/export round-trip requirements

Every adapter must report a machine-readable fidelity score with these dimensions:

- schematic fidelity;
- footprint/pad fidelity;
- net connectivity fidelity;
- placement/routing fidelity;
- constraint fidelity;
- manufacturing/export fidelity;
- unsupported-feature/degradation report.

For KiCad v1 round trips, the target path is:

`ZapTrace Design -> Canonical Hardware IR -> KiCad export -> KiCad import -> Canonical Hardware IR -> semantic diff`.

Adapters should compare canonical IR objects, not raw file text, except for preserved unsupported payload hashes.

## Schema ownership and compatibility

- Schema owner: `zaptrace/core` architecture and EDA interop maintainers.
- Canonical schema path: `docs/schemas/hardware-ir-v1.json`.
- Major version changes may remove or rename fields.
- Minor version changes may add optional fields and new enum values only when unknown values can be preserved.
- Patch version changes clarify descriptions or tighten non-breaking validation.
- Proof packs must record the IR version and state hash they validated.

## Migration plan from current `Design`

1. Add pure conversion functions: `Design -> HardwareIR` and `HardwareIR -> Design` for supported fields.
2. Move tuple-based vias into object records with IDs.
3. Promote `BoardDefinition` over `BoardConfig` for physical/manufacturing data.
4. Add unsupported-data collection to importers.
5. Store validation, proof-pack, and approval evidence in the evidence graph.
6. Add adapter scorecards for KiCad round-trip fixtures.
