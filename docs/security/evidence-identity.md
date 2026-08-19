# Evidence Source Identity

ZapTrace release-critical reports carry a shared source and toolchain identity. This identity answers **which exact repository state and validation environment produced the evidence**. It is separate from the design release identity documented in [Complete Release Evidence](release-evidence.md), which answers **which exact design, ERC/DRC state, component coverage, and approval decision an export represents**.

Both identities are required for an auditable release decision:

- source identity binds evidence to code, lock state, ref, dirty state, inputs, and tools;
- design identity binds a release export to the verified hardware-design state and approval record.

## Identity schema

`zaptrace.evidence.identity.EvidenceIdentity` records:

| Field | Purpose |
|---|---|
| `schema_version` | Version of the shared source-identity contract. |
| `mode` | `snapshot` or `release`. |
| `package_version` | Authoritative version from `pyproject.toml`. |
| `source_commit` | Full 40-character Git commit. |
| `source_ref` | Branch, pull-request, schedule, or tag ref. |
| `dirty` | Whether tracked or untracked workspace changes existed. |
| `dirty_override_id` | Explicit policy approval when a dirty release is exceptionally allowed. |
| `lock_sha256` | SHA-256 of the exact committed `uv.lock`. |
| `source_inputs` | Repository-relative files declared relevant by the producer. |
| `source_inputs_sha256` | Stable hash of source-input paths and exact bytes. |
| `generated_at` | Visible ISO-8601 generation timestamp. |
| `toolchain` | Relevant Python, Rust, KiCad, platform, or other tool identities. |
| `identity_sha256` | Canonical hash of all identity fields except `generated_at` and the hash itself. |

The generation timestamp is intentionally excluded from `identity_sha256`. Repeating the same validation later produces the same deterministic identity, while any code, ref, version, lock, source-input, dirty-policy, mode, or toolchain change produces a different identity.

## Snapshot and release modes

### Snapshot

Pull requests, branch pushes, scheduled runs, local validation, benchmarks, proof packs, generated-board gates, manufacturing evidence, and validation-environment reports use `snapshot` mode. Snapshot evidence is exact and auditable, but it is not a tagged release and cannot be represented as one.

### Release

Tagged release evidence uses `release` mode and fails closed unless:

1. `source_ref` is exactly `refs/tags/v<package_version>`;
2. `source_commit` is a full Git commit;
3. the workspace is clean, or a non-empty `dirty_override_id` records an explicit approved exception;
4. lock, source inputs, and toolchain identity are present.

The release workflow publishes `tagged-release-evidence.json` and includes it in the GitHub Release assets and checksum manifest.

## CI evidence artifacts

Current evidence is generated for the exact workflow revision and retained as CI artifacts:

| Artifact | Contents |
|---|---|
| `snapshot-gate-summary` | Branch/PR aggregate gate results and source identity. |
| `tagged-release-evidence` | Tag/version-consistent release identity. |
| `generated-board-release-gate` | Generated-board gate v3, artifact hashes, component coverage, and source identity. |
| `benchmark-evidence` | Benchmark 001, fixture coverage, and fixture integrity reports. |
| `validation-environment` | Release-environment parity and toolchain identity. |
| `evidence-identity-policy` | Repository inventory and stale/ambiguous report-policy result. |

A current report is not committed under `docs/reports/`. Embedding a commit hash in the same commit that contains the generated report would be self-referential and either stale or misleading. Deterministic report structure and content expectations remain protected by tests, while the revision-bound report is a CI artifact.

## Committed JSON classification

Committed JSON without `evidence_identity` must declare exactly one non-authoritative class:

| Marker | Required `evidence_status` | Meaning |
|---|---|---|
| `sample: true` | `non-authoritative-example` | Documentation/example payload only. |
| `reference: true` | `deterministic-reference-not-current-evidence` | Stable comparison input, not a report about the current revision. |
| `historical_snapshot: true` | `historical-governance-snapshot` | Dated historical evidence whose exact commit is recorded in the payload. |
| `policy_artifact: true` | `generated-policy-not-runtime-evidence` | Deterministic policy inventory, not runtime validation evidence. |

`scripts/ci_evidence_identity.py --strict` rejects:

- committed files that appear to be current release or benchmark evidence;
- ambiguous or unclassified JSON reports;
- malformed embedded identities;
- missing identity adoption in release-critical producers;
- historical `v0.3.0` identity hard-coded in the generic release gate or branch workflow.

## Verification

Run the repository policy locally:

```bash
python scripts/ci_evidence_identity.py \
  --output evidence-identity-policy.json \
  --strict
```

For an individual identity, `verify_evidence_identity(...)` checks canonical-hash consistency and detects stale package version, lock hash, and source-input hash against the current repository.

## Non-claims

Source identity proves provenance and internal consistency of the recorded validation context. It does not prove electrical correctness, fabrication readiness, manufacturer approval, regulatory compliance, physical validation, or safe operation without qualified engineering review.
