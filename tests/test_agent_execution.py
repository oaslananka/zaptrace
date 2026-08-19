"""Tests for cancellation-safe isolated agent tool execution."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests import execution_probe_tools as probes
from zaptrace.agent import _tool_impls

requires_posix_execution = pytest.mark.skipif(
    os.name != "posix", reason="secure isolated mutating-tool execution requires POSIX"
)


def _tool_def(fn: Any, *, output_dir: bool = False) -> dict[str, Any]:
    params: dict[str, dict[str, Any]] = {
        "session_id": {"type": "string"},
    }
    if output_dir:
        params["output_dir"] = {
            "type": "string",
            "path_policy": {"root": "workspace", "access": "output", "must_exist": False},
        }
    return {
        "fn": fn,
        "params": params,
        "capability": "sandbox-write",
    }


@pytest.fixture(autouse=True)
def _reset_execution_state() -> None:
    from zaptrace.agent.execution import clear_session_execution_state

    _tool_impls._sessions.clear()
    clear_session_execution_state()


@pytest.mark.asyncio
async def test_unsupported_platform_fails_closed_before_worker_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zaptrace.agent.execution as execution

    session_id = "unsupported-platform-session"
    original = {"designs": {}, "stable": True}
    _tool_impls._sessions[session_id] = original.copy()
    events: list[tuple[str, dict[str, Any]]] = []

    monkeypatch.setattr(execution, "_isolated_execution_supported", lambda: False)
    monkeypatch.setattr(
        execution,
        "_spawn_worker_sync",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("worker must not start")),
    )

    outcome = await execution.execute_mutating_tool(
        tool_name="write_success",
        tool_def=_tool_def(probes.write_success, output_dir=True),
        kwargs={"session_id": session_id, "output_dir": str(tmp_path / "published"), "content": "new"},
        session_id=session_id,
        timeout_s=5.0,
        workspace=tmp_path,
        job_id="job-unsupported-platform",
        event_sink=lambda decision, metadata: events.append((decision, metadata)),
    )

    assert outcome.status == "error"
    assert outcome.exception_type == "UnsupportedExecutionPlatformError"
    assert outcome.error == "isolated mutating tool execution requires a POSIX platform"
    assert outcome.worker_terminated is True
    assert outcome.job_id == "job-unsupported-platform"
    assert _tool_impls._sessions[session_id] == original
    assert [decision for decision, _metadata in events] == ["error"]
    assert events[0][1]["reason"] == "isolated mutating tool execution requires a POSIX platform"
    assert events[0][1]["exception_type"] == "UnsupportedExecutionPlatformError"
    assert not list(tmp_path.glob(".zaptrace-job-*"))


def test_direct_worker_hard_kill_uses_process_api(monkeypatch: pytest.MonkeyPatch) -> None:
    import zaptrace.agent.execution as execution

    process = subprocess.Popen.__new__(subprocess.Popen)
    states = iter((None, 1))
    calls: list[str] = []
    monkeypatch.setattr(process, "poll", lambda: next(states))
    monkeypatch.setattr(process, "terminate", lambda: calls.append("terminate"))
    monkeypatch.setattr(process, "kill", lambda: calls.append("kill"))
    reap_results = iter((False, True))
    monkeypatch.setattr(execution, "_reap_worker", lambda _process, _timeout=None: next(reap_results))

    assert execution._terminate_direct_worker(process) is True
    assert calls == ["terminate", "kill"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups are required")
def test_posix_worker_termination_reaps_the_group_leader() -> None:
    from zaptrace.agent import execution

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    try:
        assert execution._terminate_posix_worker(process) is True
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


@requires_posix_execution
def test_posix_worker_termination_reaps_after_sigkill(monkeypatch: pytest.MonkeyPatch) -> None:
    from zaptrace.agent import execution

    process = subprocess.Popen.__new__(subprocess.Popen)
    process.pid = 4242
    monkeypatch.setattr(process, "poll", lambda: None)
    signals: list[signal.Signals] = []
    reap_timeouts: list[float | None] = []
    group_timeouts: list[float] = []
    reap_results = iter((False, True))
    group_results = iter((False, True))

    monkeypatch.setattr(execution, "_signal_worker", lambda _process, sig: signals.append(sig))

    def fake_reap(_process: subprocess.Popen[object], timeout_s: float | None = None) -> bool:
        reap_timeouts.append(timeout_s)
        return next(reap_results)

    def fake_group_wait(_process_group_id: int, timeout_s: float) -> bool:
        group_timeouts.append(timeout_s)
        return next(group_results)

    monkeypatch.setattr(execution, "_reap_worker", fake_reap)
    monkeypatch.setattr(execution, "_wait_for_process_group_exit_sync", fake_group_wait)

    assert execution._terminate_posix_worker(process) is True
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert reap_timeouts == [1.0, 1.0]
    assert group_timeouts == [0.1, 1.0]


@requires_posix_execution
def test_posix_worker_termination_performs_final_reap(monkeypatch: pytest.MonkeyPatch) -> None:
    from zaptrace.agent import execution

    process = subprocess.Popen.__new__(subprocess.Popen)
    process.pid = 4243
    monkeypatch.setattr(process, "poll", lambda: None)
    signals: list[signal.Signals] = []
    reap_timeouts: list[float | None] = []
    reap_results = iter((False, True))

    monkeypatch.setattr(execution, "_signal_worker", lambda _process, sig: signals.append(sig))

    def fake_reap(_process: subprocess.Popen[object], timeout_s: float | None = None) -> bool:
        reap_timeouts.append(timeout_s)
        return next(reap_results)

    monkeypatch.setattr(execution, "_reap_worker", fake_reap)
    monkeypatch.setattr(execution, "_wait_for_process_group_exit_sync", lambda _pid, _timeout: True)

    assert execution._terminate_posix_worker(process) is True
    assert signals == [signal.SIGTERM]
    assert reap_timeouts == [1.0, None]


@pytest.mark.asyncio
@requires_posix_execution
async def test_timeout_cannot_commit_late_session_mutation(tmp_path: Path) -> None:
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "timeout-session"
    _tool_impls._sessions[session_id] = {"designs": {}, "markers": []}

    outcome = await execute_mutating_tool(
        tool_name="mutate_after_delay",
        tool_def=_tool_def(probes.mutate_after_delay),
        kwargs={"session_id": session_id, "marker": "late", "delay_s": 0.5},
        session_id=session_id,
        timeout_s=0.1,
        workspace=tmp_path,
    )

    assert outcome.status == "timeout"
    assert outcome.worker_terminated is True
    assert _tool_impls._sessions[session_id]["markers"] == []
    await asyncio.sleep(0.6)
    assert _tool_impls._sessions[session_id]["markers"] == []


@pytest.mark.asyncio
@requires_posix_execution
async def test_timeout_terminates_worker_descendants(tmp_path: Path) -> None:
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "descendant-session"
    marker_path = tmp_path / "descendant.txt"
    _tool_impls._sessions[session_id] = {"designs": {}}

    outcome = await execute_mutating_tool(
        tool_name="spawn_descendant_then_delay",
        tool_def=_tool_def(probes.spawn_descendant_then_delay),
        kwargs={"session_id": session_id, "marker_path": str(marker_path), "delay_s": 0.4},
        session_id=session_id,
        timeout_s=0.1,
        workspace=tmp_path,
    )

    assert outcome.status == "timeout"
    assert outcome.worker_terminated is True
    await asyncio.sleep(1.2)
    assert not marker_path.exists()


@pytest.mark.asyncio
@requires_posix_execution
async def test_same_session_mutators_are_serialized_without_lost_updates(tmp_path: Path) -> None:
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "serialized-session"
    _tool_impls._sessions[session_id] = {
        "designs": {},
        "markers": [],
        "active_mutators": 0,
        "max_active_mutators": 0,
    }
    tool_def = _tool_def(probes.append_with_delay)

    first = asyncio.create_task(
        execute_mutating_tool(
            tool_name="append_with_delay",
            tool_def=tool_def,
            kwargs={"session_id": session_id, "marker": "first", "delay_s": 0.2},
            session_id=session_id,
            timeout_s=5.0,
            workspace=tmp_path,
        )
    )
    await asyncio.sleep(0.02)
    second = asyncio.create_task(
        execute_mutating_tool(
            tool_name="append_with_delay",
            tool_def=tool_def,
            kwargs={"session_id": session_id, "marker": "second", "delay_s": 0.05},
            session_id=session_id,
            timeout_s=5.0,
            workspace=tmp_path,
        )
    )

    first_outcome, second_outcome = await asyncio.gather(first, second)

    assert first_outcome.status == "completed"
    assert second_outcome.status == "completed"
    session = _tool_impls._sessions[session_id]
    assert session["markers"] == ["first", "second"]
    assert session["max_active_mutators"] == 1
    assert session["active_mutators"] == 0


@pytest.mark.asyncio
@requires_posix_execution
async def test_timeout_discards_staged_artifacts(tmp_path: Path) -> None:
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "artifact-timeout-session"
    output_dir = tmp_path / "published"
    _tool_impls._sessions[session_id] = {"designs": {}}

    outcome = await execute_mutating_tool(
        tool_name="write_then_delay",
        tool_def=_tool_def(probes.write_then_delay, output_dir=True),
        kwargs={"session_id": session_id, "output_dir": str(output_dir), "delay_s": 0.5},
        session_id=session_id,
        timeout_s=0.1,
        workspace=tmp_path,
    )

    assert outcome.status == "timeout"
    assert not output_dir.exists()
    assert not list(tmp_path.glob(".zaptrace-job-*"))


@pytest.mark.asyncio
@requires_posix_execution
async def test_worker_error_rolls_back_state_and_artifacts(tmp_path: Path) -> None:
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "artifact-error-session"
    output_dir = tmp_path / "published"
    _tool_impls._sessions[session_id] = {"designs": {}, "stable": True}

    outcome = await execute_mutating_tool(
        tool_name="write_then_fail",
        tool_def=_tool_def(probes.write_then_fail, output_dir=True),
        kwargs={"session_id": session_id, "output_dir": str(output_dir)},
        session_id=session_id,
        timeout_s=5.0,
        workspace=tmp_path,
    )

    assert outcome.status == "error"
    assert "probe failure" in (outcome.error or "")
    assert _tool_impls._sessions[session_id] == {"designs": {}, "stable": True}
    assert not output_dir.exists()
    assert not list(tmp_path.glob(".zaptrace-job-*"))


@pytest.mark.asyncio
@requires_posix_execution
async def test_success_atomically_publishes_artifacts_and_commits_state(tmp_path: Path) -> None:
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "artifact-success-session"
    output_dir = tmp_path / "published"
    output_dir.mkdir()
    (output_dir / "old.txt").write_text("old", encoding="utf-8")
    _tool_impls._sessions[session_id] = {"designs": {}, "stable": True}

    outcome = await execute_mutating_tool(
        tool_name="write_success",
        tool_def=_tool_def(probes.write_success, output_dir=True),
        kwargs={"session_id": session_id, "output_dir": str(output_dir), "content": "complete"},
        session_id=session_id,
        timeout_s=5.0,
        workspace=tmp_path,
    )

    assert outcome.status == "completed"
    assert outcome.result == {
        "output_dir": str(output_dir),
        "path": str(output_dir / "result.txt"),
    }
    assert (output_dir / "result.txt").read_text(encoding="utf-8") == "complete"
    assert not (output_dir / "old.txt").exists()
    assert _tool_impls._sessions[session_id]["published_content"] == "complete"
    assert not list(tmp_path.glob(".zaptrace-job-*"))


@pytest.mark.asyncio
@requires_posix_execution
async def test_caller_cancellation_terminates_worker_and_discards_state(tmp_path: Path) -> None:
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "cancelled-session"
    marker_path = tmp_path / "cancelled-descendant.txt"
    _tool_impls._sessions[session_id] = {"designs": {}, "stable": True}

    task = asyncio.create_task(
        execute_mutating_tool(
            tool_name="spawn_descendant_then_delay",
            tool_def=_tool_def(probes.spawn_descendant_then_delay),
            kwargs={"session_id": session_id, "marker_path": str(marker_path), "delay_s": 0.5},
            session_id=session_id,
            timeout_s=5.0,
            workspace=tmp_path,
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.7)
    assert _tool_impls._sessions[session_id] == {"designs": {}, "stable": True}
    assert not marker_path.exists()
    assert not list(tmp_path.glob(".zaptrace-job-*"))


@pytest.mark.asyncio
@requires_posix_execution
async def test_publish_failure_restores_existing_target_and_discards_state(tmp_path: Path, monkeypatch) -> None:
    """A failed atomic publish must restore the pre-existing target."""
    import zaptrace.agent.execution as execution

    session_id = "publish-failure-session"
    output_dir = tmp_path / "published"
    output_dir.mkdir()
    (output_dir / "old.txt").write_text("old", encoding="utf-8")
    _tool_impls._sessions[session_id] = {"designs": {}, "stable": True}
    real_replace = execution.os.replace
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated publish failure")
        return real_replace(source, target)

    monkeypatch.setattr(execution.os, "replace", fail_second_replace)

    outcome = await execution.execute_mutating_tool(
        tool_name="write_success",
        tool_def=_tool_def(probes.write_success, output_dir=True),
        kwargs={"session_id": session_id, "output_dir": str(output_dir), "content": "new"},
        session_id=session_id,
        timeout_s=5.0,
        workspace=tmp_path,
    )

    assert outcome.status == "error"
    assert "simulated publish failure" in (outcome.error or "")
    assert (output_dir / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (output_dir / "result.txt").exists()
    assert _tool_impls._sessions[session_id] == {"designs": {}, "stable": True}
    assert not list(tmp_path.glob(".zaptrace-job-*"))


@pytest.mark.asyncio
@requires_posix_execution
async def test_timeout_emits_confirmed_termination_and_rollback_lifecycle(tmp_path: Path) -> None:
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "timeout-lifecycle-session"
    _tool_impls._sessions[session_id] = {"designs": {}, "markers": []}
    events: list[tuple[str, dict[str, Any]]] = []

    outcome = await execute_mutating_tool(
        tool_name="mutate_after_delay",
        tool_def=_tool_def(probes.mutate_after_delay),
        kwargs={"session_id": session_id, "marker": "late", "delay_s": 0.5},
        session_id=session_id,
        timeout_s=0.1,
        workspace=tmp_path,
        event_sink=lambda decision, metadata: events.append((decision, metadata)),
    )

    assert outcome.status == "timeout"
    assert [decision for decision, _ in events] == ["start", "timeout", "worker_terminated", "rollback"]
    assert all(metadata["job_id"] == outcome.job_id for _, metadata in events)
    assert events[2][1]["worker_terminated"] is True


@pytest.mark.asyncio
@requires_posix_execution
async def test_caller_cancellation_emits_termination_and_rollback_lifecycle(tmp_path: Path) -> None:
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "cancel-lifecycle-session"
    _tool_impls._sessions[session_id] = {"designs": {}, "stable": True}
    events: list[tuple[str, dict[str, Any]]] = []
    task = asyncio.create_task(
        execute_mutating_tool(
            tool_name="mutate_after_delay",
            tool_def=_tool_def(probes.mutate_after_delay),
            kwargs={"session_id": session_id, "marker": "late", "delay_s": 0.5},
            session_id=session_id,
            timeout_s=5.0,
            workspace=tmp_path,
            event_sink=lambda decision, metadata: events.append((decision, metadata)),
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert [decision for decision, _ in events] == ["start", "cancel_requested", "worker_terminated", "rollback"]
    assert events[2][1]["worker_terminated"] is True


@pytest.mark.asyncio
@requires_posix_execution
async def test_success_emits_start_and_commit_lifecycle(tmp_path: Path) -> None:
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "success-lifecycle-session"
    _tool_impls._sessions[session_id] = {"designs": {}, "markers": []}
    events: list[tuple[str, dict[str, Any]]] = []

    outcome = await execute_mutating_tool(
        tool_name="append_with_delay",
        tool_def=_tool_def(probes.append_with_delay),
        kwargs={"session_id": session_id, "marker": "done", "delay_s": 0.01},
        session_id=session_id,
        timeout_s=5.0,
        workspace=tmp_path,
        event_sink=lambda decision, metadata: events.append((decision, metadata)),
    )

    assert outcome.status == "completed"
    assert [decision for decision, _ in events] == ["start", "commit"]
    assert events[-1][1]["duration_ms"] >= 0


def test_parent_commit_failure_restores_previous_session_state() -> None:
    """A parent-side persistence failure must not leave partial committed state."""
    from zaptrace.agent.execution import _commit_session_state

    class FailingPersistentMapping(dict[str, Any]):
        def persist(self, _key: str) -> None:
            return

        def __setitem__(self, key: str, value: Any) -> None:
            if key == "bad":
                raise RuntimeError("simulated persistence failure")
            super().__setitem__(key, value)

    session_id = "commit-rollback-session"
    designs = FailingPersistentMapping({"existing": "old"})
    _tool_impls._sessions[session_id] = {"designs": designs, "stable": True}

    with pytest.raises(RuntimeError, match="simulated persistence failure"):
        _commit_session_state(
            session_id,
            {
                "designs": {"first": "new", "bad": "boom"},
                "stable": False,
            },
        )

    assert _tool_impls._sessions[session_id]["stable"] is True
    assert _tool_impls._sessions[session_id]["designs"] == {"existing": "old"}


def test_all_mutating_registry_tools_are_importable_top_level_callables() -> None:
    """The isolated worker requires stable module and qualname identities."""
    import importlib

    from zaptrace.agent._tool_impls import TOOL_REGISTRY

    failures: list[str] = []
    for tool_name, tool_def in sorted(TOOL_REGISTRY.items()):
        if tool_def["capability"] == "read":
            continue
        fn = tool_def["fn"]
        module_name = getattr(fn, "__module__", "")
        qualname = getattr(fn, "__qualname__", "")
        if not module_name or not qualname or "<locals>" in qualname:
            failures.append(f"{tool_name}: not a top-level callable")
            continue
        resolved = importlib.import_module(module_name)
        for part in qualname.split("."):
            resolved = getattr(resolved, part)
        if resolved is not fn:
            failures.append(f"{tool_name}: {module_name}.{qualname} resolves to a different object")

    assert failures == []


@pytest.mark.asyncio
@requires_posix_execution
async def test_cancellation_immediately_after_subprocess_start_terminates_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parent owns a process handle before cancellation can be delivered."""
    import zaptrace.agent.execution as execution

    session_id = "spawn-cancel-session"
    marker_path = tmp_path / "late-descendant.txt"
    _tool_impls._sessions[session_id] = {"designs": {}, "stable": True}
    real_popen = execution.subprocess.Popen
    spawned = asyncio.Event()
    processes: list[Any] = []

    def tracking_popen(*args: Any, **kwargs: Any):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        spawned.set()
        return process

    monkeypatch.setattr(execution.subprocess, "Popen", tracking_popen)
    task = asyncio.create_task(
        execution.execute_mutating_tool(
            tool_name="spawn_descendant_then_delay",
            tool_def=_tool_def(probes.spawn_descendant_then_delay),
            kwargs={
                "session_id": session_id,
                "marker_path": str(marker_path),
                "delay_s": 0.4,
            },
            session_id=session_id,
            timeout_s=5.0,
            workspace=tmp_path,
        )
    )

    await spawned.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(processes) == 1
    assert processes[0].poll() is not None
    await asyncio.sleep(0.7)
    assert not marker_path.exists()
    assert _tool_impls._sessions[session_id] == {"designs": {}, "stable": True}
    assert not list(tmp_path.glob(".zaptrace-job-*"))


