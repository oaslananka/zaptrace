"""Versioned plugin manifest schema and deterministic discovery helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PLUGIN_MANIFEST_FILENAME = "zaptrace-plugin.json"
PLUGIN_SCHEMA_URL = "https://zaptrace.dev/schemas/plugin-manifest-v1.json"
SUPPORTED_PLUGIN_API_MAJOR = 1


class PluginCapability(StrEnum):
    """Declared plugin capability strings."""

    DESIGN_READ = "design:read"
    DESIGN_WRITE = "design:write"
    DESIGN_METADATA = "design:metadata"
    PROOF_READ = "proof:read"
    PROOF_WRITE = "proof:write"
    LIBRARY_READ = "library:read"
    LIBRARY_WRITE = "library:write"
    FILESYSTEM_READ = "filesystem:read"
    FILESYSTEM_WRITE = "filesystem:write"
    NETWORK_CONNECT = "network:connect"
    SUBPROCESS_RUN = "subprocess:run"
    PLUGIN_LOAD = "plugin:load"
    MCP_TOOL_CALL = "mcp:tool_call"
    HOST_LOG = "host:log"
    HOST_NOTIFY = "host:notify"


class PluginEntry(BaseModel):
    """Plugin entry point declaration."""

    model_config = ConfigDict(extra="forbid", strict=False)

    type: Literal["python_module", "executable", "wasm"] = "python_module"
    path: str = Field(min_length=1)


class FilesystemPermissions(BaseModel):
    """Relative filesystem scopes declared by a plugin."""

    model_config = ConfigDict(extra="forbid", strict=False)

    read: list[str] = Field(default_factory=list)
    write: list[str] = Field(default_factory=list)


class NetworkPermissions(BaseModel):
    """Network scopes declared by a plugin."""

    model_config = ConfigDict(extra="forbid", strict=False)

    allowed_domains: list[str] = Field(default_factory=list)
    allowed_schemes: list[str] = Field(default_factory=list)


class PluginPermissions(BaseModel):
    """Resource access bounds for plugin admission."""

    model_config = ConfigDict(extra="forbid", strict=False)

    filesystem: FilesystemPermissions = Field(default_factory=FilesystemPermissions)
    network: NetworkPermissions = Field(default_factory=NetworkPermissions)
    subprocess: bool = False


class PluginSigning(BaseModel):
    """Manifest signing metadata."""

    model_config = ConfigDict(extra="forbid", strict=False)

    algorithm: Literal["ed25519"] = "ed25519"
    signature: str = Field(min_length=1)
    public_key_fingerprint: str = Field(min_length=1)


class PluginDependency(BaseModel):
    """Optional dependency on another plugin."""

    model_config = ConfigDict(extra="forbid", strict=False)

    plugin_id: str = Field(min_length=1)
    version_range: str = Field(default="*")


class PluginManifest(BaseModel):
    """Stable ZapTrace plugin manifest v1 contract."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=False)

    schema_url: str = Field(default=PLUGIN_SCHEMA_URL, alias="$schema")
    api_version: str = Field(default="1.0")
    plugin_id: str = Field(min_length=3, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    min_zaptrace_version: str = Field(min_length=1)
    max_zaptrace_version: str = Field(min_length=1)
    entry: PluginEntry
    extension_points: list[
        Literal[
            "importer",
            "exporter",
            "drc_rule",
            "dfm_rule",
            "synthesis_block",
            "fab_profile",
            "part_provider",
            "report_generator",
        ]
    ] = Field(default_factory=list)
    capabilities: list[PluginCapability] = Field(default_factory=list)
    permissions: PluginPermissions = Field(default_factory=PluginPermissions)
    signing: PluginSigning | None = None
    description: str = ""
    author: str = ""
    homepage: str = ""
    repository: str = ""
    documentation: str = ""
    dependencies: list[PluginDependency] = Field(default_factory=list)

    @field_validator("schema_url")
    @classmethod
    def _schema_url_matches_v1(cls, value: str) -> str:
        if value != PLUGIN_SCHEMA_URL:
            raise ValueError(f"unsupported plugin manifest schema: {value}")
        return value

    @field_validator("api_version")
    @classmethod
    def _api_version_major_supported(cls, value: str) -> str:
        major = _version_tuple(value)[0]
        if major != SUPPORTED_PLUGIN_API_MAJOR:
            raise ValueError(f"unsupported plugin API major version: {value}")
        return value


def _version_tuple(raw: str) -> tuple[int, int, int]:
    cleaned = raw.split("+", 1)[0].split("-", 1)[0]
    parts = cleaned.split(".")
    values: list[int] = []
    for part in parts[:3]:
        if not part.isdigit():
            raise ValueError(f"invalid semantic version: {raw}")
        values.append(int(part))
    while len(values) < 3:
        values.append(0)
    return values[0], values[1], values[2]


def is_host_version_compatible(manifest: PluginManifest, host_version: str) -> tuple[bool, str]:
    """Return compatibility status and actionable reason for host/plugin versions."""
    try:
        host = _version_tuple(host_version)
        minimum = _version_tuple(manifest.min_zaptrace_version)
        maximum = _version_tuple(manifest.max_zaptrace_version)
    except ValueError as exc:
        return False, str(exc)
    if host < minimum:
        return False, f"plugin requires ZapTrace >= {manifest.min_zaptrace_version}; current version is {host_version}"
    if host > maximum:
        return False, f"plugin supports ZapTrace <= {manifest.max_zaptrace_version}; current version is {host_version}"
    return True, "compatible"


def load_plugin_manifest(path: str | Path) -> PluginManifest:
    """Load a plugin manifest from a JSON file or directory containing zaptrace-plugin.json."""
    target = Path(path)
    manifest_path = target / PLUGIN_MANIFEST_FILENAME if target.is_dir() else target
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"plugin manifest must be an object: {manifest_path}")
    return PluginManifest.model_validate(data)


def discover_plugin_manifests(paths: Iterable[str | Path]) -> list[PluginManifest]:
    """Discover manifests from explicit paths without importing or executing plugin code."""
    manifests: list[PluginManifest] = []
    for raw_path in paths:
        path = Path(raw_path)
        manifest_path = path / PLUGIN_MANIFEST_FILENAME if path.is_dir() else path
        if not manifest_path.exists():
            continue
        manifests.append(load_plugin_manifest(manifest_path))
    return manifests


def generate_plugin_manifest_schema() -> dict[str, Any]:
    """Return the JSON Schema for the v1 plugin manifest contract."""
    schema = PluginManifest.model_json_schema(by_alias=True)
    schema["$id"] = PLUGIN_SCHEMA_URL
    schema["title"] = "ZapTrace Plugin Manifest v1"
    return schema
