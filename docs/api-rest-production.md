# REST API production hardening

ZapTrace REST is designed for local, CI, and controlled team deployments. The supported `zaptrace-api` entry point is secure by default: it binds to `127.0.0.1`, rejects unauthenticated non-loopback startup, and does not accept client-granted capability headers unless local development mode is explicitly enabled.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `ZAPTRACE_API_HOST` | REST bind host. | `127.0.0.1` |
| `ZAPTRACE_API_PORT` | REST bind port in `1..65535`. | `8080` |
| `ZAPTRACE_API_TOKEN` | Static bearer token. Required when binding beyond loopback. `/api/*` requests must send `Authorization: Bearer <token>`. | unset |
| `ZAPTRACE_API_TOKEN_SCOPES` | Server-controlled capability grants for the authenticated token. | none |
| `ZAPTRACE_API_TOKEN_SUBJECT` | Actor recorded in authorization audit events. | `api-token` |
| `ZAPTRACE_API_TOKEN_AUDIENCE` | Optional required `X-ZapTrace-Audience` value. | unset |
| `ZAPTRACE_API_TOKEN_SESSIONS` | Comma/space-separated session IDs available to the token; `*` permits all sessions. | `*` |
| `ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS` | Explicitly enable capability and actor headers for loopback-only development. Startup fails if this is enabled on a non-loopback bind. | disabled |
| `ZAPTRACE_CORS_ORIGINS` | Comma-separated allowed browser origins. | `http://localhost:5173,http://localhost:8080` |
| `ZAPTRACE_API_ARTIFACT_ROOT` | Filesystem root for REST artifact storage. | `.zaptrace/api-artifacts` |
| `ZAPTRACE_API_ARTIFACT_RETENTION_SECONDS` | Artifact retention before cleanup. | `86400` |
| `ZAPTRACE_API_MAX_ARTIFACT_BYTES` | Maximum stored artifact payload size. | `5242880` |

Static bearer credentials are compared with a constant-time comparison. Invalid or missing credentials return `401 AUTH_REQUIRED`; audience failures return `403 AUTH_AUDIENCE_MISMATCH`.

## Startup configuration matrix

| Bind target | Bearer token | Local capability headers | Result |
|---|---:|---:|---|
| `127.0.0.1` / `::1` | no | no | Allowed. Read-only API access; mutating calls are denied. |
| `127.0.0.1` / `::1` | yes | no | Allowed. Token identity and server-configured scopes apply. |
| `127.0.0.1` / `::1` | no | yes | Allowed only as explicit local development mode. |
| `0.0.0.0`, `::`, LAN/DNS address | no | no | Startup fails. |
| `0.0.0.0`, `::`, LAN/DNS address | yes | no | Allowed. Every `/api/*` request requires the token. |
| Any non-loopback target | yes/no | yes | Startup fails because client-granted capabilities are local-only. |

Secure team deployment example:

```bash
export ZAPTRACE_API_TOKEN='replace-with-a-long-random-secret'
export ZAPTRACE_API_TOKEN_SUBJECT='ci-agent'
export ZAPTRACE_API_TOKEN_SCOPES='preview-write sandbox-write'
export ZAPTRACE_API_TOKEN_SESSIONS='ci-session'
python -c 'from zaptrace.api.server import run; run(host="0.0.0.0", port=8080)'
```

Docker Compose authenticated deployment:

```bash
cp .env.example .env
# Edit .env and set independently generated API and MCP bearer tokens.
docker compose up --build --wait
```

The Compose file passes both token settings to the authenticated services, binds the processes to the container network, and publishes ports only on host `127.0.0.1`. It also provides protocol-aware health checks. If a token is empty, the corresponding packaged entry point rejects the non-loopback bind before Uvicorn starts and emits a clear diagnostic.

For an internal, non-published loopback diagnostic service:

```bash
docker compose --profile loopback-development up --build zaptrace-api-loopback
```

Loopback-only development example:

```bash
export ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS=1
zaptrace-api
```

Do not expose local capability-header mode through a reverse proxy or non-loopback bind. Direct custom Uvicorn launch commands are responsible for reproducing the same startup policy; the supported `zaptrace-api` entry point performs the validation automatically.

## Authorization model

Read-only routes remain available in loopback development. In authenticated deployments, every session-scoped read or write requires an explicit `X-ZapTrace-Session-Id`. Mutating routes additionally require one of these two authorization sources:

1. an authenticated bearer identity with capabilities from `ZAPTRACE_API_TOKEN_SCOPES`; or
2. explicit loopback development mode with `X-ZapTrace-Capabilities` enabled by `ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS=1`.

Without the local-development opt-in, `X-ZapTrace-Capabilities` and `X-ZapTrace-Actor` cannot grant permissions or spoof an audit actor. Capability decisions record the authenticated principal, effective grants, source, request path, and decision in the session audit log.

Session identifiers are object selectors, not authority. The first authorized principal owns a newly claimed session; later access requires ownership, an explicit delegate grant, or the `object-admin` scope. Cross-principal failures return `403 OBJECT_NOT_AUTHORIZED` without revealing whether a guessed identifier exists.

Session lifecycle and delegation endpoints:

```text
POST   /api/v1/agent/sessions
GET    /api/v1/agent/sessions/{session_id}/access
POST   /api/v1/agent/sessions/{session_id}/delegates/{principal_id}
DELETE /api/v1/agent/sessions/{session_id}/delegates/{principal_id}
```

Creating a session requires `preview-write`; changing delegates requires `approved-commit`. Delegation does not transfer capabilities: each principal must still satisfy the tool capability gate. See [Object-level authorization](security/object-authorization.md).

Examples:

- `preview-write`: parse/synthesize/register deterministic artifacts;
- `sandbox-write`: layout mutation, transaction validation, artifact deletion/cleanup;
- `approved-commit`: transaction commit after approval;
- `release-export`: KiCad/manufacturing export gates.

## Artifact lifecycle

The `/api/v1/artifacts` routes provide deterministic artifact metadata for CI and review workflows:

- `POST /api/v1/artifacts`: store UTF-8 content under an opaque server-generated artifact ID;
- `GET /api/v1/artifacts`: list artifacts for the active session;
- `DELETE /api/v1/artifacts/{artifact_id}`: delete one session artifact;
- `DELETE /api/v1/artifacts/expired`: remove expired artifacts according to retention policy;
- `GET /api/v1/artifacts/config`: expose storage configuration for clients and smoke tests.

Artifact records include `owner_principal`, `sha256`, `size_bytes`, `created_at`, `retention_seconds`, and a root-relative path. Session IDs, client filenames, artifact selectors, and design names are stored only as metadata; filesystem locations use server-generated opaque directories and fixed payload filenames. Expiration cleanup is restricted to the authorized session. The API does not claim cloud storage, multi-tenant isolation, or procurement/manufacturing approval.

## OpenAPI contract

`/openapi.json` is part of the CI surface. Tests assert that hardened routes and artifact lifecycle endpoints remain visible to clients.

## Container deployment non-claims

The Compose example does not provide TLS termination, public hosting certification, multi-tenant isolation, production distributed rate limiting, reverse-proxy trust configuration, or Kubernetes deployment. Keep published ports on host loopback and place a separately reviewed TLS proxy in front of controlled team deployments.
