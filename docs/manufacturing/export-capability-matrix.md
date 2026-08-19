# Manufacturing Export Capability Matrix

ZapTrace records manufacturing export evidence even when a format is produced by an external backend. The goal is revision-bound, reproducible proof-pack evidence, not a claim that every manufacturing format has a native exporter or byte-deterministic output.

| Format | Backend | Support | Proof-pack kind | Release impact | Notes |
|---|---|---|---|---|---|
| Gerber | ZapTrace | supported | `gerber` | blocking | Native RS-274X exporter |
| Drill / Excellon | ZapTrace | supported | `excellon` | blocking | Native drill exporter |
| BOM | ZapTrace | supported | `bom` | blocking | Native CSV/JSON BOM exporters |
| Pick-and-place | ZapTrace | supported | `pick_and_place` | blocking | Native centroid CSV from placement data |
| ODB++ | KiCad 10 CLI / external | external evidence, CI-validated | `odbpp` | blocking when required | Retain safe ZIP structure, run-bound SHA-256, path/size structural inventory digest, exact source/tool identity, and warnings |
| IPC-2581 | KiCad CLI / external | external evidence | `ipc2581` | blocking when required | Attach command/tool/hash evidence; excluded from the bounded review-export oracle |
| GLB 3D review | KiCad 10 CLI / external | external review evidence, CI-validated | `mechanical_review` | non-blocking review evidence | Retain run-bound SHA-256, structural-shape digest, and explicit model-coverage limitations; never infer mechanical completeness |

Unsupported variants, layers, stackups, or backends must fail with actionable errors. They must never silently produce partial manufacturing output.

Proof packs can include manufacturing export logs with:

- backend and tool version;
- command/config used to generate the files;
- output paths, sizes, and SHA-256 hashes;
- warnings;
- unsupported paths or variants;
- release-blocking status.

## KiCad 10 review-export oracle scope

The KiCad oracle keeps this bounded scope instead of treating every KiCad exporter as equivalent release evidence:

| Export | Oracle status | Evidence / limitation |
|---|---|---|
| ODB++ ZIP | Supported | Valid ZIP, safe member paths, required ODB++ structure, run-bound archive hash, path/size structural inventory digest, exact project/tool identity. |
| GLB | Supported for review | Valid GLB v2 structure, run-bound file hash, and structural-shape digest. Mechanical coverage remains degraded unless independent model-resolution/fit evidence exists; GLB generation alone never marks coverage complete. |
| Gerber + drill | Supported by the atomic jobset oracle | Existing fabrication evidence remains independently hashed and checked. |
| IPC-2581 | Existing external-evidence path; excluded from this bounded review-export oracle | May be attached through the manufacturing evidence adapter, but this CI path does not manufacture an IPC-2581 claim. |
| STEP / 3D PDF | KiCad CLI capability exists; excluded from this bounded CI path | A successful export would not by itself resolve component-model availability or mechanical-fit review, so it is not silently promoted to verified evidence here. |

The retained `kicad-review-exports/` bundle contains relative links, exact hashes, source/tool identity, ODB++ inventory evidence, GLB structure evidence, and per-project limitations. It is review/handoff evidence, not manufacturer acceptance.

### Rerun comparison semantics

KiCad 10.0.5 characterization on the same source project showed that ODB++ ZIP and GLB byte hashes can change across fresh reruns even when the review structure remains equivalent. The oracle therefore records the actual guarantee instead of treating full-file hashes as a deterministic golden:

- `sha256` is run-bound integrity evidence for the retained artifact;
- ODB++ `structural_inventory_sha256` hashes the sorted member path and uncompressed-size inventory, which is also retained as `member_inventory`;
- GLB `structural_shape_sha256` hashes bounded node, mesh, material, accessor, buffer-view, and buffer counts;
- both exporters record `byte_determinism=not-guaranteed`.

The structural digests are a bounded rerun-comparison surface, not a semantic-equivalence proof. CI still validates archive safety, required ODB++ members, GLB structure, exact source identity, tool version, model-coverage limitations, and the run-bound file hashes.
