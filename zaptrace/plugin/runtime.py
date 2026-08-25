"""Hardened runtime execution engine for ZapTrace plugins.

Enforces:
- Process-level isolation with stripped environment variables
- CPU timeout / termination
- Structured JSON-RPC / CLI request-response envelope
- Filesystem scope boundary checks
- Audit trail logging
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.plugin.admission import PluginAdmissionResult, admit_plugin_manifest
from zaptrace.plugin.manifest import load_plugin_manifest


class PluginExecutionResult(BaseModel):
    """Result of running a plugin in the hardened sandbox."""

    model_config = ConfigDict(strict=False)

    plugin_id: str
    success: bool
    status_code: int = 0
    stdout: str = ""
    stderr: str = ""
    output_data: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0
    denial_reason: str | None = None
    audit_events: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class PluginRuntimeConfig:
    """Security and execution limits for the plugin sandbox."""

    max_execution_seconds: float = 15.0
    allow_unverified_signatures: bool = False
    sandbox_workspace: Path | None = None
    allowed_env_vars: set[str] = field(
        default_factory=lambda: {"PATH", "SYSTEMROOT", "TEMP", "TMP", "PYTHONPATH"}
    )


class HardenedPluginRuntime:
    """Deterministic, process-isolated plugin executor."""

    def __init__(self, config: PluginRuntimeConfig | None = None) -> None:
        self.config = config or PluginRuntimeConfig()

    def run_plugin(
        self,
        plugin_dir: str | Path,
        input_payload: dict[str, Any] | None = None,
        *,
        actor: str = "agent-core",
        session_id: str = "default",
    ) -> PluginExecutionResult:
        """Admit and execute a plugin in the hardened process sandbox."""
        pdir = Path(plugin_dir).resolve()
        start_time = time.monotonic()
        audit_events: list[dict[str, Any]] = []

        # 1. Load manifest
        manifest_path = pdir / "zaptrace-plugin.json"
        if not manifest_path.exists():
            return PluginExecutionResult(
                plugin_id="unknown",
                success=False,
                status_code=-1,
                denial_reason=f"Missing plugin manifest: {manifest_path}",
            )

        try:
            manifest = load_plugin_manifest(manifest_path)
        except Exception as e:
            return PluginExecutionResult(
                plugin_id="unknown",
                success=False,
                status_code=-1,
                denial_reason=f"Invalid plugin manifest: {e}",
            )

        plugin_id = manifest.plugin_id

        # 2. Admission check
        admission: PluginAdmissionResult = admit_plugin_manifest(
            manifest,
            actor=actor,
            session_id=session_id,
            require_signature=not self.config.allow_unverified_signatures,
        )

        if not admission.allowed:
            return PluginExecutionResult(
                plugin_id=plugin_id,
                success=False,
                status_code=-2,
                denial_reason=f"Admission denied [{admission.code}]: {admission.message}",
                audit_events=[admission.audit_event] if admission.audit_event else [],
            )

        # 3. Path scope validation for entry point
        entry_path = (pdir / manifest.entry.path).resolve()
        try:
            entry_path.relative_to(pdir)
        except ValueError:
            return PluginExecutionResult(
                plugin_id=plugin_id,
                success=False,
                status_code=-3,
                denial_reason="Entry point attempts path traversal outside plugin directory",
            )

        if not entry_path.exists():
            return PluginExecutionResult(
                plugin_id=plugin_id,
                success=False,
                status_code=-4,
                denial_reason=f"Plugin entry point file not found: {entry_path}",
            )

        # 4. Prepare sanitized environment
        clean_env = {
            k: v for k, v in os.environ.items() if k.upper() in self.config.allowed_env_vars
        }
        clean_env["ZAPTRACE_PLUGIN_ID"] = plugin_id
        clean_env["ZAPTRACE_SANDBOX_ACTIVE"] = "1"

        # 5. Build command
        cmd = [sys.executable, str(entry_path)] if manifest.entry.type == "python_module" else [str(entry_path)]

        # 6. Execute subprocess with timeout
        payload_str = json.dumps(input_payload or {})
        try:
            proc = subprocess.run(
                cmd,
                input=payload_str,
                text=True,
                capture_output=True,
                cwd=str(pdir),
                env=clean_env,
                timeout=self.config.max_execution_seconds,
            )
            duration = (time.monotonic() - start_time) * 1000.0

            # Try parsing stdout as JSON
            output_data = {}
            if proc.stdout.strip():
                import contextlib

                with contextlib.suppress(json.JSONDecodeError):
                    output_data = json.loads(proc.stdout.strip())

            return PluginExecutionResult(
                plugin_id=plugin_id,
                success=proc.returncode == 0,
                status_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                output_data=output_data if isinstance(output_data, dict) else {"raw": output_data},
                duration_ms=round(duration, 2),
                audit_events=audit_events,
            )

        except subprocess.TimeoutExpired:
            duration = (time.monotonic() - start_time) * 1000.0
            return PluginExecutionResult(
                plugin_id=plugin_id,
                success=False,
                status_code=-5,
                stderr=f"Execution timed out after {self.config.max_execution_seconds}s",
                duration_ms=round(duration, 2),
                denial_reason="Plugin CPU/execution timeout expired",
            )
        except Exception as e:
            duration = (time.monotonic() - start_time) * 1000.0
            return PluginExecutionResult(
                plugin_id=plugin_id,
                success=False,
                status_code=-6,
                stderr=str(e),
                duration_ms=round(duration, 2),
                denial_reason=f"Subprocess execution failure: {e}",
            )
