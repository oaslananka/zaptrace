#!/usr/bin/env python3
"""Generate the deterministic public tool capability and path-policy matrix."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from zaptrace.agent._tool_impls import list_tools

REPO_ROOT = Path(__file__).resolve().parent.parent
MATRIX_PATH = REPO_ROOT / "docs" / "reports" / "tool-policy-matrix.json"


def _path_parameters(params: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name, spec in sorted(params.items()):
        policy = spec.get("path_policy")
        if policy is None:
            continue
        entry: dict[str, Any] = {
            "access": policy["access"],
            "must_exist": policy["must_exist"],
            "name": name,
            "root": policy["root"],
        }
        if path_suffixes := policy.get("path_suffixes"):
            entry["path_suffixes"] = list(path_suffixes)
        entries.append(entry)
    return entries


def build_matrix() -> dict[str, Any]:
    """Return a stable inventory of every public tool security policy."""
    tools = sorted(list_tools(), key=lambda tool: tool["name"])
    return {
        "schema_version": "tool-policy-matrix-v1",
        "policy_artifact": True,
        "evidence_status": "generated-policy-not-runtime-evidence",
        "tool_count": len(tools),
        "tools": [
            {
                "capability": tool["capability"],
                "name": tool["name"],
                "path_parameters": _path_parameters(tool["params"]),
            }
            for tool in tools
        ],
    }


def generate() -> str:
    """Serialize the policy matrix deterministically."""
    return json.dumps(build_matrix(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    output = generate()
    if "--check" in args:
        current = MATRIX_PATH.read_text(encoding="utf-8") if MATRIX_PATH.exists() else ""
        if current != output:
            print(f"ERROR: {MATRIX_PATH} is stale. Run `python scripts/generate_tool_policy_matrix.py`.")
            return 1
        print(f"OK: {MATRIX_PATH} is up to date ({build_matrix()['tool_count']} tools)")
        return 0

    MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
    MATRIX_PATH.write_text(output, encoding="utf-8")
    print(f"Wrote {MATRIX_PATH} ({build_matrix()['tool_count']} tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
