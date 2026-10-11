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


@pytest.fixture
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


@pytest.fixture
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


class TestAdversarialPluginIsolation:
    def test_path_traversal_entry_rejected(self, tmp_path: Path) -> None:
        pdir = tmp_path / "traversal_plugin"
        pdir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "api_version": "1.0",
            "plugin_id": "test.traversal-plugin",
            "name": "Traversal Plugin",
            "version": "0.1.0",
            "min_zaptrace_version": "0.3.0",
            "max_zaptrace_version": "1.0.0",
            "capabilities": ["design:read"],
            "permissions": {
                "filesystem": {"read": [], "write": []},
                "network": {"allowed_domains": [], "allowed_schemes": []},
                "subprocess": False,
            },
            "entry": {"type": "python_module", "path": "../../etc/passwd"},
        }
        (pdir / "zaptrace-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        runtime = HardenedPluginRuntime(PluginRuntimeConfig(allow_unverified_signatures=True))
        res = runtime.run_plugin(pdir)
        assert not res.success
        assert res.status_code == -3
        assert "path traversal" in (res.denial_reason or "").lower()

    def test_environment_sanitization(self, valid_plugin_dir: Path, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("HOST_SECRET", "super-secret-key")
        outside_imports = tmp_path / "host-controlled-imports"
        outside_imports.mkdir()
        (outside_imports / "untrusted_host_module.py").write_text("marker = True\n", encoding="utf-8")
        monkeypatch.setenv("PYTHONPATH", str(outside_imports))
        code = """import importlib.util, json, os, sys
print(json.dumps({
    "has_secret": "HOST_SECRET" in os.environ,
    "has_pythonpath": "PYTHONPATH" in os.environ,
    "outside_imports": HOST_IMPORT_ROOT in sys.path,
    "host_module_found": importlib.util.find_spec("untrusted_host_module") is not None,
}))
""".replace("HOST_IMPORT_ROOT", json.dumps(str(outside_imports)))
        (valid_plugin_dir / "main.py").write_text(code, encoding="utf-8")
        runtime = HardenedPluginRuntime(PluginRuntimeConfig(allow_unverified_signatures=True))
        res = runtime.run_plugin(valid_plugin_dir)
        assert res.success, res.stderr
        assert res.output_data == {
            "has_secret": False,
            "has_pythonpath": False,
            "outside_imports": False,
            "host_module_found": False,
        }


def test_wasm_entry_never_runs_as_native_executable(valid_plugin_dir: Path, tmp_path: Path) -> None:
    """A WASM entry declaration cannot dispatch a native shebang script."""
    manifest_path = valid_plugin_dir / "zaptrace-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entry"] = {"type": "wasm", "path": "entry.wasm"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    marker = tmp_path / "wasm-executed.txt"
    executable = valid_plugin_dir / "entry.wasm"
    executable.write_text(
        "#!/usr/bin/env python3\nfrom pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('executed')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    runtime = HardenedPluginRuntime(PluginRuntimeConfig(allow_unverified_signatures=True))
    result = runtime.run_plugin(valid_plugin_dir)
    assert not result.success
    assert result.status_code == -7
    assert "WASI" in (result.denial_reason or "")
    assert not marker.exists()


def test_plugin_entry_directory_is_denied(valid_plugin_dir: Path) -> None:
    manifest_path = valid_plugin_dir / "zaptrace-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entry"] = {"type": "python_module", "path": "subdir"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (valid_plugin_dir / "subdir").mkdir()
    result = HardenedPluginRuntime(PluginRuntimeConfig(allow_unverified_signatures=True)).run_plugin(valid_plugin_dir)
    assert not result.success
    assert result.status_code == -4
    assert "regular file" in (result.denial_reason or "")
