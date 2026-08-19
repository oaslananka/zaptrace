"""Security and protocol tests for the isolated agent worker IPC boundary."""

from __future__ import annotations

import asyncio
import os
import pickle
import stat
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from zaptrace.agent import _tool_impls, worker

requires_posix_worker = pytest.mark.skipif(
    os.name != "posix", reason="secure isolated worker IPC requires POSIX dir_fd semantics"
)


@pytest.fixture(autouse=True)
def _reset_sessions() -> Iterator[None]:
    _tool_impls._sessions.clear()
    yield
    _tool_impls._sessions.clear()


def _ipc_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    job_dir = workspace / ".zaptrace-job-test"
    job_dir.mkdir(mode=0o700)
    request_path = job_dir / "request.pickle"
    request_path.write_bytes(b"request")
    request_path.chmod(0o600)
    response_path = job_dir / "response.pickle"
    return workspace, request_path, response_path


def _request_payload(
    *,
    session_id: str = "worker-session",
    module_name: str = "tests.execution_probe_tools",
    qualname: str = "release_probe",
    kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "job_id": "job-test",
        "tool_name": qualname,
        "module_name": module_name,
        "qualname": qualname,
        "kwargs": kwargs or {"session_id": session_id},
        "session_id": session_id,
        "session_state": {"designs": {}, "stable": True},
    }


def _validated_paths(tmp_path: Path, payload: Any | None = None) -> worker._ValidatedIPCPaths:
    workspace, request_path, response_path = _ipc_paths(tmp_path)
    request_path.write_bytes(pickle.dumps(_request_payload() if payload is None else payload))
    request_path.chmod(0o600)
    return worker._validate_ipc_paths(
        raw_request=str(request_path),
        raw_response=str(response_path),
        raw_workspace=str(workspace),
    )


def _validate(
    request_path: Path,
    response_path: Path,
    workspace: Path,
) -> worker._ValidatedIPCPaths:
    return worker._validate_ipc_paths(
        raw_request=str(request_path),
        raw_response=str(response_path),
        raw_workspace=str(workspace),
    )


def test_validate_ipc_paths_accepts_parent_owned_private_job_directory(tmp_path: Path) -> None:
    workspace, request_path, response_path = _ipc_paths(tmp_path)

    validated = _validate(request_path, response_path, workspace)

    assert validated.workspace == workspace.resolve()
    assert validated.job_dir == request_path.parent.resolve()
    assert validated.request_path == request_path.resolve()
    assert validated.response_path == response_path.resolve(strict=False)


def test_validate_ipc_paths_rejects_request_outside_workspace(tmp_path: Path) -> None:
    workspace, _request_path, response_path = _ipc_paths(tmp_path)
    outside = tmp_path / "request.pickle"
    outside.write_bytes(b"request")
    outside.chmod(0o600)

    with pytest.raises(ValueError, match="same private job directory"):
        _validate(outside, response_path, workspace)


def test_validate_ipc_paths_rejects_symlink_request(tmp_path: Path) -> None:
    workspace, request_path, response_path = _ipc_paths(tmp_path)
    target = request_path.parent / "request-target.pickle"
    request_path.rename(target)
    request_path.symlink_to(target)

    with pytest.raises(ValueError, match="regular non-symlink file"):
        _validate(request_path, response_path, workspace)


def test_validate_ipc_paths_rejects_unexpected_filenames(tmp_path: Path) -> None:
    workspace, request_path, response_path = _ipc_paths(tmp_path)
    wrong_request = request_path.with_name("other.pickle")
    request_path.rename(wrong_request)

    with pytest.raises(ValueError, match="request.pickle and response.pickle"):
        _validate(wrong_request, response_path, workspace)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are required")
def test_validate_ipc_paths_rejects_group_or_world_accessible_job_directory(tmp_path: Path) -> None:
    workspace, request_path, response_path = _ipc_paths(tmp_path)
    request_path.parent.chmod(0o755)

    with pytest.raises(ValueError, match="mode 0700"):
        _validate(request_path, response_path, workspace)


def test_validate_ipc_paths_requires_workspace(tmp_path: Path) -> None:
    _workspace, request_path, response_path = _ipc_paths(tmp_path)

    with pytest.raises(ValueError, match="ZAPTRACE_WORKSPACE is required"):
        _validate(request_path, response_path, Path(" "))


def test_validate_ipc_paths_rejects_workspace_file(tmp_path: Path) -> None:
    _workspace, request_path, response_path = _ipc_paths(tmp_path)
    workspace_file = tmp_path / "workspace-file"
    workspace_file.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValueError, match="workspace must be a directory"):
        _validate(request_path, response_path, workspace_file)


def test_validate_ipc_paths_rejects_unexpected_job_directory_name(tmp_path: Path) -> None:
    workspace, request_path, response_path = _ipc_paths(tmp_path)
    invalid_job = workspace / "job-test"
    request_path.parent.rename(invalid_job)

    with pytest.raises(ValueError, match="private .zaptrace-job"):
        _validate(invalid_job / request_path.name, invalid_job / response_path.name, workspace)


def test_validate_ipc_paths_rejects_existing_response(tmp_path: Path) -> None:
    workspace, request_path, response_path = _ipc_paths(tmp_path)
    response_path.write_bytes(b"existing")

    with pytest.raises(ValueError, match="response path must not already exist"):
        _validate(request_path, response_path, workspace)


def test_validate_ipc_paths_rejects_existing_temporary_response(tmp_path: Path) -> None:
    workspace, request_path, response_path = _ipc_paths(tmp_path)
    response_path.with_suffix(".pickle.tmp").write_bytes(b"existing")

    with pytest.raises(ValueError, match="temporary response path must not already exist"):
        _validate(request_path, response_path, workspace)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are required")
