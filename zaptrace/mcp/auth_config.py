"""Versioned, fail-closed configuration for MCP HTTP authorization profiles."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, cast
from urllib.parse import SplitResult, urlsplit

from zaptrace.security.network import (
    environment_flag,
    is_loopback_host,
    validate_network_auth_configuration,
)

MCPHTTPAuthProfile = Literal["local", "static-bearer", "oauth-jwt"]

_CONTRACT_VERSION = "1"
_SUPPORTED_PROFILES = frozenset({"local", "static-bearer", "oauth-jwt"})
_OAUTH_ENV_NAMES = (
    "ZAPTRACE_MCP_PUBLIC_BASE_URL",
    "ZAPTRACE_MCP_AUTH_RESOURCE_URI",
    "ZAPTRACE_MCP_AUTHORIZATION_SERVER",
    "ZAPTRACE_MCP_AUTH_JWKS_URI",
)
_LEGACY_GRANT_ENV_NAMES = (
    "ZAPTRACE_MCP_HTTP_TOKEN",
    "ZAPTRACE_MCP_TOKEN_SUBJECT",
    "ZAPTRACE_MCP_CAPABILITIES",
)


@dataclass(frozen=True)
class MCPHTTPAuthConfiguration:
    """Resolved MCP HTTP authentication posture without exposing secret values."""

    profile: MCPHTTPAuthProfile
    host: str
    loopback: bool
    explicit: bool
    contract_version: str | None
    static_token: str = field(default="", repr=False)
    public_base_url: str | None = None
    resource_uri: str | None = None
    authorization_server: str | None = None
    jwks_uri: str | None = None

    @property
    def authentication_configured(self) -> bool:
        return self.profile in {"static-bearer", "oauth-jwt"}


@dataclass(frozen=True)
class _OAuthURLs:
    public_base_url: str
    resource_uri: str
    authorization_server: str
    jwks_uri: str


def _value(environ: Mapping[str, str], name: str) -> str:
    return environ.get(name, "").strip()


def _nonempty_names(environ: Mapping[str, str], names: tuple[str, ...]) -> list[str]:
    return [name for name in names if _value(environ, name)]


def _parse_https_url(name: str, value: str) -> SplitResult:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a valid HTTPS URL") from exc
    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"{name} must use HTTPS")
    if not parsed.hostname:
        raise RuntimeError(f"{name} must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeError(f"{name} must not contain credentials")
    if parsed.query:
        raise RuntimeError(f"{name} must not contain a query")
    if parsed.fragment:
        raise RuntimeError(f"{name} must not contain a fragment")
    return parsed


def _origin(parsed: SplitResult) -> tuple[str, str, int]:
    assert parsed.hostname is not None
    return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port or 443


def _resolve_oauth_urls(environ: Mapping[str, str]) -> _OAuthURLs:
    values = {name: _value(environ, name) for name in _OAUTH_ENV_NAMES}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"oauth-jwt MCP auth profile requires {missing[0]}")

    parsed = {name: _parse_https_url(name, value) for name, value in values.items()}
    if _origin(parsed["ZAPTRACE_MCP_AUTH_RESOURCE_URI"]) != _origin(parsed["ZAPTRACE_MCP_PUBLIC_BASE_URL"]):
        raise RuntimeError("oauth-jwt resource URI must use the same origin as the public base URL")

    return _OAuthURLs(
        public_base_url=values["ZAPTRACE_MCP_PUBLIC_BASE_URL"],
        resource_uri=values["ZAPTRACE_MCP_AUTH_RESOURCE_URI"],
        authorization_server=values["ZAPTRACE_MCP_AUTHORIZATION_SERVER"],
        jwks_uri=values["ZAPTRACE_MCP_AUTH_JWKS_URI"],
    )


def _resolve_explicit_profile(environ: Mapping[str, str]) -> tuple[MCPHTTPAuthProfile, str]:
    raw_profile = _value(environ, "ZAPTRACE_MCP_AUTH_PROFILE")
    version = _value(environ, "ZAPTRACE_MCP_AUTH_CONFIG_VERSION")
    if raw_profile and not version:
        raise RuntimeError("ZAPTRACE_MCP_AUTH_CONFIG_VERSION is required when ZAPTRACE_MCP_AUTH_PROFILE is set")
    if version and not raw_profile:
        raise RuntimeError("ZAPTRACE_MCP_AUTH_PROFILE is required when ZAPTRACE_MCP_AUTH_CONFIG_VERSION is set")
    if version != _CONTRACT_VERSION:
        raise RuntimeError(
            f"unsupported MCP auth configuration version {version!r}; "
            f"ZAPTRACE_MCP_AUTH_CONFIG_VERSION must be {_CONTRACT_VERSION!r}"
        )
    if raw_profile not in _SUPPORTED_PROFILES:
        raise RuntimeError(f"unsupported MCP auth profile {raw_profile!r}")
    return cast(MCPHTTPAuthProfile, raw_profile), version


def _resolve_legacy_profile(environ: Mapping[str, str]) -> MCPHTTPAuthProfile:
    oauth_names = _nonempty_names(environ, _OAUTH_ENV_NAMES)
    if oauth_names:
        raise RuntimeError(
            f"{oauth_names[0]} requires explicit ZAPTRACE_MCP_AUTH_PROFILE=oauth-jwt "
            "and ZAPTRACE_MCP_AUTH_CONFIG_VERSION=1"
        )
    return "static-bearer" if _value(environ, "ZAPTRACE_MCP_HTTP_TOKEN") else "local"


def _reject_profile_conflicts(
    profile: MCPHTTPAuthProfile,
    environ: Mapping[str, str],
    *,
    explicit: bool,
) -> None:
    if profile == "oauth-jwt":
        conflicts = _nonempty_names(environ, _LEGACY_GRANT_ENV_NAMES)
    elif profile == "local" and explicit:
        conflicts = _nonempty_names(environ, _LEGACY_GRANT_ENV_NAMES + _OAUTH_ENV_NAMES)
    else:
        conflicts = _nonempty_names(environ, _OAUTH_ENV_NAMES)
    if conflicts:
        raise RuntimeError(f"{profile} MCP auth profile conflicts with {conflicts[0]}")


def resolve_mcp_http_auth_configuration(
    *,
    host: str,
    environ: Mapping[str, str] | None = None,
) -> MCPHTTPAuthConfiguration:
    """Resolve one exclusive MCP HTTP auth profile and reject ambiguous startup."""
    source = os.environ if environ is None else environ
    raw_profile = _value(source, "ZAPTRACE_MCP_AUTH_PROFILE")
    raw_version = _value(source, "ZAPTRACE_MCP_AUTH_CONFIG_VERSION")
    explicit = bool(raw_profile or raw_version)
    if explicit:
        profile, contract_version = _resolve_explicit_profile(source)
    else:
        profile = _resolve_legacy_profile(source)
        contract_version = None

    _reject_profile_conflicts(profile, source, explicit=explicit)
    loopback = is_loopback_host(host)
    token = _value(source, "ZAPTRACE_MCP_HTTP_TOKEN")
    allow_local_development = (
        environment_flag("ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS")
        if environ is None
        else _value(source, "ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS").lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )

    if explicit and profile == "local" and not loopback:
        raise RuntimeError("local MCP auth profile is restricted to loopback binds")
    if profile == "static-bearer" and not token:
        raise RuntimeError("static-bearer MCP auth profile requires ZAPTRACE_MCP_HTTP_TOKEN")
    if profile != "oauth-jwt":
        validate_network_auth_configuration(
            surface="ZapTrace MCP HTTP",
            host=host,
            token=token,
            allow_local_development=allow_local_development,
        )
        return MCPHTTPAuthConfiguration(
            profile=profile,
            host=host,
            loopback=loopback,
            explicit=explicit,
            contract_version=contract_version,
            static_token=token,
        )

    if not loopback and allow_local_development:
        raise RuntimeError("ZapTrace MCP HTTP local-development authorization is restricted to loopback binds")
    oauth = _resolve_oauth_urls(source)
    return MCPHTTPAuthConfiguration(
        profile=profile,
        host=host,
        loopback=loopback,
        explicit=explicit,
        contract_version=contract_version,
        public_base_url=oauth.public_base_url,
        resource_uri=oauth.resource_uri,
        authorization_server=oauth.authorization_server,
        jwks_uri=oauth.jwks_uri,
    )
