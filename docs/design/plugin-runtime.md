# Plugin Runtime Safety Design

> **Status:** Manifest/admission contract implemented — runtime execution remains closed by default.
> **Scope:** Plugin runtime security model, capability permissions, sandbox model, and integration with existing ZapTrace systems.
> **Out of scope:** Plugin runtime implementation, plugin registry, plugin lifecycle management.

---

## 1. Motivation

ZapTrace must support third-party plugins — analysis engines, export formats, DFM checks, specialized routers — without compromising:

- **Design integrity:** A plugin must not silently corrupt design state.
- **Reproducibility:** Proof packs must attest which plugins ran and with what permissions.
- **Safety:** A buggy or malicious plugin must not read/write files outside its scope, access the network unexpectedly, or crash the host process in an unrecoverable way.

This document defines the security boundary before any plugin runtime code is written.

---

## 2. Plugin Manifest Schema

Every plugin MUST carry a signed manifest (`zaptrace-plugin.json`) at its root:

```jsonc
{
  "$schema": "https://zaptrace.dev/schemas/plugin-manifest-v1.json",
  "api_version": "1.0",
  "plugin_id": "com.example.my-analyzer",
  "name": "My Analyzer",
  "version": "0.1.0",
  "min_zaptrace_version": "0.2.0",
  "max_zaptrace_version": "0.3.6",
  "entry": {
    "type": "python_module",   // "python_module", "executable", "wasm"
    "path": "plugin/main.py"
  },
  "capabilities": [
    "design:read",
    "design:write"
  ],
  "permissions": {
    "filesystem": {
      "read": ["inputs/", "data/"],
      "write": ["outputs/"]
    },
    "network": {
      "allowed_domains": ["api.example.com"],
      "allowed_schemes": ["https"]
    },
    "subprocess": false
  },
  "signing": {
    "algorithm": "ed25519",
    "signature": "base64-encoded-signature..."
  }
}
```

### Required Fields

| Field | Description | Validation |
|-------|-------------|------------|
| `api_version` | Plugin API protocol version | SemVer; must match host supported range |
| `plugin_id` | Reverse-domain identifier | Unique per plugin; no two plugins share an ID |
| `version` | Plugin version | SemVer |
| `min_zaptrace_version` | Minimum host version | SemVer range check on load |
| `max_zaptrace_version` | Maximum host version | SemVer range check on load |
| `entry.type` | Plugin execution model | Must be a supported type (`python_module` initially) |
| `capabilities` | Declared capability set | Each capability must be a known string from the capability table |
| `permissions` | Resource access bounds | Must not request more than the capability set implies |

### Optional Fields

| Field | Description |
|-------|-------------|
| `description` | Human-readable description |
| `author` | Author name / organisation |
| `homepage` | Plugin project URL |
| `repository` | Source code URL |
| `documentation` | Docs URL |
| `dependencies` | List of `{plugin_id, version_range}` |

---

## 3. Capability Permissions Model

Every plugin declares a set of capabilities at manifest load time. The host maps each capability to a set of allowed operations.

| Capability | Operations | Risk |
|------------|------------|------|
| `design:read` | Read design model, nets, components, layers, stackup | Low — read-only access to design tree |
| `design:write` | Modify design model (components, nets, placement, routing) | **High** — can corrupt design state |
| `design:metadata` | Read/write design metadata only (labels, tags, notes) | Low |
| `proof:read` | Read proof-pack manifests and artifacts | Low |
| `proof:write` | Append check records to an existing proof pack | Medium — can inject false attestations |
| `library:read` | Query component library | Low |
| `library:write` | Add/modify library entries | Medium — supply-chain risk |
| `filesystem:read` | Read files from plugin-scoped directories | Medium |
| `filesystem:write` | Write files to plugin-scoped output directories | Medium |
| `network:connect` | Make outbound HTTPS connections to declared domains | Medium |
| `subprocess:run` | Spawn child processes | **High** — sandbox escape risk |
| `plugin:load` | Load other plugins on behalf of this plugin | **High** — delegation attack surface |
| `mcp:tool_call` | Invoke MCP tools from within a plugin | **High** — indirect state mutation |
| `host:log` | Emit structured logs | Low |
| `host:notify` | Send user-facing notifications | Low |

### Capability Review Process

1. **Declared caps** must be a _subset_ of what the signer is authorised for.
2. At install time, the host displays requested capabilities and the user must explicitly approve.
3. At runtime, the sandbox enforces the declared capability set — a plugin cannot exceed its manifest even if code tries.

