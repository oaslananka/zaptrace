"""FastAPI REST API server for ZapTrace — hardened with safety middleware."""

from __future__ import annotations

import hmac
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from zaptrace import __version__
from zaptrace.api.abuse_control import (
    AbuseControlConfiguration,
    RateLimitBackend,
    RequestBodyLimitMiddleware,
    log_rejection,
    resolve_client_ip,
)
from zaptrace.api.routes import api_router
from zaptrace.security.network import environment_flag, resolve_network_bind, validate_network_auth_configuration

API_VERSION = __version__

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class SecurityMiddleware:
    """Add authentication, security headers, and bounded rate limiting."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        abuse_control: AbuseControlConfiguration,
        rate_limit_backend: RateLimitBackend,
    ) -> None:
        self.app = app
        self.abuse_control = abuse_control
        self.rate_limit_backend = rate_limit_backend

    def _resolve_client_ip(self, request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        return resolve_client_ip(
            peer,
            request.headers.get("X-Forwarded-For", ""),
            self.abuse_control.trusted_proxies,
        )

    @staticmethod
    def _set_security_headers(headers: MutableHeaders) -> None:
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["X-XSS-Protection"] = "0"
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        headers["Cache-Control"] = "no-store"

    async def _respond(
        self,
        response: JSONResponse,
        *,
        scope: Scope,
        receive: Receive,
        send: Send,
        client_ip: str,
    ) -> None:
        info = self.rate_limit_backend.info(client_ip)
        response.headers["X-RateLimit-Limit"] = str(info.limit)
        response.headers["X-RateLimit-Remaining"] = str(info.remaining)
        self._set_security_headers(response.headers)
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        client_ip = self._resolve_client_ip(request)
        rate_limit = self.rate_limit_backend.check(client_ip)
        if not rate_limit.allowed:
            log_rejection(
                code="RATE_LIMITED",
                client_ip=client_ip,
                path=request.url.path,
                reason=rate_limit.reason,
            )
            await self._respond(
                JSONResponse(
                    status_code=429,
                    content={
                        "ok": False,
                        "error": {"code": "RATE_LIMITED", "message": "Too many requests. Try again later."},
                    },
                    headers={
                        "Retry-After": str(rate_limit.window_seconds),
                        "X-RateLimit-Limit": str(rate_limit.limit),
                    },
                ),
                scope=scope,
                receive=receive,
                send=send,
                client_ip=client_ip,
            )
            return

        api_token = os.environ.get("ZAPTRACE_API_TOKEN", "")
        if api_token and request.method != "OPTIONS" and request.url.path.startswith("/api/"):
            expected = f"Bearer {api_token}"
            if not hmac.compare_digest(request.headers.get("Authorization", ""), expected):
                await self._respond(
                    JSONResponse(
                        status_code=401,
                        content={
                            "ok": False,
                            "error": {"code": "AUTH_REQUIRED", "message": "Valid bearer token is required"},
                        },
                        headers={"WWW-Authenticate": "Bearer"},
                    ),
                    scope=scope,
                    receive=receive,
                    send=send,
                    client_ip=client_ip,
                )
                return
            expected_audience = os.environ.get("ZAPTRACE_API_TOKEN_AUDIENCE", "")
            if expected_audience and request.headers.get("X-ZapTrace-Audience", "") != expected_audience:
                await self._respond(
                    JSONResponse(
                        status_code=403,
                        content={
                            "ok": False,
                            "error": {"code": "AUTH_AUDIENCE_MISMATCH", "message": "Token audience is not accepted"},
                        },
                    ),
                    scope=scope,
                    receive=receive,
                    send=send,
                    client_ip=client_ip,
                )
                return
            request.state.zaptrace_auth = {
                "actor": os.environ.get("ZAPTRACE_API_TOKEN_SUBJECT", "api-token"),
                "scopes": {
                    item.strip().lower()
                    for item in os.environ.get("ZAPTRACE_API_TOKEN_SCOPES", "").replace(",", " ").split()
                    if item.strip()
                },
                "audience": expected_audience,
                "allowed_sessions": {
                    item.strip()
                    for item in os.environ.get("ZAPTRACE_API_TOKEN_SESSIONS", "*").replace(",", " ").split()
                    if item.strip()
                },
            }

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                self._set_security_headers(headers)
                info = self.rate_limit_backend.info(client_ip)
                headers["X-RateLimit-Limit"] = str(info.limit)
                headers["X-RateLimit-Remaining"] = str(info.remaining)
            await send(message)

        await self.app(scope, receive, secured_send)


# ---------------------------------------------------------------------------
# CORS origins
# ---------------------------------------------------------------------------


def _cors_origins() -> list[str]:
    raw = os.environ.get("ZAPTRACE_CORS_ORIGINS", "")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:5173", "http://localhost:8080"]


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — currently a no-op."""
    yield


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    abuse_control: AbuseControlConfiguration | None = None,
    rate_limit_backend: RateLimitBackend | None = None,
) -> FastAPI:
    abuse_control = abuse_control or AbuseControlConfiguration.from_environment()
    abuse_control.validate_deployment()
    rate_limit_backend = rate_limit_backend or abuse_control.build_backend()

    app = FastAPI(
        title="ZapTrace API",
        description="Agent-native electronics design REST API",
        version=API_VERSION,
        lifespan=lifespan,
    )

    app.state.abuse_control = abuse_control
    app.state.rate_limit_backend = rate_limit_backend

    # Add CORS last so it remains the outermost Starlette middleware.
    app.add_middleware(
        SecurityMiddleware,
        abuse_control=abuse_control,
        rate_limit_backend=rate_limit_backend,
    )

    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=abuse_control.max_body_bytes,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Requested-With",
            "Accept",
            "Origin",
            "X-ZapTrace-Session-Id",
            "X-ZapTrace-Actor",
            "X-ZapTrace-Reason",
            "X-Request-ID",
            *(["X-ZapTrace-Capabilities"] if environment_flag("ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS") else []),
        ],
    )

    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": API_VERSION}

    return app


app = create_app()


def run(host: str | None = None, port: int | None = None) -> None:
    """Run the API server with secure network defaults."""
    AbuseControlConfiguration.from_environment().validate_deployment()
    host, port = resolve_network_bind(
        surface="ZapTrace REST API",
        host=host,
        port=port,
        host_env="ZAPTRACE_API_HOST",
        port_env="ZAPTRACE_API_PORT",
        default_host="127.0.0.1",
        default_port=8080,
    )
    validate_network_auth_configuration(
        surface="ZapTrace REST API",
        host=host,
        token=os.environ.get("ZAPTRACE_API_TOKEN", ""),
        allow_local_development=environment_flag("ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS"),
    )

    import uvicorn

    uvicorn.run("zaptrace.api.server:app", host=host, port=port, reload=False)
