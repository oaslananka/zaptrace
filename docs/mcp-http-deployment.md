# MCP HTTP deployment

`zaptrace-mcp` is the stdio entry point used by local MCP clients. Network deployments use the separate `zaptrace-mcp-http` entry point so transport choice cannot drift through undocumented command-line flags.

The current HTTP runtime supports secure loopback operation, a controlled static-bearer profile, and the versioned supported `oauth-jwt` resource-server profile. Slices 2-5 provide the FastMCP JWT provider/discovery app, stable bearer challenges, fixed validated scope mapping, redacted `(iss, sub)` principals, per-request transport scope enforcement, object authorization/audit integration, real asymmetric-JWT negative coverage, and packaged Compose evidence. The complete design and verification contract are defined in [MCP HTTP authorization contract](security/mcp-http-authorization-contract.md).

## MCP protocol compatibility

The current HTTP protocol path is MCP `2026-07-28`. Its stateless protocol core does not use `Mcp-Session-Id` and does not require the legacy `initialize` / `initialized` handshake. Modern requests carry protocol and client metadata per request, may use `server/discover`, and expose method/tool routing through the standard MCP headers.

Existing legacy handshake-era clients remain supported by the same FastMCP deployment through the SDK compatibility path. ZapTrace keeps that compatibility intentionally, but new integrations should use the current protocol line. A legacy transport session is compatibility state only; it is not an authorization cache.

ZapTrace design persistence is independent of either protocol era. An application-level `session_id` returned by `session_create` is an explicit ZapTrace object handle that callers pass to tools when they need isolated design state. Authorization and object access are still evaluated on each HTTP request.

## Secure defaults

`zaptrace-mcp-http` binds to `127.0.0.1:8090` by default. The supported environment variables are:

| Variable | Purpose | Default |
|---|---|---|
| `ZAPTRACE_MCP_HTTP_HOST` | HTTP bind host. | `127.0.0.1` |
| `ZAPTRACE_MCP_HTTP_PORT` | HTTP bind port in `1..65535`. | `8090` |
| `ZAPTRACE_MCP_AUTH_CONFIG_VERSION` | Version for explicit profile selection. Must be `1`. | unset (legacy inference) |
| `ZAPTRACE_MCP_AUTH_PROFILE` | Explicit `local`, `static-bearer`, or `oauth-jwt` profile. | unset (legacy inference) |
| `ZAPTRACE_MCP_HTTP_TOKEN` | Static bearer token. Required by `static-bearer`. | unset |
| `ZAPTRACE_MCP_TOKEN_SUBJECT` | Stable principal recorded for the bearer token. | `mcp-token` |
| `ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS` | Explicit loopback-only development grant mode. | disabled |
| `ZAPTRACE_MCP_PUBLIC_BASE_URL` | Public HTTPS base URL used to construct the FastMCP resource-server provider and metadata. | unset |
| `ZAPTRACE_MCP_AUTH_RESOURCE_URI` | Exact HTTPS protected resource URI `<public-base-url>/mcp` used as the JWT audience and RFC 9728 resource. | unset |
| `ZAPTRACE_MCP_AUTHORIZATION_SERVER` | Exact canonical HTTPS authorization-server/issuer URL used by `JWTVerifier` and protected-resource metadata; a host-root issuer ends in `/`. | unset |
| `ZAPTRACE_MCP_AUTH_JWKS_URI` | HTTPS asymmetric JWKS URL used by `JWTVerifier`. | unset |

Start a native loopback server:

```bash
zaptrace-mcp-http
```

For a controlled single-tenant network bind, provide a token and explicit bind configuration:

```bash
export ZAPTRACE_MCP_HTTP_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export ZAPTRACE_MCP_HTTP_HOST=0.0.0.0
zaptrace-mcp-http
```

Requests to `/mcp` must send `Authorization: Bearer <token>`. Missing or invalid credentials return `401 AUTH_REQUIRED`. This static token is a bounded controlled-deployment credential, not a general OAuth or multi-tenant authorization profile. Compose publishes the authenticated service only on host loopback by default even though it binds to the container network interface.

## Versioned profile selection

Leaving both versioned variables unset preserves the `0.3.x` compatibility inference:

- a configured `ZAPTRACE_MCP_HTTP_TOKEN` selects controlled `static-bearer`;
- no token on an explicit loopback bind selects `local`;
- no token on a non-loopback bind fails startup.