@pytest.mark.asyncio
@requires_posix_execution
async def test_recovery_journal_maps_staged_outputs_to_final_targets(tmp_path: Path) -> None:
    """Abandoned job directories retain enough metadata for manual recovery."""
    import json

    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "recovery-journal-session"
    output_dir = tmp_path / "published"
    _tool_impls._sessions[session_id] = {"designs": {}}
    task = asyncio.create_task(
        execute_mutating_tool(
            tool_name="write_then_delay",
            tool_def=_tool_def(probes.write_then_delay, output_dir=True),
            kwargs={"session_id": session_id, "output_dir": str(output_dir), "delay_s": 0.4},
            session_id=session_id,
            timeout_s=5.0,
            workspace=tmp_path,
        )
    )

    journal_path: Path | None = None
    for _ in range(100):
        matches = list(tmp_path.glob(".zaptrace-job-*/recovery.json"))
        if matches:
            journal_path = matches[0]
            break
        await asyncio.sleep(0.01)

    assert journal_path is not None
    payload = json.loads(journal_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["phase"] == "worker_running"
    assert payload["session_id"] == session_id
    assert payload["tool_name"] == "write_then_delay"
    assert payload["outputs"][0]["parameter"] == "output_dir"
    assert payload["outputs"][0]["target_path"] == str(output_dir)
    assert payload["outputs"][0]["staged_path"].startswith("outputs/")
    assert payload["outputs"][0]["backup_path"].startswith("backups/")

    outcome = await task
    assert outcome.status == "completed"
    assert not list(tmp_path.glob(".zaptrace-job-*"))


@pytest.mark.asyncio
@requires_posix_execution
async def test_commit_audit_failure_rolls_back_state_and_published_artifacts(tmp_path: Path) -> None:
    """A failed terminal audit write cannot leave state or artifacts committed."""
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "commit-audit-failure-session"
    output_dir = tmp_path / "published"
    output_dir.mkdir()
    (output_dir / "old.txt").write_text("old", encoding="utf-8")
    _tool_impls._sessions[session_id] = {"designs": {}, "stable": True}
    events: list[str] = []

    def failing_sink(decision: str, _metadata: dict[str, Any]) -> None:
        events.append(decision)
        if decision == "commit":
            raise RuntimeError("audit commit failure")

    outcome = await execute_mutating_tool(
        tool_name="write_success",
        tool_def=_tool_def(probes.write_success, output_dir=True),
        kwargs={"session_id": session_id, "output_dir": str(output_dir), "content": "new"},
        session_id=session_id,
        timeout_s=5.0,
        workspace=tmp_path,
        event_sink=failing_sink,
    )

    assert outcome.status == "error"
    assert "audit commit failure" in (outcome.error or "")
    assert _tool_impls._sessions[session_id] == {"designs": {}, "stable": True}
    assert (output_dir / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (output_dir / "result.txt").exists()
    assert events == ["start", "commit", "rollback"]


@pytest.mark.asyncio
@requires_posix_execution
async def test_cross_session_writes_to_same_target_are_serialized(tmp_path: Path) -> None:
    """Different sessions cannot race while publishing the same output path."""
    from zaptrace.agent.execution import execute_mutating_tool

    output_dir = tmp_path / "shared-output"
    first_session = "output-lock-first"
    second_session = "output-lock-second"
    _tool_impls._sessions[first_session] = {"designs": {}}
    _tool_impls._sessions[second_session] = {"designs": {}}
    tool_def = _tool_def(probes.write_content_after_delay, output_dir=True)

    first = asyncio.create_task(
        execute_mutating_tool(
            tool_name="write_content_after_delay",
            tool_def=tool_def,
            kwargs={
                "session_id": first_session,
                "output_dir": str(output_dir),
                "content": "first",
                "delay_s": 0.25,
            },
            session_id=first_session,
            timeout_s=5.0,
            workspace=tmp_path,
        )
    )
    await asyncio.sleep(0.03)
    second = asyncio.create_task(
        execute_mutating_tool(
            tool_name="write_content_after_delay",
            tool_def=tool_def,
            kwargs={
                "session_id": second_session,
                "output_dir": str(output_dir),
                "content": "second",
                "delay_s": 0.01,
            },
            session_id=second_session,
            timeout_s=5.0,
            workspace=tmp_path,
        )
    )

    first_outcome, second_outcome = await asyncio.gather(first, second)

    assert first_outcome.status == "completed"
    assert second_outcome.status == "completed"
    assert (output_dir / "result.txt").read_text(encoding="utf-8") == "second"
    assert _tool_impls._sessions[first_session]["published_content"] == "first"
    assert _tool_impls._sessions[second_session]["published_content"] == "second"


@pytest.mark.asyncio
@requires_posix_execution
async def test_coordinator_failure_after_spawn_terminates_worker_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parent-side failure after spawn cannot abandon a live worker."""
    import zaptrace.agent.execution as execution

    session_id = "coordinator-failure-session"
    marker_path = tmp_path / "late-descendant.txt"
    _tool_impls._sessions[session_id] = {"designs": {}, "stable": True}
    real_journal = execution._write_recovery_journal
    processes: list[Any] = []
    real_popen = execution.subprocess.Popen

    def tracking_popen(*args: Any, **kwargs: Any):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    def fail_worker_journal(**kwargs: Any) -> None:
        if kwargs["phase"] == "worker_running":
            raise OSError("simulated journal failure")
        real_journal(**kwargs)

    monkeypatch.setattr(execution.subprocess, "Popen", tracking_popen)
    monkeypatch.setattr(execution, "_write_recovery_journal", fail_worker_journal)

    outcome = await execution.execute_mutating_tool(
        tool_name="spawn_descendant_then_delay",
        tool_def=_tool_def(probes.spawn_descendant_then_delay),
        kwargs={
            "session_id": session_id,
            "marker_path": str(marker_path),
            "delay_s": 0.3,
        },
        session_id=session_id,
        timeout_s=5.0,
        workspace=tmp_path,
    )

    assert outcome.status == "error"
    assert "simulated journal failure" in (outcome.error or "")
    assert len(processes) == 1
    assert processes[0].poll() is not None
    await asyncio.sleep(0.6)
    assert not marker_path.exists()
    assert _tool_impls._sessions[session_id] == {"designs": {}, "stable": True}
    assert not list(tmp_path.glob(".zaptrace-job-*"))


@pytest.mark.asyncio
@requires_posix_execution
async def test_timeout_terminates_descendants_after_worker_parent_exits(tmp_path: Path) -> None:
    """The process group is terminated even when the worker leader exited first."""
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "exited-parent-descendant-session"
    marker_path = tmp_path / "late-child.txt"
    _tool_impls._sessions[session_id] = {"designs": {}}

    outcome = await execute_mutating_tool(
        tool_name="spawn_descendant_and_return",
        tool_def=_tool_def(probes.spawn_descendant_and_return),
        kwargs={
            "session_id": session_id,
            "marker_path": str(marker_path),
            "delay_s": 3.0,
        },
        session_id=session_id,
        timeout_s=1.5,
        workspace=tmp_path,
    )

    assert outcome.status == "timeout"
    assert outcome.worker_terminated is True
    await asyncio.sleep(3.5)
    assert not marker_path.exists()


@pytest.mark.asyncio
@requires_posix_execution
async def test_success_terminates_background_descendants_before_commit(tmp_path: Path) -> None:
    """A successful tool cannot leave same-group background children running."""
    from zaptrace.agent.execution import execute_mutating_tool

    session_id = "success-background-child-session"
    marker_path = tmp_path / "late-background-child.txt"
    _tool_impls._sessions[session_id] = {"designs": {}}

    outcome = await execute_mutating_tool(
        tool_name="spawn_background_descendant",
        tool_def=_tool_def(probes.spawn_background_descendant),
        kwargs={
            "session_id": session_id,
            "marker_path": str(marker_path),
            "delay_s": 1.0,
        },
        session_id=session_id,
        timeout_s=5.0,
        workspace=tmp_path,
    )

    assert outcome.status == "completed"
    assert outcome.worker_terminated is True
    assert _tool_impls._sessions[session_id]["background_child_pid"] == outcome.result["child_pid"]
    await asyncio.sleep(1.2)
    assert not marker_path.exists()


def test_get_session_rejects_destroyed_session() -> None:
    """Direct session access cannot resurrect an execution-destroyed session."""
    from zaptrace.agent.execution import SessionDestroyedError, mark_session_destroyed

    session_id = "direct-destroyed-session"
    mark_session_destroyed(session_id)

    with pytest.raises(SessionDestroyedError, match="has been destroyed"):
        _tool_impls._get_session(session_id)

    assert session_id not in _tool_impls._sessions


@pytest.mark.asyncio
@requires_posix_execution
async def test_failed_worker_cannot_change_persistent_design_heads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zaptrace.agent.execution import execute_mutating_tool
    from zaptrace.core.models import Design, DesignMeta
    from zaptrace.core.state_store import SQLiteStateStore

    workspace = tmp_path / "workspace"
    store_root = tmp_path / "state"
    workspace.mkdir()
    monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(store_root))
    session_id = "persistent-worker-error"
    _tool_impls._sessions.clear()
    session = _tool_impls._get_session(session_id)
    initial = Design(meta=DesignMeta(name="stable"))
    initial.board.width_mm = 42
    session["designs"]["stable"] = initial
    before = SQLiteStateStore(store_root).current_design_identity(session_id, "stable")

    outcome = await execute_mutating_tool(
        tool_name="persist_design_then_fail",
        tool_def=_tool_def(probes.persist_design_then_fail),
        kwargs={"session_id": session_id},
        session_id=session_id,
        timeout_s=5.0,
        workspace=workspace,
    )

    reopened = SQLiteStateStore(store_root)
    assert outcome.status == "error"
    assert reopened.current_design_identity(session_id, "stable") == before
    assert "worker-candidate" not in reopened.load_designs(session_id)
    assert "worker-candidate" not in _tool_impls._get_session(session_id)["designs"]


def test_worker_environment_disables_durable_writes(tmp_path: Path) -> None:
    from zaptrace.agent.execution import _worker_environment

    _, child_env = _worker_environment(tmp_path)

    assert child_env["ZAPTRACE_PERSISTENCE_DISABLED"] == "1"
