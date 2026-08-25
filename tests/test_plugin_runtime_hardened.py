"""Tests for hardened plugin runtime execution and process isolation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.plugin.runtime import (
    HardenedPluginRuntime,
    PluginExecutionResult,
    PluginRuntimeConfig,
)


@pytest.fixture()
def valid_plugin_dir(tmp_path: Path) -> Path:
    """Create a temporary valid plugin directory."""
    pdir = tmp_path / "simple_plugin"
    pdir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "api_version": "1.0",
        "plugin_id": "test.simple-echo",
        "name": "Simple Echo Plugin",
        "version": "0.1.0",
        "min_zaptrace_version": "0.3.0",
        "max_zaptrace_version": "1.0.0",
        "capabilities": ["design:read"],
        "permissions": {
            "filesystem": {"read": [], "write": []},
            "network": {"allowed_domains": [], "allowed_schemes": []},
            "subprocess": False,
        },
        "entry": {"type": "python_module", "path": "main.py"},
    }
    (pdir / "zaptrace-plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    code = """\
import json
import sys

raw = sys.stdin.read()
data = json.loads(raw) if raw.strip() else {}
out = {"echo": data, "status": "ok"}
print(json.dumps(out))
"""
    (pdir / "main.py").write_text(code, encoding="utf-8")
    return pdir


@pytest.fixture()
def slow_plugin_dir(tmp_path: Path) -> Path:
    """Create a temporary plugin that sleeps indefinitely."""
    pdir = tmp_path / "slow_plugin"
    pdir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "api_version": "1.0",
        "plugin_id": "test.slow-plugin",
        "name": "Slow Plugin",
        "version": "0.1.0",
        "min_zaptrace_version": "0.3.0",
        "max_zaptrace_version": "1.0.0",
        "capabilities": ["design:read"],
        "permissions": {
            "filesystem": {"read": [], "write": []},
            "network": {"allowed_domains": [], "allowed_schemes": []},
            "subprocess": False,
        },
        "entry": {"type": "python_module", "path": "main.py"},
    }
    (pdir / "zaptrace-plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    code = """\
import time
time.sleep(10.0)
print('done')
"""
    (pdir / "main.py").write_text(code, encoding="utf-8")
    return pdir



class TestHardenedPluginRuntime:
    """Test process sandbox, timeout, and admission in runtime."""

    def test_missing_manifest_fails(self, tmp_path: Path) -> None:
        runtime = HardenedPluginRuntime(PluginRuntimeConfig(allow_unverified_signatures=True))
        res = runtime.run_plugin(tmp_path)
        assert isinstance(res, PluginExecutionResult)
        assert not res.success
        assert "Missing plugin manifest" in (res.denial_reason or "")

    def test_unverified_signature_denied_by_default(self, valid_plugin_dir: Path) -> None:
        # Default config requires verified signatures
        runtime = HardenedPluginRuntime(PluginRuntimeConfig(allow_unverified_signatures=False))
        res = runtime.run_plugin(valid_plugin_dir)
        assert not res.success
        assert "Admission denied" in (res.denial_reason or "")

    def test_successful_execution_in_sandbox(self, valid_plugin_dir: Path) -> None:
        runtime = HardenedPluginRuntime(PluginRuntimeConfig(allow_unverified_signatures=True))
        res = runtime.run_plugin(valid_plugin_dir, input_payload={"action": "test", "val": 42})
        assert res.success
        assert res.status_code == 0
        assert res.output_data.get("status") == "ok"
        assert res.output_data.get("echo", {}).get("val") == 42
        assert res.duration_ms >= 0.0

    def test_timeout_enforcement(self, slow_plugin_dir: Path) -> None:
        # Enforce strict 0.5s timeout
        runtime = HardenedPluginRuntime(
            PluginRuntimeConfig(max_execution_seconds=0.5, allow_unverified_signatures=True)
        )
        res = runtime.run_plugin(slow_plugin_dir)
        assert not res.success
        assert res.status_code == -5
        assert "timeout" in (res.denial_reason or "").lower()
