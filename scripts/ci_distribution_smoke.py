#!/usr/bin/env python3
"""Clean-install and smoke-test one ZapTrace distribution artifact."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ci_distribution_support import (  # noqa: E402
    DistributionPolicyError,
    load_policy,
    select_target,
)

_MAX_LOG_CHARS = 4096
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DISTRIBUTION_NAME = "zaptrace-eda"
_NON_CLAIMS = [
    "This report covers only the named artifact, interpreter, runner, and bounded smoke checks.",
    "It does not establish universal platform support, formal verification, or production qualification.",
    "It does not establish fabrication readiness, manufacturer approval, or immunity from platform-specific defects.",
]


class DistributionSmokeError(RuntimeError):
    """Raised when clean-install distribution evidence cannot be trusted."""


def _validated_input_file(path: Path, *, allowed_root: Path, label: str) -> Path:
    root = allowed_root.resolve(strict=True)
    candidate = path if path.is_absolute() else root / path
    lexical = Path(os.path.abspath(candidate))
    for segment in (lexical, *lexical.parents):
        if segment.is_symlink():
            raise DistributionSmokeError(f"{label} path must not contain a symbolic link: {segment}")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise DistributionSmokeError(f"Cannot resolve {label} {path}: {exc}") from exc
    if not resolved.is_relative_to(root):
        raise DistributionSmokeError(f"{label} is outside allowed root {root}: {resolved}")
    if not resolved.is_file():
        raise DistributionSmokeError(f"{label} is not a regular file: {resolved}")
    return resolved


def sha256_file(path: Path, *, allowed_root: Path, label: str = "input file") -> str:
    """Return the SHA-256 of one workspace-bounded regular file."""
    resolved = _validated_input_file(path, allowed_root=allowed_root, label=label)
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def verify_installed_path(installed_path: Path, source_root: Path) -> dict[str, Any]:
    """Reject source-tree imports while claiming installed-artifact evidence."""
    resolved_path = installed_path.resolve()
    resolved_source = source_root.resolve()
    if _is_within(resolved_path, resolved_source):
        raise DistributionSmokeError(f"Installed package resolved inside the source tree: {resolved_path}")
    return {
        "passed": True,
        "installed_path": resolved_path.as_posix(),
        "source_root": resolved_source.as_posix(),
        "source_tree_import": False,
    }


def verify_native_state(
    expected: str,
    *,
    native_path: Path | None,
    import_error: str | None,
) -> dict[str, Any]:
    """Enforce the support row's native-extension expectation."""
    if expected not in {"required", "optional", "absent"}:
        raise DistributionSmokeError(f"Unsupported native expectation: {expected}")
    present = native_path is not None
    if expected == "required" and not present:
        detail = import_error or "unknown error"
        raise DistributionSmokeError(f"The required native extension could not be imported: {detail}")
    if expected == "absent" and present:
        raise DistributionSmokeError(
            f"The source-only environment loaded an unexpected native extension: {native_path}"
        )
    return {
        "passed": True,
        "expected": expected,
        "present": present,
        "path": native_path.resolve().as_posix() if native_path is not None else "",
        "import_error": import_error or "",
    }


