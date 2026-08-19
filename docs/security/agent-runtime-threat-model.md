# Agent Runtime Threat Model

Status: v0.2.3 M0 release-gate hardening

Scope: MCP server, REST API, in-memory or opt-in persistent sessions, file-export surfaces, and proof/audit evidence

ZapTrace is an agent-facing EDA runtime. Agent clients can create or mutate hardware designs, place and route boards, export manufacturing artifacts, and run verification workflows. This document treats MCP and REST as controlled capability surfaces rather than trusted local helper APIs.

## Security objectives

1. Deny mutating operations unless an explicit capability grant is present.
2. Keep all file I/O inside the configured workspace sandbox.
3. Bind every session-scoped object to an owner principal and explicit delegates.
4. Record who/what/when/why audit evidence for capability and object decisions.
5. Make blocked operations observable through structured errors and audit events.
6. Avoid implying that generated manufacturing output is safe without engineering review.

## Trust boundaries

| Boundary | Trusted? | Notes |
|---|---:|---|
| Core Python process | Yes | In-process policy enforcement and session store. |
| MCP client / LLM agent | No | May be prompt-injected, confused, or over-scoped. |
| REST caller | No | Network authentication, server scopes, session allowlists, and object ACLs are enforced. |
| External OAuth authorization server and JWKS endpoint | Configured trust | The production MCP HTTP design trusts one configured HTTPS issuer and its asymmetric keys; every token still requires issuer, audience/resource, expiry, subject, and scope validation. |
| Workspace files | Partially | Paths must resolve under the workspace root. |
| External tools / plugins | No | Must be treated as separate capability subjects in later issues. |
| Manufacturing artifacts | No | Must be checked and human-reviewed before use. |

## Capability model

ZapTrace uses an ordered capability ladder:

| Capability | Intended operations | Examples |
|---|---|---|
| `read` | Inspection only | library search, ERC rules, design inspect, audit read |
| `preview-write` | In-memory candidate creation | parse design, synthesize, run pipeline candidate |
| `sandbox-write` | In-memory mutation or sandbox file preview | component add/remove, board update, place, route, report/SVG write |
| `approved-commit` | Explicit confirmation of a design state | design commit |
| `release-export` | Manufacturing or release artifact generation | KiCad, Gerber, Excellon, manufacturing bundle |

Read-only operations remain capability-public, but session-scoped reads require object authorization. Every non-read operation is deny-by-default unless the caller owns or is delegated to the target object and presents a capability at the required level or higher. Release-export tools additionally require a non-empty `approval_id` bound to complete current release evidence: fresh passing ERC and DRC for one design identity, fabrication-profile policy evidence, full component/BOM/pick-and-place/footprint reconciliation, and risky-package review where applicable.

## Threats and controls

| Threat | Impact | Current control |
|---|---|---|
| Confused deputy agent calls write/export tool after prompt injection | Design mutation or unsafe release artifacts | Capability-gated write/export operations; audit event with actor/tool/reason. |
| Missing, guessed, or reused object identifier | Cross-client state disclosure or mutation | Central owner/delegate/admin ACL; stable `OBJECT_NOT_AUTHORIZED`; parent authorization for review objects. |
| Token/capability misuse | Over-scoped operations | Production capabilities are server-controlled; client grants are loopback-only; object ACL and token session allowlist are enforced before tools run. |
| Workspace escape / path traversal | Arbitrary file read/write | Shared path validation rejects resolved paths outside workspace. |
| Unsafe manufacturing export | False confidence or accidental fab submission | `release-export` capability required; the release approval is bound to the complete current evidence identity, including fresh ERC/DRC, fab-profile policy, component/BOM/PnP/footprint coverage, and risky-package review. |
| MCP session overreach | LLM reads or writes another session | Cryptographic session IDs, central ACL checks in every tool wrapper, filtered session listing, and capability enforcement. |
| Timed-out or cancelled mutator continues after the terminal response | Late state changes, partial artifacts, or misleading audit evidence | Non-read MCP tools run in isolated workers; same-session mutations are serialized; timeout/cancellation confirms worker termination; state and output paths commit only on success. |
| REST unauthorized read/write | Remote disclosure or mutation | Authenticated session-scoped requests require an explicit session selector; session ACL, review-parent ACL, artifact ownership, and capability dependencies deny cross-principal access. |
| Missing evidence for decisions | Cannot reconstruct incident | Audit events include principal, actor, object, action, capability, request ID, decision, and reason. |
| SSRF-like URL access | Remote data exfiltration | Current agent tools do not accept arbitrary remote URLs; future network tools must declare separate capability. |
| Unsafe subprocess/tool execution | Host compromise or post-timeout mutation | The MCP wrapper exposes no generic shell tool. Mutating registry tools run in dedicated process groups against cloned state, publish only declared staged outputs, and terminate descendants before timeout/cancellation rollback. Future plugins still require stronger sandboxing and deny-by-default admission. |
| Malformed parser/import/archive input | Crash, hang, resource exhaustion, or containment bypass | Deterministic child-process fuzz campaigns apply timeout/memory budgets across parser, importer, ZIP, API/MCP, plugin, path, and exporter boundaries. |

