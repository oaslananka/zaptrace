from __future__ import annotations

import os
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest
from packaging.version import Version

from scripts import ci_validation_environment
from tests.validation_environment_test_support import install_fake_validation_toolchain
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
    with (Path(__file__).resolve().parents[1] / "uv.lock").open("rb") as lock_file:
        lock = tomllib.load(lock_file)
    expected = {record["name"]: record["version"] for record in lock["package"] if record["name"] in {"fastmcp", "mcp"}}
    assert set(expected) == {"fastmcp", "mcp"}
    assert Version(expected["fastmcp"]) >= Version("4.0.2")
    assert Version(expected["mcp"]) >= Version("2.1.1")
    assert report["locked_dependencies"] == expected
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
        if os.name == "posix":
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
        Path(".github/workflows/quality.yml"): 2,
        Path(".github/workflows/quality-test-lanes.yml"): 2,
        Path(".github/workflows/quality-benchmark.yml"): 1,
        Path(".github/workflows/release.yml"): 1,
        Path(".github/workflows/hardware.yml"): 0,
        Path(".github/workflows/kicad-oracle.yml"): 0,
        Path(".github/actions/kicad-oracle/action.yml"): 1,
    }
    for workflow_path, count in expected_calls.items():
        workflow = workflow_path.read_text(encoding="utf-8")
        assert workflow.count("bash scripts/ci_install_kicad.sh") == count
        assert "add-apt-repository --yes ppa:kicad/kicad-10.0-releases" not in workflow

    benchmark_workflow = Path(".github/workflows/quality-benchmark.yml").read_text(encoding="utf-8")
    benchmark = benchmark_workflow[
        benchmark_workflow.index("      - name: Install simulation runtime") : benchmark_workflow.index(
            "      - name: Run simulation-backed sign-off evidence gate"
        )
    ]
    assert "bash scripts/ci_install_kicad.sh ngspice" in benchmark
    assert "sudo apt-get update" not in benchmark
    assert "sudo apt-get install --no-install-recommends -y ngspice" not in benchmark


