from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from scripts import ci_validation_environment
from zaptrace import __version__


def test_version_parser_reads_major_minor() -> None:
    assert ci_validation_environment._first_version_number("Python 3.12.7") == (3, 12)
    assert ci_validation_environment._first_version_number("KiCad CLI 9.0.1") == (9, 0)


def test_kicad_requirement_rejects_legacy_cli() -> None:
    requirement = next(req for req in ci_validation_environment.TOOL_REQUIREMENTS if req.name == "KiCad CLI")

    assert (requirement.min_major, requirement.min_minor) == (9, 0)


def test_report_contains_release_commands_and_non_claims() -> None:
    report = ci_validation_environment.build_report()
    assert report["schema_version"] == "2.0"
    identity = report["evidence_identity"]
    assert identity["mode"] == "snapshot"
    assert identity["package_version"] == __version__
    assert len(identity["source_commit"]) == 40
    assert len(identity["identity_sha256"]) == 64
    assert "uv lock --check" in report["recommended_release_commands"]
    assert "uv sync --locked --all-extras --all-groups" in report["recommended_release_commands"]
    assert "uv run pytest --cov=zaptrace --cov-report=term-missing" in report["recommended_release_commands"]
    assert any("fabrication" in claim for claim in report["non_claims"])


def test_report_json_is_stable_json() -> None:
    report = {
        "schema_version": "1.0",
        "passed": True,
        "tools": [],
    }
    rendered = ci_validation_environment.report_json(report)
    assert rendered.endswith("\n")
    assert '"passed": true' in rendered


def test_report_identifies_authoritative_release_role_and_dependency_identity() -> None:
    report = ci_validation_environment.build_report()

    assert report["environment_role"] == "authoritative-release"
    assert report["authoritative_release_path"] == ".github/workflows/release.yml"
    assert report["scoped_validator_role"] == "diagnostic-only"
    assert len(report["lock_sha256"]) == 64
    assert report["locked_dependencies"] == {"fastmcp": "3.4.2", "mcp": "1.28.1"}
    assert len(report["policy_sha256"]) == 64
    assert report["evidence_identity"]["lock_sha256"] == report["lock_sha256"]
    assert "scripts/ci_validation_environment.py" in report["evidence_identity"]["source_inputs"]


def test_full_release_parity_requires_container_and_simulation_tools() -> None:
    requirements = {requirement.name: requirement for requirement in ci_validation_environment.TOOL_REQUIREMENTS}

    assert requirements["Docker"].required is True
    assert requirements["Docker Buildx"].required is True
    assert requirements["ngspice"].required is True


def test_report_recommends_immutable_lock_commands() -> None:
    report = ci_validation_environment.build_report()

    assert "uv lock --check" in report["recommended_release_commands"]
    assert "uv sync --locked --all-extras --all-groups" in report["recommended_release_commands"]
    assert "uv sync --all-extras --all-groups" not in report["recommended_release_commands"]


