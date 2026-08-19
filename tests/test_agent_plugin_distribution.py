from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
MCP_CONFIG = ROOT / ".mcp.json"
REGISTRY = ROOT / "config" / "agent-tool-registry-contract.json"
PUBLICATION_DOC = ROOT / "docs" / "agent-plugin-publication.md"


def _skill_front_matter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, block, _ = text.split("---\n", 2)
    result: dict[str, str] = {}
    for line in block.splitlines():
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def test_agent_plugin_manifest_matches_product_contract() -> None:
    manifest = json.loads(PLUGIN.read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert manifest["name"] == "zaptrace"
    assert manifest["version"] == project["version"].replace(".dev", "-dev.")
    assert manifest["$schema"] == "https://anthropic.com/claude-code/plugin.schema.json"
    assert manifest["author"]["url"] == "https://github.com/oaslananka"
    assert len(manifest["skills"]) == 3

    for relative in manifest["skills"]:
        skill_dir = (ROOT / relative.removeprefix("./")).resolve()
        assert skill_dir.is_relative_to(ROOT)
        skill = skill_dir / "SKILL.md"
        assert skill.is_file()
        front_matter = _skill_front_matter(skill)
        assert front_matter["name"] == skill_dir.name
        assert front_matter["description"]


def test_agent_plugin_mcp_config_is_portable_and_secret_free() -> None:
    config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    server = config["mcpServers"]["zaptrace"]

    assert server == {
        "command": "uv",
        "args": ["run", "--project", "${CLAUDE_PLUGIN_ROOT:-.}", "zaptrace-mcp"],
    }
    serialized = json.dumps(config)
    assert "/srv/" not in serialized
    assert "token" not in serialized.lower()
    assert "secret" not in serialized.lower()


def test_agent_plugin_skills_reference_public_tools_only() -> None:
    manifest = json.loads(PLUGIN.read_text(encoding="utf-8"))
    registry_payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    public_tools = {item["name"] for item in registry_payload["tools"]}
    tool_token = re.compile(r"`([a-z][a-z0-9_]+)`")

    referenced: set[str] = set()
    for relative in manifest["skills"]:
        text = (ROOT / relative.removeprefix("./") / "SKILL.md").resolve().read_text(encoding="utf-8")
        referenced.update(token for token in tool_token.findall(text) if "_" in token)

    assert referenced
    assert referenced <= public_tools


def test_publication_plan_keeps_network_and_catalog_activation_bounded() -> None:
    text = PUBLICATION_DOC.read_text(encoding="utf-8")

    assert "Network transports are not part of phase 1" in text
    assert "planned_plugins" in text
    assert "agent-tools" in text
    assert "server identity `zaptrace` and 96 exposed tools" in text
    assert "never represents an autonomous pass as engineering approval" in text