For an explicit controlled static-bearer deployment:

```bash
export ZAPTRACE_MCP_AUTH_CONFIG_VERSION=1
export ZAPTRACE_MCP_AUTH_PROFILE=static-bearer
export ZAPTRACE_MCP_HTTP_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
zaptrace-mcp-http
```

Explicit profiles are exclusive. `local` rejects static-bearer and OAuth settings, `static-bearer` rejects OAuth settings and requires a token, and `oauth-jwt` rejects legacy token/subject/capability settings. OAuth URLs must use HTTPS, contain no credentials/query/fragment, and use the same origin for the public base and MCP resource URI.

A complete `oauth-jwt` configuration builds the FastMCP provider/discovery boundary and validated scope/principal adapter, then starts the supported HTTP listener. Every MCP request is re-authorized from the current validated token. Missing or invalid bearer credentials receive stable `401` challenges; insufficient tool scope receives RFC 6750 `403 insufficient_scope` with the minimum required scope before object access; a valid principal that fails a session ACL remains an MCP `OBJECT_NOT_AUTHORIZED` denial. OAuth authority ignores environment/session capability grants, and audit identity uses a redacted pair-bound principal rather than raw token or subject data.

For Compose migration to OAuth/JWT, use only public resource-server identity in `.env`; keep legacy static-bearer values empty:

```dotenv
ZAPTRACE_MCP_HTTP_TOKEN=
ZAPTRACE_MCP_TOKEN_SUBJECT=
ZAPTRACE_MCP_AUTH_CONFIG_VERSION=1
ZAPTRACE_MCP_AUTH_PROFILE=oauth-jwt
ZAPTRACE_MCP_PUBLIC_BASE_URL=https://mcp.example.com
ZAPTRACE_MCP_AUTH_RESOURCE_URI=https://mcp.example.com/mcp
ZAPTRACE_MCP_AUTHORIZATION_SERVER=https://auth.example.com/
ZAPTRACE_MCP_AUTH_JWKS_URI=https://auth.example.com/.well-known/jwks.json
```

These URLs are safe placeholders, not production issuer details. Access tokens, authorization-server credentials, private keys, and other signing material must not be stored in `.env`, Compose, or the repository. Maintained deployment secrets remain in Doppler or the external authorization system. ZapTrace remains a resource server and does not issue tokens.

## Docker Compose

Copy `.env.example` to `.env`, set independently generated REST and MCP tokens, then run:

```bash
cp .env.example .env
# Edit .env and set both token values.
docker compose up --build --wait
```

The MCP health check is profile-aware. The controlled static-bearer profile performs an authenticated MCP `2026-07-28` `server/discover` request and verifies that the modern response is stateless (no `Mcp-Session-Id`); `oauth-jwt` validates the public RFC 9728 protected-resource metadata without requiring or persisting a bearer token or signing material in the container health check. Logs remain available through `docker compose logs zaptrace-mcp-http`.

CI runs both packaged profiles in `scripts/ci_compose_smoke.py`: first the existing static-bearer MCP flow, then a recreated `oauth-jwt` container whose discovery metadata and missing-bearer `401` challenge are checked. The redacted machine-readable result is written to `artifacts/compose-smoke/summary.json` and uploaded by the Quality workflow as the `compose-runtime-smoke` artifact. It records public provider/configuration identity and exercised denial cases only; bearer tokens and signing material are excluded. Real signed-token validation is covered separately by `tests/test_mcp_oauth_jwt_e2e.py`, which creates ephemeral asymmetric RSA keys and JWTs in memory.

An internal, non-published development service is available for diagnostics:

```bash
docker compose --profile loopback-development up --build zaptrace-mcp-loopback
```

The loopback profile is accessible only inside its container; it is not a shortcut for host or LAN exposure.

## Non-claims

The controlled static-bearer profile does not provide OAuth resource discovery or audience-bound identity federation. The supported `oauth-jwt` profile provides resource-server discovery, audience-bound JWT validation, fixed scope mapping, and object authorization, but it does not provide TLS termination, public hosting certification, public multi-tenant isolation, external rate-limit infrastructure, reverse-proxy hardening, or Kubernetes deployment. Place a reviewed TLS reverse proxy in front of any controlled team deployment and keep the Compose-published ports bound to host loopback unless a separately reviewed deployment intentionally exposes the service.
