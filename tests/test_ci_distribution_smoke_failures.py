from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_distribution_smoke.py"
POLICY = ROOT / "config" / "distribution-support.json"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_distribution_smoke_failure_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _target(**overrides: str) -> dict[str, str]:
    target = {
        "target_id": "sdist-linux-x86_64-cp313",
        "operating_system": "linux",
        "architecture": "x86_64",
        "python": "CPython 3.13",
        "artifact_type": "source-distribution",
        "platform_tag": "source",
        "native_extension": "absent",
        "support_level": "supported",
        "distribution_channel": "github-releases",
        "verification_workflow": "quality:distribution-clean-install",
        "guidance": "Install the verified sdist.",
    }
    target.update(overrides)
    return target


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    artifact = tmp_path / "zaptrace.tar.gz"
    lockfile = tmp_path / "uv.lock"
    installed = tmp_path / "site-packages" / "zaptrace" / "__init__.py"
    artifact.write_bytes(b"artifact")
    lockfile.write_bytes(b"lock")
    installed.parent.mkdir(parents=True)
    installed.write_text("", encoding="utf-8")
    return artifact, lockfile, installed


def test_sha256_and_native_validation_reject_invalid_inputs(tmp_path: Path) -> None:
    module = _load_module()
    with pytest.raises(module.DistributionSmokeError, match="Cannot resolve"):
        module.sha256_file(tmp_path / "missing.whl", allowed_root=tmp_path)
    with pytest.raises(module.DistributionSmokeError, match="Unsupported native expectation"):
        module.verify_native_state("unknown", native_path=None, import_error=None)


def test_console_script_resolution_falls_back_to_path_and_rejects_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    fallback = tmp_path / "zaptrace"
    fallback.write_text("", encoding="utf-8")
    monkeypatch.setattr(module.sys, "executable", str(tmp_path / "venv" / "bin" / "python"))
    monkeypatch.setattr(module.shutil, "which", lambda name: str(fallback) if name == "zaptrace" else None)

    assert module.resolve_console_script("zaptrace") == fallback.resolve()
    with pytest.raises(module.DistributionSmokeError, match="console script is missing"):
        module.resolve_console_script("zaptrace-api")


def test_run_command_and_console_check_fail_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()
    ok = module._run_command([sys.executable, "-c", "print('ok')"], timeout_s=5)
    assert ok["passed"] is True
    assert ok["stdout"].strip() == "ok"

    with pytest.raises(module.DistributionSmokeError, match="Command failed"):
        module._run_command([sys.executable, "-c", "raise SystemExit(3)"], timeout_s=5)

    script = tmp_path / "zaptrace"
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr(module, "resolve_console_script", lambda _name: script)
    monkeypatch.setattr(
        module,
        "_run_command",
        lambda args, timeout_s: {"passed": True, "returncode": 0, "stdout": "wrong-version", "stderr": ""},
    )
    with pytest.raises(module.DistributionSmokeError, match="did not report installed version"):
        module.run_console_checks("9.9.9")


def test_wait_for_port_reports_early_exit_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    exited = SimpleNamespace(poll=lambda: 7, returncode=7)
    with pytest.raises(module.DistributionSmokeError, match="exited before startup"):
        module._wait_for_port(1, exited, 1.0)

    running = SimpleNamespace(poll=lambda: None, returncode=None)
    ticks = iter((0.0, 0.1, 0.2))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    def fail_connect(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("closed")

    monkeypatch.setattr(module.socket, "create_connection", fail_connect)
    with pytest.raises(module.DistributionSmokeError, match="did not bind"):
        module._wait_for_port(1, running, 0.15)


def test_stop_process_kills_after_terminate_timeout() -> None:
    module = _load_module()

    class FakeProcess:
        returncode: int | None = None
        killed = False
        wait_calls = 0

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float) -> int:
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired("fake", timeout)
            self.returncode = -9
            return self.returncode

        def kill(self) -> None:
            self.killed = True

        def communicate(self, timeout: float) -> tuple[str, str]:
            return "stdout", "stderr"

    process = FakeProcess()
    terminated, stdout, stderr = module._stop_process(process)
    assert terminated is True
    assert process.killed is True
    assert (stdout, stderr) == ("stdout", "stderr")


def test_parse_mcp_initialize_ignores_irrelevant_messages_and_rejects_missing_identity() -> None:
    module = _load_module()
    payload = b'event: message\ndata: []\ndata: {"result":{}}\n'
    with pytest.raises(module.DistributionSmokeError, match="did not contain server identity"):
        module._parse_mcp_initialize(payload)


