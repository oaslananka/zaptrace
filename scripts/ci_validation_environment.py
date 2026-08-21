"""Validate local toolchain parity for ZapTrace release gates.

This script checks whether a host has the tools required to reproduce the
repository's quality, test, Rust, KiCad, and simulation gates. It runs in the
locked project environment so the shared evidence-identity schema is available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.evidence.identity import EvidenceMode, capture_evidence_identity  # noqa: E402
from zaptrace.security.temporary import private_subprocess_environment  # noqa: E402

AUTHORITATIVE_RELEASE_PATH = ".github/workflows/release.yml"
UV_LOCK_PATH = "uv.lock"
SUPPORTED_DEPENDENCIES = frozenset({"fastmcp", "mcp"})
EVIDENCE_SOURCE_INPUTS = (
    "pyproject.toml",
    UV_LOCK_PATH,
    "scripts/ci_validation_environment.py",
    ".github/workflows/quality.yml",
    ".github/workflows/release.yml",
)


@dataclass(frozen=True)
class ToolRequirement:
    name: str
    executable: str
    version_args: tuple[str, ...] = ("--version",)
    required: bool = True
    min_major: int | None = None
    min_minor: int | None = None
    gate: str = "quality"
    install_hint: str = ""


TOOL_REQUIREMENTS: tuple[ToolRequirement, ...] = (
    ToolRequirement(
        name="Python",
        executable="python3",
        min_major=3,
        min_minor=12,
        gate="quality/test/build",
        install_hint="Install Python 3.12+ or use `uv python install 3.12`.",
    ),
    ToolRequirement(
        name="uv",
        executable="uv",
        gate="dependency/install/build",
        install_hint="Install uv from Astral, then run `uv lock --check` and the documented locked sync.",
    ),
    ToolRequirement(
        name="Ruff",
        executable="ruff",
        required=False,
        gate="quality",
        install_hint="Run through `uv run ruff ...` after `uv sync`; a global binary is optional.",
    ),
    ToolRequirement(
        name="Pyright",
        executable="pyright",
        required=False,
        gate="typecheck",
        install_hint="Run through `uv run pyright` after `uv sync`; a global binary is optional.",
    ),
    ToolRequirement(
        name="Rust compiler",
        executable="rustc",
        min_major=1,
        min_minor=91,
        gate="rust-extension",
        install_hint="Install Rust 1.91+ or ensure `/usr/lib/rust-1.91/bin` is on PATH.",
    ),
    ToolRequirement(
        name="Cargo",
        executable="cargo",
        min_major=1,
        min_minor=91,
        gate="rust-extension",
        install_hint="Install Cargo 1.91+ or ensure `/usr/lib/rust-1.91/bin` is on PATH.",
    ),
    ToolRequirement(
        name="Docker",
        executable="docker",
        gate="container-build/release",
        install_hint="Install Docker Engine from the supported vendor repository.",
    ),
    ToolRequirement(
        name="Docker Buildx",
        executable="docker",
        version_args=("buildx", "version"),
        gate="container-build/release",
        install_hint="Install the Docker Buildx plugin used by GitHub-hosted release runners.",
    ),
    ToolRequirement(
        name="maturin",
        executable="maturin",
        required=False,
        gate="rust-extension/build",
        install_hint="Run through `uv run maturin ...` after dependency sync; a global binary is optional.",
    ),
    ToolRequirement(
        name="KiCad CLI",
        executable="kicad-cli",
        min_major=9,
        min_minor=0,
        gate="external-oracle",
        install_hint="Install KiCad 9+ for release validation and KiCad oracle evidence.",
    ),
    ToolRequirement(
        name="ngspice",
        executable="ngspice",
        gate="simulation/release",
        install_hint=(
            "Install ngspice (`sudo apt-get install ngspice` or `brew install ngspice`) "
            "for simulation sign-off gates; optional in developer mode."
        ),
    ),
)

VALID_ENVIRONMENT_ROLES: frozenset[str] = frozenset({"authoritative-release", "diagnostic-only", "developer"})


def get_tool_requirements(
    environment_role: str = "authoritative-release",
) -> tuple[ToolRequirement, ...]:
    if environment_role not in VALID_ENVIRONMENT_ROLES:
        raise ValueError(f"unsupported environment role: {environment_role}")
    if environment_role in {"developer", "diagnostic-only"}:
        return tuple(
            replace(
                req,
                required=False,
                gate="simulation/developer-optional" if req.name == "ngspice" else req.gate,
                install_hint=(
                    "Install ngspice (`sudo apt-get install ngspice` or `brew install ngspice`) "
                    "for simulation sign-off gates; optional in developer mode."
                    if req.name == "ngspice"
                    else req.install_hint
                ),
            )
            if req.name == "ngspice"
            else req
            for req in TOOL_REQUIREMENTS
        )
    return TOOL_REQUIREMENTS


def _first_version_number(text: str) -> tuple[int, int] | None:
    match = re.search(r"(\d{1,4})\.(\d{1,4})", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _candidate_paths(executable: str) -> list[str]:
    candidates: list[str] = []
    if executable in {"rustc", "cargo"}:
        for rust_dir in sorted(Path("/usr/lib").glob("rust-*/bin"), reverse=True):
            candidate = rust_dir / executable
            if candidate.exists():
                candidates.append(str(candidate))
    path = shutil.which(executable)
    if path:
        candidates.append(path)
    local = Path.home() / ".local" / "bin" / executable
    if local.exists():
        candidates.append(str(local))
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _which(executable: str) -> str | None:
    candidates = _candidate_paths(executable)
    return candidates[0] if candidates else None


def _tool_result(req: ToolRequirement, path: str | None) -> dict[str, Any]:
    return {
        "name": req.name,
        "executable": req.executable,
        "gate": req.gate,
        "required": req.required,
        "found": bool(path),
        "path": path or "",
        "version": "",
        "status": "missing" if req.required else "optional-missing",
        "install_hint": req.install_hint,
    }


def _run_tool_version(path: str, req: ToolRequirement) -> subprocess.CompletedProcess[str]:
    with private_subprocess_environment() as env:
        return subprocess.run(
            [path, *req.version_args],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )


def _apply_minimum_version(
    req: ToolRequirement,
    text: str,
    result: dict[str, Any],
) -> bool:
    if req.min_major is None:
        return True
    parsed = _first_version_number(text)
    if parsed is None:
        result.update({"status": "failed", "error": "could not parse version"})
        return False
    major, minor = parsed
    minimum_minor = req.min_minor or 0
    if (major, minor) < (req.min_major, minimum_minor):
        result.update({"status": "too-old", "required_version": f">={req.min_major}.{minimum_minor}"})
        return False
    return True


def check_tool(req: ToolRequirement) -> dict[str, Any]:
    path = _which(req.executable)
    result = _tool_result(req, path)
    if path is None:
        return result

    try:
        proc = _run_tool_version(path, req)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result.update({"status": "failed", "error": str(exc)})
        return result

    text = (proc.stdout or proc.stderr).strip()
    result.update({"version": text, "exit_code": proc.returncode})
    if proc.returncode != 0:
        result["status"] = "failed" if req.required else "optional-failed"
        return result
    if not _apply_minimum_version(req, text, result):
        return result
    result["status"] = "ok"
    return result


def _lock_sha256(root: Path) -> str:
    return hashlib.sha256((root / UV_LOCK_PATH).read_bytes()).hexdigest()


def _locked_dependencies(root: Path) -> dict[str, str]:
    data = tomllib.loads((root / UV_LOCK_PATH).read_text(encoding="utf-8"))
    return {
        package["name"]: package["version"]
        for package in data.get("package", [])
        if package.get("name") in SUPPORTED_DEPENDENCIES
    }


def _policy_sha256(
    *,
    environment_role: str,
    commands: list[str],
    requirements: tuple[ToolRequirement, ...] = TOOL_REQUIREMENTS,
) -> str:
    payload = {
        "environment_role": environment_role,
        "authoritative_release_path": AUTHORITATIVE_RELEASE_PATH,
        "commands": commands,
        "requirements": [
            {
                "name": item.name,
                "executable": item.executable,
                "version_args": item.version_args,
                "required": item.required,
                "min_major": item.min_major,
                "min_minor": item.min_minor,
                "gate": item.gate,
            }
            for item in requirements
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_report(
    *,
    environment_role: str = "authoritative-release",
    root: Path = ROOT,
) -> dict[str, Any]:
    if environment_role not in VALID_ENVIRONMENT_ROLES:
        raise ValueError(f"unsupported environment role: {environment_role}")
    requirements = get_tool_requirements(environment_role)
    tools = [check_tool(req) for req in requirements]
    identity = capture_evidence_identity(
        root=root,
        mode=EvidenceMode.SNAPSHOT,
        source_inputs=EVIDENCE_SOURCE_INPUTS,
        toolchain={str(tool["name"]): str(tool.get("version") or tool.get("path") or tool["status"]) for tool in tools},
    )
    blockers = [tool for tool in tools if tool["required"] and tool["status"] not in {"ok"}]
    warnings = [tool for tool in tools if not tool["required"] and tool["status"] not in {"ok"}]
    commands = [
        "uv lock --check",
        "uv sync --locked --all-extras --all-groups",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run pyright",
        "uv run pytest --cov=zaptrace --cov-report=term-missing",
        "cargo fmt --manifest-path zaptrace_core/Cargo.toml --check",
        "cargo clippy --manifest-path zaptrace_core/Cargo.toml -- -D warnings",
        "cargo test --manifest-path zaptrace_core/Cargo.toml",
        "uv run python scripts/ci_kicad_oracle.py --strict-skips --output kicad-oracle-summary.json",
        (
            "uv run python scripts/ci_generated_board_release_gate.py "
            "--strict --output generated-board-release-gate.json"
        ),
        "uv run python scripts/ci_kicad_roundtrip_scorecard.py --strict --output kicad-roundtrip-scorecard.json",
    ]
    return {
        "schema_version": "2.0",
        "evidence_identity": identity.model_dump(mode="json"),
        "gate_id": "validation-environment-v1",
        "passed": not blockers,
        "environment_role": environment_role,
        "authoritative_release_path": AUTHORITATIVE_RELEASE_PATH,
        "scoped_validator_role": "diagnostic-only",
        "lock_sha256": _lock_sha256(root),
        "locked_dependencies": _locked_dependencies(root),
        "policy_sha256": _policy_sha256(
            environment_role=environment_role, commands=commands, requirements=requirements
        ),
        "tools": tools,
        "blocking_tool_count": len(blockers),
        "warning_tool_count": len(warnings),
        "blocking_tools": [tool["name"] for tool in blockers],
        "warning_tools": [tool["name"] for tool in warnings],
        "recommended_release_commands": commands,
        "non_claims": [
            "environment parity does not prove board correctness",
            "tool availability does not imply fabrication readiness",
        ],
    }


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"Validation environment: {'PASS' if report['passed'] else 'FAIL'}",
        f"Blocking tools: {report['blocking_tool_count']}",
        f"Warnings: {report['warning_tool_count']}",
    ]
    for tool in report["tools"]:
        marker = "OK" if tool["status"] == "ok" else "!!"
        detail = tool.get("version") or tool.get("path") or "not found"
        lines.append(f"{marker} {tool['name']}: {tool['status']} ({detail})")
        if tool["status"] != "ok" and tool.get("install_hint"):
            lines.append(f"   hint: {tool['install_hint']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate ZapTrace release-gate toolchain parity")
    parser.add_argument("--output", type=Path, help="Write JSON evidence to this path")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    parser.add_argument(
        "--role",
        choices=("authoritative-release", "diagnostic-only", "developer"),
        default="authoritative-release",
        help="Declare whether this host may originate release evidence",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero if required tools are missing or too old",
    )
    args = parser.parse_args(argv)

    report = build_report(environment_role=args.role)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report_json(report), encoding="utf-8")
    print(report_json(report) if args.json else render_text(report), end="")
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
