from __future__ import annotations

import logging
from ipaddress import ip_address
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from zaptrace.api.abuse_control import (
    AbuseControlConfiguration,
    InMemorySlidingWindowRateLimiter,
    RateLimitBackend,
    TrustedProxyPolicy,
    resolve_client_ip,
)
from zaptrace.api.server import create_app


def test_untrusted_peer_cannot_spoof_forwarded_client_address() -> None:
    policy = TrustedProxyPolicy.from_strings(["10.0.0.0/8"])

    assert resolve_client_ip("203.0.113.20", "198.51.100.8", policy) == "203.0.113.20"


def test_trusted_proxy_chain_resolves_nearest_untrusted_client() -> None:
    policy = TrustedProxyPolicy.from_strings(["10.0.0.0/8", "2001:db8:ffff::/48"])

    assert resolve_client_ip("10.0.0.3", "198.51.100.8, 10.0.0.2", policy) == "198.51.100.8"
    assert resolve_client_ip("2001:db8:ffff::2", "2001:db8:1234::10, 2001:db8:ffff::1", policy) == "2001:db8:1234::10"


def test_invalid_forwarded_chain_fails_closed_to_direct_peer() -> None:
    policy = TrustedProxyPolicy.from_strings(["10.0.0.0/8"])

    assert resolve_client_ip("10.0.0.3", "not-an-ip, 10.0.0.2", policy) == "10.0.0.3"


def test_in_memory_rate_limiter_is_bounded_and_removes_stale_keys() -> None:
    limiter = InMemorySlidingWindowRateLimiter(
        limit=2,
        window_seconds=10,
        max_keys=2,
        cleanup_interval_seconds=5,
    )
    assert isinstance(limiter, RateLimitBackend)

    assert limiter.check("client-a", now=0).allowed is True
    assert limiter.check("client-a", now=1).allowed is True
    assert limiter.check("client-a", now=2).allowed is False
    assert limiter.check("client-b", now=2).allowed is True
    assert limiter.key_count == 2

    capacity = limiter.check("client-c", now=2)
    assert capacity.allowed is False
    assert capacity.reason == "key-capacity"

    assert limiter.check("client-c", now=20).allowed is True
    assert limiter.key_count == 1
    assert limiter.keys == ("client-c",)


def test_multi_worker_memory_rate_limit_configuration_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_API_WORKERS", "2")
    monkeypatch.setenv("ZAPTRACE_API_RATE_LIMIT_BACKEND", "memory")

    configuration = AbuseControlConfiguration.from_environment()
    with pytest.raises(RuntimeError, match="multi-worker.*shared rate-limit backend"):
        configuration.validate_deployment()


def test_invalid_trusted_proxy_network_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_API_TRUSTED_PROXIES", "10.0.0.0/8,not-a-network")

    with pytest.raises(RuntimeError, match="ZAPTRACE_API_TRUSTED_PROXIES"):
        AbuseControlConfiguration.from_environment()


def test_oversized_stream_without_content_length_is_rejected() -> None:
    config = AbuseControlConfiguration(
        max_body_bytes=8,
        trusted_proxies=TrustedProxyPolicy.empty(),
        rate_limit_requests=100,
        rate_limit_window_seconds=60,
        rate_limit_max_keys=100,
        rate_limit_cleanup_interval_seconds=60,
        rate_limit_backend="memory",
        workers=1,
    )
    app = create_app(abuse_control=config)

    @app.post("/test/read-body")
    async def read_body(request: Request) -> JSONResponse:
        body = await request.body()
        return JSONResponse({"size": len(body)})

    def chunks():
        yield b"12345"
        yield b"67890"

    response = TestClient(app, client=("127.0.0.1", 50000)).post(
        "/test/read-body",
        content=chunks(),
        headers={"Transfer-Encoding": "chunked"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_rate_limit_rejection_emits_structured_security_log(caplog: pytest.LogCaptureFixture) -> None:
    config = AbuseControlConfiguration(
        max_body_bytes=1024,
        trusted_proxies=TrustedProxyPolicy.empty(),
        rate_limit_requests=1,
        rate_limit_window_seconds=60,
        rate_limit_max_keys=100,
        rate_limit_cleanup_interval_seconds=60,
        rate_limit_backend="memory",
        workers=1,
    )
    client = TestClient(create_app(abuse_control=config), client=("127.0.0.1", 50000))

    assert client.get("/health").status_code == 200
    with caplog.at_level(logging.WARNING, logger="zaptrace.api.security"):
        rejected = client.get("/health")

    assert rejected.status_code == 429
    record = next(record for record in caplog.records if getattr(record, "event", "") == "api_request_rejected")
    assert record.code == "RATE_LIMITED"
    assert ip_address(record.client_ip).is_loopback


def _test_config(*, trusted: TrustedProxyPolicy, requests: int = 1) -> AbuseControlConfiguration:
    return AbuseControlConfiguration(
        max_body_bytes=1024,
        trusted_proxies=trusted,
        rate_limit_requests=requests,
        rate_limit_window_seconds=60,
        rate_limit_max_keys=100,
        rate_limit_cleanup_interval_seconds=60,
        rate_limit_backend="memory",
        workers=1,
    )


def test_spoofed_forwarded_addresses_do_not_bypass_integrated_rate_limit() -> None:
    client = TestClient(
        create_app(abuse_control=_test_config(trusted=TrustedProxyPolicy.empty())),
        client=("203.0.113.20", 50000),
    )

    assert client.get("/health", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    assert client.get("/health", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 429


def test_trusted_proxy_can_separate_forwarded_clients() -> None:
    client = TestClient(
        create_app(abuse_control=_test_config(trusted=TrustedProxyPolicy.from_strings(["10.0.0.0/8"]))),
        client=("10.0.0.2", 50000),
    )

    assert client.get("/health", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    assert client.get("/health", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 200


def test_new_in_memory_backend_starts_with_empty_rate_state() -> None:
    config = _test_config(trusted=TrustedProxyPolicy.empty())
    first = config.build_backend()
    assert first.check("client").allowed is True
    assert first.check("client").allowed is False

    restarted = config.build_backend()
    assert restarted.check("client").allowed is True


def test_api_abuse_control_deployment_policy_is_documented() -> None:
    document = Path("docs/security/api-abuse-controls.md").read_text(encoding="utf-8")

    for value in (
        "ZAPTRACE_API_TRUSTED_PROXIES",
        "ZAPTRACE_API_MAX_BODY_BYTES",
        "ZAPTRACE_API_RATE_LIMIT_MAX_KEYS",
        "ZAPTRACE_API_RATE_LIMIT_BACKEND",
        "ZAPTRACE_API_WORKERS",
        "single-process",
        "shared rate-limit backend",
        "reverse proxy",
        "413",
        "429",
    ):
        assert value in document


def test_cors_is_outermost_application_middleware() -> None:
    from starlette.middleware.cors import CORSMiddleware

    application = create_app(abuse_control=_test_config(trusted=TrustedProxyPolicy.empty(), requests=10))

    assert application.user_middleware[0].cls is CORSMiddleware
