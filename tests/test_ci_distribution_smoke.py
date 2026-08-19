from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_distribution_smoke.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_distribution_smoke_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_entrypoint(tmp_path: Path, name: str, import_line: str, call: str) -> Path:
    entrypoint = tmp_path / name
    entrypoint.write_text(
        f"#!{sys.executable}\n{import_line}\n{call}\n",
        encoding="utf-8",
    )
    entrypoint.chmod(0o755)
    return entrypoint


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


def test_sha256_file_records_exact_artifact_bytes(tmp_path: Path) -> None:
    module = _load_module()
    artifact = tmp_path / "zaptrace.tar.gz"
    artifact.write_bytes(b"distribution-artifact")

    assert (
        module.sha256_file(artifact, allowed_root=tmp_path)
        == "0d4bc362959f3288e2a288a4f60d08d2280f0e4611d64f67b100e744335e8948"
    )


def test_installed_boundary_rejects_source_tree_import(tmp_path: Path) -> None:
    module = _load_module()
    source_root = tmp_path / "source"
    installed = source_root / "zaptrace" / "__init__.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("", encoding="utf-8")

    with pytest.raises(module.DistributionSmokeError, match="source tree"):
        module.verify_installed_path(installed, source_root)


def test_installed_boundary_accepts_external_environment(tmp_path: Path) -> None:
    module = _load_module()
    source_root = tmp_path / "source"
    installed = tmp_path / "clean-venv" / "site-packages" / "zaptrace" / "__init__.py"
    source_root.mkdir()
    installed.parent.mkdir(parents=True)
    installed.write_text("", encoding="utf-8")

    result = module.verify_installed_path(installed, source_root)

    assert result["passed"] is True
    assert result["source_tree_import"] is False


def test_native_state_enforces_required_and_absent_modes(tmp_path: Path) -> None:
    module = _load_module()
    native_path = tmp_path / "zaptrace" / "_core.so"
    native_path.parent.mkdir()
    native_path.write_bytes(b"native")

    assert module.verify_native_state("required", native_path=native_path, import_error=None)["passed"] is True
    assert module.verify_native_state("optional", native_path=None, import_error="missing")["passed"] is True
    with pytest.raises(module.DistributionSmokeError, match="required native extension"):
        module.verify_native_state("required", native_path=None, import_error="missing")
    with pytest.raises(module.DistributionSmokeError, match="unexpected native extension"):
        module.verify_native_state("absent", native_path=native_path, import_error=None)


def test_evidence_digest_excludes_generation_time(tmp_path: Path) -> None:
    module = _load_module()
    artifact = tmp_path / "zaptrace.tar.gz"
    lockfile = tmp_path / "uv.lock"
    artifact.write_bytes(b"artifact")
    lockfile.write_bytes(b"lock")
    checks = {"cli": {"passed": True}, "api": {"passed": True}}

    first = module.build_report(
        artifact=artifact,
        artifact_root=tmp_path,
        target=_target(),
        source_commit="a" * 40,
        lockfile=lockfile,
        source_root=tmp_path,
        installed_path=tmp_path / "site-packages" / "zaptrace" / "__init__.py",
        checks=checks,
        generated_at="2026-07-28T00:00:00Z",
    )
    second = module.build_report(
        artifact=artifact,
        artifact_root=tmp_path,
        target=_target(),
        source_commit="a" * 40,
        lockfile=lockfile,
        source_root=tmp_path,
        installed_path=tmp_path / "site-packages" / "zaptrace" / "__init__.py",
        checks=checks,
        generated_at="2026-07-28T01:00:00Z",
    )

    assert first["evidence_digest"] == second["evidence_digest"]
    assert first["generated_at"] != second["generated_at"]


def test_api_entrypoint_starts_on_loopback_and_enforces_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    entrypoint = _write_entrypoint(
        tmp_path,
        "zaptrace-api",
        "from zaptrace.api.server import run",
        "run()",
    )
    monkeypatch.setattr(module, "resolve_console_script", lambda _name: entrypoint)

    result = module.probe_api(timeout_s=15.0)

    assert result["passed"] is True
    assert result["health_status"] == 200
    assert result["missing_token_status"] == 401
    assert result["valid_token_status"] == 200
    assert result["process_terminated"] is True


def test_mcp_http_entrypoint_starts_and_returns_server_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    entrypoint = _write_entrypoint(
        tmp_path,
        "zaptrace-mcp-http",
        "from zaptrace.mcp.server import run_http",
        "run_http()",
    )
    monkeypatch.setattr(module, "resolve_console_script", lambda _name: entrypoint)

    result = module.probe_mcp_http(timeout_s=15.0)

    assert result["passed"] is True
    assert result["missing_token_status"] == 401
    assert result["valid_token_status"] == 200
    assert result["server_name"] == "zaptrace"
    assert result["process_terminated"] is True


def test_smoke_runner_imports_support_helper_without_prepending_source_root() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "sys.path.insert(0, str(ROOT))" not in source
    assert "sys.path.insert(0, str(SCRIPT_DIR))" in source
    assert "from ci_distribution_support import" in source


def test_sdk_check_constructs_minimal_public_design(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.importlib.metadata, "version", lambda _name: "0.3.1.dev0")

    installed_path, version, result = module._sdk_check()

    assert installed_path.is_file()
    assert version
    assert result["passed"] is True
    assert result["design_name"] == "distribution-smoke"


def test_sdk_check_reads_registry_distribution_metadata_name(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    requested: list[str] = []

    def _version(name: str) -> str:
        requested.append(name)
        return "0.3.2.dev0"

    monkeypatch.setattr(module.importlib.metadata, "version", _version)

    _installed_path, version, result = module._sdk_check()

    assert requested == ["zaptrace-eda"]
    assert version == "0.3.2.dev0"
    assert result["module_version"]