---

## 4. Read/Write Separation

Plugins MUST declare separate read and write paths. A plugin declared with only `design:read` must never be able to write.

### Enforcement

- **Filesystem:** `filesystem.read` paths are mounted read-only; `filesystem.write` paths are mounted read-write in a temp directory, synced back on success.
- **Design tree:** Plugins with `design:read` only receive a frozen/copied design model. Mutator methods raise `PermissionError`.
- **Proof pack:** Plugins with `proof:read` only receive read-only handles. `proof:write` required to append check records.

### Rationale

Read-only plugins are significantly safer — they can audit, analyse, and report without risking design corruption. The capability model makes this distinction explicit at the manifest level.

---

## 5. Sandbox Model

### Phase 1 (this design) — Process-Level Isolation

No sandbox enforcement yet. This design defines the security contract.

### Phase 2 — Subprocess with Restricted User

Plugin runs as a dedicated OS user/group with filesystem and network ACLs matching declared permissions.

### Phase 3 — Container / Wasm Sandbox

- **Python plugins:** Run in an isolated subprocess with `chroot` or container (Docker/Podman) with read-only rootfs, declared volume mounts, and network policy.
- **Wasm plugins:** Run in a WebAssembly sandbox (wasi) with capability-based I/O — `wasmtime` or similar runtime. Memory safety is guaranteed by the Wasm model; filesystem/network access is gated by WASI preview 2 capabilities.
- **Executable plugins:** Run in a container with strict seccomp / AppArmor profile.

### Recommended Path

Start with subprocess sandbox (Phase 2) for `python_module` plugins. Wasm sandbox (Phase 3) for untrusted third-party plugins. Docker container for `executable` plugins.

---

## 6. Version Negotiation

On plugin load:

1. Host reads plugin manifest.
2. Host checks `min_zaptrace_version` ≤ `ZAPTRACE_VERSION` ≤ `max_zaptrace_version`.
3. Host checks `api_version` is in its supported range.
4. If versions mismatch, plugin load **fails** with a clear error message: `"Plugin X requires zaptrace >= Y, < Z. Current version: W"`.

### API Versioning Strategy

- `api_version` uses `MAJOR.MINOR`.
- MAJOR bump = breaking protocol change (capability model, manifest format).
- MINOR bump = additive change (new capabilities, new entry types).
- Host supporting `1.x` must accept any `1.MINOR`.

---

## 7. Dependency Policy

A plugin may declare dependencies on other plugins (`dependencies` array in manifest). Rules:

1. **No circular dependencies** — the host detects cycles at load time and fails.
2. **Version range** — each dependency specifies a SemVer range.
3. **Transitive capability escalation** — if plugin A depends on plugin B, and A has `design:write`, B inherits no extra capability. B operates within its own declared capability set.
4. **Dependency trust** — if the host does not trust a dependency's signer, it may refuse to load the dependent plugin.

---

## 8. Network Access Policy

| Level | Allowed | Enforcement |
|-------|---------|-------------|
| `none` | No network access | Block all sockets |
| `domains` | HTTPS to declared domains only | DNS + TLS SNI enforcement |
| `internal` | Internal/loopback only | For plugins co-located with local services |
| `full` | Unrestricted | Only for trusted/audited system plugins |

- Default is `none`.
- `network.connect` capability required for any level above `none`.
- Allowed domains must be explicit FQDNs — no wildcards (except for well-known subdomain patterns like `*.api.example.com`).
- Network policy is enforced via network namespace / container network policy (Phase 3) or `iptables` / `pf` (Phase 2).

---

## 9. Artifact Access Policy

- Plugins with `filesystem:read` may read files only from their declared read paths.
- Plugins with `filesystem:write` may write only to their declared write paths.
- Paths are relative to the plugin's workspace root.
- Path traversal attacks (`../../etc/passwd`) are blocked via path canonicalisation before access.
- Design files passed to plugins are **snapshot copies** — the plugin operates on a frozen design tree unless it holds `design:write`.

---

## 10. Signing / Trust Model

### Goals

- Verify plugin integrity by binding admission to the exact canonical manifest payload.
- Verify that the declared signer resolves to a public key explicitly trusted by the host deployment.
- Fail closed on missing signatures, unknown signers, malformed signatures, content mutation, and unknown manifest fields.

### Mechanism

