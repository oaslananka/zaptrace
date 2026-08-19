"""Generated documentation contracts for the public tool security policy."""

from __future__ import annotations

import json

from scripts.generate_mcp_docs import DOC_PATH, generate
from scripts.generate_tool_policy_matrix import MATRIX_PATH
from scripts.generate_tool_policy_matrix import generate as generate_policy_matrix
from zaptrace.agent._tool_impls import TOOL_REGISTRY


def test_mcp_tool_reference_exposes_capability_and_path_policy() -> None:
    generated = generate()
    assert "**Required capability:** `release-export`" in generated
    assert "workspace / output / may-create" in generated
    assert "| `approval_id` | `string` |" in generated
    assert DOC_PATH.read_text(encoding="utf-8") == generated


def test_tool_policy_matrix_is_complete_and_current() -> None:
    assert MATRIX_PATH.exists(), "generate docs/reports/tool-policy-matrix.json"
    current = MATRIX_PATH.read_text(encoding="utf-8")
    assert current == generate_policy_matrix()
    payload = json.loads(current)
    assert payload["schema_version"] == "tool-policy-matrix-v1"
    assert payload["tool_count"] == len(TOOL_REGISTRY) == 93
    tools = payload["tools"]
    assert [tool["name"] for tool in tools] == sorted(TOOL_REGISTRY)
    assert all(tool["capability"] == TOOL_REGISTRY[tool["name"]]["capability"] for tool in tools)

    manufacture = next(tool for tool in tools if tool["name"] == "synthesize_board_manufacture")
    assert manufacture["capability"] == "release-export"
    assert manufacture["path_parameters"] == [
        {
            "access": "output",
            "must_exist": False,
            "name": "output_dir",
            "root": "workspace",
        }
    ]

    drc = next(tool for tool in tools if tool["name"] == "drc_run")
    assert drc["path_parameters"] == [
        {
            "access": "input",
            "must_exist": True,
            "name": "fab_profile",
            "path_suffixes": [".yaml", ".yml"],
            "root": "workspace",
        }
    ]
