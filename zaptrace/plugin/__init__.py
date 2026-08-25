"""Plugin manifest and admission contracts for ZapTrace."""

from __future__ import annotations

from zaptrace.plugin.admission import PluginAdmissionResult, admit_plugin_manifest
from zaptrace.plugin.manifest import (
    PluginCapability,
    PluginEntry,
    PluginManifest,
    PluginPermissions,
    PluginSigning,
    discover_plugin_manifests,
    generate_plugin_manifest_schema,
    load_plugin_manifest,
)
from zaptrace.plugin.runtime import (
    HardenedPluginRuntime,
    PluginExecutionResult,
    PluginRuntimeConfig,
)

__all__ = [
    "HardenedPluginRuntime",
    "PluginAdmissionResult",
    "PluginCapability",
    "PluginEntry",
    "PluginExecutionResult",
    "PluginManifest",
    "PluginPermissions",
    "PluginRuntimeConfig",
    "PluginSigning",
    "admit_plugin_manifest",
    "discover_plugin_manifests",
    "generate_plugin_manifest_schema",
    "load_plugin_manifest",
]