def _fake_process() -> SimpleNamespace:
    return SimpleNamespace(stdout=None, stderr=None)


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        ([(503, b'{"status":"bad"}', {}), (401, b"", {}), (200, b"{}", {})], "REST health"),
        ([(200, b'{"status":"ok"}', {}), (200, b"", {}), (200, b"{}", {})], "REST authorization"),
    ],
)
def test_api_probe_converts_invalid_responses_to_bounded_failure(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[tuple[int, bytes, dict[str, str]]],
    message: str,
) -> None:
    module = _load_module()
    iterator = iter(responses)
    monkeypatch.setattr(module, "resolve_console_script", lambda _name: Path("/bin/true"))
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: _fake_process())
    monkeypatch.setattr(module, "_wait_for_port", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_http_request", lambda *_args, **_kwargs: next(iterator))
    monkeypatch.setattr(module, "_stop_process", lambda _process: (True, "bounded-out", "bounded-err"))

    with pytest.raises(module.DistributionSmokeError, match=message):
        module.probe_api()


def _mcp_body() -> bytes:
    return b'data: {"result":{"protocolVersion":"2025-06-18","serverInfo":{"name":"zaptrace","version":"1"}}}\n'


@pytest.mark.parametrize("close_status", [0, 500])
def test_mcp_probe_converts_auth_and_cleanup_failures(
    monkeypatch: pytest.MonkeyPatch,
    close_status: int,
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "resolve_console_script", lambda _name: Path("/bin/true"))
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: _fake_process())
    monkeypatch.setattr(module, "_wait_for_port", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_stop_process", lambda _process: (True, "bounded-out", "bounded-err"))
    if close_status == 0:
        responses = iter([(200, b"", {}), (200, _mcp_body(), {})])
        expected = "MCP authorization"
    else:
        responses = iter([(401, b"", {}), (200, _mcp_body(), {"mcp-session-id": "session"}), (close_status, b"", {})])
        expected = "session cleanup"
    monkeypatch.setattr(module, "_http_request", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(module.DistributionSmokeError, match=expected):
        module.probe_mcp_http()


def test_build_report_rejects_invalid_identity(tmp_path: Path) -> None:
    module = _load_module()
    artifact, lockfile, installed = _files(tmp_path)
    target = _target()
    checks = {"sdk": {"passed": True}}
    with pytest.raises(module.DistributionSmokeError, match="source_commit"):
        module.build_report(
            artifact=artifact,
            artifact_root=tmp_path,
            target=target,
            source_commit="bad",
            lockfile=lockfile,
            source_root=tmp_path,
            installed_path=installed,
            checks=checks,
        )


def test_build_report_rejects_missing_lock(tmp_path: Path) -> None:
    module = _load_module()
    artifact, lockfile, installed = _files(tmp_path)
    target = _target()
    checks = {"sdk": {"passed": True}}
    lockfile.unlink()
    with pytest.raises(module.DistributionSmokeError, match="Cannot resolve dependency lockfile"):
        module.build_report(
            artifact=artifact,
            artifact_root=tmp_path,
            target=target,
            source_commit="a" * 40,
            lockfile=lockfile,
            source_root=tmp_path,
            installed_path=installed,
            checks=checks,
        )


def test_build_report_blocks_failed_checks_and_unsupported_target(tmp_path: Path) -> None:
    module = _load_module()
    artifact, lockfile, installed = _files(tmp_path)
    failed = module.build_report(
        artifact=artifact,
        artifact_root=tmp_path,
        target=_target(),
        source_commit="a" * 40,
        lockfile=lockfile,
        source_root=tmp_path,
        installed_path=installed,
        checks={"sdk": {"passed": False}},
    )
    unsupported = module.build_report(
        artifact=artifact,
        artifact_root=tmp_path,
        target=_target(support_level="unsupported"),
        source_commit="a" * 40,
        lockfile=lockfile,
        source_root=tmp_path,
        installed_path=installed,
        checks={"sdk": {"passed": True}},
    )
    assert failed["passed"] is False
    assert unsupported["passed"] is False


def test_native_check_records_import_success_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()
    native_path = tmp_path / "_core.so"
    native_path.write_bytes(b"native")
    native = SimpleNamespace(__file__=str(native_path))
    monkeypatch.setattr(module.importlib, "import_module", lambda _name: native)
    assert module._native_check("required")["present"] is True

    def missing(_name: str) -> None:
        raise ImportError("missing native")

    monkeypatch.setattr(module.importlib, "import_module", missing)
    result = module._native_check("optional")
    assert result["present"] is False
    assert result["import_error"] == "missing native"


def test_execute_smoke_composes_all_checks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact, lockfile, installed = _files(tmp_path)
    monkeypatch.setattr(module, "_sdk_check", lambda: (installed, "1.2.3", {"passed": True}))
    monkeypatch.setattr(module, "verify_installed_path", lambda *_args: {"passed": True})
    monkeypatch.setattr(module, "_native_check", lambda _expected: {"passed": True})
    monkeypatch.setattr(module, "run_console_checks", lambda _version: {"passed": True})
    monkeypatch.setattr(module, "probe_api", lambda: {"passed": True})
    monkeypatch.setattr(module, "probe_mcp_http", lambda: {"passed": True})

    report = module.execute_smoke(
        artifact=artifact,
        artifact_root=tmp_path,
        target=_target(),
        source_root=tmp_path,
        source_commit="a" * 40,
        lockfile=lockfile,
        expected_native="absent",
    )

    assert report["passed"] is True
    assert set(report["checks"]) == {"installed_boundary", "sdk", "native_extension", "cli", "api", "mcp_http"}


def test_render_markdown_includes_failure_and_error() -> None:
    module = _load_module()
    markdown = module.render_markdown(
        {
            "passed": False,
            "target": {"target_id": "target"},
            "artifact": {"filename": "artifact", "sha256": "a" * 64},
            "evidence_identity": {"source_commit": "b" * 40, "uv_lock_sha256": "c" * 64},
            "checks": {"sdk": {"passed": False}},
            "error": "bounded failure",
            "non_claims": ["not universal"],
        }
    )
    assert "Status: **FAIL**" in markdown
    assert "`sdk`: FAIL" in markdown
    assert "bounded failure" in markdown
    assert "not universal" in markdown


def _main_args(tmp_path: Path, artifact: Path, lockfile: Path) -> list[str]:
    return [
        "--artifact",
        str(artifact),
        "--artifact-root",
        str(tmp_path),
        "--artifact-type",
        "source-distribution",
        "--target",
        "sdist-linux-x86_64-cp313",
        "--policy",
        str(POLICY),
        "--source-root",
        str(ROOT),
        "--source-commit",
        "a" * 40,
        "--lockfile",
        str(lockfile),
        "--expected-native",
        "absent",
        "--output",
        str(tmp_path / "nested" / "report.json"),
        "--markdown",
        str(tmp_path / "nested" / "report.md"),
        "--strict",
    ]


def test_main_writes_success_and_failure_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    artifact, lockfile, installed = _files(tmp_path)
    success = module.build_report(
        artifact=artifact,
        artifact_root=tmp_path,
        target=_target(),
        source_commit="a" * 40,
        lockfile=lockfile,
        source_root=tmp_path,
        installed_path=installed,
        checks={"sdk": {"passed": True}},
    )
    monkeypatch.setattr(module, "execute_smoke", lambda **_kwargs: success)
    args = _main_args(tmp_path, artifact, lockfile)

    assert module.main(args) == 0
    written = json.loads((tmp_path / "nested" / "report.json").read_text(encoding="utf-8"))
    assert written["passed"] is True

    mismatched = list(args)
    mismatched[mismatched.index("source-distribution")] = "native-wheel"
    assert module.main(mismatched) == 1
    failed = json.loads((tmp_path / "nested" / "report.json").read_text(encoding="utf-8"))
    assert failed["passed"] is False
    assert "expects artifact_type" in failed["error"]


def test_failure_report_bounds_error_text(tmp_path: Path) -> None:
    module = _load_module()
    args = argparse.Namespace(target="target", artifact=tmp_path / "artifact", source_commit="a" * 40)
    report = module._failure_report(args, RuntimeError("x" * 5000))
    assert report["passed"] is False
    assert len(report["error"]) == module._MAX_LOG_CHARS


def test_sha256_rejects_workspace_escape_and_symlink(tmp_path: Path) -> None:
    module = _load_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.whl"
    outside.write_bytes(b"artifact")
    symlink = workspace / "artifact.whl"
    symlink.symlink_to(outside)

    with pytest.raises(module.DistributionSmokeError, match="outside allowed root"):
        module.sha256_file(outside, allowed_root=workspace)
    with pytest.raises(module.DistributionSmokeError, match="symbolic link"):
        module.sha256_file(symlink, allowed_root=workspace)
