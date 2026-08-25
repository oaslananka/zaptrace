"""Trusted local subprocess entrypoint for isolated agent tool execution."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import pickle  # noqa: S403 - trusted local IPC owned by the parent process
import stat
import sys
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REQUEST_FILENAME = "request.pickle"
_RESPONSE_FILENAME = "response.pickle"
_JOB_PREFIX = ".zaptrace-job-"
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600


def _isolated_worker_supported() -> bool:
    """Return whether the secure worker IPC implementation is available."""
    return os.name == "posix"


@dataclass(frozen=True, slots=True)
class _ValidatedIPCPaths:
    """Parent-created IPC paths after containment and ownership validation."""

    workspace: Path
    job_dir: Path
    request_path: Path
    response_path: Path


def _require_private_owner(path: Path, *, expected_mode: int, kind: str) -> os.stat_result:
    """Require a non-symlink object owned by this worker with private mode bits."""
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{kind} must be a regular non-symlink file or directory")
    if os.name == "posix":
        if metadata.st_uid != os.getuid():
            raise ValueError(f"{kind} must be owned by the current worker user")
        if stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise ValueError(f"{kind} must use mode {expected_mode:04o}")
    return metadata


def _lexical_ipc_paths(raw_request: str, raw_response: str) -> tuple[Path, Path]:
    """Return absolute lexical IPC paths after fixed-name validation."""
    request_path = Path(os.path.abspath(raw_request))
    response_path = Path(os.path.abspath(raw_response))
    if request_path.name != _REQUEST_FILENAME or response_path.name != _RESPONSE_FILENAME:
        raise ValueError("worker IPC filenames must be request.pickle and response.pickle")
    if request_path.parent != response_path.parent:
        raise ValueError("request and response must share the same private job directory")
    return request_path, response_path


def _validated_workspace(raw_workspace: str) -> Path:
    """Resolve the configured workspace and require a directory."""
    if not raw_workspace.strip():
        raise ValueError("ZAPTRACE_WORKSPACE is required for isolated worker IPC")
    candidate = Path(raw_workspace)
    metadata = candidate.stat()  # NOSONAR - containment root is validated before IPC access
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("workspace must be a directory")
    return candidate.resolve(strict=True)


def _validated_job_directory(request_path: Path, response_path: Path, workspace: Path) -> Path:
    """Resolve the private job directory and prove workspace containment."""
    metadata = _require_private_owner(
        request_path.parent,
        expected_mode=_PRIVATE_DIRECTORY_MODE,
        kind="job directory",
    )
    if not stat.S_ISDIR(metadata.st_mode) or not request_path.parent.name.startswith(_JOB_PREFIX):
        raise ValueError("job directory must be a private .zaptrace-job-* directory")
    job_dir = request_path.parent.resolve(strict=True)
    if response_path.parent.resolve(strict=True) != job_dir:
        raise ValueError("request and response must share the same private job directory")
    try:
        job_dir.relative_to(workspace)
    except ValueError:
        raise ValueError("request and response must share the same private job directory inside workspace") from None
    return job_dir


def _validated_request_path(request_path: Path, job_dir: Path) -> Path:
    """Require the fixed request file to be private, regular, and contained."""
    metadata = _require_private_owner(
        request_path,
        expected_mode=_PRIVATE_FILE_MODE,
        kind="request",
    )
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("request must be a regular non-symlink file")
    resolved = request_path.resolve(strict=True)
    if resolved != job_dir / _REQUEST_FILENAME:
        raise ValueError("request must be the private request.pickle file inside the job directory")
    return resolved


def _validated_response_path(response_path: Path, job_dir: Path) -> Path:
    """Require a not-yet-created fixed response path inside the job directory."""
    if response_path.exists() or response_path.is_symlink():
        raise ValueError("response path must not already exist")
    temporary_response = response_path.with_suffix(response_path.suffix + ".tmp")
    if temporary_response.exists() or temporary_response.is_symlink():
        raise ValueError("temporary response path must not already exist")
    resolved = response_path.resolve(strict=False)
    if resolved != job_dir / _RESPONSE_FILENAME:
        raise ValueError("response must be the private response.pickle file inside the job directory")
    return resolved


def _validate_ipc_paths(*, raw_request: str, raw_response: str, raw_workspace: str) -> _ValidatedIPCPaths:
    """Validate that CLI paths are the exact private files created by the parent."""
    request_lexical, response_lexical = _lexical_ipc_paths(raw_request, raw_response)
    workspace = _validated_workspace(raw_workspace)
    job_dir = _validated_job_directory(request_lexical, response_lexical, workspace)
    request_path = _validated_request_path(request_lexical, job_dir)
    response_path = _validated_response_path(response_lexical, job_dir)
    return _ValidatedIPCPaths(
        workspace=workspace,
        job_dir=job_dir,
        request_path=request_path,
        response_path=response_path,
    )


def _resolve_callable(module_name: str, qualname: str) -> Callable[..., Any]:
    """Resolve a top-level callable identified by module and qualified name."""
    if "<locals>" in qualname:
        raise ValueError("isolated tool functions must be importable top-level callables")
    target: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        target = getattr(target, part)
    if not callable(target):
        raise TypeError(f"resolved tool target is not callable: {module_name}.{qualname}")
    return target


async def _await_result(awaitable: Awaitable[Any]) -> Any:
    """Await a dynamically returned awaitable for ``asyncio.run``."""
    return await awaitable


def _open_validated_job_directory(paths: _ValidatedIPCPaths) -> int:
    """Open the validated private job directory without following symlinks."""
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(paths.job_dir, flags)  # NOSONAR - job_dir passed strict containment/owner checks
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise ValueError("validated job directory changed before worker access")
    if os.name == "posix" and (
        metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != _PRIVATE_DIRECTORY_MODE
    ):
        os.close(descriptor)
        raise ValueError("validated job directory ownership or permissions changed")
    return descriptor


def _read_request(paths: _ValidatedIPCPaths) -> dict[str, Any]:
    """Read the request by fixed basename from the validated job directory."""
    directory_fd = _open_validated_job_directory(paths)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        request_fd = os.open(_REQUEST_FILENAME, flags, dir_fd=directory_fd)
        metadata = os.fstat(request_fd)
        if not stat.S_ISREG(metadata.st_mode):
            os.close(request_fd)
            raise ValueError("request changed to a non-regular file")
        if os.name == "posix" and (
            metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
        ):
            os.close(request_fd)
            raise ValueError("request ownership or permissions changed")
        with os.fdopen(request_fd, "rb") as handle:
            payload = pickle.load(handle)  # nosec: B301
    finally:
        os.close(directory_fd)
    if not isinstance(payload, dict):
        raise TypeError("isolated worker request must be an object")
    return payload


def _write_response(paths: _ValidatedIPCPaths, payload: dict[str, Any]) -> None:
    """Write the response atomically by fixed basename in the validated job directory."""
    directory_fd = _open_validated_job_directory(paths)
    temporary_name = f"{_RESPONSE_FILENAME}.tmp"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        response_fd = os.open(temporary_name, flags, _PRIVATE_FILE_MODE, dir_fd=directory_fd)
        with os.fdopen(response_fd, "wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary_name,
            _RESPONSE_FILENAME,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
    finally:
        os.close(directory_fd)


def _execute_request(paths: _ValidatedIPCPaths) -> dict[str, Any]:
    """Read and execute one trusted request from the validated IPC directory."""
    request = _read_request(paths)
    session_id = str(request["session_id"])
    module_name = str(request["module_name"])
    qualname = str(request["qualname"])
    kwargs = dict(request["kwargs"])
    session_state = dict(request["session_state"])

    from zaptrace.agent import _tool_impls

    _tool_impls._sessions[session_id] = session_state
    fn = _resolve_callable(module_name, qualname)
    result = fn(**kwargs)
    if inspect.isawaitable(result):
        result = asyncio.run(_await_result(result))
    return {
        "status": "completed",
        "result": result,
        "session_state": _tool_impls._sessions[session_id],
    }


def run_worker(paths: _ValidatedIPCPaths) -> int:
    """Run one validated isolated tool request and persist its terminal result."""
    try:
        payload = _execute_request(paths)
    except Exception as exc:  # NOSONAR - protocol must serialize arbitrary registered-tool failures
        payload = {
            "status": "error",
            "error": str(exc),
            "exception_type": type(exc).__name__,
            "traceback": traceback.format_exc(limit=20),
        }
        exit_code = 1
    else:
        exit_code = 0

    try:
        _write_response(paths, payload)
    except (OSError, pickle.PickleError, TypeError, AttributeError):
        traceback.print_exc()
        return 1
    return exit_code


def main() -> int:
    """CLI entrypoint used exclusively by the parent execution coordinator."""
    if len(sys.argv) != 3:
        print("usage: python -m zaptrace.agent.worker REQUEST RESPONSE", file=sys.stderr)
        return 2
    if not _isolated_worker_supported():
        print("isolated agent worker requires a POSIX platform", file=sys.stderr)
        return 2
    try:
        paths = _validate_ipc_paths(
            raw_request=sys.argv[1],
            raw_response=sys.argv[2],
            raw_workspace=os.environ.get("ZAPTRACE_WORKSPACE", ""),
        )
    except (OSError, ValueError) as exc:
        print(f"invalid isolated worker IPC paths: {exc}", file=sys.stderr)
        return 2
    return run_worker(paths)


if __name__ == "__main__":
    raise SystemExit(main())
