from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_build_system_is_hatchling() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build_system = pyproject.get("build-system", {})

    assert build_system.get("build-backend") == "hatchling.build"
    assert "hatchling" in build_system.get("requires", [])


def test_pyproject_maturin_configuration_includes_data_and_core() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    maturin = pyproject.get("tool", {}).get("maturin", {})

    assert maturin.get("manifest-path") == "zaptrace_core/Cargo.toml"
    assert maturin.get("module-name") == "zaptrace._core"
    assert maturin.get("python-source") == "."
    includes = maturin.get("include", [])
    assert any(
        isinstance(inc, dict) and inc.get("path") == "data/**/*" and "wheel" in inc.get("format", [])
        for inc in includes
    ), "maturin must include data/**/* in wheel format"


def test_taskfile_defines_canonical_build_paths() -> None:
    taskfile_content = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")
    tasks = yaml.safe_load(taskfile_content).get("tasks", {})

    assert "build" in tasks
    assert "build-sdist" in tasks
    assert "build-wheel" in tasks
    assert "build-dev" in tasks

    assert any("uv build --sdist" in str(cmd) for cmd in tasks["build-sdist"]["cmds"])
    assert any("maturin build" in str(cmd) for cmd in tasks["build-wheel"]["cmds"])
    assert any("maturin develop" in str(cmd) for cmd in tasks["build-dev"]["cmds"])


def test_cargo_manifest_defines_cdylib_and_pyo3() -> None:
    cargo = tomllib.loads((ROOT / "zaptrace_core" / "Cargo.toml").read_text(encoding="utf-8"))

    assert cargo.get("lib", {}).get("crate-type") == ["cdylib"]
    assert "pyo3" in cargo.get("dependencies", {})