def test_signed_ubuntu_mirror_failover_is_ci_only(tmp_path: Path) -> None:
    """Fail closed locally; in CI, apt uses the distro keyring on pinned mirrors."""
    script = Path("scripts/ci_install_ubuntu_packages.sh").read_text(encoding="utf-8")
    assert "ubuntu-archive-keyring.gpg" in script
    assert "signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg" in script
    assert "https://mirrors.mit.edu/ubuntu" in script
    assert "https://mirrors.kernel.org/ubuntu" in script
    assert "APT::Update::Error-Mode=any" in script
    assert "trusted=yes" not in script and "allow-unauthenticated" not in script
    assert "Dir::Etc::sourceparts=-" in script
    assert "GITHUB_ACTIONS" in script

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo = fake_bin / "sudo"
    sudo.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$MOCK_SUDO_LOG"\n'
        'if [[ "$*" == *"APT::Update::Error-Mode=any update"* && '
        '"$*" != *"Dir::Etc::sourcelist="* ]]; then exit 1; fi\n',
        encoding="utf-8",
    )
    sudo.chmod(0o755)

    for github_ci, should_succeed in (("false", False), ("true", True)):
        log = tmp_path / "sudo.log"
        log.write_text("", encoding="utf-8")
        completed = subprocess.run(
            ["bash", "scripts/ci_install_ubuntu_packages.sh", "desktop-file-utils"],
            env={
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "MOCK_SUDO_LOG": str(log),
                "GITHUB_ACTIONS": github_ci,
            },
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert (completed.returncode == 0) is should_succeed, completed.stderr
        calls = log.read_text(encoding="utf-8")
        assert "APT::Update::Error-Mode=any update" in calls
        assert ("Dir::Etc::sourcelist=" in calls) is should_succeed
        if should_succeed:
            assert "desktop-file-utils" in calls
            assert "signed mirror" in completed.stdout


def test_kicad_appimage_and_utility_jobs_share_signed_ubuntu_install_helper() -> None:
    assert 'exec bash scripts/ci_install_ubuntu_packages.sh "$@"' in Path("scripts/ci_install_kicad.sh").read_text(
        encoding="utf-8"
    )
    assert 'bash scripts/ci_install_ubuntu_packages.sh "${native_packages[@]}"' in Path(
        "scripts/ci_install_kicad_appimage.sh"
    ).read_text(encoding="utf-8")


def test_simulation_install_does_not_require_kicad_ppa(tmp_path: Path) -> None:
    """Run the real installer with only sudo mocked; no host packages are changed."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo = fake_bin / "sudo"
    sudo.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$MOCK_SUDO_LOG"\n',
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "MOCK_SUDO_LOG": str(tmp_path / "sudo.log")}
    installer = "scripts/ci_install_kicad.sh"

    for packages, expected_ppa in ((["ngspice"], False), (["desktop-file-utils"], False), (["kicad", "ngspice"], True)):
        (tmp_path / "sudo.log").write_text("", encoding="utf-8")
        completed = subprocess.run(
            ["bash", installer, *packages],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert completed.returncode == 0, completed.stderr
        calls = (tmp_path / "sudo.log").read_text(encoding="utf-8")
        assert ("add-apt-repository" in calls) is expected_ppa
        assert "apt-get" in calls and "install" in calls
        assert packages[-1] in calls


def test_issue35_native_oracle_uses_matching_kicad_cli_and_python_modes() -> None:
    """The signed AppImage CI mode must not demand absent /usr/bin KiCad."""
    script = Path("scripts/issue35_native_grid_oracle.sh")
    source = script.read_text(encoding="utf-8")
    assert 'case "${ZAPTRACE_KICAD_PYTHON:-}" in' in source
    assert "readonly CLI=/usr/local/bin/kicad-cli" in source
    assert "readonly PYTHON=/usr/local/bin/kicad-python" in source
    assert "readonly CLI=/usr/bin/kicad-cli" in source
    assert "readonly PYTHON=/usr/bin/python3" in source
    assert '"$PCBNEW_VERSION" == "$KICAD_VERSION"' in source
    assert subprocess.run(["bash", "-n", str(script)], check=False, capture_output=True).returncode == 0
    invalid = subprocess.run(
        ["bash", str(script)],
        env={**os.environ, "ZAPTRACE_KICAD_PYTHON": "unsupported"},
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert invalid.returncode == 2
    assert "Unsupported KiCad Python install mode" in invalid.stderr


def test_kicad_official_appimage_ci_selection_is_pinned_and_scoped(tmp_path: Path) -> None:
    """Keep original PPA behavior unless a KiCad-requiring CI step opts in."""
    installer = Path("scripts/ci_install_kicad_appimage.sh").read_text(encoding="utf-8")
    router = Path("scripts/ci_install_kicad.sh").read_text(encoding="utf-8")
    assert "KICAD_CI_INSTALL_METHOD:-apt" in router
    assert 'exec bash scripts/ci_install_kicad_appimage.sh "$@"' in router
    assert "10.0.8" in installer
    assert "abb59cee9f9782736c1b9a92e3ab08b31320ee01d72a6f9442a07fdef71b87d0" in installer
    assert "4dfc6a52f89aa072d206e466a2a1de4c5ef5975d7ef49da24e4d4db0bb40ba3b" in installer
    assert "RWSyix0AVvjWQGZChX64ywBpE5XqV1Eg+ZXYHR3Y27md9EoZ0AtVr9i9" in installer
    assert "mirrors.mit.edu/kicad/appimage/stable" in installer
    assert "mirror.nju.edu.cn/kicad/appimage/stable" in installer
    assert "minisign -Vm" in installer
    assert "sha256sum --check" in installer
    assert "--appimage-extract" in installer
    assert "kicad-cli version" in installer
    assert "import pcbnew; print(pcbnew.Version())" in installer
    assert 'assert pcbnew.Version() == "10.0.8"' in installer
    assert "ZAPTRACE_KICAD_PYTHON=appimage" in installer
    for path in (
        "scripts/review_studio_local_server.py",
        "scripts/review_studio_native_copper_bundle.py",
        "tests/test_review_studio_pcb_eco.py",
        "tests/test_review_studio_schematic_pcb_parity.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert "ZAPTRACE_KICAD_PYTHON" in source
        assert "/usr/local/bin/kicad-python" in source
        assert "/usr/bin/python3" in source
    assert "trusted=yes" not in installer
    assert "allow-unauthenticated" not in installer

    for path, step_name, invocation in (
        (".github/workflows/quality.yml", "Install KiCad 10 CLI", "kicad ngspice"),
        (".github/workflows/quality-test-lanes.yml", "Install external test tools", "kicad ngspice"),
        (".github/workflows/release.yml", "Run Python quality gates", "kicad ngspice"),
        (".github/actions/kicad-oracle/action.yml", "Install KiCad 10 CLI", "kicad"),
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert source.count("KICAD_CI_INSTALL_METHOD:") == 1
        assert source.index(step_name) < source.index('KICAD_CI_INSTALL_METHOD: "appimage"')
        assert f"bash scripts/ci_install_kicad.sh {invocation}" in source

    completed = subprocess.run(
        ["bash", "scripts/ci_install_kicad.sh", "ngspice"],
        env={**os.environ, "KICAD_CI_INSTALL_METHOD": "invalid"},
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 2
    assert "Unsupported KiCad CI install method" in completed.stderr

    completed = subprocess.run(
        ["bash", "scripts/ci_install_kicad_appimage.sh", "ngspice"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 2
    assert "Missing requested KiCad package" in completed.stderr


def test_kicad_ppa_pinned_public_signing_key() -> None:
    import shutil

    key = Path("security/kicad-10-ppa-signing-key.asc")
    assert key.is_file()
    if not shutil.which("gpg"):
        pytest.skip("GPG is needed for verifying the pinned public signing key")
    result = subprocess.run(
        ["gpg", "--batch", "--show-keys", "--with-colons", str(key)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    fingerprints = [line.split(":")[9] for line in result.stdout.splitlines() if line.startswith("fpr:")]
    assert fingerprints[0] == "FDA854F61C4D0D9572BB95E5245D5502FAD7A805"


def test_kicad_ppa_api_failure_uses_verified_apt_signed_by_fallback(tmp_path: Path) -> None:
    """No real root commands run; verify the fallback preserves APT signature checks."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo = fake_bin / "sudo"
    sudo.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$MOCK_SUDO_LOG"\n'
        'if [[ "$*" == *"add-apt-repository"* ]]; then exit 1; fi\n'
        'if [[ "$1" == "tee" ]]; then cat >/dev/null; fi\n',
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    sleep = fake_bin / "sleep"
    sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)
    log = tmp_path / "sudo.log"
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "MOCK_SUDO_LOG": str(log)}
    result = subprocess.run(
        ["bash", "scripts/ci_install_kicad.sh", "kicad", "ngspice"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8")
    assert calls.count("add-apt-repository") == 3
    assert "install -D -m 0644 security/kicad-10-ppa-signing-key.asc" in calls
    assert "kicad-ubuntu-kicad-10_0-releases-" in calls
    assert "apt-get" in calls and "install" in calls
    assert "Configuring KiCad 10 PPA using pre-verified fingerprint" in result.stdout
    script = Path("scripts/ci_install_kicad.sh").read_text(encoding="utf-8")
    assert "Signed-By: /usr/share/keyrings/zaptrace-kicad-10-ppa.asc" in script
    assert "trusted=yes" not in script
    assert "allow-insecure-repositories" not in script


def test_get_tool_requirements_rejects_unknown_role() -> None:
    with pytest.raises(ValueError, match="unsupported environment role"):
        ci_validation_environment.get_tool_requirements("invalid-role")
    with pytest.raises(ValueError, match="unsupported environment role"):
        ci_validation_environment.build_report(environment_role="invalid-role")


def test_ngspice_absent_in_developer_mode_is_optional_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_validation_toolchain(monkeypatch, ngspice="missing")

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
    install_fake_validation_toolchain(monkeypatch, ngspice="missing")

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
    install_fake_validation_toolchain(monkeypatch, ngspice="present")

    for role in ("developer", "authoritative-release", "diagnostic-only"):
        report = ci_validation_environment.build_report(environment_role=role)
        assert report["passed"] is True
        assert "ngspice" not in report["blocking_tools"]
        assert "ngspice" not in report["warning_tools"]
        ngspice_tool = next(t for t in report["tools"] if t["name"] == "ngspice")
        assert ngspice_tool["status"] == "ok"
        assert ngspice_tool["version"] == "ngspice-42"


def test_ngspice_execution_failure_in_developer_mode_vs_strict_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_validation_toolchain(monkeypatch, ngspice="error")

    dev_report = ci_validation_environment.build_report(environment_role="developer")
    assert dev_report["passed"] is True
    assert "ngspice" in dev_report["warning_tools"]
    assert "ngspice" not in dev_report["blocking_tools"]
    ngspice_dev = next(t for t in dev_report["tools"] if t["name"] == "ngspice")
    assert ngspice_dev["status"] == "optional-failed"

    rel_report = ci_validation_environment.build_report(environment_role="authoritative-release")
    assert rel_report["passed"] is False
    assert "ngspice" in rel_report["blocking_tools"]
    ngspice_rel = next(t for t in rel_report["tools"] if t["name"] == "ngspice")
    assert ngspice_rel["status"] == "failed"


def test_validation_environment_cli_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_validation_toolchain(monkeypatch, ngspice="missing")

    exit_code_dev = ci_validation_environment.main(["--role", "developer", "--strict"])
    assert exit_code_dev == 0

    exit_code_rel = ci_validation_environment.main(["--role", "authoritative-release", "--strict"])
    assert exit_code_rel == 1
