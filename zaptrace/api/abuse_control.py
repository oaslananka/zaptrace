"""Trusted-proxy, request-size, and rate-limit controls for the REST API."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network
from typing import Protocol, runtime_checkable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SECURITY_LOGGER = logging.getLogger("zaptrace.api.security")

_DEFAULT_MAX_BODY_BYTES = 10 * 1024 * 1024
_DEFAULT_RATE_LIMIT_REQUESTS = 120
_DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
_DEFAULT_RATE_LIMIT_MAX_KEYS = 10_000
_DEFAULT_RATE_LIMIT_CLEANUP_INTERVAL_SECONDS = 300

IPAddress = IPv4Address | IPv6Address
IPNetwork = IPv4Network | IPv6Network


def _positive_int(environment: Mapping[str, str], name: str, default: int) -> int:
    raw = environment.get(name)
    if raw is None:
        return default
    normalized = raw.strip()
    if not normalized.isdecimal() or int(normalized) <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return int(normalized)


@dataclass(frozen=True)
class TrustedProxyPolicy:
    """IP networks whose direct connections may supply forwarding metadata."""

    networks: tuple[IPNetwork, ...]

    @classmethod
    def empty(cls) -> TrustedProxyPolicy:
        return cls(networks=())

    @classmethod
    def from_strings(cls, values: Iterable[str]) -> TrustedProxyPolicy:
        networks: list[IPNetwork] = []
        for raw in values:
            value = raw.strip()
            if not value:
                continue
            try:
                networks.append(ip_network(value, strict=False))
            except ValueError as exc:
                raise RuntimeError(f"ZAPTRACE_API_TRUSTED_PROXIES contains invalid network {value!r}") from exc
        return cls(networks=tuple(networks))

    def trusts(self, address: IPAddress) -> bool:
        return any(address in network for network in self.networks if address.version == network.version)


def _parse_address(raw: str) -> IPAddress | None:
    value = raw.strip().strip("[]")
    if not value:
        return None
    try:
        return ip_address(value)
    except ValueError:
        return None


def resolve_client_ip(peer_host: str, forwarded_for: str, policy: TrustedProxyPolicy) -> str:
    """Resolve the rate-limit identity without trusting unapproved proxies.

    The direct peer is authoritative unless it belongs to a configured trusted
    proxy network. For a trusted peer, the forwarded chain is evaluated from
    right to left and the nearest untrusted address is used.
    """
    peer = _parse_address(peer_host)
    if peer is None:
        return "unknown"
    if not forwarded_for or not policy.trusts(peer):
        return str(peer)

    chain: list[IPAddress] = []
    for item in forwarded_for.split(","):
        address = _parse_address(item)
        if address is None:
            return str(peer)
        chain.append(address)
    if not chain:
        return str(peer)

    for address in reversed(chain):
        if not policy.trusts(address):
            return str(address)
    return str(chain[0])


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    window_seconds: int
    reason: str = "allowed"


@runtime_checkable
class RateLimitBackend(Protocol):
    """Backend contract for one sliding-window rate-limit namespace."""

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision: ...

    def info(self, key: str, *, now: float | None = None) -> RateLimitDecision: ...

    def reset(self) -> None: ...


class InMemorySlidingWindowRateLimiter:
    """Bounded single-process sliding-window implementation."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        max_keys: int,
        cleanup_interval_seconds: int,
    ) -> None:
        if min(limit, window_seconds, max_keys, cleanup_interval_seconds) <= 0:
            raise ValueError("rate-limit values must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self._hits: dict[str, deque[float]] = {}
        self._last_cleanup = 0.0
        self._lock = threading.RLock()

    @property
    def key_count(self) -> int:
        with self._lock:
            return len(self._hits)

    @property
    def keys(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._hits))

    def _prune_key(self, key: str, window_start: float) -> deque[float]:
        hits = self._hits.get(key, deque())
        while hits and hits[0] <= window_start:
            hits.popleft()
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def _cleanup(self, now: float, *, force: bool = False) -> None:
        if not force and now - self._last_cleanup < self.cleanup_interval_seconds:
            return
        window_start = now - self.window_seconds
        for key in tuple(self._hits):
            self._prune_key(key, window_start)
        self._last_cleanup = now

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        current = time.time() if now is None else now
        window_start = current - self.window_seconds
        with self._lock:
            self._cleanup(current)
            hits = self._prune_key(key, window_start)
            if key not in self._hits and len(self._hits) >= self.max_keys:
                self._cleanup(current, force=True)
                if len(self._hits) >= self.max_keys:
                    return RateLimitDecision(
                        allowed=False,
                        limit=self.limit,
                        remaining=0,
                        window_seconds=self.window_seconds,
                        reason="key-capacity",
                    )
                hits = deque()
            if len(hits) >= self.limit:
                return RateLimitDecision(
                    allowed=False,
                    limit=self.limit,
                    remaining=0,
                    window_seconds=self.window_seconds,
                    reason="request-limit",
                )
            hits.append(current)
            self._hits[key] = hits
            return RateLimitDecision(
                allowed=True,
                limit=self.limit,
                remaining=max(0, self.limit - len(hits)),
                window_seconds=self.window_seconds,
            )

    def info(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        current = time.time() if now is None else now
        with self._lock:
            hits = self._prune_key(key, current - self.window_seconds)
            return RateLimitDecision(
                allowed=len(hits) < self.limit,
                limit=self.limit,
                remaining=max(0, self.limit - len(hits)),
                window_seconds=self.window_seconds,
                reason="request-limit" if len(hits) >= self.limit else "allowed",
            )

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._last_cleanup = 0.0


@dataclass(frozen=True)
class AbuseControlConfiguration:
    max_body_bytes: int
    trusted_proxies: TrustedProxyPolicy
    rate_limit_requests: int
    rate_limit_window_seconds: int
    rate_limit_max_keys: int
    rate_limit_cleanup_interval_seconds: int
    rate_limit_backend: str
    workers: int

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> AbuseControlConfiguration:
        env = os.environ if environment is None else environment
        trusted_raw = env.get("ZAPTRACE_API_TRUSTED_PROXIES", "")
        backend = env.get("ZAPTRACE_API_RATE_LIMIT_BACKEND", "memory").strip().lower()
        if backend != "memory":
            raise RuntimeError(
                "ZAPTRACE_API_RATE_LIMIT_BACKEND must be 'memory' in this distribution; "
                "inject a RateLimitBackend for a controlled shared deployment"
            )
        return cls(
            max_body_bytes=_positive_int(env, "ZAPTRACE_API_MAX_BODY_BYTES", _DEFAULT_MAX_BODY_BYTES),
            trusted_proxies=TrustedProxyPolicy.from_strings(trusted_raw.split(",")),
            rate_limit_requests=_positive_int(
                env,
                "ZAPTRACE_API_RATE_LIMIT_REQUESTS",
                _DEFAULT_RATE_LIMIT_REQUESTS,
            ),
            rate_limit_window_seconds=_positive_int(
                env,
                "ZAPTRACE_API_RATE_LIMIT_WINDOW_SECONDS",
                _DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
            ),
            rate_limit_max_keys=_positive_int(
                env,
                "ZAPTRACE_API_RATE_LIMIT_MAX_KEYS",
                _DEFAULT_RATE_LIMIT_MAX_KEYS,
            ),
            rate_limit_cleanup_interval_seconds=_positive_int(
                env,
                "ZAPTRACE_API_RATE_LIMIT_CLEANUP_INTERVAL_SECONDS",
                _DEFAULT_RATE_LIMIT_CLEANUP_INTERVAL_SECONDS,
            ),
            rate_limit_backend=backend,
            workers=_positive_int(env, "ZAPTRACE_API_WORKERS", 1),
        )

    def validate_deployment(self) -> None:
        if self.workers > 1 and self.rate_limit_backend == "memory":
            raise RuntimeError(
                "ZapTrace REST API multi-worker deployment requires a shared rate-limit backend; "
                "the built-in memory backend is single-process only"
            )

    def build_backend(self) -> RateLimitBackend:
        self.validate_deployment()
        return InMemorySlidingWindowRateLimiter(
            limit=self.rate_limit_requests,
            window_seconds=self.rate_limit_window_seconds,
            max_keys=self.rate_limit_max_keys,
            cleanup_interval_seconds=self.rate_limit_cleanup_interval_seconds,
        )


def log_rejection(*, code: str, client_ip: str, path: str, reason: str) -> None:
    SECURITY_LOGGER.warning(
        "API request rejected",
        extra={
            "event": "api_request_rejected",
            "code": code,
            "client_ip": client_ip,
            "request_path": path,
            "reason": reason,
        },
    )


class RequestBodyLimitMiddleware:
    """Count HTTP request bytes while they are consumed by the application."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def _reject(self, scope: Scope, receive: Receive, send: Send, *, reason: str) -> None:
        client = scope.get("client")
        client_ip = str(client[0]) if client else "unknown"
        log_rejection(
            code="PAYLOAD_TOO_LARGE",
            client_ip=client_ip,
            path=str(scope.get("path", "")),
            reason=reason,
        )
        response = JSONResponse(
            status_code=413,
            content={
                "ok": False,
                "error": {
                    "code": "PAYLOAD_TOO_LARGE",
                    "message": f"Request body exceeds {self.max_body_bytes} byte limit",
                },
            },
        )
        await response(scope, receive, send)

    def _declared_body_too_large(self, scope: Scope) -> bool:
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is None:
            return False
        try:
            return int(content_length) > self.max_body_bytes
        except ValueError:
            return False

    async def _run_with_stream_limit(self, scope: Scope, receive: Receive, send: Send) -> None:
        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] != "http.request":
                return message
            received += len(message.get("body", b""))
            if received > self.max_body_bytes:
                raise _PayloadTooLargeError
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            response_started = response_started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _PayloadTooLargeError:
            if response_started:
                raise
            await self._reject(scope, receive, send, reason="streamed-body")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if self._declared_body_too_large(scope):
            await self._reject(scope, receive, send, reason="declared-content-length")
            return
        await self._run_with_stream_limit(scope, receive, send)


class _PayloadTooLargeError(Exception):
    pass