def resolve_console_script(name: str) -> Path:
    """Resolve a console entry point from the active clean environment."""
    scripts_dir = Path(sys.executable).absolute().parent
    candidates = [scripts_dir / name]
    if os.name == "nt":
        candidates.extend((scripts_dir / f"{name}.exe", scripts_dir / f"{name}.cmd"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    resolved = shutil.which(name)
    if not resolved:
        raise DistributionSmokeError(f"Installed console script is missing: {name}")
    return Path(resolved).resolve()


def _bounded(value: str) -> str:
    return value[-_MAX_LOG_CHARS:]


def _run_command(args: list[str], *, timeout_s: float) -> dict[str, Any]:
    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    result = {
        "passed": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": _bounded(completed.stdout),
        "stderr": _bounded(completed.stderr),
    }
    if completed.returncode != 0:
        raise DistributionSmokeError(
            f"Command failed ({completed.returncode}): {args[0]} {' '.join(args[1:])}\n"
            f"{result['stdout']}\n{result['stderr']}"
        )
    return result


def run_console_checks(expected_version: str, *, timeout_s: float = 15.0) -> dict[str, Any]:
    """Exercise installed CLI entry points without importing the source tree."""
    cli = resolve_console_script("zaptrace")
    version_result = _run_command([str(cli), "--version"], timeout_s=timeout_s)
    help_result = _run_command([str(cli), "--help"], timeout_s=timeout_s)
    version_output = f"{version_result['stdout']}\n{version_result['stderr']}"
    if expected_version not in version_output:
        raise DistributionSmokeError(
            f"zaptrace --version did not report installed version {expected_version}: {version_output.strip()}"
        )
    for name in ("zaptrace-mcp", "zaptrace-mcp-http", "zaptrace-api"):
        resolve_console_script(name)
    return {
        "passed": True,
        "cli_path": cli.as_posix(),
        "version": expected_version,
        "version_returncode": version_result["returncode"],
        "help_returncode": help_result["returncode"],
        "entrypoints": ["zaptrace", "zaptrace-mcp", "zaptrace-mcp-http", "zaptrace-api"],
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, process: subprocess.Popen[str], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise DistributionSmokeError(f"Entrypoint exited before startup with code {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise DistributionSmokeError(f"Entrypoint did not bind 127.0.0.1:{port} within {timeout_s:.1f}s")


def _http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: bytes | None = None,
    timeout_s: float = 5.0,
) -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(url, method=method, headers=headers or {}, data=payload)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - loopback-only CI probe
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            return response.status, response.read(1024 * 1024), response_headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(1024 * 1024), {key.lower(): value for key, value in exc.headers.items()}


def _stop_process(process: subprocess.Popen[str]) -> tuple[bool, str, str]:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    stdout, stderr = process.communicate(timeout=1)
    return process.poll() is not None, _bounded(stdout or ""), _bounded(stderr or "")


def _entrypoint_environment() -> dict[str, str]:
    env = dict(os.environ)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    return env


def probe_api(*, timeout_s: float = 15.0) -> dict[str, Any]:
    """Start the installed REST entry point and exercise health/auth behavior."""
    port = _free_port()
    token = secrets.token_urlsafe(24)
    env = _entrypoint_environment()
    env.update(
        {
            "ZAPTRACE_API_HOST": "127.0.0.1",
            "ZAPTRACE_API_PORT": str(port),
            "ZAPTRACE_API_TOKEN": token,
        }
    )
    process = subprocess.Popen(
        [str(resolve_console_script("zaptrace-api"))],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    result: dict[str, Any] = {}
    error: Exception | None = None
    try:
        _wait_for_port(port, process, timeout_s)
        base = f"http://127.0.0.1:{port}"
        health_status, health_body, _ = _http_request(f"{base}/health")
        health = json.loads(health_body)
        missing_status, _, _ = _http_request(f"{base}/api/v1/artifacts/config")
        valid_status, valid_body, _ = _http_request(
            f"{base}/api/v1/artifacts/config",
            headers={"Authorization": f"Bearer {token}"},
        )
        if health_status != 200 or health.get("status") != "ok":
            raise DistributionSmokeError(f"REST health returned unexpected response: {health_status} {health}")
        if (missing_status, valid_status) != (401, 200):
            raise DistributionSmokeError(
                f"REST authorization returned unexpected statuses: missing={missing_status}, valid={valid_status}"
            )
        result = {
            "passed": True,
            "bind": f"127.0.0.1:{port}",
            "health_status": health_status,
            "version": str(health.get("version", "")),
            "missing_token_status": missing_status,
            "valid_token_status": valid_status,
            "valid_response_bytes": len(valid_body),
        }
    except Exception as exc:  # noqa: BLE001 - process boundary is converted to bounded evidence
        error = exc
    finally:
        terminated, stdout, stderr = _stop_process(process)
    if error is not None:
        raise DistributionSmokeError(f"REST startup smoke failed: {error}\n{stdout}\n{stderr}") from error
    result["process_terminated"] = terminated
    return result


def _parse_mcp_initialize(payload: bytes) -> dict[str, str]:
    for line in payload.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        message = json.loads(line.removeprefix("data:").strip())
        result = message.get("result") if isinstance(message, dict) else None
        if not isinstance(result, dict):
            continue
        server_info = result.get("serverInfo")
        if not isinstance(server_info, dict):
            continue
        return {
            "protocol_version": str(result.get("protocolVersion", "")),
            "server_name": str(server_info.get("name", "")),
            "server_version": str(server_info.get("version", "")),
        }
    raise DistributionSmokeError("MCP initialize response did not contain server identity")


def probe_mcp_http(*, timeout_s: float = 15.0) -> dict[str, Any]:
    """Start the installed MCP HTTP entry point and exercise initialize/auth behavior."""
    port = _free_port()
    token = secrets.token_urlsafe(24)
    env = _entrypoint_environment()
    env.update(
        {
            "ZAPTRACE_MCP_HTTP_HOST": "127.0.0.1",
            "ZAPTRACE_MCP_HTTP_PORT": str(port),
            "ZAPTRACE_MCP_HTTP_TOKEN": token,
        }
    )
    process = subprocess.Popen(
        [str(resolve_console_script("zaptrace-mcp-http"))],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    result: dict[str, Any] = {}
    error: Exception | None = None
    try:
        _wait_for_port(port, process, timeout_s)
        url = f"http://127.0.0.1:{port}/mcp"
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "zaptrace-distribution-smoke", "version": "1"},
                },
            },
            separators=(",", ":"),
        ).encode()
        protocol_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        missing_status, _, _ = _http_request(url, method="POST", headers=protocol_headers, payload=payload)
        valid_status, valid_body, valid_headers = _http_request(
            url,
            method="POST",
            headers={**protocol_headers, "Authorization": f"Bearer {token}"},
            payload=payload,
        )
        if (missing_status, valid_status) != (401, 200):
            raise DistributionSmokeError(
                f"MCP authorization returned unexpected statuses: missing={missing_status}, valid={valid_status}"
            )
        identity = _parse_mcp_initialize(valid_body)
        session_id = valid_headers.get("mcp-session-id", "")
        close_status = 0
        if session_id:
            close_status, _, _ = _http_request(
                url,
                method="DELETE",
                headers={
                    **protocol_headers,
                    "Authorization": f"Bearer {token}",
                    "mcp-session-id": session_id,
                },
            )
            if close_status not in {200, 202, 204}:
                raise DistributionSmokeError(f"MCP session cleanup returned status {close_status}")
        result = {
            "passed": True,
            "bind": f"127.0.0.1:{port}",
            "missing_token_status": missing_status,
            "valid_token_status": valid_status,
            "session_close_status": close_status,
            **identity,
        }
    except Exception as exc:  # noqa: BLE001 - process boundary is converted to bounded evidence
        error = exc
    finally:
        terminated, stdout, stderr = _stop_process(process)
    if error is not None:
        raise DistributionSmokeError(f"MCP HTTP startup smoke failed: {error}\n{stdout}\n{stderr}") from error
    result["process_terminated"] = terminated
    return result


def _canonical_digest(report: dict[str, Any]) -> str:
    digest_input = {key: value for key, value in report.items() if key not in {"generated_at", "evidence_digest"}}
    payload = json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def build_report(
    *,
    artifact: Path,
    artifact_root: Path,
    target: dict[str, Any],
    source_commit: str,
    lockfile: Path,
    source_root: Path,
    installed_path: Path,
    checks: dict[str, dict[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build identity-bound distribution smoke evidence."""
    normalized_commit = source_commit.strip().lower()
    if not _COMMIT_RE.fullmatch(normalized_commit):
        raise DistributionSmokeError("source_commit must be a 40-character lowercase hexadecimal commit")
    artifact_path = _validated_input_file(artifact, allowed_root=artifact_root, label="artifact")
    lockfile_path = _validated_input_file(lockfile, allowed_root=source_root, label="dependency lockfile")
    checks_passed = bool(checks) and all(check.get("passed") is True for check in checks.values())
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "gate_id": "distribution-clean-install-v1",
        "passed": checks_passed and target.get("support_level") != "unsupported",
        "generated_at": generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "target": target,
        "artifact": {
            "filename": artifact_path.name,
            "size": artifact_path.stat().st_size,
            "sha256": sha256_file(artifact_path, allowed_root=artifact_root, label="artifact"),
        },
        "evidence_identity": {
            "source_commit": normalized_commit,
            "uv_lock_sha256": sha256_file(
                lockfile_path,
                allowed_root=source_root,
                label="dependency lockfile",
            ),
        },
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "system": platform.system().lower(),
            "machine": platform.machine().lower(),
        },
        "installed_path": installed_path.resolve().as_posix(),
        "checks": checks,
        "non_claims": list(_NON_CLAIMS),
    }
    report["evidence_digest"] = _canonical_digest(report)
    return report


def _sdk_check() -> tuple[Path, str, dict[str, Any]]:
    zaptrace = importlib.import_module("zaptrace")
    installed_path = Path(zaptrace.__file__ or "")
    version = importlib.metadata.version(_DISTRIBUTION_NAME)
    design_type = zaptrace.Design
    design = design_type(meta={"name": "distribution-smoke"})
    return (
        installed_path,
        version,
        {
            "passed": True,
            "version": version,
            "module_version": str(zaptrace.__version__),
            "design_name": str(design.meta.name),
        },
    )


def _native_check(expected: str) -> dict[str, Any]:
    native_path: Path | None = None
    import_error: str | None = None
    try:
        native = importlib.import_module("zaptrace._core")
        native_path = Path(native.__file__ or "")
    except ImportError as exc:
        import_error = str(exc)
    return verify_native_state(expected, native_path=native_path, import_error=import_error)


def execute_smoke(
    *,
    artifact: Path,
    artifact_root: Path,
    target: dict[str, Any],
    source_root: Path,
    source_commit: str,
    lockfile: Path,
    expected_native: str,
) -> dict[str, Any]:
    """Execute all clean-install checks and return a complete report."""
    installed_path, version, sdk = _sdk_check()
    checks = {
        "installed_boundary": verify_installed_path(installed_path, source_root),
        "sdk": sdk,
        "native_extension": _native_check(expected_native),
        "cli": run_console_checks(version),
        "api": probe_api(),
        "mcp_http": probe_mcp_http(),
    }
    return build_report(
        artifact=artifact,
        artifact_root=artifact_root,
        target=target,
        source_commit=source_commit,
        lockfile=lockfile,
        source_root=source_root,
        installed_path=installed_path,
        checks=checks,
    )


def render_markdown(report: dict[str, Any]) -> str:
    status = "PASS" if report.get("passed") else "FAIL"
    target = report.get("target") or {}
    artifact = report.get("artifact") or {}
    identity = report.get("evidence_identity") or {}
    lines = [
        "# Distribution clean-install evidence",
        "",
        f"- Status: **{status}**",
        f"- Target: `{target.get('target_id', 'unknown')}`",
        f"- Artifact: `{artifact.get('filename', 'unknown')}`",
        f"- Artifact SHA-256: `{artifact.get('sha256', '')}`",
        f"- Source commit: `{identity.get('source_commit', '')}`",
        f"- uv.lock SHA-256: `{identity.get('uv_lock_sha256', '')}`",
        f"- Evidence digest: `{report.get('evidence_digest', '')}`",
        "",
        "## Checks",
        "",
    ]
    for name, check in sorted((report.get("checks") or {}).items()):
        lines.append(f"- `{name}`: {'PASS' if check.get('passed') else 'FAIL'}")
    if report.get("error"):
        lines.extend(["", "## Error", "", str(report["error"])])
    lines.extend(["", "## Non-claims", ""])
    lines.extend(f"- {claim}" for claim in report.get("non_claims", _NON_CLAIMS))
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--artifact-type", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--lockfile", type=Path, required=True)
    parser.add_argument("--expected-native", choices=("required", "optional", "absent"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    return parser


def _failure_report(args: argparse.Namespace, error: Exception) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "gate_id": "distribution-clean-install-v1",
        "passed": False,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "target": {"target_id": args.target},
        "artifact": {"filename": args.artifact.name},
        "evidence_identity": {"source_commit": args.source_commit},
        "checks": {},
        "error": _bounded(str(error)),
        "non_claims": list(_NON_CLAIMS),
        "evidence_digest": "",
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        policy = load_policy(args.policy, allowed_root=args.source_root)
        target = select_target(policy, args.target, require_supported=args.strict)
        if target["artifact_type"] != args.artifact_type:
            raise DistributionSmokeError(
                f"Target {args.target} expects artifact_type={target['artifact_type']}, got {args.artifact_type}"
            )
        if target["native_extension"] != args.expected_native:
            raise DistributionSmokeError(
                f"Target {args.target} expects native_extension={target['native_extension']}, "
                f"got {args.expected_native}"
            )
        report = execute_smoke(
            artifact=args.artifact,
            artifact_root=args.artifact_root,
            target=target,
            source_root=args.source_root,
            source_commit=args.source_commit,
            lockfile=args.lockfile,
            expected_native=args.expected_native,
        )
    except (DistributionPolicyError, DistributionSmokeError, OSError, subprocess.SubprocessError) as exc:
        report = _failure_report(args, exc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