## Remote MCP HTTP production authorization

The production OAuth/JWT profile is specified in `docs/security/mcp-http-authorization-contract.md` and is implemented separately by #524. The design adds the following required controls without weakening the current static-bearer or loopback profiles:

| Threat | Required production control |
|---|---|
| Token passthrough / confused deputy | Validate the inbound token locally for ZapTrace and never forward it to a downstream service. |
| Audience confusion | Require the JWT `aud` claim to contain the canonical MCP resource URI. |
| Scope escalation | Map only fixed validated OAuth scopes to the server-owned capability ladder; unknown scopes and client headers grant nothing. |
| Client mix-up | Accept one configured issuer, require exact `iss`, and treat `client_id` only as audit context. |
| Bearer replay | Revalidate every request, require external HTTPS, avoid token/session carryover, and use short-lived tokens; proof-of-possession remains a documented residual risk. |
| Cross-session object access | Derive the principal from validated `(iss, sub)` and retain owner/delegate ACL checks after authentication succeeds. |

Negative evidence must cover missing, malformed, expired, wrong-issuer, wrong-audience, insufficient-scope, follow-up-without-header, and cross-principal session requests. No raw bearer value or key material may enter logs or audit evidence.

## Required runtime evidence

For each mutating or release-export operation, ZapTrace records an audit event in the session:

```json
{
  "surface": "rest",
  "session_id": "api-allowed-session",
  "actor": "pytest",
  "tool": "design_parse_str",
  "capability": "preview-write",
  "decision": "allow",
  "reason": "audit allow example"
}
```

Denied requests are also recorded:

```json
{
  "surface": "mcp",
  "tool": "design_parse_str",
  "capability": "preview-write",
  "decision": "deny",
  "reason": "missing required capability: preview-write"
}
```

REST audit events are available at:

```text
GET /api/v1/audit/events
X-ZapTrace-Session-Id: <session-id>
```

MCP audit evidence is available through:

```text
zaptrace://audit/events
```

## Current limitations

- Static bearer credentials and local SQLite ACLs are intended for controlled deployments, not enterprise identity federation or arbitrary untrusted multi-tenancy. The OAuth/JWT production profile remains design-only until #524 is complete.
- When `ZAPTRACE_SESSION_STORE_ROOT` is configured, committed session state, audit events, and object ACLs are persistent; mutation locks and destroyed-session guards remain process-local coordination mechanisms.
- Cancellation-safe execution does not coordinate incorrectly configured independent server processes and is not an operating-system container or general plugin sandbox.
- SQLite commits session state atomically, but artifact payload publication and database metadata do not form a distributed cross-filesystem transaction. Protected evidence references prevent retention cleanup after successful registration.
- Crash detection, online backup/restore, checksum-verified migrations, and corruption fail-closed behavior are documented in `docs/storage/persistent-state.md`; plugin admission and signed plugin manifests remain separate work.
- This policy does not certify generated hardware output; it only controls agent/runtime authority.

## Related policy

- Object ownership, delegation, administrator override, and stable denial semantics: `docs/security/object-authorization.md`.
- Cancellation-safe mutation execution and artifact publication: `docs/security/cancellation-safe-tool-execution.md`.
- Persistent session state, backup, migration, recovery, and deployment limits: `docs/storage/persistent-state.md`.
- Complete current release evidence and approval binding: `docs/security/release-evidence.md`.
- Network transport authentication: `docs/security/network-transport-authentication.md`.
- Remote MCP HTTP OAuth resource-server contract: `docs/security/mcp-http-authorization-contract.md`.
- Untrusted-input fuzz target inventory, limits, reports, and reproduction: `docs/security/fuzzing.md`.
