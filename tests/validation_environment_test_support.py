"""Shared fake validation-toolchain support for CLI and policy tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

import pytest

from scripts import ci_validation_environment

_VERSION_OUTPUTS = {
    "python3": "Python 3.12.0",
    "rustc": "rustc 1.91.0",
    "cargo": "cargo 1.91.0",
    "kicad-cli": "kicad-cli 9.0.0",
    "docker": "Docker version 27.0.0",
    "uv": "uv 0.5.0",
    "ngspice": "ngspice-42",
}


def install_fake_validation_toolchain(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ngspice: Literal["missing", "present", "error"] = "missing",
) -> None:
    """Install a deterministic fake host toolchain for validation tests."""

    def fake_which(executable: str) -> str | None:
        if executable == "ngspice" and ngspice == "missing":
            return None
        return f"/usr/bin/{executable}"

    def fake_run(
        path: str,
        req: ci_validation_environment.ToolRequirement,
    ) -> subprocess.CompletedProcess[str]:
        if req.name == "ngspice" and ngspice == "error":
            return subprocess.CompletedProcess([path], 1, "", "simulation driver error")
        name = Path(path).name
        return subprocess.CompletedProcess([path], 0, _VERSION_OUTPUTS.get(name, "1.0.0"), "")

    monkeypatch.setattr(ci_validation_environment, "_which", fake_which)
    monkeypatch.setattr(ci_validation_environment, "_run_tool_version", fake_run)
