# MCP Server Quickstart

> **ZapTrace MCP** enables LLMs (Claude, Copilot, Codex, Gemini) to design PCBs through
> the Model Context Protocol. 96 tools are exposed: 93 design tools plus 3 session-administration tools.

---

## 1. Starting the Server

```bash
# Install from source (pre-1.0, not yet on PyPI)
git clone https://github.com/oaslananka/zaptrace.git && cd zaptrace && uv sync --all-extras

# Start MCP server (stdio transport)
uv run zaptrace-mcp

# Optional authenticated loopback HTTP deployment uses the separate entry point.
# See docs/mcp-http-deployment.md before enabling it.
uv run zaptrace-mcp-http
```

## 2. Claude Desktop Configuration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "zaptrace": {
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/zaptrace", "zaptrace-mcp"],
      "env": {}
    }
  }
}
```

## 3. Testing with MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv run --project /absolute/path/to/zaptrace zaptrace-mcp
```

Opens browser UI to test individual tools.

## 4. Available Tools

| Tool | Description |
|------|-------------|
| `design_parse_file` | Parse a design YAML file |
| `design_parse_str` | Parse a YAML string |
| `design_inspect` | Inspect a parsed design |
| `design_list_nets` | List all nets in a design |
| `synthesize_design` | Synthesize from intent |
| `erc_validate` | Run electrical rule checks |
| `drc_run` | Run design rule checks |
| `place_components` | Auto-place all components |
| `route_nets` | Route all nets (MST) |
| `design_route_smart` | Net-class-aware smart routing |
| `export_gerber` | Generate Gerber RS-274X files |
| `export_bom_csv` | Generate BOM as CSV |
| `board_update` | Update board configuration |
| `component_add` | Add a component |
| `footprint_generate` | Generate parametric footprint |
| `proof_run` | Run a Proof Pack |
| *96 tools total* | 93 design tools plus `session_create`, `session_list`, and `session_destroy` |

Full reference: `docs/mcp/tools-reference.md`

For Claude Code plugin packaging, first-phase skills, and marketplace activation gates, see [`docs/agent-plugin-publication.md`](../agent-plugin-publication.md).

## 5. Example Workflow

```
1. design_parse_file("project.yaml")         → load design
2. design_inspect("my_design")               → see what's there
3. place_components("my_design")             → auto-place all components
4. design_route_smart("my_design")           → route with net-class awareness
5. drc_run("my_design")                      → check for violations
6. export_gerber("my_design", "output/")     → generate Gerber files
```
