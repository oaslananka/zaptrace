# Network transport authentication

ZapTrace network transports are secure by default. The supported REST and MCP HTTP launchers bind to `127.0.0.1`, reject unauthenticated non-loopback startup, and keep client-controlled capability grants disabled unless an explicit loopback-development override is enabled.

## Shared policy

- `127.0.0.1`, any `127.0.0.0/8` address, `::1`, and `localhost` are treated as loopback.
- `0.0.0.0`, `::`, LAN addresses, and DNS names are treated as non-loopback.
- Non-loopback startup requires a configured authentication profile. Controlled static bearer remains available. The supported `oauth-jwt` profile uses the FastMCP provider/discovery boundary, validated scope/principal adapter, per-request `403 insufficient_scope` enforcement, and central object-authorization audit.
- Local capability or session self-grants are rejected on non-loopback binds, even when authentication exists.
- Static bearer credentials use constant-time comparison.
- Server-controlled capability configuration determines effective production permissions.

## REST startup matrix

| Bind target | Authentication | Local capability headers | Result |
|---|---:|---:|---|
| Loopback | absent | disabled | Allowed. Read-only access; mutating calls are denied. |
| Loopback | configured | disabled | Allowed. Authenticated identity and server scopes apply. |
| Loopback | absent | enabled | Allowed as explicit local-development mode. |
| Non-loopback | absent | disabled | Startup fails. |
| Non-loopback | configured | disabled | Allowed. Every `/api/*` request requires authentication. |
| Non-loopback | any | enabled | Startup fails because client-granted capabilities are local-only. |

REST production capabilities come from `ZAPTRACE_API_TOKEN_SCOPES`. The authenticated actor comes from `ZAPTRACE_API_TOKEN_SUBJECT`, and session access can be bounded with `ZAPTRACE_API_TOKEN_SESSIONS`.

## MCP HTTP startup matrix

The stdio transport remains the preferred local integration and opens no network listener.

| Transport/bind | Authentication | Local session grants | Result |
|---|---:|---:|---|
| stdio | n/a | optional explicit opt-in | Allowed; no network listener. |
| HTTP loopback | absent | disabled | Allowed; mutating tools remain deny-by-default. |
| HTTP loopback | configured | disabled | Allowed; every HTTP request requires authentication. |
| HTTP non-loopback | absent | disabled | Startup fails. |
| HTTP non-loopback | configured | disabled | Allowed with either the controlled static-bearer profile or the supported `oauth-jwt` resource-server profile. OAuth/JWT requests are re-authorized from the current validated token on every request. |
| HTTP non-loopback | any | enabled | Startup fails because session self-grants are loopback-only. |

Controlled static-bearer MCP capabilities come from `ZAPTRACE_MCP_CAPABILITIES`. The authenticated actor comes from `ZAPTRACE_MCP_TOKEN_SUBJECT`. Missing or invalid credentials receive `401 AUTH_REQUIRED` with `WWW-Authenticate: Bearer`. The versioned production resource-server, scope, discovery, challenge, and migration contract is [MCP HTTP authorization contract](mcp-http-authorization-contract.md).

## Local development

REST capability headers require `ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS=1`. MCP session self-grants require `ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS=1`.

These overrides are intentionally rejected for non-loopback binds. Do not expose them through a reverse proxy. Direct custom Uvicorn launch commands are responsible for reproducing the same policy; the supported ZapTrace entry points perform startup validation automatically.

Trusted-proxy resolution, streamed request-body limits, bounded rate limiting, and multi-worker constraints are documented in [REST API Abuse Controls](api-abuse-controls.md).

## Audit evidence

Authorization events include the surface, session, authenticated actor, effective capabilities, authorization source, requested tool, decision, and reason. This evidence allows proof packs and engineering reviews to distinguish authenticated production calls from explicit loopback-development calls.
