"""Cancellation-safe isolated execution for mutating agent tools.

Mutating tools execute against a cloned session in a dedicated subprocess.
Filesystem outputs are redirected to a private staging directory and both state
and artifacts are committed only after the worker exits successfully.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import pickle  # trusted local IPC between parent and child
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe
from typing import Any
from weakref import WeakValueDictionary

ExecutionEventSink = Callable[[str, dict[str, Any]], None]


class SessionDestroyedError(RuntimeError):
    """Raised when work targets a session that has completed destruction."""


class UnsupportedExecutionPlatformError(RuntimeError):
    """Raised when the secure isolated-worker boundary is unavailable."""


@dataclass(slots=True)
class ToolExecutionOutcome:
    """Result of an isolated mutating tool execution."""

    status: str
    result: Any = None
    error: str | None = None
    worker_terminated: bool = False
    job_id: str = ""
    duration_ms: float = 0.0
    exception_type: str | None = None


@dataclass(slots=True)
class _OutputStage:
    parameter: str
    staged_path: Path
    target_path: Path
    public_value: str
    backup_path: Path
    had_original: bool = False


_SESSION_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_OUTPUT_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_DESTROYED_SESSION_IDS: set[str] = set()
_POSIX_SIGKILL: signal.Signals = getattr(signal, "SIGKILL", signal.SIGTERM)


def _isolated_execution_supported() -> bool:
    """Return whether the secure isolated-worker boundary is available."""
    return os.name == "posix"


def clear_session_execution_state() -> None:
    """Clear process-local execution coordination state used by tests."""
    _SESSION_LOCKS.clear()
    _OUTPUT_LOCKS.clear()
    _DESTROYED_SESSION_IDS.clear()


def mark_session_destroyed(session_id: str) -> None:
    """Prevent a completed session destruction from being resurrected."""
    _DESTROYED_SESSION_IDS.add(session_id)


def is_session_destroyed(session_id: str) -> bool:
    """Return whether a session ID has completed destruction."""
    return session_id in _DESTROYED_SESSION_IDS


def session_execution_lock(session_id: str) -> asyncio.Lock:
    """Return the process-local mutation lock for one session."""
    lock = _SESSION_LOCKS.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _SESSION_LOCKS[session_id] = lock
    return lock


def _output_execution_lock(target_path: Path) -> asyncio.Lock:
    key = str(target_path)
    lock = _OUTPUT_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _OUTPUT_LOCKS[key] = lock
    return lock


def _emit_execution_event(
    event_sink: ExecutionEventSink | None,
    decision: str,
    *,
    job_id: str,
    tool_name: str,
    session_id: str,
    **metadata: Any,
) -> None:
    """Emit one trusted parent-process lifecycle event."""
    if event_sink is None:
        return
    event_sink(
        decision,
        {
            "job_id": job_id,
            "tool_name": tool_name,
            "session_id": session_id,
            **metadata,
        },
    )


def _clone_session_state(session: dict[str, Any]) -> dict[str, Any]:
    """Clone a session without retaining persistence-backed mapping behavior."""
    cloned: dict[str, Any] = {}
    for key, value in session.items():
        if key == "designs":
            cloned[key] = copy.deepcopy(dict(value))
        else:
            cloned[key] = copy.deepcopy(value)
    cloned.setdefault("designs", {})
    return cloned


def _resolve_workspace_path(workspace: Path, raw: str) -> Path:
    root = workspace.resolve()
    candidate = Path(raw)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"output path is outside workspace: {raw}") from None
    return resolved


def _output_stage_for_parameter(
    *,
    index: int,
    name: str,
    spec: Any,
    rewritten: dict[str, Any],
    workspace: Path,
    staging_root: Path,
) -> _OutputStage | None:
    """Build one staging record for an explicitly declared output parameter."""
    policy = spec.get("path_policy") if isinstance(spec, dict) else None
    if not isinstance(policy, dict) or policy.get("access") != "output":
        return None
    raw = rewritten.get(name)
    if not isinstance(raw, str) or not raw:
        return None
    target = _resolve_workspace_path(workspace, raw)
    staged_parent = staging_root / "outputs" / str(index)
    staged_parent.mkdir(parents=True, exist_ok=True)
    staged = staged_parent / (target.name or name)
    rewritten[name] = str(staged)
    return _OutputStage(
        parameter=name,
        staged_path=staged,
        target_path=target,
        public_value=raw,
        backup_path=staging_root / "backups" / str(index),
    )


def _validate_non_overlapping_output_targets(stages: list[_OutputStage]) -> None:
    """Reject targets whose publication order would be ambiguous."""
    targets = [stage.target_path for stage in stages]
    for index, left in enumerate(targets):
        for right in targets[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise ValueError(f"overlapping output paths are not supported: {left} and {right}")


def _prepare_output_staging(
    *,
    tool_def: dict[str, Any],
    kwargs: dict[str, Any],
    workspace: Path,
    staging_root: Path,
) -> tuple[dict[str, Any], list[_OutputStage]]:
    """Rewrite declared output parameters to private job-local paths."""
    rewritten = dict(kwargs)
    stages = [
        stage
        for index, (name, spec) in enumerate(tool_def.get("params", {}).items())
        if (
            stage := _output_stage_for_parameter(
                index=index,
                name=name,
                spec=spec,
                rewritten=rewritten,
                workspace=workspace,
                staging_root=staging_root,
            )
        )
        is not None
    ]
    _validate_non_overlapping_output_targets(stages)
    return rewritten, stages


async def _acquire_output_locks(stages: list[_OutputStage]) -> list[asyncio.Lock]:
    """Acquire output locks in stable order to prevent cross-session races."""
    locks = [_output_execution_lock(path) for path in sorted({stage.target_path for stage in stages})]
    acquired: list[asyncio.Lock] = []
    try:
        for lock in locks:
            await lock.acquire()
            acquired.append(lock)
        return acquired
    except asyncio.CancelledError:
        for lock in reversed(acquired):
            lock.release()
        raise


def _write_recovery_journal(
    *,
    staging_root: Path,
    job_id: str,
    session_id: str,
    tool_name: str,
    phase: str,
    stages: list[_OutputStage],
    worker_pid: int | None = None,
) -> None:
    """Persist enough local metadata to inspect an abruptly abandoned job."""
    payload = {
        "schema_version": "1.0",
        "job_id": job_id,
        "parent_pid": os.getpid(),
        "worker_pid": worker_pid,
        "session_id": session_id,
        "tool_name": tool_name,
        "phase": phase,
        "updated_at_unix": time.time(),
        "outputs": [
            {
                "parameter": stage.parameter,
                "staged_path": str(stage.staged_path.relative_to(staging_root)),
                "target_path": str(stage.target_path),
                "public_value": stage.public_value,
                "backup_path": str(stage.backup_path.relative_to(staging_root)),
                "had_original": stage.had_original,
            }
            for stage in stages
        ],
    }
    journal_path = staging_root / "recovery.json"
    temporary = journal_path.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, journal_path)


def _rewrite_staged_paths(value: Any, stages: list[_OutputStage]) -> Any:
    if isinstance(value, str):
        for stage in stages:
            staged = str(stage.staged_path)
            if value == staged:
                return stage.public_value
            prefix = staged + os.sep
            if value.startswith(prefix):
                suffix = value[len(staged) :]
                return stage.public_value.rstrip("/\\") + suffix
        return value
    if isinstance(value, dict):
        return {key: _rewrite_staged_paths(item, stages) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_staged_paths(item, stages) for item in value]
    if isinstance(value, tuple):
        return tuple(_rewrite_staged_paths(item, stages) for item in value)
    if isinstance(value, set):
        return {_rewrite_staged_paths(item, stages) for item in value}
    return value


def _publish_staged_outputs(stages: list[_OutputStage]) -> list[_OutputStage]:
    touched: list[_OutputStage] = []
    try:
        for stage in stages:
            if not stage.staged_path.exists():
                continue
            stage.target_path.parent.mkdir(parents=True, exist_ok=True)
            stage.had_original = stage.target_path.exists() or stage.target_path.is_symlink()
            if stage.had_original:
                stage.backup_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage.target_path, stage.backup_path)
                touched.append(stage)
            os.replace(stage.staged_path, stage.target_path)
            if not stage.had_original:
                touched.append(stage)
        return touched
    except OSError:
        _rollback_published_outputs(touched)
        raise


def _rollback_published_outputs(stages: list[_OutputStage]) -> None:
    for stage in reversed(stages):
        if stage.target_path.exists() or stage.target_path.is_symlink():
            if stage.target_path.is_dir() and not stage.target_path.is_symlink():
                shutil.rmtree(stage.target_path)
            else:
                stage.target_path.unlink(missing_ok=True)
        if stage.backup_path.exists() or stage.backup_path.is_symlink():
            stage.target_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage.backup_path, stage.target_path)


def _audit_event_identity(event: Any) -> str:
    """Return a stable identity for audit de-duplication."""
    event_id = event.get("event_id") if isinstance(event, dict) else None
    return str(event_id) if event_id else repr(event)


def _unique_audit_events(*collections: Any) -> list[Any]:
    """Collect unique events while retaining first-seen order."""
    combined: list[Any] = []
    seen: set[str] = set()
    for collection in collections:
        if not isinstance(collection, list):
            continue
        for event in collection:
            key = _audit_event_identity(event)
            if key not in seen:
                seen.add(key)
                combined.append(event)
    return combined


def _merge_audit_events(incoming: Any, current: Any) -> list[Any]:
    """Preserve append-only audit events written while a worker was running."""
    combined = _unique_audit_events(incoming, current)
    timestamped = all(isinstance(event, dict) and isinstance(event.get("timestamp"), str) for event in combined)
    if timestamped:
        combined.sort(key=lambda event: event["timestamp"])
    return combined


def _replace_session_state(
    session_id: str,
    incoming: dict[str, Any],
    *,
    merge_current_audit: bool,
) -> None:
    """Replace one parent session while preserving its design mapping type."""
    from zaptrace.agent import _tool_impls

    current = _tool_impls._get_session(session_id)
    current_designs = current.get("designs", {})
    current_audit = current.get("audit_events", [])
    incoming_designs = dict(incoming.get("designs", {}))
    replacement = {key: value for key, value in incoming.items() if key != "designs"}
    if merge_current_audit:
        merged_audit = _merge_audit_events(replacement.get("audit_events", []), current_audit)
        if merged_audit:
            replacement["audit_events"] = merged_audit

    current.clear()
    current.update(replacement)
    replace_all = getattr(current_designs, "replace_all", None)
    if callable(replace_all):
        operation = "worker-commit" if merge_current_audit else "worker-state-restore"
        replace_all(incoming_designs, operation=operation)
        current["designs"] = current_designs
    elif hasattr(current_designs, "persist"):
        current_designs.clear()
        for name, design in incoming_designs.items():
            current_designs[name] = design
        current["designs"] = current_designs
    else:
        current["designs"] = incoming_designs


def _restore_session_state(session_id: str, previous: dict[str, Any]) -> None:
    """Restore an exact parent-session snapshot after a failed terminal commit."""
    try:
        _replace_session_state(session_id, previous, merge_current_audit=False)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as rollback_error:
        raise RuntimeError("session commit failed and previous state could not be restored") from rollback_error


def _commit_session_state(session_id: str, incoming: dict[str, Any]) -> dict[str, Any]:
    """Commit a worker snapshot and return the exact prior parent state."""
    from zaptrace.agent import _tool_impls

    previous = _clone_session_state(_tool_impls._get_session(session_id))
    try:
        _replace_session_state(session_id, incoming, merge_current_audit=True)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        _restore_session_state(session_id, previous)
        raise
    return previous


def _write_request(path: Path, payload: dict[str, Any]) -> None:
    with path.open("wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def _read_response(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, dict):
        raise TypeError("isolated worker returned an invalid response")
    return payload


def _spawn_worker_sync(
    *,
    request_path: Path,
    response_path: Path,
    project_root: str,
    child_env: dict[str, str],
) -> subprocess.Popen[Any]:
    """Start the worker outside the event-loop thread and return its handle."""
    subprocess_options: dict[str, Any] = {}
    if os.name == "posix":
        subprocess_options["start_new_session"] = True
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "zaptrace.agent.worker",
            str(request_path),
            str(response_path),
        ],
        cwd=project_root,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        **subprocess_options,
    )


def _process_group_exists(process_group_id: int) -> bool:
    """Return whether a POSIX process group still has live members."""
    killpg = getattr(os, "killpg", None)
    if killpg is None:
        raise UnsupportedExecutionPlatformError("POSIX process-group signaling is unavailable")
    try:
        killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_process_group_exit_sync(process_group_id: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while _process_group_exists(process_group_id) and time.monotonic() < deadline:
        time.sleep(0.02)
    return not _process_group_exists(process_group_id)


def _signal_worker(process: subprocess.Popen[Any], sig: signal.Signals) -> None:
    """Send a termination signal to the worker or its POSIX process group."""
    with suppress(ProcessLookupError):
        if os.name == "posix":
            killpg = getattr(os, "killpg", None)
            if killpg is None:
                raise UnsupportedExecutionPlatformError("POSIX process-group signaling is unavailable")
            killpg(process.pid, sig)
        elif sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()


def _reap_worker(process: subprocess.Popen[Any], timeout_s: float | None = None) -> bool:
    """Wait for the worker leader and report whether it exited."""
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return False
    return process.poll() is not None


def _terminate_posix_worker(process: subprocess.Popen[Any]) -> bool:
    """Terminate and reap the complete POSIX worker process group."""
    process_group_id = process.pid
    leader_stopped = process.poll() is not None
    if not leader_stopped:
        _signal_worker(process, signal.SIGTERM)
        # Reap the leader before checking group existence. A terminated but
        # unreaped leader remains a zombie and keeps ``killpg(..., 0)`` true.
        leader_stopped = _reap_worker(process, 1.0)

    group_stopped = _wait_for_process_group_exit_sync(process_group_id, 0.1)
    if not group_stopped:
        _signal_worker(process, _POSIX_SIGKILL)
        if not leader_stopped:
            leader_stopped = _reap_worker(process, 1.0)
        group_stopped = _wait_for_process_group_exit_sync(process_group_id, 1.0)

    if not leader_stopped:
        leader_stopped = _reap_worker(process)
    return group_stopped and leader_stopped


def _terminate_direct_worker(process: subprocess.Popen[Any]) -> bool:
    """Terminate a direct worker using cross-platform process APIs."""
    if process.poll() is not None:
        return True
    with suppress(ProcessLookupError):
        process.terminate()
    if not _reap_worker(process, 1.0):
        with suppress(ProcessLookupError):
            process.kill()
        _reap_worker(process)
    return process.poll() is not None


def _terminate_worker_sync(process: subprocess.Popen[Any]) -> bool:
    """Terminate and reap a worker without blocking the event-loop thread."""
    if os.name == "posix":
        return _terminate_posix_worker(process)
    return _terminate_direct_worker(process)


async def _terminate_worker(process: subprocess.Popen[Any]) -> bool:
    """Terminate the worker process group and wait until it is reaped."""
    return await asyncio.to_thread(_terminate_worker_sync, process)


def _emit_lifecycle_event_safely(
    event_sink: ExecutionEventSink | None,
    decision: str,
    *,
    job_id: str,
    tool_name: str,
    session_id: str,
    **metadata: Any,
) -> Exception | None:
    """Capture arbitrary audit-sink failures without interrupting worker cleanup."""
    try:
        _emit_execution_event(
            event_sink,
            decision,
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
            **metadata,
        )
    except Exception as exc:  # NOSONAR - external lifecycle sinks may raise arbitrary exceptions
        return exc
    return None


async def _terminate_and_record(
    *,
    process: subprocess.Popen[Any],
    communication_task: asyncio.Task[tuple[Any, Any]] | None,
    event_sink: ExecutionEventSink | None,
    decision: str,
    reason: str,
    started: float,
    job_id: str,
    tool_name: str,
    session_id: str,
    timeout_s: float | None = None,
) -> bool:
    """Terminate and drain the worker even when lifecycle auditing fails."""
    request_metadata = {"timeout_s": timeout_s} if timeout_s is not None else {}
    audit_error = _emit_lifecycle_event_safely(
        event_sink,
        decision,
        job_id=job_id,
        tool_name=tool_name,
        session_id=session_id,
        **request_metadata,
    )

    terminated = await _terminate_worker(process)
    if communication_task is None:
        await asyncio.to_thread(process.communicate)
    else:
        await asyncio.shield(communication_task)
    duration_ms = (time.monotonic() - started) * 1000

    termination_error = _emit_lifecycle_event_safely(
        event_sink,
        "worker_terminated",
        job_id=job_id,
        tool_name=tool_name,
        session_id=session_id,
        worker_terminated=terminated,
        duration_ms=duration_ms,
    )
    rollback_error = _emit_lifecycle_event_safely(
        event_sink,
        "rollback",
        job_id=job_id,
        tool_name=tool_name,
        session_id=session_id,
        reason=reason,
        worker_terminated=terminated,
        duration_ms=duration_ms,
    )
    lifecycle_error = audit_error or termination_error or rollback_error
    if lifecycle_error is not None:
        raise RuntimeError(f"execution lifecycle audit failed: {lifecycle_error}")
    return terminated


async def _spawn_worker_cancellation_safe(
    *,
    request_path: Path,
    response_path: Path,
    project_root: str,
    child_env: dict[str, str],
    event_sink: ExecutionEventSink | None,
    started: float,
    job_id: str,
    tool_name: str,
    session_id: str,
) -> subprocess.Popen[Any]:
    """Own the worker handle before propagating cancellation to the caller."""
    spawn_task = asyncio.create_task(
        asyncio.to_thread(
            _spawn_worker_sync,
            request_path=request_path,
            response_path=response_path,
            project_root=project_root,
            child_env=child_env,
        )
    )
    try:
        return await asyncio.shield(spawn_task)
    except asyncio.CancelledError:
        process = await asyncio.shield(spawn_task)
        await _terminate_and_record(
            process=process,
            communication_task=None,
            event_sink=event_sink,
            decision="cancel_requested",
            reason="caller cancellation during worker startup",
            started=started,
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
        )
        raise


def _resolve_tool_identity(tool_def: dict[str, Any]) -> tuple[str, str]:
    """Return the import identity required by the isolated worker."""
    fn = tool_def["fn"]
    module_name = str(getattr(fn, "__module__", ""))
    qualname = str(getattr(fn, "__qualname__", ""))
    if not module_name or not qualname or "<locals>" in qualname:
        raise ValueError("isolated mutating tools must use importable top-level callables")
    return module_name, qualname


def _worker_environment(workspace: Path) -> tuple[str, dict[str, str]]:
    """Build the child environment without mutating the parent environment."""
    project_root = str(Path(__file__).resolve().parents[2])
    child_env = os.environ.copy()
    child_env["ZAPTRACE_WORKSPACE"] = str(workspace)
    # Isolated workers operate only on the serialized candidate state. Durable
    # publication belongs exclusively to the trusted parent coordinator.
    child_env["ZAPTRACE_PERSISTENCE_DISABLED"] = "1"
    existing_pythonpath = child_env.get("PYTHONPATH", "")
    child_env["PYTHONPATH"] = (
        project_root if not existing_pythonpath else os.pathsep.join((project_root, existing_pythonpath))
    )
    return project_root, child_env


def _request_payload(
    *,
    job_id: str,
    tool_name: str,
    module_name: str,
    qualname: str,
    kwargs: dict[str, Any],
    session_id: str,
    session: dict[str, Any],
) -> dict[str, Any]:
    """Build the trusted parent-to-worker request object."""
    return {
        "job_id": job_id,
        "tool_name": tool_name,
        "module_name": module_name,
        "qualname": qualname,
        "kwargs": kwargs,
        "session_id": session_id,
        "session_state": _clone_session_state(session),
    }


async def _communicate_with_deadline(
    *,
    process: subprocess.Popen[Any],
    timeout_s: float,
    event_sink: ExecutionEventSink | None,
    started: float,
    job_id: str,
    tool_name: str,
    session_id: str,
) -> tuple[Any, Any] | ToolExecutionOutcome:
    """Wait for one worker, terminating it before timeout/cancellation returns."""
    communication_task = asyncio.create_task(asyncio.to_thread(process.communicate))
    try:
        return await asyncio.wait_for(asyncio.shield(communication_task), timeout=timeout_s)
    except TimeoutError:
        terminated = await _terminate_and_record(
            process=process,
            communication_task=communication_task,
            event_sink=event_sink,
            decision="timeout",
            reason="timeout",
            started=started,
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
            timeout_s=timeout_s,
        )
        return ToolExecutionOutcome(
            status="timeout",
            error=f"tool timed out after {timeout_s}s",
            worker_terminated=terminated,
            job_id=job_id,
            duration_ms=(time.monotonic() - started) * 1000,
        )
    except asyncio.CancelledError:
        await _terminate_and_record(
            process=process,
            communication_task=communication_task,
            event_sink=event_sink,
            decision="cancel_requested",
            reason="caller cancellation",
            started=started,
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
        )
        raise


def _worker_response(
    *,
    response_path: Path,
    stderr: Any,
    process: subprocess.Popen[Any],
    event_sink: ExecutionEventSink | None,
    started: float,
    job_id: str,
    tool_name: str,
    session_id: str,
) -> dict[str, Any] | ToolExecutionOutcome:
    """Load a completed worker response or return a structured terminal error."""
    duration_ms = (time.monotonic() - started) * 1000
    if not response_path.exists():
        stderr_text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else str(stderr)
        error = stderr_text.strip() or f"isolated worker exited with status {process.returncode}"
        _emit_execution_event(
            event_sink,
            "rollback",
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
            reason="worker exited without a response",
            worker_terminated=process.returncode is not None,
            duration_ms=duration_ms,
        )
        return ToolExecutionOutcome(
            status="error",
            error=error,
            worker_terminated=process.returncode is not None,
            job_id=job_id,
            duration_ms=duration_ms,
        )

    response = _read_response(response_path)
    if response.get("status") == "completed":
        return response

    exception_type = str(response.get("exception_type") or "") or None
    _emit_execution_event(
        event_sink,
        "rollback",
        job_id=job_id,
        tool_name=tool_name,
        session_id=session_id,
        reason="worker error",
        worker_terminated=process.returncode is not None,
        exception_type=exception_type,
        duration_ms=duration_ms,
    )
    return ToolExecutionOutcome(
        status="error",
        error=str(response.get("error") or "isolated worker failed"),
        exception_type=exception_type,
        worker_terminated=process.returncode is not None,
        job_id=job_id,
        duration_ms=duration_ms,
    )


def _commit_worker_response(
    *,
    response: dict[str, Any],
    stages: list[_OutputStage],
    staging_root: Path,
    process: subprocess.Popen[Any],
    event_sink: ExecutionEventSink | None,
    started: float,
    job_id: str,
    tool_name: str,
    session_id: str,
) -> ToolExecutionOutcome:
    """Atomically publish a successful worker result and parent session state."""
    incoming_state = _rewrite_staged_paths(dict(response["session_state"]), stages)
    result = _rewrite_staged_paths(response.get("result"), stages)
    _write_recovery_journal(
        staging_root=staging_root,
        job_id=job_id,
        session_id=session_id,
        tool_name=tool_name,
        phase="publishing_outputs",
        stages=stages,
        worker_pid=process.pid,
    )
    published = _publish_staged_outputs(stages)
    _write_recovery_journal(
        staging_root=staging_root,
        job_id=job_id,
        session_id=session_id,
        tool_name=tool_name,
        phase="committing_state",
        stages=stages,
        worker_pid=process.pid,
    )
    previous_state: dict[str, Any] | None = None
    try:
        previous_state = _commit_session_state(session_id, incoming_state)
        duration_ms = (time.monotonic() - started) * 1000
        _emit_execution_event(
            event_sink,
            "commit",
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
            worker_terminated=process.returncode is not None,
            duration_ms=duration_ms,
        )
        _write_recovery_journal(
            staging_root=staging_root,
            job_id=job_id,
            session_id=session_id,
            tool_name=tool_name,
            phase="committed",
            stages=stages,
            worker_pid=process.pid,
        )
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        if previous_state is not None:
            _restore_session_state(session_id, previous_state)
        _rollback_published_outputs(published)
        raise
    return ToolExecutionOutcome(
        status="completed",
        result=result,
        worker_terminated=process.returncode is not None,
        job_id=job_id,
        duration_ms=duration_ms,
    )


async def _coordinator_error_outcome(
    *,
    error: Exception,
    process: subprocess.Popen[Any] | None,
    event_sink: ExecutionEventSink | None,
    started: float,
    job_id: str,
    tool_name: str,
    session_id: str,
) -> ToolExecutionOutcome:
    """Terminate any active worker and return one structured coordinator error."""
    worker_terminated = process is None or process.poll() is not None
    if process is not None and process.poll() is None:
        worker_terminated = await _terminate_worker(process)
        _emit_execution_event(
            event_sink,
            "worker_terminated",
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
            worker_terminated=worker_terminated,
            reason="coordinator error",
        )
    duration_ms = (time.monotonic() - started) * 1000
    with suppress(OSError, ValueError, TypeError, KeyError, RuntimeError):
        _emit_execution_event(
            event_sink,
            "rollback",
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
            reason="coordinator error",
            worker_terminated=worker_terminated,
            exception_type=type(error).__name__,
            duration_ms=duration_ms,
        )
    return ToolExecutionOutcome(
        status="error",
        error=str(error),
        exception_type=type(error).__name__,
        worker_terminated=worker_terminated,
        job_id=job_id,
        duration_ms=duration_ms,
    )


async def _execute_locked(
    *,
    tool_name: str,
    tool_def: dict[str, Any],
    kwargs: dict[str, Any],
    session_id: str,
    timeout_s: float,
    workspace: Path,
    job_id: str,
    event_sink: ExecutionEventSink | None,
) -> ToolExecutionOutcome:
    """Coordinate one isolated mutation while the session lock is held."""
    from zaptrace.agent import _tool_impls

    started = time.monotonic()
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".zaptrace-job-", dir=workspace))
    staging_root.chmod(0o700)
    request_path = staging_root / "request.pickle"
    response_path = staging_root / "response.pickle"
    process: subprocess.Popen[Any] | None = None
    acquired_output_locks: list[asyncio.Lock] = []

    try:
        rewritten_kwargs, stages = _prepare_output_staging(
            tool_def=tool_def,
            kwargs=kwargs,
            workspace=workspace,
            staging_root=staging_root,
        )
        acquired_output_locks = await _acquire_output_locks(stages)
        for stage in stages:
            stage.had_original = stage.target_path.exists() or stage.target_path.is_symlink()

        _emit_execution_event(
            event_sink,
            "start",
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
        )
        module_name, qualname = _resolve_tool_identity(tool_def)
        _write_request(
            request_path,
            _request_payload(
                job_id=job_id,
                tool_name=tool_name,
                module_name=module_name,
                qualname=qualname,
                kwargs=rewritten_kwargs,
                session_id=session_id,
                session=_tool_impls._get_session(session_id),
            ),
        )
        project_root, child_env = _worker_environment(workspace)
        process = await _spawn_worker_cancellation_safe(
            request_path=request_path,
            response_path=response_path,
            project_root=project_root,
            child_env=child_env,
            event_sink=event_sink,
            started=started,
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
        )
        _write_recovery_journal(
            staging_root=staging_root,
            job_id=job_id,
            session_id=session_id,
            tool_name=tool_name,
            phase="worker_running",
            stages=stages,
            worker_pid=process.pid,
        )
        communication = await _communicate_with_deadline(
            process=process,
            timeout_s=timeout_s,
            event_sink=event_sink,
            started=started,
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
        )
        if isinstance(communication, ToolExecutionOutcome):
            return communication

        _stdout, stderr = communication
        if not await _terminate_worker(process):
            raise RuntimeError("isolated worker process group did not terminate")
        response = _worker_response(
            response_path=response_path,
            stderr=stderr,
            process=process,
            event_sink=event_sink,
            started=started,
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
        )
        if isinstance(response, ToolExecutionOutcome):
            return response
        return _commit_worker_response(
            response=response,
            stages=stages,
            staging_root=staging_root,
            process=process,
            event_sink=event_sink,
            started=started,
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
        )
    except asyncio.CancelledError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, EOFError, pickle.PickleError) as exc:
        return await _coordinator_error_outcome(
            error=exc,
            process=process,
            event_sink=event_sink,
            started=started,
            job_id=job_id,
            tool_name=tool_name,
            session_id=session_id,
        )
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
        for lock in reversed(acquired_output_locks):
            lock.release()


async def execute_mutating_tool(
    *,
    tool_name: str,
    tool_def: dict[str, Any],
    kwargs: dict[str, Any],
    session_id: str,
    timeout_s: float,
    workspace: Path,
    job_id: str | None = None,
    event_sink: ExecutionEventSink | None = None,
) -> ToolExecutionOutcome:
    """Execute one mutating tool with session and output-target serialization."""
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    resolved_job_id = job_id or f"job-{token_urlsafe(18)}"
    if not _isolated_execution_supported():
        error = "isolated mutating tool execution requires a POSIX platform"
        _emit_execution_event(
            event_sink,
            "error",
            job_id=resolved_job_id,
            tool_name=tool_name,
            session_id=session_id,
            reason=error,
            exception_type=UnsupportedExecutionPlatformError.__name__,
        )
        return ToolExecutionOutcome(
            status="error",
            error=error,
            worker_terminated=True,
            exception_type=UnsupportedExecutionPlatformError.__name__,
            job_id=resolved_job_id,
        )
    async with session_execution_lock(session_id):
        if is_session_destroyed(session_id):
            return ToolExecutionOutcome(
                status="conflict",
                error=f"Session '{session_id}' has been destroyed",
                exception_type=SessionDestroyedError.__name__,
                job_id=resolved_job_id,
            )
        return await _execute_locked(
            tool_name=tool_name,
            tool_def=tool_def,
            kwargs=kwargs,
            session_id=session_id,
            timeout_s=timeout_s,
            workspace=workspace,
            job_id=resolved_job_id,
            event_sink=event_sink,
        )
