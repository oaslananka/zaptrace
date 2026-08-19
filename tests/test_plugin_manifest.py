from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from zaptrace.plugin import (
    PluginCapability,
    PluginManifest,
    PluginSigning,
    admit_plugin_manifest,
    discover_plugin_manifests,
    generate_plugin_manifest_schema,
    load_plugin_manifest,
)
from zaptrace.plugin.signature import _canonical_payload, public_key_fingerprint

VALID = Path("tests/fixtures/plugins/valid")
UNSIGNED = Path("tests/fixtures/plugins/unsigned")
OVERBROAD = Path("tests/fixtures/plugins/overbroad")
INCOMPATIBLE = Path("tests/fixtures/plugins/incompatible")
MALFORMED = Path("tests/fixtures/plugins/malformed")
SCHEMA = Path("schemas/plugin-manifest-v1.schema.json")


def _sign_manifest(manifest: PluginManifest) -> tuple[PluginManifest, dict[str, bytes]]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes_raw()
    fingerprint = public_key_fingerprint(public_key)
    unsigned = manifest.model_copy(update={"signing": None})
    signature = base64.urlsafe_b64encode(private_key.sign(_canonical_payload(unsigned))).decode()
    signed = unsigned.model_copy(
        update={
            "signing": PluginSigning(
                signature=signature,
                public_key_fingerprint=fingerprint,
            )
        }
    )
    return PluginManifest.model_validate(signed.model_dump(mode="json", by_alias=True)), {fingerprint: public_key}


def test_valid_plugin_manifest_loads_and_generates_schema_contract() -> None:
    manifest = load_plugin_manifest(VALID)

    assert manifest.plugin_id == "dev.zaptrace.examples.hello-analyzer"
    assert manifest.entry.type == "python_module"
    assert [cap.value for cap in manifest.capabilities] == ["design:read", "proof:read", "host:log"]

    committed = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert committed == generate_plugin_manifest_schema()


def test_generated_schema_forbids_unknown_fields_at_every_object_boundary() -> None:
    schema = generate_plugin_manifest_schema()

    assert schema["additionalProperties"] is False
    definitions = schema["$defs"]
    for model_name in (
        "PluginEntry",
        "FilesystemPermissions",
        "NetworkPermissions",
        "PluginPermissions",
        "PluginSigning",
        "PluginDependency",
    ):
        assert definitions[model_name]["additionalProperties"] is False


