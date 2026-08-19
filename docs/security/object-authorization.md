# Object-level authorization

ZapTrace treats every session-scoped identifier as an object selector, never as authority. Possession or guessing of a session, review, transaction, sandbox, replay, or artifact identifier does not grant access.

## Principal model

| Runtime mode | `principal_id` | Audit actor | Authority source |
|---|---|---|---|
| Authenticated REST | `ZAPTRACE_API_TOKEN_SUBJECT` | Same token subject | Bearer token, server scopes, session allowlist |
| Explicit loopback REST development | Stable `local-development` principal | Optional local actor header | Loopback-only capability-header opt-in |
| Loopback read-only REST | Stable `loopback-read-only` principal | `unauthenticated-rest-client` | Process-local read-only mode |
| Authenticated MCP HTTP | `ZAPTRACE_MCP_TOKEN_SUBJECT` | Same token subject | MCP bearer token and server capabilities |
| MCP stdio/local | Stable `mcp-local` principal | Same value | Local process boundary |

The stable principal controls ownership. Human-readable actor values are audit metadata and cannot change ownership in production.

## Object policy table

| Object | Ownership record | Parent | Read | Mutate | Delegate/admin behavior |
|---|---|---|---|---|---|
| Design/API session | Central ACL record | none | Owner, delegate, or `object-admin` | Same plus required capability | Owner/admin may add or revoke delegates |
| Sandbox | Inherits design-session ACL | design session | Authorized session principals | Authorized session principals plus `sandbox-write` | Session delegation applies |
| Replay log | Inherits design-session ACL | design session | Authorized session principals | Runtime-only recording | Session delegation applies |
| Transaction | Record includes parent `session_id` | design session | Authorized session principals | Authorized session principals plus transaction capability | Session delegation applies |
| Review session | Dedicated ACL record | linked design session | Direct owner/delegate/admin and authorized parent principals | Same plus review capability | Parent session delegation is inherited |
| REST artifact | Manifest includes owner principal | design session | Authorized session principals | Authorized session principals plus artifact capability | Cleanup is scoped to current session |
| MCP session | Central ACL record | none | Owner, delegate, or admin | Same plus MCP tool capability | Session list filters inaccessible sessions |

## Decision algorithm

1. Resolve the authenticated or explicit local principal.
2. Require an explicit `X-ZapTrace-Session-Id` for authenticated session-scoped reads and writes, then validate the token session allowlist unless the principal has `object-admin`.
3. Look up the object ACL without creating or revealing protected state.
4. Permit owner, delegated principal, or administrator.
5. For child objects, also require authorization to the parent object. A parent-session delegation may provide inherited child access.
6. Apply the tool capability policy after object authorization.
7. Record principal, actor, object type, object ID, action, outcome, reason, and request correlation ID.

Cross-principal failures use the stable `403 OBJECT_NOT_AUTHORIZED` error. This intentionally avoids distinguishing an existing protected identifier from a guessed identifier.

## Delegated access

REST session owners can delegate and revoke access through:

```text
POST   /api/v1/agent/sessions/{session_id}/delegates/{principal_id}
DELETE /api/v1/agent/sessions/{session_id}/delegates/{principal_id}
```

These operations require the `approved-commit` capability. A delegate can use the session according to their own capability grants, but cannot delegate it further. The `object-admin` scope provides an explicit administrative override and does not bypass ordinary tool capability checks.

## Identifier generation

Supported API and MCP session-creation operations use `secrets.token_urlsafe(24)`-derived identifiers. Review, decision, approval, and transaction identifiers use the same class of cryptographically secure opaque token generation. Client-provided selectors remain accepted for compatibility when they identify a new session. Existing in-memory sessions without ACL metadata cannot be claimed retroactively; they are denied until created or migrated through an authorized lifecycle.

## Artifact lifecycle

Artifact manifests include `owner_principal`. List and delete operations authorize the parent session before accessing the filesystem. Expiration cleanup invoked through REST is restricted to the caller's current session; it no longer deletes artifacts belonging to unrelated sessions.

## Audit evidence

Capability audit events include:

- `principal_id` and actor;
- target object type and ID;
- required and granted capabilities;
- authorization source;
- request correlation ID;
- allow/deny decision and reason.

Object-level authorization events are returned separately from capability events by `GET /api/v1/audit/events`, preserving the existing capability-event contract while exposing BOLA/IDOR decision evidence.

## Residual limitations

- ACL and authorization-event storage are process-local and ephemeral.
- Static bearer subjects are suitable for controlled deployments, not full enterprise identity federation.
- Persistent multi-process object ownership requires the versioned design-storage work tracked separately.
- This policy controls runtime authority; it does not certify generated electronics or manufacturing output.
