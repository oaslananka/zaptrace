# MCP HTTP authorization contract

Status: approved design for implementation issue [#524](https://github.com/oaslananka/zaptrace/issues/524)

Contract version: `1`

This document defines ZapTrace's production authorization contract for remote MCP HTTP deployments. Slice 1 implements versioned profile resolution and fail-closed startup validation. Slice 2 implements FastMCP provider construction, RFC 9728 discovery, and stable `401` challenges. Slice 3 consumes FastMCP's validated `AccessToken.scopes`, maps only the fixed contract scopes to the existing capability ladder, and derives a redacted stable principal from validated `(iss, sub)`. Slice 4 completes the supported request boundary: every request is authorized from the current validated token, insufficient tool scope returns transport-level `403 insufficient_scope` before object access, session ACL denial remains structured `OBJECT_NOT_AUTHORIZED`, and authorization audit identity is redacted. Slice 5 completes end-to-end evidence and migration with an ephemeral asymmetric JWT/JWKS fixture, the required negative matrix, profile-aware Compose smoke evidence, and safe migration examples. The profile still makes no public-SaaS or multi-tenant-readiness claim.

## Decision

The first production profile will use FastMCP's `RemoteAuthProvider` composed with `JWTVerifier` and an external OAuth 2.1/OpenID Connect authorization server. ZapTrace remains an OAuth resource server: it validates access tokens and publishes protected-resource metadata, but it does not host user login, consent, client registration, or token issuance.

The v1 profile accepts asymmetric JWT access tokens obtained from one configured authorization server and validated through its HTTPS JWKS endpoint. Repository-owned JWT parsing, symmetric HMAC signing keys, debug token verifiers, token passthrough, and a hosted identity provider are excluded.

Alternatives considered:

| Approach | Decision | Reason |
|---|---|---|
| Repository-owned JWT/OAuth implementation | Rejected | Duplicates security-sensitive validation, discovery, and challenge behavior already provided by FastMCP and the MCP SDK. |
| `RemoteAuthProvider` + `JWTVerifier` | Selected | Provides issuer/audience/expiry/signature validation and RFC 9728 discovery without making ZapTrace an authorization server. |
| FastMCP OAuth/OIDC proxy | Deferred | Useful for providers without suitable client registration, but introduces client credentials, token storage, refresh flows, and a larger operational boundary. |
| RFC 7662 opaque-token introspection | Deferred | Requires resource-server credentials and a network call for validation; it should be a separately reviewed profile. |

## Standards baseline

The implementation must follow the MCP authorization specification dated `2025-11-25` and its referenced OAuth standards:

- OAuth 2.1 resource-server behavior for bearer requests;
- RFC 8707 resource indicators and audience/resource binding;
- RFC 9728 protected-resource metadata;
- RFC 6750 bearer challenges and `insufficient_scope` handling;
- OAuth or OpenID Connect authorization-server discovery supplied by the external provider.

Authorization applies only to HTTP transports. Stdio continues to use local process/environment trust and must not expose OAuth routes.

## Deployment profiles

| Profile | Bind/exposure | Status | Authentication and authorization contract |
|---|---|---|---|
| `stdio` | Local process pipe | Supported | No network listener. Existing local capability policy applies. |
| `local` | Explicit loopback HTTP only | Supported | No bearer credential required; read-only by default. Explicit development grants remain loopback-only. |
| `static-bearer` | Loopback or reviewed non-loopback deployment | Controlled | Existing constant-time static token comparison and server-configured capabilities. Intended for bounded single-tenant automation behind reviewed TLS/proxy controls. |
| `oauth-jwt` | Remote HTTP, normally behind TLS termination | Supported bounded resource-server profile | Slices 2-5 provide the external resource-server provider, asymmetric JWT/JWKS verifier, RFC 9728 metadata, stable `401`/`403` challenges, fixed validated scope mapping, redacted `(iss, sub)` principal binding, per-request authorization, central object-ACL audit, full negative JWT coverage, and packaged Compose evidence. |
| OAuth/OIDC proxy | Remote HTTP | Experimental/deferred | Requires a separate design for provider client credentials, encrypted token storage, callback URLs, refresh, and incident recovery. |
| Opaque-token introspection | Remote HTTP | Experimental/deferred | Requires a separate design for introspection credentials, availability, caching, and revocation semantics. |
| Public anonymous HTTP | Any non-loopback listener | Unsupported | Startup must fail. |
| Arbitrary public multi-tenant SaaS | Internet-facing | Unsupported | This contract does not establish tenant isolation, abuse controls, certification, or public-hosting readiness. |

## Versioned configuration contract

New-profile configuration is activated only when both of these variables are set:

| Variable | Required value/purpose |
|---|---|
| `ZAPTRACE_MCP_AUTH_CONFIG_VERSION` | Exact value `1`. Unknown or missing versions fail when an explicit new profile is selected. |
| `ZAPTRACE_MCP_AUTH_PROFILE` | One of `local`, `static-bearer`, or `oauth-jwt`. Unknown values fail startup. |

The `oauth-jwt` profile requires:

| Variable | Contract |
|---|---|
| `ZAPTRACE_MCP_PUBLIC_BASE_URL` | Externally visible HTTPS base URL, for example `https://mcp.example.com`. No credentials, query, or fragment. |
| `ZAPTRACE_MCP_AUTH_RESOURCE_URI` | Canonical protected resource URI. Slice 2 requires exact `<public-base-url>/mcp` because `/mcp` is the fixed protected endpoint. It must be HTTPS, same-origin with the public base URL, and contain no query or fragment. |
| `ZAPTRACE_MCP_AUTHORIZATION_SERVER` | Exact HTTPS issuer/authorization-server URL advertised in protected-resource metadata and accepted in `iss`. V1 accepts one server and requires FastMCP canonical URL form; a host-root issuer therefore ends in `/`. |
| `ZAPTRACE_MCP_AUTH_JWKS_URI` | HTTPS JWKS endpoint used by `JWTVerifier` for asymmetric signature validation and key rotation. |

The scope vocabulary is fixed by this contract and is not operator-remappable in v1. OAuth profile startup must reject conflicting legacy grant configuration rather than silently combining trust models.

### Fail-closed combinations

Startup must fail for all of the following:

- `local` on a non-loopback bind;
- any non-loopback bind with local-development session grants enabled;
- `oauth-jwt` with `ZAPTRACE_MCP_HTTP_TOKEN`, `ZAPTRACE_MCP_TOKEN_SUBJECT`, or `ZAPTRACE_MCP_CAPABILITIES` set;
- `oauth-jwt` with a missing issuer, resource URI, public base URL, or JWKS URI;
- a non-HTTPS OAuth URL, a resource URI on another origin, or a URI containing credentials, query, or fragment;
- OAuth-specific variables set under `local` or `static-bearer`;
- `static-bearer` without a non-empty `ZAPTRACE_MCP_HTTP_TOKEN`;
- an unknown configuration version or profile.

Secret values remain outside the repository and are supplied through the deployment secret system. For maintained deployments, Doppler is the source system.

## Token validation contract

Every HTTP request to the MCP endpoint must carry `Authorization: Bearer <access-token>`. Tokens in query strings, cookies, MCP session state, or custom headers are not accepted.

`oauth-jwt` validation must be delegated to FastMCP `JWTVerifier` and require:

- a valid asymmetric signature from the configured JWKS;
- exact configured issuer validation;
- an `aud` value containing the canonical `ZAPTRACE_MCP_AUTH_RESOURCE_URI`;
- a present, non-empty `sub` claim;
- a present expiration time that has not elapsed;
- `nbf` enforcement when supplied by the issuer;
- scopes exposed by FastMCP's validated `AccessToken.scopes`, not reparsed from untrusted request metadata.

Tokens with `alg=none`, symmetric HMAC algorithms, another issuer, another audience/resource, malformed claims, missing subject, missing expiration, or expired/not-yet-valid times are invalid. Signature, JWKS, issuer, audience, and JWT decoding remain delegated to FastMCP's `JWTVerifier`; ZapTrace's `ZapTraceJWTVerifier` subclass only tightens the reviewed contract by requiring a numeric `exp` claim and enforcing a numeric `nbf` claim when present, because the pinned FastMCP verifier does not impose those two conditions itself. The inbound access token must never be forwarded to an EDA tool, plugin, external API, authorization server, or downstream service.

The stable principal is derived from the validated `(iss, sub)` pair. A validated `client_id` may be recorded as audit context but never replaces the resource-owner subject or grants capabilities by itself. Raw tokens, JWT signatures, JWKS key material, and authorization headers must not appear in logs or audit records.

## Scope-to-capability mapping

Only these exact scopes grant ZapTrace authority:

| OAuth scope | ZapTrace capability |
|---|---|
| `zaptrace:read` | `read` |
| `zaptrace:preview-write` | `preview-write` |
| `zaptrace:sandbox-write` | `sandbox-write` |
| `zaptrace:approved-commit` | `approved-commit` |
| `zaptrace:release-export` | `release-export` |

ZapTrace derives the effective capability set only from FastMCP's validated `AccessToken.scopes` and applies the existing ordered capability ladder. Unknown scopes grant nothing. OAuth requests do not merge environment/session capability grants into token authority. A higher validated ZapTrace scope satisfies lower capability levels through the existing ladder, while a token containing no recognized ZapTrace scope cannot use even read-only MCP components.

Slice 3 derives `RequestPrincipal` identity from validated `(iss, sub)` using a deterministic SHA-256 identifier. Raw bearer values, raw subject values, issuer strings, and `client_id` are not embedded in that principal identifier; `client_id` never grants authority. Scope authorization runs before session object claim so an under-scoped caller cannot use object existence as an authorization side channel. Session ownership/delegation ACLs, release approval evidence, path policy, cancellation safety, and tool-specific validation remain mandatory after transport authentication succeeds.

## Protected-resource discovery

For a canonical resource `https://mcp.example.com/mcp`, the OAuth profile must publish RFC 9728 metadata at:

```text
https://mcp.example.com/.well-known/oauth-protected-resource/mcp
```

The document must identify the exact protected resource and configured authorization server:

```json
{
  "resource": "https://mcp.example.com/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": [
    "zaptrace:read",
    "zaptrace:preview-write",
    "zaptrace:sandbox-write",
    "zaptrace:approved-commit",
    "zaptrace:release-export"
  ],
  "bearer_methods_supported": ["header"],
  "resource_name": "ZapTrace MCP"
}
```

The metadata is public and must contain no token, client secret, signing material, internal filesystem path, or deployment-only credential.

Slice 2 exercises this route from the auth-bound FastMCP view and verifies the exact resource, authorization server, scope vocabulary, header-only bearer method, and resource name. After Slice 4 the supported `oauth-jwt` launcher serves this discovery endpoint as part of the bounded resource-server profile; this does not make ZapTrace an authorization server or a certified public multi-tenant service.

## Bearer challenge and error contract

Authorization failures preserve standards-compatible HTTP status and stable ZapTrace error codes:

| Condition | HTTP status | ZapTrace code | Challenge |
|---|---:|---|---|
| Missing bearer credential | `401` | `AUTH_REQUIRED` | `Bearer resource_metadata="<metadata-url>", scope="zaptrace:read"` |
| Malformed, expired, wrong-issuer, wrong-audience, or invalid-signature token | `401` | `AUTH_INVALID_TOKEN` | Add `error="invalid_token"`; do not disclose validation internals. |
| Valid token with insufficient capability scope | `403` | `OPERATION_NOT_AUTHORIZED` | Add `error="insufficient_scope"`, the minimum required scope, and `resource_metadata`. |
| Malformed OAuth request metadata | `400` | `AUTH_REQUEST_INVALID` | No credential value in body or logs. |
| Valid token denied by session ACL | MCP structured denial | `OBJECT_NOT_AUTHORIZED` | Do not misreport object denial as missing OAuth scope. |

The initial `401` challenge advertises only `zaptrace:read`. Slice 2 implements missing/invalid bearer handling and a stable `resource_metadata` challenge while preserving FastMCP token verification. Slice 3 applies the fixed scope/principal adapter. Slice 4 adds transport-level `403 insufficient_scope` before tool/object execution, preserves `OBJECT_NOT_AUTHORIZED` for valid-principal session ACL denial, and records redacted authorization audit identity. Authorization is evaluated from the current validated token on every HTTP request rather than cached as session authority.

## Threat model and residual risk

| Threat | Required control | Evidence expected from #524 |
|---|---|---|
| Token passthrough/confused deputy | Validate issuer and resource locally; never forward the inbound token. | Wrong-audience token and downstream-token leakage tests. |
| Audience confusion | Require `aud` to contain the canonical resource URI. | Token for another API receives `401 AUTH_INVALID_TOKEN`. |
| Scope escalation | Fixed server-owned scope mapping; unknown scopes and client headers grant nothing. | Unknown/insufficient scope tests and capability audit evidence. |
| Client mix-up | One configured authorization server, exact `iss`, resource-bound tokens, and optional audited `client_id`. | Wrong-issuer/client-context tests. |
| Bearer replay | Revalidate every request, require HTTPS externally, issue short-lived tokens, never cache authorization in an MCP session, and never accept tokens from URLs/cookies. | Expiry, missing-header-on-follow-up, and no-session-carryover tests. |
| Cross-session object access | Derive a stable principal from `(iss, sub)` and keep central owner/delegate ACL checks after token validation. | Principal A cannot read, mutate, list, or destroy principal B's session. |

A bearer token remains replayable by anyone who steals it while it is valid. V1 does not claim proof-of-possession, DPoP, mTLS-bound tokens, online revocation, or one-time access tokens. Short lifetime, TLS, secret-safe logging, audience binding, and object authorization reduce but do not eliminate that residual risk.

## Migration from static bearer

The migration is intentionally non-destructive:

1. During the `0.3.x` line, an unset `ZAPTRACE_MCP_AUTH_PROFILE` preserves legacy inference: a configured `ZAPTRACE_MCP_HTTP_TOKEN` selects controlled `static-bearer`; no token on loopback selects `local`; no token on non-loopback fails.
2. Explicit `ZAPTRACE_MCP_AUTH_PROFILE=static-bearer` with configuration version `1` is the stable controlled-deployment form.
3. Operators adopting OAuth configure a separate deployment with `oauth-jwt`; static token and server-grant variables are rejected in that profile.
4. Static bearer credentials are not converted into JWTs and must not be reused as authorization-server client secrets.
5. No earlier than `0.4.0`, non-loopback deployments may require an explicit profile after release notes and startup warnings have provided a migration window.

Docker Compose remains backward-compatible with the controlled static-bearer profile and is now profile-aware for `oauth-jwt`. The OAuth example uses only variable names and safe placeholder URLs; legacy static-token/subject values are empty in that profile. Real issuer deployment details, access tokens, client credentials, private keys, and signing material remain outside the repository in Doppler and/or the external authorization system.

## Required negative tests

Implementation issue #524 must include deterministic tests for:

- missing authorization header;
- token in a query string with no header;
- malformed bearer syntax and malformed JWT;
- invalid signature and unknown key identifier;
- expired and not-yet-valid tokens;
- missing subject;
- wrong issuer;
- wrong audience/resource;
- unknown scope and insufficient scope;
- untrusted client capability/session-grant headers;
- authorization header omitted on a later request in the same MCP session;
- token for principal A attempting to access principal B's session;
- audit/log output containing no raw token or signing material.

A bounded local test fixture may generate ephemeral asymmetric keys and tokens. Private keys and generated tokens must remain temporary test data and must not be committed.

## Bounded implementation sequence

#524 should be delivered as reviewable changes in this order:

1. **Configuration and startup validation — complete:** introduced the versioned profile model, URI validation, compatibility inference, and fail-closed conflict tests without changing request authentication.
2. **FastMCP resource-server integration — complete:** constructs `RemoteAuthProvider(JWTVerifier(...))`, publishes protected-resource metadata, and normalizes stable `401` challenges.
3. **Scope/principal adapter — complete:** reads FastMCP's validated access-token context, maps only fixed scopes to the capability ladder, binds a redacted stable `(iss, sub)` identity to `RequestPrincipal`, ignores legacy grants for OAuth authority, and checks minimum scope before object access.
4. **Object and denial integration — complete:** preserves central session ACL behavior across the HTTP surface, returns transport-level `403 insufficient_scope` before object access, keeps valid-principal ACL failure as `OBJECT_NOT_AUTHORIZED`, records redacted authorization audit identity, and enables the supported OAuth listener.
5. **End-to-end evidence and migration — complete:** `tests/test_mcp_oauth_jwt_e2e.py` generates ephemeral asymmetric RS256 keys/JWTs in memory and exercises the real FastMCP verifier/HTTP boundary across the required negative matrix; Compose forwards the versioned OAuth profile and validates packaged discovery/missing-bearer behavior; `.env.example` and deployment docs contain safe public placeholders only; the Quality workflow uploads the redacted `compose-runtime-smoke` evidence artifact.

Each change must keep existing stdio, loopback, controlled static-bearer, MCP compatibility, network hardening, object authorization, security, and release-gate tests green. The historical Sonar debt budget must not be raised to accommodate the implementation.

## Slice 5 verification evidence

- `tests/test_mcp_oauth_jwt_e2e.py` creates an ephemeral asymmetric RSA keypair and JWKS entirely in test memory. It exercises the real `RemoteAuthProvider`/`JWTVerifier` path for valid RS256 tokens and deterministic denials covering malformed JWTs, `alg=none`, symmetric HMAC, invalid signatures, unknown `kid`, missing/expired `exp`, future or malformed `nbf`, missing subject, wrong issuer, wrong audience/resource, unknown scope, client self-grants, omitted follow-up authorization, token passthrough, and cross-principal session access. Generated private keys and tokens are never committed.
- `scripts/ci_compose_smoke.py` exercises the packaged static-bearer service and then recreates the MCP container with the versioned `oauth-jwt` profile. It validates RFC 9728 discovery and the missing-bearer challenge without placing a bearer token or signing material in the OAuth container.
- `artifacts/compose-smoke/summary.json` is the redacted machine-readable deployment evidence produced by that smoke run. The Quality workflow uploads it as `compose-runtime-smoke`; it contains the public provider/configuration identity and exercised denial cases, not credentials or private material.
- `.env.example` and `docs/mcp-http-deployment.md` provide migration through public placeholder URLs only. Production secrets remain external; TLS termination, public multi-tenant isolation, authorization-server operation, and public-hosting certification remain non-goals.

## Non-goals

This contract does not operate an authorization server, store user credentials, enable arbitrary identity providers, certify public hosting, establish general multi-tenant isolation, terminate TLS, configure an external gateway, or replace human engineering review for hardware outputs.

## References

- [MCP authorization specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [MCP security best practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices)
- [FastMCP authentication providers](https://gofastmcp.com/servers/auth/authentication)
- [FastMCP remote OAuth](https://gofastmcp.com/servers/auth/remote-oauth)
- [FastMCP token verification](https://gofastmcp.com/servers/auth/token-verification)