def test_plugin_discovery_is_deterministic_when_no_plugins_are_installed(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    assert discover_plugin_manifests([]) == []
    assert discover_plugin_manifests([missing]) == []
    assert [item.plugin_id for item in discover_plugin_manifests([VALID])] == ["dev.zaptrace.examples.hello-analyzer"]


def test_signed_trusted_plugin_is_admitted_and_audited() -> None:
    session: dict[str, Any] = {}
    manifest, trusted_keys = _sign_manifest(load_plugin_manifest(VALID))

    result = admit_plugin_manifest(
        manifest,
        trusted_public_keys=trusted_keys,
        audit_session=session,
        session_id="plugin-test-session",
        actor="pytest",
    )

    assert result.allowed is True
    assert result.code == "PLUGIN_ADMITTED"
    assert result.agent_capability == "read"
    assert result.audit_event is not None
    assert result.audit_event["decision"] == "allow"
    assert result.audit_event["metadata"]["plugin_id"] == manifest.plugin_id
    assert session["audit_events"][-1]["tool"] == "plugin_admission"


def test_fingerprint_allowlist_alone_cannot_admit_a_plugin() -> None:
    manifest, trusted_keys = _sign_manifest(load_plugin_manifest(VALID))
    fingerprint = next(iter(trusted_keys))

    result = admit_plugin_manifest(manifest, trusted_fingerprints={fingerprint})

    assert result.allowed is False
    assert result.code == "PLUGIN_SIGNER_UNTRUSTED"
    assert "public key" in result.message


def test_valid_signature_from_unknown_signer_is_rejected() -> None:
    manifest, _ = _sign_manifest(load_plugin_manifest(VALID))

    result = admit_plugin_manifest(manifest, trusted_public_keys={})

    assert result.allowed is False
    assert result.code == "PLUGIN_SIGNER_UNTRUSTED"


def test_wrong_public_key_for_declared_fingerprint_is_rejected() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    manifest, trusted_keys = _sign_manifest(load_plugin_manifest(VALID))
    fingerprint = next(iter(trusted_keys))
    wrong_public_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()

    result = admit_plugin_manifest(manifest, trusted_public_keys={fingerprint: wrong_public_key})

    assert result.allowed is False
    assert result.code == "PLUGIN_SIGNATURE_INVALID"
    assert "fingerprint" in result.message


def test_tampered_signed_manifest_is_rejected() -> None:
    manifest, trusted_keys = _sign_manifest(load_plugin_manifest(VALID))
    tampered = manifest.model_copy(update={"description": "tampered after signing"})

    result = admit_plugin_manifest(tampered, trusted_public_keys=trusted_keys)

    assert result.allowed is False
    assert result.code == "PLUGIN_SIGNATURE_INVALID"


def test_malformed_signature_is_rejected_with_stable_code() -> None:
    manifest, trusted_keys = _sign_manifest(load_plugin_manifest(VALID))
    signing = manifest.signing
    assert signing is not None
    malformed = manifest.model_copy(update={"signing": signing.model_copy(update={"signature": "%%%"})})

    result = admit_plugin_manifest(malformed, trusted_public_keys=trusted_keys)

    assert result.allowed is False
    assert result.code == "PLUGIN_SIGNATURE_INVALID"


def test_unsigned_plugin_is_rejected_by_default_and_audited() -> None:
    session: dict[str, Any] = {}
    manifest = load_plugin_manifest(UNSIGNED)

    result = admit_plugin_manifest(manifest, audit_session=session)

    assert result.allowed is False
    assert result.code == "PLUGIN_SIGNATURE_REQUIRED"
    assert result.audit_event is not None
    assert result.audit_event["decision"] == "deny"
    assert result.audit_event["metadata"]["code"] == "PLUGIN_SIGNATURE_REQUIRED"


def test_invalid_raw_manifest_is_rejected_and_audited_without_execution() -> None:
    session: dict[str, Any] = {}
    raw = json.loads((VALID / "zaptrace-plugin.json").read_text(encoding="utf-8"))
    raw["unexpected_security_policy"] = {"credential": "SENSITIVE-SENTINEL"}

    result = admit_plugin_manifest(raw, audit_session=session)

    assert result.allowed is False
    assert result.code == "PLUGIN_SCHEMA_INVALID"
    assert result.plugin_id == "dev.zaptrace.examples.hello-analyzer"
    assert "unexpected_security_policy" in result.message
    assert "SENSITIVE-SENTINEL" not in result.message
    assert result.audit_event is not None
    assert result.audit_event["metadata"]["code"] == "PLUGIN_SCHEMA_INVALID"
    assert "SENSITIVE-SENTINEL" not in result.audit_event["reason"]


def test_overbroad_permissions_are_rejected_with_actionable_error() -> None:
    manifest = load_plugin_manifest(OVERBROAD)

    result = admit_plugin_manifest(manifest, require_signature=False)

    assert result.allowed is False
    assert result.code == "PLUGIN_PERMISSION_MISMATCH"
    assert "filesystem write paths require filesystem:write" in result.message


def test_dangerous_capabilities_require_explicit_admission_after_signature_verification() -> None:
    manifest = load_plugin_manifest(VALID)
    patched = manifest.model_copy(
        update={"capabilities": [PluginCapability.DESIGN_READ, PluginCapability.SUBPROCESS_RUN]}
    )
    patched = PluginManifest.model_validate(patched.model_dump(mode="json", by_alias=True))
    signed, trusted_keys = _sign_manifest(patched)

    result = admit_plugin_manifest(signed, trusted_public_keys=trusted_keys)

    assert result.allowed is False
    assert result.code == "PLUGIN_DANGEROUS_CAPABILITY_DENIED"
    assert "subprocess:run" in result.message


def test_incompatible_plugin_version_fails_with_current_version_message() -> None:
    manifest = load_plugin_manifest(INCOMPATIBLE)

    result = admit_plugin_manifest(manifest, trusted_fingerprints={"sha256:dev-fixture"})

    assert result.allowed is False
    assert result.code == "PLUGIN_VERSION_INCOMPATIBLE"
    assert "current version" in result.message


def test_malformed_plugin_manifest_is_rejected_before_admission() -> None:
    with pytest.raises(ValidationError):
        load_plugin_manifest(MALFORMED)


UnknownFieldMutation = Callable[[dict[str, Any]], None]


def _unknown_top_level(data: dict[str, Any]) -> None:
    data["unexpected"] = True


def _unknown_entry(data: dict[str, Any]) -> None:
    data["entry"]["loader"] = "unsafe"


def _unknown_permissions(data: dict[str, Any]) -> None:
    data["permissions"]["escape_sandbox"] = True


def _unknown_filesystem(data: dict[str, Any]) -> None:
    data["permissions"]["filesystem"]["root"] = "/"


def _unknown_network(data: dict[str, Any]) -> None:
    data["permissions"]["network"]["allowed_ports"] = [22]


def _unknown_signing(data: dict[str, Any]) -> None:
    data["signing"]["key_id"] = "unreviewed-key"


def _unknown_dependency(data: dict[str, Any]) -> None:
    data["dependencies"] = [{"plugin_id": "example.dep", "checksum": "ignored"}]


@pytest.mark.parametrize(
    "mutate,field_name",
    [
        (_unknown_top_level, "unexpected"),
        (_unknown_entry, "loader"),
        (_unknown_permissions, "escape_sandbox"),
        (_unknown_filesystem, "root"),
        (_unknown_network, "allowed_ports"),
        (_unknown_signing, "key_id"),
        (_unknown_dependency, "checksum"),
    ],
)
def test_unknown_manifest_fields_are_rejected_at_every_object_boundary(
    mutate: UnknownFieldMutation,
    field_name: str,
) -> None:
    raw = json.loads((VALID / "zaptrace-plugin.json").read_text(encoding="utf-8"))
    mutate(raw)

    with pytest.raises(ValidationError) as exc_info:
        PluginManifest.model_validate(raw)

    assert field_name in str(exc_info.value)