def test_check_tool_uses_ephemeral_private_home_when_home_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_home: Path | None = None

    def fake_run(*_args: object, env: dict[str, str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal observed_home
        observed_home = Path(env["HOME"])
        assert observed_home.is_dir()
        assert not observed_home.is_symlink()
        assert stat.S_IMODE(observed_home.stat().st_mode) == 0o700
        return subprocess.CompletedProcess(["tool", "--version"], 0, "tool 1.0", "")

    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setattr(ci_validation_environment, "_which", lambda _executable: "/usr/bin/tool")
    monkeypatch.setattr(ci_validation_environment.subprocess, "run", fake_run)
    requirement = ci_validation_environment.ToolRequirement(name="Tool", executable="tool")

    result = ci_validation_environment.check_tool(requirement)

    assert result["status"] == "ok"
    assert observed_home is not None
    assert not observed_home.exists()


def test_tool_check_helpers_cover_missing_failure_and_version_states(monkeypatch: pytest.MonkeyPatch) -> None:
    required = ci_validation_environment.ToolRequirement(
        name="Required", executable="required", min_major=3, min_minor=2
    )
    optional = ci_validation_environment.ToolRequirement(name="Optional", executable="optional", required=False)

    assert ci_validation_environment._tool_result(required, None)["status"] == "missing"
    assert ci_validation_environment._tool_result(optional, None)["status"] == "optional-missing"

    result = ci_validation_environment._tool_result(required, "/tool")
    assert ci_validation_environment._apply_minimum_version(required, "not-a-version", result) is False
    assert result["error"] == "could not parse version"

    result = ci_validation_environment._tool_result(required, "/tool")
    assert ci_validation_environment._apply_minimum_version(required, "tool 3.1", result) is False
    assert result["status"] == "too-old"
    assert result["required_version"] == ">=3.2"

    result = ci_validation_environment._tool_result(required, "/tool")
    assert ci_validation_environment._apply_minimum_version(required, "tool 3.2", result) is True

    monkeypatch.setattr(ci_validation_environment, "_which", lambda _executable: "/tool")
    monkeypatch.setattr(
        ci_validation_environment,
        "_run_tool_version",
        lambda _path, _req: subprocess.CompletedProcess(["tool"], 1, "", "broken"),
    )
    assert ci_validation_environment.check_tool(optional)["status"] == "optional-failed"


def test_tool_check_records_version_runner_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    requirement = ci_validation_environment.ToolRequirement(name="Tool", executable="tool")
    monkeypatch.setattr(ci_validation_environment, "_which", lambda _executable: "/tool")

    def fail(_path: str, _req: ci_validation_environment.ToolRequirement) -> subprocess.CompletedProcess[str]:
        raise OSError("cannot execute")

    monkeypatch.setattr(ci_validation_environment, "_run_tool_version", fail)
    result = ci_validation_environment.check_tool(requirement)
    assert result["status"] == "failed"
    assert result["error"] == "cannot execute"


def test_kicad_install_workflows_use_bounded_retry_helper() -> None:
    helper = Path("scripts/ci_install_kicad.sh")
    assert helper.is_file()
    script = helper.read_text(encoding="utf-8")
    assert "for attempt in 1 2 3" in script
    assert "timeout 90s" in script
    assert "add-apt-repository --yes --no-update ppa:kicad/kicad-10.0-releases" in script
    assert "Acquire::Retries=3" in script
    assert "timeout 300s apt-get" in script
    assert "timeout 600s apt-get" in script
    assert "Acquire::http::Timeout=30" in script
    assert "Acquire::https::Timeout=30" in script
    assert "/etc/apt/apt-mirrors.txt" in script
    assert "azure.archive.ubuntu.com/ubuntu" in script
    assert "https://archive.ubuntu.com/ubuntu" in script

    expected_calls = {
        Path(".github/workflows/quality.yml"): 4,
        Path(".github/workflows/release.yml"): 1,
        Path(".github/workflows/hardware.yml"): 1,
        Path(".github/workflows/kicad-oracle.yml"): 1,
    }
    for workflow_path, count in expected_calls.items():
        workflow = workflow_path.read_text(encoding="utf-8")
        assert workflow.count("bash scripts/ci_install_kicad.sh") == count
        assert "add-apt-repository --yes ppa:kicad/kicad-10.0-releases" not in workflow

    quality = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    benchmark = quality[
        quality.index("      - name: Install simulation runtime") : quality.index(
            "      - name: Run simulation-backed sign-off evidence gate"
        )
    ]
    assert "bash scripts/ci_install_kicad.sh ngspice" in benchmark
    assert "sudo apt-get update" not in benchmark
    assert "sudo apt-get install --no-install-recommends -y ngspice" not in benchmark


def test_get_tool_requirements_rejects_unknown_role() -> None:
    with pytest.raises(ValueError, match="unsupported environment role"):
        ci_validation_environment.get_tool_requirements("invalid-role")
    with pytest.raises(ValueError, match="unsupported environment role"):
        ci_validation_environment.build_report(environment_role="invalid-role")


def test_ngspice_absent_in_developer_mode_is_optional_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(executable: str) -> str | None:
        if executable == "ngspice":
            return None
        return f"/usr/bin/{executable}"

    def fake_run(path: str, _req: ci_validation_environment.ToolRequirement) -> subprocess.CompletedProcess[str]:
        version_map = {
            "python3": "Python 3.12.0",
            "rustc": "rustc 1.91.0",
            "cargo": "cargo 1.91.0",
            "kicad-cli": "kicad-cli 9.0.0",
            "docker": "Docker version 27.0.0",
            "uv": "uv 0.5.0",
        }
        name = Path(path).name
        return subprocess.CompletedProcess([path], 0, version_map.get(name, "1.0.0"), "")

    monkeypatch.setattr(ci_validation_environment, "_which", fake_which)
    monkeypatch.setattr(ci_validation_environment, "_run_tool_version", fake_run)

    report = ci_validation_environment.build_report(environment_role="developer")

    assert report["environment_role"] == "developer"
    assert report["passed"] is True
    assert "ngspice" not in report["blocking_tools"]
    assert "ngspice" in report["warning_tools"]

    ngspice_tool = next(t for t in report["tools"] if t["name"] == "ngspice")
    assert ngspice_tool["status"] == "optional-missing"
    assert ngspice_tool["required"] is False
    assert "apt-get install ngspice" in ngspice_tool["install_hint"]
    assert "optional in developer mode" in ngspice_tool["install_hint"]

    rendered = ci_validation_environment.render_text(report)
    assert "Validation environment: PASS" in rendered
    assert "!! ngspice: optional-missing" in rendered
    assert "hint: Install ngspice" in rendered


def test_ngspice_absent_in_strict_mode_is_blocking_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(executable: str) -> str | None:
        if executable == "ngspice":
            return None
        return f"/usr/bin/{executable}"

    def fake_run(path: str, _req: ci_validation_environment.ToolRequirement) -> subprocess.CompletedProcess[str]:
        version_map = {
            "python3": "Python 3.12.0",
            "rustc": "rustc 1.91.0",
            "cargo": "cargo 1.91.0",
            "kicad-cli": "kicad-cli 9.0.0",
            "docker": "Docker version 27.0.0",
            "uv": "uv 0.5.0",
        }
        name = Path(path).name
        return subprocess.CompletedProcess([path], 0, version_map.get(name, "1.0.0"), "")

    monkeypatch.setattr(ci_validation_environment, "_which", fake_which)
    monkeypatch.setattr(ci_validation_environment, "_run_tool_version", fake_run)

    report = ci_validation_environment.build_report(environment_role="authoritative-release")

    assert report["environment_role"] == "authoritative-release"
    assert report["passed"] is False
    assert "ngspice" in report["blocking_tools"]

    ngspice_tool = next(t for t in report["tools"] if t["name"] == "ngspice")
    assert ngspice_tool["status"] == "missing"
    assert ngspice_tool["required"] is True

    rendered = ci_validation_environment.render_text(report)
    assert "Validation environment: FAIL" in rendered
    assert "!! ngspice: missing" in rendered


def test_ngspice_present_passes_in_both_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(executable: str) -> str | None:
        return f"/usr/bin/{executable}"

    def fake_run(path: str, _req: ci_validation_environment.ToolRequirement) -> subprocess.CompletedProcess[str]:
        version_map = {
            "python3": "Python 3.12.0",
            "rustc": "rustc 1.91.0",
            "cargo": "cargo 1.91.0",
            "kicad-cli": "kicad-cli 9.0.0",
            "docker": "Docker version 27.0.0",
            "uv": "uv 0.5.0",
            "ngspice": "ngspice-42",
        }
        name = Path(path).name
        return subprocess.CompletedProcess([path], 0, version_map.get(name, "1.0.0"), "")

    monkeypatch.setattr(ci_validation_environment, "_which", fake_which)
    monkeypatch.setattr(ci_validation_environment, "_run_tool_version", fake_run)

    for role in ("developer", "authoritative-release", "diagnostic-only"):
        report = ci_validation_environment.build_report(environment_role=role)
        assert report["passed"] is True
        assert "ngspice" not in report["blocking_tools"]
        assert "ngspice" not in report["warning_tools"]
        ngspice_tool = next(t for t in report["tools"] if t["name"] == "ngspice")
        assert ngspice_tool["status"] == "ok"
        assert ngspice_tool["version"] == "ngspice-42"


def test_ngspice_execution_failure_in_developer_mode_vs_strict_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(executable: str) -> str | None:
        return f"/usr/bin/{executable}"

    def fake_run(path: str, req: ci_validation_environment.ToolRequirement) -> subprocess.CompletedProcess[str]:
        if req.name == "ngspice":
            return subprocess.CompletedProcess([path], 1, "", "simulation driver error")
        version_map = {
            "python3": "Python 3.12.0",
            "rustc": "rustc 1.91.0",
            "cargo": "cargo 1.91.0",
            "kicad-cli": "kicad-cli 9.0.0",
            "docker": "Docker version 27.0.0",
            "uv": "uv 0.5.0",
        }
        name = Path(path).name
        return subprocess.CompletedProcess([path], 0, version_map.get(name, "1.0.0"), "")

    monkeypatch.setattr(ci_validation_environment, "_which", fake_which)
    monkeypatch.setattr(ci_validation_environment, "_run_tool_version", fake_run)

    # In developer mode: failed execution is optional-failed (warning, not blocking)
    dev_report = ci_validation_environment.build_report(environment_role="developer")
    assert dev_report["passed"] is True
    assert "ngspice" in dev_report["warning_tools"]
    assert "ngspice" not in dev_report["blocking_tools"]
    ngspice_dev = next(t for t in dev_report["tools"] if t["name"] == "ngspice")
    assert ngspice_dev["status"] == "optional-failed"

    # In authoritative-release mode: failed execution is blocking failure
    rel_report = ci_validation_environment.build_report(environment_role="authoritative-release")
    assert rel_report["passed"] is False
    assert "ngspice" in rel_report["blocking_tools"]
    ngspice_rel = next(t for t in rel_report["tools"] if t["name"] == "ngspice")
    assert ngspice_rel["status"] == "failed"


def test_validation_environment_cli_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_which(executable: str) -> str | None:
        if executable == "ngspice":
            return None
        return f"/usr/bin/{executable}"

    def fake_run(path: str, _req: ci_validation_environment.ToolRequirement) -> subprocess.CompletedProcess[str]:
        version_map = {
            "python3": "Python 3.12.0",
            "rustc": "rustc 1.91.0",
            "cargo": "cargo 1.91.0",
            "kicad-cli": "kicad-cli 9.0.0",
            "docker": "Docker version 27.0.0",
            "uv": "uv 0.5.0",
        }
        name = Path(path).name
        return subprocess.CompletedProcess([path], 0, version_map.get(name, "1.0.0"), "")

    monkeypatch.setattr(ci_validation_environment, "_which", fake_which)
    monkeypatch.setattr(ci_validation_environment, "_run_tool_version", fake_run)

    # Developer mode strict exit code should be 0 when only ngspice is missing
    exit_code_dev = ci_validation_environment.main(["--role", "developer", "--strict"])
    assert exit_code_dev == 0

    # Authoritative release mode strict exit code should be 1 when ngspice is missing
    exit_code_rel = ci_validation_environment.main(["--role", "authoritative-release", "--strict"])
    assert exit_code_rel == 1
