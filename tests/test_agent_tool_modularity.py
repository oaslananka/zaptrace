"""Contract and maintainability gates for the domain-split agent tool surface."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import zaptrace.agent._tool_impls as facade
from zaptrace.agent._tool_impls import TOOL_REGISTRY, list_tools

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "zaptrace/agent/tool_impls"
MODULARITY_POLICY = ROOT / "config/agent-tool-modularity.json"
REGISTRY_CONTRACT = ROOT / "config/agent-tool-registry-contract.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _internal_import_graph() -> dict[str, set[str]]:
    module_names = {path.stem for path in PACKAGE.glob("*.py")}
    graph: dict[str, set[str]] = {name: set() for name in module_names}
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level != 1 or not node.module:
                continue
            target = node.module.split(".", maxsplit=1)[0]
            if target in module_names:
                graph[path.stem].add(target)
    return graph


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visited: set[str] = set()
    active: list[str] = []
    active_set: set[str] = set()

    def visit(node: str) -> list[str] | None:
        if node in active_set:
            start = active.index(node)
            return [*active[start:], node]
        if node in visited:
            return None
        active.append(node)
        active_set.add(node)
        for dependency in sorted(graph[node]):
            cycle = visit(dependency)
            if cycle:
                return cycle
        active.pop()
        active_set.remove(node)
        visited.add(node)
        return None

    for node in sorted(graph):
        cycle = visit(node)
        if cycle:
            return cycle
    return None


def test_registry_contract_matches_pre_refactor_baseline() -> None:
    expected = _load_json(REGISTRY_CONTRACT)
    actual = {
        "schema": "zaptrace-agent-tool-registry-contract-v1",
        "tool_count": len(TOOL_REGISTRY),
        "tool_order": list(TOOL_REGISTRY),
        "tools": list_tools(),
    }
    assert actual == expected


def test_facade_reexports_every_registry_callable_by_identity() -> None:
    assert len(TOOL_REGISTRY) == 93
    for tool_name, definition in TOOL_REGISTRY.items():
        facade_name = f"tool_{tool_name}"
        assert getattr(facade, facade_name) is definition["fn"]
        assert definition["fn"].__module__.startswith("zaptrace.agent.tool_impls.")
        assert definition["fn"].__module__ != "zaptrace.agent._tool_impls"


def test_all_implementation_modules_respect_line_budget() -> None:
    policy = _load_json(MODULARITY_POLICY)
    limit = policy["max_python_lines"]
    violations = {}
    for relative in policy["implementation_modules"]:
        line_count = len((ROOT / relative).read_text(encoding="utf-8").splitlines())
        if line_count > limit:
            violations[relative] = line_count
    assert not violations, f"agent tool implementation modules exceed {limit} lines: {violations}"


def test_internal_tool_implementation_import_graph_is_acyclic() -> None:
    graph = _internal_import_graph()
    assert _find_cycle(graph) is None, graph


def test_domain_modules_do_not_import_compatibility_facade() -> None:
    offenders = []
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "zaptrace.agent._tool_impls":
                offenders.append(path.name)
            if isinstance(node, ast.Import) and any(alias.name == "zaptrace.agent._tool_impls" for alias in node.names):
                offenders.append(path.name)
    assert not offenders


def test_registry_fragments_remain_declarative() -> None:
    offenders = {}
    for path in PACKAGE.glob("registry_*.py"):
        if path.name == "registry_shared.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        if functions:
            offenders[path.name] = functions
    assert not offenders


def test_invalid_model_registry_json_remains_fail_safe() -> None:
    result = facade.tool_kicad_3d_model_coverage("(kicad_pcb)", model_registry_json="not-json")

    assert result["schema"] == "model-coverage-v1"
    assert result["total"] == 0
    assert result["complete"] is True
