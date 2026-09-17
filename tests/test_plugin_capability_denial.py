from __future__ import annotations

import json
from pathlib import Path

from zaptrace.plugin.admission import admit_plugin_manifest
from zaptrace.plugin.manifest import PluginManifest
from zaptrace.plugin.runtime import HardenedPluginRuntime, PluginRuntimeConfig


def test_undeclared_dangerous_capability_denied_by_default(tmp_path: Path) -> None:
    manifest_data = {
        "$schema": "https://zaptrace.dev/schemas/plugin-manifest-v1.json",
        "api_version": "1.0",
        "plugin_id": "test.dangerous.plugin",
        "name": "Dangerous Plugin",
        "version": "1.0.0",
        "min_zaptrace_version": "0.1.0",
        "max_zaptrace_version": "0.9.0",
        "entry": {"type": "python_module", "path": "main.py"},
        "capabilities": ["network:connect", "subprocess:run"],
    }
    manifest = PluginManifest.model_validate(manifest_data)
    admission = admit_plugin_manifest(manifest, require_signature=False, allow_dangerous=False)

    assert admission.allowed is False
    assert admission.code == "PLUGIN_DANGEROUS_CAPABILITY_DENIED"
    assert "network:connect" in admission.message or "subprocess:run" in admission.message


def test_runtime_denies_plugin_execution_when_admission_fails(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "test_plugin"
    plugin_dir.mkdir()
    manifest_path = plugin_dir / "zaptrace-plugin.json"
    manifest_path.write_text(
        json.dumps(
            {
                "$schema": "https://zaptrace.dev/schemas/plugin-manifest-v1.json",
                "api_version": "1.0",
                "plugin_id": "test.runtime.plugin",
                "name": "Runtime Plugin",
                "version": "1.0.0",
                "min_zaptrace_version": "0.1.0",
                "max_zaptrace_version": "0.9.0",
                "entry": {"type": "python_module", "path": "main.py"},
                "capabilities": ["subprocess:run"],
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "main.py").write_text("print('hello')", encoding="utf-8")

    runtime = HardenedPluginRuntime(config=PluginRuntimeConfig(allow_unverified_signatures=True))
    res = runtime.run_plugin(plugin_dir)

    assert res.success is False
    assert res.status_code == -2
    assert "PLUGIN_DANGEROUS_CAPABILITY_DENIED" in (res.denial_reason or "")