1. A plugin publisher generates an Ed25519 key pair and keeps the private key outside ZapTrace.
2. The publisher signs the canonical manifest payload, which excludes only the `signing` object.
3. The signature and SHA-256 public-key fingerprint are stored in `manifest.signing`.
4. The host deployment supplies a fingerprint-to-public-key trust mapping from reviewed configuration.
5. Admission validates the strict manifest schema, resolves the fingerprint, verifies the Ed25519 signature, and only then evaluates dangerous capabilities and scoped permissions.

A fingerprint allowlist without the corresponding public key is not cryptographic trust and cannot admit a plugin. The explicit `require_signature=False` override exists only for bounded development and policy tests; it is not a production profile.

### Admission States

| State | Behaviour |
|-------|-----------|
| `verified` | A trusted public key exists and the signature verifies over the canonical manifest payload |
| `unsigned-development` | Allowed only through an explicit local policy override; no production trust claim |
| `denied` | Missing signature, unknown signer, invalid signature, invalid schema, or denied capability prevents admission |

ZapTrace does not currently implement trust-on-first-use, implicit system-plugin trust, automatic key retrieval, or a general third-party execution runtime.

### Key Distribution

- The embedding application or deployment constructs the reviewed fingerprint-to-public-key mapping.
- Public keys may be distributed through deployment configuration, but plugin packages cannot self-authorize by supplying their own trust root.
- Private signing keys and production trust-store values must not be committed to the repository.
- Automatic publisher-key discovery or a signed marketplace index requires a separate reviewed design.

---

## 11. Failure Isolation

A plugin must not crash the host process. Mechanisms:

1. **Subprocess model:** Plugin runs in a separate process. If it crashes, the host receives exit code + stderr and continues.
2. **Timeout:** Plugin operations have a configurable timeout (default 30s). Exceeding the timeout terminates the subprocess.
3. **Resource limits:** Memory limit (configurable, default 256 MB), file descriptor limit (default 64).
4. **Panic recovery:** Python plugins wrapped in a top-level `try/except` that catches `SystemExit`, `KeyboardInterrupt`, and unhandled exceptions, logs the error, and returns a failure result without crashing the host.

### Error Propagation

```
Plugin error → Host logs with plugin_id + traceback → Capability rollback → User notification
```

- If a plugin with `design:write` fails mid-mutation, the design state is rolled back to the last MCP transaction boundary (see §12).
- The user sees: `"Plugin X failed: <error summary>. Design state restored to <transaction>."`

---

## 12. MCP Transaction Boundary Integration

ZapTrace already has MCP transaction safety with snapshot/rollback/commit. Plugin mutation integration:

### Flow

1. Plugin acquires `design:write` capability.
2. Before first mutation, host creates an MCP snapshot.
3. Plugin runs.
4. On success → commit snapshot.
5. On failure → rollback to snapshot.
6. Multiple plugins in sequence → each plugin gets its own snapshot boundary.

### Plugin Transaction Isolation

| Scenario | Behaviour |
|----------|-----------|
| Plugin succeeds | Snapshot committed; changes visible |
| Plugin fails (error) | Snapshot rolled back; no partial state |
| Plugin crashes | Host detects subprocess death; rollback |
| Plugin timeout | Host sends SIGTERM; rollback |
| Plugin violates permissions | Host terminates plugin; rollback |

### Integration API (future)

```python
class PluginContext:
    def snapshot(self) -> str: ...
    def commit(self, snapshot_id: str) -> None: ...
    def rollback(self, snapshot_id: str) -> None: ...
    def read_design(self) -> Design: ...
    def write_design(self, design: Design) -> None: ...
```

---

## 13. Proof Pack Integration

Every plugin execution is recorded in the proof pack:

```json
{
  "plugin_executions": [
    {
      "plugin_id": "com.example.my-analyzer",
      "version": "0.1.0",
      "capabilities_used": ["design:read", "host:log"],
      "started_at": "2026-06-17T10:00:00Z",
      "completed_at": "2026-06-17T10:00:05Z",
      "exit_code": 0,
      "errors": [],
      "check_records_appended": 3
    }
  ]
}
```

### Attestation

- Host signs the plugin execution record with its own key to attest that it ran with declared capabilities.
- A malicious plugin cannot forge proof-pack records — the record structure is host-controlled.
- If a plugin declares `proof:write` and appends check records, those records are tagged with the plugin ID for auditability.

---

## 14. Test Strategy

### Unit Tests

