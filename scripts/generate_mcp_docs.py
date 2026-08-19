#!/usr/bin/env python3
"""Regenerate docs/mcp/tools-reference.md from TOOL_REGISTRY.

Usage:
    python scripts/generate_mcp_docs.py

The output is written to docs/mcp/tools-reference.md.
Run this whenever TOOL_REGISTRY changes, and commit the updated file.
"""

from __future__ import annotations

from pathlib import Path

from zaptrace.agent._tool_impls import list_tools

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = REPO_ROOT / "docs" / "mcp" / "tools-reference.md"

HEADER = """# MCP Tools Reference

> **Auto-generated from `TOOL_REGISTRY`**
> Run `python scripts/generate_mcp_docs.py` to regenerate.
> Total tools: {count}

---

"""


def _format_path_policy(info: dict) -> str:
    policy = info.get("path_policy")
    if not policy:
        return "—"
    existence = "must-exist" if policy["must_exist"] else "may-create"
    parts = [policy["root"], policy["access"], existence]
    if path_suffixes := policy.get("path_suffixes"):
        parts.append(f"suffixes={','.join(path_suffixes)}")
    return " / ".join(parts)


def _param_table(params: dict) -> str:
    if not params:
        return "*No parameters*"
    rows = []
    for name, info in params.items():
        ptype = info.get("type", "any")
        desc = info.get("description", "")
        rows.append(f"| `{name}` | `{ptype}` | {desc} | {_format_path_policy(info)} |")
    header = "| Parameter | Type | Description | Path policy |\n|-----------|------|-------------|-------------|\n"
    return header + "\n".join(rows)


def _tool_category(name: str) -> str:
    category_rules = (
        (("design_",), (), "Design I/O"),
        (("synthesize_", "list_synthesis_"), (), "Synthesis"),
        (("erc_",), (), "Electrical Rule Checking (ERC)"),
        (("drc_",), (), "Design Rule Checking (DRC)"),
        (("place_",), (), "Placement"),
        (("route_",), ("_route_smart",), "Routing"),
        (("library_", "footprint_"), (), "Library & Footprints"),
        (("export_",), (), "Export"),
        (("pipeline_",), (), "Pipeline"),
        (("board_",), (), "Board"),
        (("schematic_",), (), "Schematic"),
        (("component_", "patch_suggest"), (), "Component Operations"),
        (("proof_",), (), "Proof Pack"),
    )
    for prefixes, suffixes, category in category_rules:
        if name.startswith(prefixes) or name.endswith(suffixes):
            return category
    return "Other"


def _group_tools(tools: list[dict]) -> dict[str, list[dict]]:
    categories: dict[str, list[dict]] = {}
    for tool in tools:
        categories.setdefault(_tool_category(tool["name"]), []).append(tool)
    return categories


def _tool_reference_lines(tool: dict) -> list[str]:
    return [
        f"### `{tool['name']}`\n",
        f"{tool['description']}\n",
        f"**Required capability:** `{tool['capability']}`\n",
        "**Parameters:**\n",
        _param_table(tool.get("params", {})),
        "",
    ]


def _error_handling_lines() -> list[str]:
    return [
        "## Error Handling\n",
        "All tools return errors as structured JSON envelopes:\n",
        "```json\n"
        "{\n"
        '  "error": true,\n'
        '  "code": "TOOL_ERROR",\n'
        '  "message": "Human-readable description",\n'
        '  "details": {}\n'
        "}\n"
        "```\n",
        "Common error codes:\n",
        "- `DESIGN_NOT_FOUND` — Design name not found in session\n",
        "- `INVALID_PARAMETER` — Parameter out of range or invalid\n",
        "- `EXPORT_FAILED` — Export process failed\n",
    ]


def generate() -> str:
    tools = list_tools()
    lines = [HEADER.format(count=len(tools))]
    for category, category_tools in sorted(_group_tools(tools).items()):
        lines.append(f"## {category}\n")
        for tool in category_tools:
            lines.extend(_tool_reference_lines(tool))
        lines.append("---\n")
    lines.extend(_error_handling_lines())
    return "\n".join(lines)


def main() -> None:
    import sys

    output = generate()
    is_check = "--check" in sys.argv
    if is_check:
        current = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else ""
        if current != output:
            print(f"ERROR: {DOC_PATH} is stale. Run `python scripts/generate_mcp_docs.py` to regenerate.")
            sys.exit(1)
        print(f"OK: {DOC_PATH} is up to date ({output.count('### `')} tools)")
    else:
        DOC_PATH.write_text(output, encoding="utf-8")
        print(f"Wrote {DOC_PATH} ({len(output)} chars, {output.count('### `')} tools)")


if __name__ == "__main__":
    main()
