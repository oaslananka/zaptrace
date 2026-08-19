"""Deny-by-default plugin admission and permission mapping."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from zaptrace import __version__
from zaptrace.plugin.manifest import PluginCapability, PluginManifest, is_host_version_compatible
from zaptrace.plugin.signature import verify_plugin_signature
from zaptrace.security.policy import CAPABILITY_RANK, record_audit_event

PLUGIN_TO_AGENT_CAPABILITY: dict[PluginCapability, str] = {
    PluginCapability.DESIGN_READ: "read",
    PluginCapability.DESIGN_METADATA: "preview-write",
    PluginCapability.DESIGN_WRITE: "sandbox-write",
    PluginCapability.PROOF_READ: "read",
    PluginCapability.PROOF_WRITE: "sandbox-write",
    PluginCapability.LIBRARY_READ: "read",
    PluginCapability.LIBRARY_WRITE: "sandbox-write",
    PluginCapability.FILESYSTEM_READ: "read",
    PluginCapability.FILESYSTEM_WRITE: "sandbox-write",
    PluginCapability.NETWORK_CONNECT: "sandbox-write",
    PluginCapability.SUBPROCESS_RUN: "approved-commit",
    PluginCapability.PLUGIN_LOAD: "approved-commit",
    PluginCapability.MCP_TOOL_CALL: "approved-commit",
    PluginCapability.HOST_LOG: "read",
    PluginCapability.HOST_NOTIFY: "read",
}
DANGEROUS_CAPABILITIES = {
    PluginCapability.SUBPROCESS_RUN,
    PluginCapability.PLUGIN_LOAD,
    PluginCapability.MCP_TOOL_CALL,
}


class PluginAdmissionResult(BaseModel):
    """Result of deterministic plugin admission."""

    model_config = ConfigDict(strict=False)

    allowed: bool
    code: str
    message: str
    plugin_id: str = ""
    agent_capability: str = "read"
    requested_capabilities: list[str] = Field(default_factory=list)
    audit_event: dict[str, Any] | None = None


def _highest_agent_capability(capabilities: Iterable[PluginCapability]) -> str:
    required = "read"
    for capability in capabilities:
        mapped = PLUGIN_TO_AGENT_CAPABILITY.get(capability, "read")
        if CAPABILITY_RANK.get(mapped, 0) > CAPABILITY_RANK.get(required, 0):
            required = mapped
    return required


def _safe_relative_path(path: str) -> bool:
    if not path or "\x00" in path:
        return False
    pure = PurePosixPath(path.replace("\\", "/"))
    return not pure.is_absolute() and ".." not in pure.parts


def _deny(
    manifest: PluginManifest,
    *,
    code: str,
    message: str,
    session: dict[str, Any] | None,
    session_id: str,
    actor: str,
) -> PluginAdmissionResult:
    capability = _highest_agent_capability(manifest.capabilities)
    audit_event = _record(
        session,
        session_id=session_id,
        actor=actor,
        manifest=manifest,
        decision="deny",
        reason=message,
        capability=capability,
        code=code,
    )
    return PluginAdmissionResult(
        allowed=False,
        code=code,
        message=message,
        plugin_id=manifest.plugin_id,
        agent_capability=capability,
        requested_capabilities=[cap.value for cap in manifest.capabilities],
        audit_event=audit_event,
    )


def _format_validation_error(error: ValidationError) -> str:
    details: list[str] = []
    for item in error.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in item["loc"]) or "manifest"
        details.append(f"{location}: {item['msg']}")
    return "; ".join(details)


def _deny_invalid_schema(
    raw_manifest: Mapping[str, Any],
    *,
    error: ValidationError,
    session: dict[str, Any] | None,
    session_id: str,
    actor: str,
) -> PluginAdmissionResult:
    plugin_id_value = raw_manifest.get("plugin_id", "")
    plugin_id = plugin_id_value if isinstance(plugin_id_value, str) else ""
    message = f"plugin manifest schema validation failed: {_format_validation_error(error)}"
    audit_event = None
    if session is not None:
        audit_event = record_audit_event(
            session,
            surface="plugin",
            session_id=session_id,
            actor=actor,
            tool="plugin_admission",
            capability="read",
            decision="deny",
            reason=message,
            metadata={
                "code": "PLUGIN_SCHEMA_INVALID",
                "plugin_id": plugin_id,
                "requested_capabilities": [],
            },
        )
    return PluginAdmissionResult(
        allowed=False,
        code="PLUGIN_SCHEMA_INVALID",
        message=message,
        plugin_id=plugin_id,
        audit_event=audit_event,
    )


def _allow(
    manifest: PluginManifest, *, session: dict[str, Any] | None, session_id: str, actor: str
) -> PluginAdmissionResult:
    capability = _highest_agent_capability(manifest.capabilities)
    message = "plugin admitted"
    audit_event = _record(
        session,
        session_id=session_id,
        actor=actor,
        manifest=manifest,
        decision="allow",
        reason=message,
        capability=capability,
        code="PLUGIN_ADMITTED",
    )
    return PluginAdmissionResult(
        allowed=True,
        code="PLUGIN_ADMITTED",
        message=message,
        plugin_id=manifest.plugin_id,
        agent_capability=capability,
        requested_capabilities=[cap.value for cap in manifest.capabilities],
        audit_event=audit_event,
    )


def _record(
    session: dict[str, Any] | None,
    *,
    session_id: str,
    actor: str,
    manifest: PluginManifest,
    decision: str,
    reason: str,
    capability: str,
    code: str,
) -> dict[str, Any] | None:
    if session is None:
        return None
    return record_audit_event(
        session,
        surface="plugin",
        session_id=session_id,
        actor=actor,
        tool="plugin_admission",
        capability=capability,
        decision=decision,
        reason=reason,
        metadata={
            "code": code,
            "plugin_id": manifest.plugin_id,
            "plugin_version": manifest.version,
            "requested_capabilities": [cap.value for cap in manifest.capabilities],
        },
    )


def _validate_permissions(manifest: PluginManifest) -> tuple[bool, str, str]:
    caps = set(manifest.capabilities)
    permissions = manifest.permissions
    for path in [*permissions.filesystem.read, *permissions.filesystem.write]:
        if not _safe_relative_path(path):
            return False, "PLUGIN_UNSAFE_PATH", f"plugin declares unsafe filesystem path: {path}"
    if permissions.filesystem.read and PluginCapability.FILESYSTEM_READ not in caps:
        return False, "PLUGIN_PERMISSION_MISMATCH", "filesystem read paths require filesystem:read capability"
    if permissions.filesystem.write and PluginCapability.FILESYSTEM_WRITE not in caps:
        return False, "PLUGIN_PERMISSION_MISMATCH", "filesystem write paths require filesystem:write capability"
    network = permissions.network
    if (network.allowed_domains or network.allowed_schemes) and PluginCapability.NETWORK_CONNECT not in caps:
        return False, "PLUGIN_PERMISSION_MISMATCH", "network permissions require network:connect capability"
    if any("*" in domain or not domain for domain in network.allowed_domains):
        return False, "PLUGIN_NETWORK_SCOPE_INVALID", "network domains must be explicit and non-wildcard"
    if any(scheme != "https" for scheme in network.allowed_schemes):
        return False, "PLUGIN_NETWORK_SCOPE_INVALID", "plugin network access is limited to https schemes"
    if permissions.subprocess and PluginCapability.SUBPROCESS_RUN not in caps:
        return False, "PLUGIN_PERMISSION_MISMATCH", "subprocess permission requires subprocess:run capability"
    return True, "PLUGIN_PERMISSIONS_OK", "permissions are scoped"


def _validate_signature_policy(
    manifest: PluginManifest,
    *,
    require_signature: bool,
    trusted_fingerprints: set[str] | None,
    trusted_public_keys: Mapping[str, bytes] | None,
) -> tuple[bool, str, str]:
    if not require_signature:
        return True, "PLUGIN_SIGNATURE_OK", "signature verification is not required"
    signing = manifest.signing
    if signing is None:
        return False, "PLUGIN_SIGNATURE_REQUIRED", "signed plugin manifest is required by default"
    fingerprint = signing.public_key_fingerprint
    if trusted_fingerprints is not None and fingerprint not in trusted_fingerprints:
        return False, "PLUGIN_SIGNER_UNTRUSTED", "plugin signer fingerprint is not trusted"
    if trusted_public_keys is None or fingerprint not in trusted_public_keys:
        return False, "PLUGIN_SIGNER_UNTRUSTED", "trusted public key is required for plugin signature verification"
    verified, reason = verify_plugin_signature(manifest, trusted_public_keys=trusted_public_keys)
    if not verified:
        return False, "PLUGIN_SIGNATURE_INVALID", reason
    return True, "PLUGIN_SIGNATURE_OK", "plugin signature verified"


def admit_plugin_manifest(
    manifest: PluginManifest | Mapping[str, Any],
    *,
    host_version: str = __version__,
    require_signature: bool = True,
    trusted_fingerprints: set[str] | None = None,
    trusted_public_keys: Mapping[str, bytes] | None = None,
    allow_dangerous: bool = False,
    audit_session: dict[str, Any] | None = None,
    session_id: str = "plugin-admission",
    actor: str = "plugin-loader",
) -> PluginAdmissionResult:
    """Validate and admit a plugin manifest without importing or executing plugin code."""
    if not isinstance(manifest, PluginManifest):
        try:
            manifest = PluginManifest.model_validate(manifest)
        except ValidationError as exc:
            return _deny_invalid_schema(
                manifest,
                error=exc,
                session=audit_session,
                session_id=session_id,
                actor=actor,
            )

    compatible, reason = is_host_version_compatible(manifest, host_version)
    if not compatible:
        return _deny(
            manifest,
            code="PLUGIN_VERSION_INCOMPATIBLE",
            message=reason,
            session=audit_session,
            session_id=session_id,
            actor=actor,
        )
    signature_ok, signature_code, signature_message = _validate_signature_policy(
        manifest,
        require_signature=require_signature,
        trusted_fingerprints=trusted_fingerprints,
        trusted_public_keys=trusted_public_keys,
    )
    if not signature_ok:
        return _deny(
            manifest,
            code=signature_code,
            message=signature_message,
            session=audit_session,
            session_id=session_id,
            actor=actor,
        )
    dangerous = sorted(cap.value for cap in set(manifest.capabilities) & DANGEROUS_CAPABILITIES)
    if dangerous and not allow_dangerous:
        return _deny(
            manifest,
            code="PLUGIN_DANGEROUS_CAPABILITY_DENIED",
            message=f"dangerous plugin capabilities require explicit admission: {', '.join(dangerous)}",
            session=audit_session,
            session_id=session_id,
            actor=actor,
        )
    ok, code, message = _validate_permissions(manifest)
    if not ok:
        return _deny(manifest, code=code, message=message, session=audit_session, session_id=session_id, actor=actor)
    return _allow(manifest, session=audit_session, session_id=session_id, actor=actor)