| Test | Description |
|------|-------------|
| `test_manifest_parsing_valid` | Parses a well-formed manifest |
| `test_manifest_parsing_missing_field` | Rejects manifest without required fields |
| `test_manifest_parsing_unknown_capability` | Rejects manifest with unknown capability |
| `test_version_check_compatible` | `min/max_zaptrace_version` in range → pass |
| `test_version_check_too_old` | Plugin requires newer host → fail |
| `test_version_check_too_new` | Plugin requires older host → fail |
| `test_api_version_mismatch` | `api_version` MAJOR mismatch → fail |
| `test_dependency_cycle_detection` | A→B→A cycle → fail |
| `test_capability_approval_boundary` | `design:read` only → no write mutation |
| `test_path_traversal_blocked` | `../../etc/passwd` → `PermissionError` |
| `test_network_policy_domain_allowed` | Allowed domain → connect passes |
| `test_network_policy_domain_blocked` | Blocked domain → connect fails |
| `test_signing_verification_valid` | Valid signature → pass |
| `test_signing_verification_tampered` | Tampered manifest → fail |
| `test_failure_isolation_crash` | Plugin crash → host continues |
| `test_failure_isolation_timeout` | Plugin timeout → host continues |
| `test_transaction_rollback_on_failure` | Failed plugin → design reverted |
| `test_transaction_commit_on_success` | Successful plugin → design updated |
| `test_proof_pack_plugin_record` | Plugin execution recorded in proof pack |

### Integration Tests

| Test | Description |
|------|-------------|
| `test_plugin_load_lifecycle` | Load → verify → execute → unload |
| `test_plugin_with_dependencies` | A depends on B → both load in order |
| `test_plugin_capability_enforcement` | Read-only plugin prevented from writing |
| `test_plugin_proof_pack_attestation` | Host-signed plugin record appears in pack |

### Security Tests

| Test | Description |
|------|-------------|
| `test_malicious_manifest_dos` | Extremely large manifest → rejected |
| `test_permission_escalation_attempt` | Plugin claims `design:write` but not approved |
| `test_signature_forgery` | Invalid signature → rejected |
| `test_supply_chain_dependency_attack` | Compromised dependency → blocked by trust |

---

## 15. Implementation Phasing

| Phase | Scope | Depends On |
|-------|-------|------------|
| 0 | Design document (this file) | — |
| 1 | `Manifest` pydantic model + validation | Phase 0 |
| 2 | `PermissionSet` model + capability checking | Phase 1 |
| 3 | Plugin directory scanning + manifest load | Phase 1 |
| 4 | Subprocess sandbox (read-only plugin) | Phase 2, 3 |
| 5 | Filesystem sandbox (read/write paths) | Phase 4 |
| 6 | Network sandbox | Phase 4 |
| 7 | Signing/trust verification | Phase 1 |
| 8 | MCP transaction boundary integration | Phase 5, MCP transaction safety |
| 9 | Proof pack integration | Phase 8, proof-pack system |
| 10 | Wasm sandbox | Independent of Phase 4 |

---

## 16. Open Questions

1. **Plugin distribution:** Should plugins be pip-installable Python packages, or loaded from a dedicated directory? **Recommendation:** Both — a plugin can be a regular pip package with a `zaptrace-plugin.json` manifest, or a standalone directory loaded via `zaptrace plugin install <path>`.
2. **Wasm plugins:** Wasm has no direct Python object access — how do plugins interact with the design model? **Recommendation:** Wasm plugins receive a JSON-serialised design snapshot and return a JSON diff. The host applies the diff.
3. **Plugin marketplace:** Future — a signed plugin index with automated trust evaluation. Out of scope for now.
4. **Multi-tenant:** If ZapTrace runs as a service, plugin isolation must prevent cross-tenant data leaks. For now, single-tenant assumed.

---

## Implemented v1 admission contract

The repository includes a non-executing plugin admission layer:

- `zaptrace/plugin/manifest.py` defines a strict versioned `zaptrace-plugin.json` schema and rejects unknown fields at every nested object boundary.
- `zaptrace/plugin/signature.py` verifies Ed25519 signatures over a deterministic canonical manifest payload.
- `zaptrace/plugin/admission.py` requires a trusted public key and a valid signature by default before capability and permission policy is evaluated.
- `schemas/plugin-manifest-v1.schema.json` is generated from the Pydantic contract and checked in CI.
- Tests create ephemeral Ed25519 keys; no private signing key or production trust value is committed.
- Audit evidence distinguishes invalid schema, missing signature, unknown signer, invalid signature, denied capability, and successful admission.
- Runtime plugin code is not imported or executed during discovery or admission.

This implements the manifest/schema/admission trust boundary only. ZapTrace still has no approved general third-party execution runtime, and successful admission does not prove that plugin code is safe to execute.
