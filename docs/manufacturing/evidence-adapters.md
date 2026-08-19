# Manufacturing Evidence Adapters

Manufacturing evidence adapters turn generated fabrication files into proof-pack evidence. The directory adapter scans an output directory and records:

- Gerber files;
- Excellon drill files;
- BOM CSV;
- pick-and-place CSV;
- manufacturing manifest JSON;
- manufacturer-aware DFM readiness JSON;
- ZIP bundles;
- optional ODB++ and IPC-2581 attachments when present.

Each artifact record includes a relative path, kind, file size, and SHA-256 hash. Gerber and Excellon files receive smoke validation so CI can fail early when an exporter emits malformed or incomplete files.

## Versioned fabrication and assembly profiles

A `FabProfile` is a versioned capability contract. Its deterministic SHA-256 identity covers the manufacturer, source/freshness metadata, board dimensions, trace and spacing limits, copper options, drill and via limits, annular ring, solder-mask and silkscreen limits, special fabrication capabilities, and assembly limits.

Assembly fields cover minimum component and BGA pitch, optional stencil aperture and component-height limits, double-sided assembly support, and through-hole assembly support. Built-in profiles declare published values and leave unpublished numeric limits null rather than inventing them. Profile metadata remains evidence captured from published capability information; it is not a live quotation or manufacturer approval.

## DFM readiness report

`generate_manufacturing_bundle(...)` always writes `<design>-dfm-readiness.json` and includes it in the ZIP package. When a profile is selected, the report contains:

- profile name, manufacturer, version, verification date, and profile SHA-256;
- the classified DFM and assembly findings;
- hashes of the pre-archive manufacturing artifacts;
- explicit human-review reasons and approved skips;
- a top-level readiness status and autonomous-release blocking flag;
- non-claims that preserve the distinction between evidence and manufacturer approval.

The status vocabulary is intentionally small:

| Status | Meaning |
|---|---|
| `hard-fail` | A profile or assembly limit is violated and autonomous release is blocked. |
| `warning` | No blocking violation exists, but the finding remains visible to reviewers. |
| `approved-skip` | No manufacturer profile was run; an authenticated external approval ID and rationale explicitly accepted the skip. |
| `human-review-required` | A profile is missing, stale, or required geometry/assembly evidence is unavailable. Autonomous release is blocked until reviewed. |
| `pass` | Modeled fabrication and assembly checks passed for the selected profile. |

A profile-less export does not silently pass. It produces `human-review-required` unless both an approved skip rationale and approval identity are supplied.

## Proof-pack integration

`ManufacturingEvidenceBundle` schema `2.1` preserves the profile version and digest, readiness status, readiness-report digest, validation results, and every collected artifact hash. `ManufacturingProofEvidence.from_evidence_bundle(...)` copies that identity into proof-pack metadata.

Synthesis proof generation remains backward compatible: manufacturing evidence is attached when a fabrication profile or approved profile skip is explicitly requested. The default proof path does not silently select a manufacturer. Profile-bound proof packs include the readiness report as a hashed manifest artifact.

CI exercises the same readiness gate with three generated board families: an ESP32 I2C sensor, an RP2040 USB HID peripheral, and an STM32 RS-485 node. These fixtures verify report generation and evidence shape; they do not claim physical validation or manufacturer acceptance.

## Current limitations

- Gerber/Excellon smoke validation checks basic syntax markers only.
- Assembly checks depend on modeled footprint geometry, placement, side, height, and pad pitch. Missing inputs become `human-review-required`, not pass.
- Silkscreen checks only evaluate modeled stroke widths; full text-to-pad and panelization analysis remains outside this adapter.
- ODB++ and IPC-2581 records can be attached to proof packs, but full external parsers remain provider-specific.
- The report is not manufacturer approval, a fabrication quotation, electrical-safety certification, or evidence that a board has been physically assembled successfully.

### KiCad review exports

`*-odb.zip` is classified as `odbpp` before the generic ZIP/bundle rule, and `.glb` is classified as `mechanical_review`. This lets retained KiCad 10 review-export artifacts flow through the same manufacturing evidence inventory and proof metadata used by Review Studio.

The classification is intentionally conservative:

- an attached ODB++ archive yields `odbpp_status=attached`; archive safety/structure is still established by the KiCad jobset oracle before retention;
- an attached GLB yields `mechanical_review_status=attached-degraded`; attachment does not establish model resolution, enclosure fit, component height, or assembly clearance;
- retained ODB++ and GLB SHA-256 values are run-bound integrity evidence; cross-run comparison uses the oracle structural inventory/shape digests and records `byte_determinism=not-guaranteed`;
- missing model references and unverified model resolution remain visible limitations and cannot be converted into a complete mechanical-review claim.

The CI bundle is `kicad-review-exports/`. Its root and per-family `index.html` files link only to retained relative artifacts; `review-index.json` records the machine-readable evidence and limitations.