def test_validate_ipc_paths_rejects_non_private_request_mode(tmp_path: Path) -> None:
    workspace, request_path, response_path = _ipc_paths(tmp_path)
    request_path.chmod(0o644)

    with pytest.raises(ValueError, match="mode 0600"):
        _validate(request_path, response_path, workspace)


def test_resolve_callable_accepts_importable_function() -> None:
    resolved = worker._resolve_callable("tests.execution_probe_tools", "release_probe")

    assert resolved.__name__ == "release_probe"


def test_resolve_callable_rejects_local_and_non_callable_targets() -> None:
    with pytest.raises(ValueError, match="top-level callables"):
        worker._resolve_callable("tests.execution_probe_tools", "function.<locals>.probe")

    with pytest.raises(TypeError, match="not callable"):
        worker._resolve_callable("tests.execution_probe_tools", "_RESULT_FILENAME")


def test_await_result_returns_async_value() -> None:
    async def value() -> str:
        return "done"

    assert asyncio.run(worker._await_result(value())) == "done"


@requires_posix_worker
def test_read_request_returns_validated_mapping(tmp_path: Path) -> None:
    payload = _request_payload()
    paths = _validated_paths(tmp_path, payload)

    assert worker._read_request(paths) == payload


@requires_posix_worker
def test_read_request_rejects_non_mapping_payload(tmp_path: Path) -> None:
    paths = _validated_paths(tmp_path, ["not", "a", "mapping"])

    with pytest.raises(TypeError, match="request must be an object"):
        worker._read_request(paths)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are required")
def test_read_request_rechecks_permissions_after_validation(tmp_path: Path) -> None:
    paths = _validated_paths(tmp_path)
    paths.request_path.chmod(0o644)

    with pytest.raises(ValueError, match="request ownership or permissions changed"):
        worker._read_request(paths)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are required")
def test_open_job_directory_rechecks_permissions_after_validation(tmp_path: Path) -> None:
    paths = _validated_paths(tmp_path)
    paths.job_dir.chmod(0o755)

    with pytest.raises(ValueError, match="ownership or permissions changed"):
        worker._open_validated_job_directory(paths)


@requires_posix_worker
def test_write_response_is_atomic_and_private(tmp_path: Path) -> None:
    paths = _validated_paths(tmp_path)
    payload = {"status": "completed", "result": {"ok": True}}

    worker._write_response(paths, payload)

    with paths.response_path.open("rb") as handle:
        assert pickle.load(handle) == payload
    assert not paths.response_path.with_suffix(".pickle.tmp").exists()
    if os.name == "posix":
        assert stat.S_IMODE(paths.response_path.stat().st_mode) == 0o600


@requires_posix_worker
def test_execute_request_runs_registered_sync_callable(tmp_path: Path) -> None:
    paths = _validated_paths(tmp_path)

    response = worker._execute_request(paths)

    assert response["status"] == "completed"
    assert response["result"] == {"session_id": "worker-session", "status": "authorized"}
    assert response["session_state"] == {"designs": {}, "stable": True}


@requires_posix_worker
def test_run_worker_writes_success_response(tmp_path: Path) -> None:
    paths = _validated_paths(tmp_path)

    assert worker.run_worker(paths) == 0
    with paths.response_path.open("rb") as handle:
        response = pickle.load(handle)
    assert response["status"] == "completed"
    assert response["result"]["status"] == "authorized"


@requires_posix_worker
def test_run_worker_serializes_tool_failure(tmp_path: Path) -> None:
    payload = _request_payload(qualname="missing_probe")
    paths = _validated_paths(tmp_path, payload)

    assert worker.run_worker(paths) == 1
    with paths.response_path.open("rb") as handle:
        response = pickle.load(handle)
    assert response["status"] == "error"
    assert response["exception_type"] == "AttributeError"
    assert "missing_probe" in response["error"]
    assert "Traceback" in response["traceback"]


@requires_posix_worker
def test_run_worker_returns_error_when_response_cannot_be_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _validated_paths(tmp_path)

    def fail_write(_paths: worker._ValidatedIPCPaths, _payload: dict[str, Any]) -> None:
        raise OSError("simulated response failure")

    monkeypatch.setattr(worker, "_write_response", fail_write)

    assert worker.run_worker(paths) == 1


def test_main_rejects_unsupported_platform(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(worker, "_isolated_worker_supported", lambda: False)
    monkeypatch.setattr(sys, "argv", ["worker", "request.pickle", "response.pickle"])

    assert worker.main() == 2
    assert capsys.readouterr().err.strip() == "isolated agent worker requires a POSIX platform"


def test_main_rejects_invalid_argument_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["worker"])

    assert worker.main() == 2


def test_main_rejects_invalid_ipc_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["worker", "request.pickle", "response.pickle"])
    monkeypatch.delenv("ZAPTRACE_WORKSPACE", raising=False)

    assert worker.main() == 2


def test_main_delegates_validated_paths_to_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _validated_paths(tmp_path)
    observed: list[worker._ValidatedIPCPaths] = []

    def fake_run_worker(validated: worker._ValidatedIPCPaths) -> int:
        observed.append(validated)
        return 7

    monkeypatch.setattr(sys, "argv", ["worker", str(paths.request_path), str(paths.response_path)])
    monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(paths.workspace))
    monkeypatch.setattr(worker, "_isolated_worker_supported", lambda: True)
    monkeypatch.setattr(worker, "run_worker", fake_run_worker)

    assert worker.main() == 7
    assert observed == [paths]
