from __future__ import annotations

import tomllib
from pathlib import Path


def test_registry_distribution_name_is_distinct_while_python_and_cli_names_stay_stable() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))

    assert project["name"] == "zaptrace-eda"
    assert {package["name"] for package in lock["package"] if package.get("source", {}).get("editable") == "."} == {
        "zaptrace-eda"
    }
    assert set(project["scripts"]) == {"zaptrace", "zaptrace-mcp", "zaptrace-mcp-http", "zaptrace-api"}
    assert Path("zaptrace/__init__.py").is_file()
    for workflow_path in (Path(".github/workflows/quality.yml"), Path(".github/workflows/release.yml")):
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "printf 'zaptrace @" not in workflow
        assert "zaptrace-eda @ file://" in workflow
