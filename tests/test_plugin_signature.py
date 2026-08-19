"""Tests for Ed25519 plugin signature verification."""

from __future__ import annotations

import base64
from collections.abc import Callable

import pytest

from zaptrace.plugin.manifest import (
    FilesystemPermissions,
    PluginCapability,
    PluginEntry,
    PluginManifest,
    PluginPermissions,
    PluginSigning,
)
from zaptrace.plugin.signature import (
    _canonical_payload,
    public_key_fingerprint,
    verify_plugin_signature,
)


def _make_manifest(signing: PluginSigning | None = None) -> PluginManifest:
    return PluginManifest(
        plugin_id="test.plugin",
        name="Test Plugin",
        version="1.0.0",
        min_zaptrace_version="0.1.0",
        max_zaptrace_version="99.0.0",
        entry=PluginEntry(path="plugin.py"),
        signing=signing,
    )


def _generate_keypair() -> tuple[bytes, bytes]:
    """Return (private_key_bytes, public_key_bytes) for an Ed25519 key pair."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    priv_bytes = priv.private_bytes_raw()
    return priv_bytes, pub_bytes


def _sign_manifest(manifest: PluginManifest, priv_bytes: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.from_private_bytes(priv_bytes)
    payload = _canonical_payload(manifest)
    sig = priv.sign(payload)
    return base64.urlsafe_b64encode(sig).decode()


class TestSignatureVerification:
    def test_valid_signature_verifies(self) -> None:
        priv_bytes, pub_bytes = _generate_keypair()
        fp = public_key_fingerprint(pub_bytes)
        unsigned = _make_manifest()
        sig = _sign_manifest(unsigned, priv_bytes)
        signed = _make_manifest(signing=PluginSigning(signature=sig, public_key_fingerprint=fp))

        ok, reason = verify_plugin_signature(signed, trusted_public_keys={fp: pub_bytes})
        assert ok
        assert reason == "verified"

    def test_wrong_fingerprint_is_rejected(self) -> None:
        priv_bytes, pub_bytes = _generate_keypair()
        fp = public_key_fingerprint(pub_bytes)
        unsigned = _make_manifest()
        sig = _sign_manifest(unsigned, priv_bytes)
        signed = _make_manifest(signing=PluginSigning(signature=sig, public_key_fingerprint=fp))

        ok, reason = verify_plugin_signature(signed, trusted_public_keys={"bad_fp": pub_bytes})
        assert not ok
        assert "not in trusted set" in reason

    def test_tampered_signature_fails(self) -> None:
        priv_bytes, pub_bytes = _generate_keypair()
        fp = public_key_fingerprint(pub_bytes)
        unsigned = _make_manifest()
        sig = _sign_manifest(unsigned, priv_bytes)

        sig_bytes = base64.urlsafe_b64decode(sig + "==")
        corrupted = bytearray(sig_bytes)
        corrupted[0] ^= 0xFF
        bad_sig = base64.urlsafe_b64encode(bytes(corrupted)).decode()

        signed = _make_manifest(signing=PluginSigning(signature=bad_sig, public_key_fingerprint=fp))
        ok, reason = verify_plugin_signature(signed, trusted_public_keys={fp: pub_bytes})
        assert not ok
        assert "failed" in reason.lower()

    def test_unsigned_manifest_fails(self) -> None:
        _, pub_bytes = _generate_keypair()
        fp = public_key_fingerprint(pub_bytes)
        manifest = _make_manifest(signing=None)
        ok, reason = verify_plugin_signature(manifest, trusted_public_keys={fp: pub_bytes})
        assert not ok
        assert "no signing section" in reason

    def test_fingerprint_is_deterministic(self) -> None:
        _, pub_bytes = _generate_keypair()
        fp1 = public_key_fingerprint(pub_bytes)
        fp2 = public_key_fingerprint(pub_bytes)
        assert fp1 == fp2
        assert len(fp1) == 64

    def test_canonical_payload_excludes_signing(self) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        priv_bytes, pub_bytes = _generate_keypair()
        fp = public_key_fingerprint(pub_bytes)
        priv = Ed25519PrivateKey.from_private_bytes(priv_bytes)
        unsigned = _make_manifest()

        payload_unsigned = _canonical_payload(unsigned)
        signed = _make_manifest(
            signing=PluginSigning(
                signature=base64.urlsafe_b64encode(priv.sign(payload_unsigned)).decode(),
                public_key_fingerprint=fp,
            )
        )
        payload_signed = _canonical_payload(signed)
        assert payload_unsigned == payload_signed
        assert b"signing" not in payload_signed


ManifestMutation = Callable[[PluginManifest], PluginManifest]


def _mutate_name(manifest: PluginManifest) -> PluginManifest:
    return manifest.model_copy(update={"name": "Changed Name"})


def _mutate_version(manifest: PluginManifest) -> PluginManifest:
    return manifest.model_copy(update={"version": "1.0.1"})


def _mutate_entry(manifest: PluginManifest) -> PluginManifest:
    return manifest.model_copy(update={"entry": PluginEntry(path="changed.py")})


def _mutate_capabilities(manifest: PluginManifest) -> PluginManifest:
    return manifest.model_copy(update={"capabilities": [PluginCapability.DESIGN_READ]})


def _mutate_permissions(manifest: PluginManifest) -> PluginManifest:
    permissions = PluginPermissions(filesystem=FilesystemPermissions(read=["inputs/"]))
    return manifest.model_copy(update={"permissions": permissions})


@pytest.mark.parametrize(
    "mutate",
    [_mutate_name, _mutate_version, _mutate_entry, _mutate_capabilities, _mutate_permissions],
)
def test_any_signed_manifest_content_mutation_invalidates_signature(mutate: ManifestMutation) -> None:
    priv_bytes, pub_bytes = _generate_keypair()
    fingerprint = public_key_fingerprint(pub_bytes)
    unsigned = _make_manifest()
    signed = unsigned.model_copy(
        update={
            "signing": PluginSigning(
                signature=_sign_manifest(unsigned, priv_bytes),
                public_key_fingerprint=fingerprint,
            )
        }
    )

    tampered = mutate(signed)
    ok, reason = verify_plugin_signature(tampered, trusted_public_keys={fingerprint: pub_bytes})

    assert ok is False
    assert "failed" in reason.lower()


def test_canonical_payload_is_independent_of_input_key_order() -> None:
    first = PluginManifest.model_validate(
        {
            "plugin_id": "test.plugin",
            "name": "Test Plugin",
            "version": "1.0.0",
            "min_zaptrace_version": "0.1.0",
            "max_zaptrace_version": "99.0.0",
            "entry": {"path": "plugin.py", "type": "python_module"},
        }
    )
    second = PluginManifest.model_validate(
        {
            "entry": {"type": "python_module", "path": "plugin.py"},
            "max_zaptrace_version": "99.0.0",
            "min_zaptrace_version": "0.1.0",
            "version": "1.0.0",
            "name": "Test Plugin",
            "plugin_id": "test.plugin",
        }
    )

    assert _canonical_payload(first) == _canonical_payload(second)
