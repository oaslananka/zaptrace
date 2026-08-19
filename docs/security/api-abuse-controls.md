# REST API abuse controls

ZapTrace applies bounded request-body and per-client request-rate controls in the
REST API process. These controls reduce accidental and low-complexity abuse; they
do not replace a reverse proxy, API gateway, WAF, authentication, or deployment
monitoring.

## Policy table

| Control | Default | Failure response | Boundary |
|---|---:|---:|---|
| Request body | 10 MiB | `413 PAYLOAD_TOO_LARGE` | Counts streamed chunks and also rejects an oversized declared `Content-Length`. |
| Request rate | 120 requests / 60 seconds | `429 RATE_LIMITED` | Sliding window per resolved client identity. |
| Client-key cardinality | 10,000 active keys | `429 RATE_LIMITED` | New identities fail closed when the bounded in-memory table is full. |
| Forwarded client address | Disabled unless the direct peer is trusted | Uses direct peer | Only configured proxy CIDRs may supply `X-Forwarded-For`. |
| Worker count | One with the built-in backend | Startup failure | Multi-worker service requires an injected shared rate-limit backend or gateway-level enforcement. |

Rejected requests emit a structured `zaptrace.api.security` log record with the
event `api_request_rejected`, response code, resolved client identity, path, and
rejection reason.

## Environment configuration

| Variable | Meaning | Default |
|---|---|---|
| `ZAPTRACE_API_TRUSTED_PROXIES` | Comma-separated IP addresses or CIDRs allowed to provide `X-Forwarded-For`. | Empty; forwarding headers ignored. |
| `ZAPTRACE_API_MAX_BODY_BYTES` | Maximum request body after counting all streamed chunks. | `10485760` |
| `ZAPTRACE_API_RATE_LIMIT_REQUESTS` | Requests allowed in one window. | `120` |
| `ZAPTRACE_API_RATE_LIMIT_WINDOW_SECONDS` | Sliding-window duration. | `60` |
| `ZAPTRACE_API_RATE_LIMIT_MAX_KEYS` | Maximum active in-memory client identities. | `10000` |
| `ZAPTRACE_API_RATE_LIMIT_CLEANUP_INTERVAL_SECONDS` | Maximum delay between global stale-key sweeps. | `300` |
| `ZAPTRACE_API_RATE_LIMIT_BACKEND` | Built-in backend selection. The distributed package currently accepts `memory`. | `memory` |
| `ZAPTRACE_API_WORKERS` | Intended API worker count used for startup validation. | `1` |

Every numeric setting must be a positive integer. Invalid networks, values, or
unsupported backends fail startup rather than silently weakening controls.

## Trusted reverse proxy example

A deployment with a reverse proxy on `10.20.0.0/16` can use:

```bash
export ZAPTRACE_API_TRUSTED_PROXIES="10.20.0.0/16"
export ZAPTRACE_API_MAX_BODY_BYTES="10485760"
export ZAPTRACE_API_RATE_LIMIT_REQUESTS="120"
export ZAPTRACE_API_RATE_LIMIT_WINDOW_SECONDS="60"
export ZAPTRACE_API_RATE_LIMIT_MAX_KEYS="10000"
export ZAPTRACE_API_WORKERS="1"
```

The proxy must overwrite, not append blindly to, inbound forwarding headers and
must enforce its own connection, header, request-body, and request-rate limits.
ZapTrace evaluates a trusted chain from right to left and selects the nearest
untrusted address. A direct untrusted peer cannot change its rate-limit identity
by sending a forged forwarding header.

## Single-process and multi-worker deployments

The built-in backend is dependency-light and intentionally single-process. Its
state resets on process restart and is not synchronized between workers. Setting
`ZAPTRACE_API_WORKERS` above `1` with `ZAPTRACE_API_RATE_LIMIT_BACKEND=memory`
fails configuration validation.

A controlled multi-worker integration must inject an implementation of the
`RateLimitBackend` protocol backed by a shared rate-limit backend, or enforce the
same policy at a trusted gateway. Starting several independent memory-backed
workers and describing the result as one consistent rate limit is unsupported.

## Operational non-claims

A successful local rate-limit decision does not establish identity, authorization,
DDoS resistance, or multi-tenant isolation. Keep non-loopback authentication,
object authorization, gateway policy, logs, and resource monitoring enabled.
