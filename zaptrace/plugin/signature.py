"""Ed25519 signature verification for plugin manifests.

Verifies that a plugin manifest's declared signature matches the manifest
content, preventing tampered plugins from being loaded. The canonical payload
is the manifest JSON with the ``signing`` field removed, serialized
deterministically (sorted keys, no extra whitespace).

This is *verification only* — key generation and signing are out-of-scope for
the runtime.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from zaptrace.plugin.manifest import PluginManifest


def _canonical_payload(manifest: PluginManifest) -> bytes:
    """Return the canonical bytes that the signature covers.

    The manifest is serialized without the ``signing`` sub-object so the
    signature covers everything *except* the signature itself. Keys are sorted
    for determinism, no extra whitespace.
    """
    data: dict[str, Any] = manifest.model_dump(exclude={"signing"}, by_alias=True)
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _decode_b64(value: str, label: str) -> bytes:
    """Strictly decode a standard or URL-safe base64 value."""
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.b64decode(padded, altchars=b"-_", validate=True)
    except ValueError as exc:
        raise ValueError(f"invalid base64 for {label}: {exc}") from exc


def public_key_fingerprint(public_key_bytes: bytes) -> str:
    """Return the SHA-256 fingerprint (hex) of a raw 32-byte Ed25519 public key."""
    return hashlib.sha256(public_key_bytes).hexdigest()


def verify_plugin_signature(
    manifest: PluginManifest,
    *,
    trusted_public_keys: Mapping[str, bytes],
) -> tuple[bool, str]:
    """Verify the Ed25519 signature on a plugin manifest.

    The manifest must have a ``signing`` section. The public key is looked up
    by fingerprint from ``trusted_public_keys``.

    Args:
        manifest: Loaded plugin manifest with a ``signing`` field.
        trusted_public_keys: Mapping of fingerprint (hex) → raw 32-byte
            Ed25519 public key bytes.

    Returns:
        ``(True, "verified")`` on success, or ``(False, "<reason>")`` on failure.
    """
    if manifest.signing is None:
        return False, "manifest has no signing section"

    fingerprint = manifest.signing.public_key_fingerprint
    public_key_bytes = trusted_public_keys.get(fingerprint)
    if public_key_bytes is None:
        return False, f"public key fingerprint '{fingerprint}' not in trusted set"
    if public_key_fingerprint(public_key_bytes) != fingerprint:
        return False, "trusted public key does not match its configured fingerprint"

    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return False, "cryptography package not installed; cannot verify Ed25519 signatures"

    try:
        sig_bytes = _decode_b64(manifest.signing.signature, "signature")
    except ValueError as exc:
        return False, str(exc)

    try:
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    except (ValueError, TypeError) as exc:
        return False, f"invalid Ed25519 public key: {exc}"

    payload = _canonical_payload(manifest)
    try:
        public_key.verify(sig_bytes, payload)
        return True, "verified"
    except InvalidSignature:
        return False, "signature verification failed — manifest may have been tampered"
    except Exception as exc:
        return False, f"unexpected verification error: {exc}"
