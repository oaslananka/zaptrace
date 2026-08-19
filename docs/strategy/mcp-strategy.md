# MCP Expansion Strategy

> **Status:** Draft
> **Owner:** Core team
> **Last updated:** 2026-06-16
> **Related:** `docs/strategy/current-state-audit.md`, `docs/mcp/`

---

## 1. Current State

ZapTrace ships a FastMCP server with **93 design tools** generated from
`zaptrace.agent._tool_impls.TOOL_REGISTRY`. The generated source of truth is
`docs/mcp/tools-reference.md`. Current categories include:

- **Board:** board updates, net classification, net summaries, board JSON export
- **Component Operations:** patch suggestions and component mutation tools
- **Design I/O:** parse, inspect, diff, export, and session-backed design operations
- **Electrical Rule Checking:** validation, rule listing, and structured results
- **Design Rule Checking:** DRC execution and rule listing
- **Export:** Gerber, Excellon, BOM, KiCad, SVG/report, manufacturing, pick-and-place, proof-related outputs
- **Library & Footprints:** component library search/get/list and footprint generation
- **Pipeline:** end-to-end autopilot runs from design files or intent
- **Placement, Routing, Schematic, Synthesis, Proof Pack:** workflow-specific agent tools

**Gaps identified in audit:**

1. No read-only "preview" tools (e.g., `preview_placement`, `preview_reroute`)
2. No undo/transaction support for multi-step operations
3. No MCP resource definitions (templates, exposed via `resources/`)
4. No MCP prompts for common workflows
5. No streaming/large-file support for export tools
6. No MCP tool categories / discoverability metadata

---

## 2. Strategic Goals

| Goal | Priority | Target |
|------|----------|--------|
| MCP tool discoverability & metadata | P0 | v0.2.0 |
| Transaction/undo support | P0 | v0.2.0 |
| Read-only preview tools | P1 | v0.2.0 |
| MCP resource endpoints | P1 | v0.3.0 |
| MCP workflow prompts | P1 | v0.3.0 |
| Streaming export | P2 | v0.4.0 |
| Multi-user isolation | P2 | v0.5.0 |

---

## 3. Tool Categorization

### Read Tools (safe, no side effects)

- `list_*`, `get_*`, `search_*`, `run_drc`, `run_erc`, `analyze_*`

### Write Tools (modify design state)

- `place_component`, `move_component`, `rotate_component`, `route_net`, `autoroute`, `auto_place`, `auto_route`
- `set_board_shape`, `copper_pour`, `diff_pair_route`

### Export Tools (generate artifacts)

- `export_*`, `write_design`

### Admin Tools (pipeline, cost, advanced)

- `run_sim`, `thermal_analysis`, `cost_analysis`

---

## 4. Transaction / Undo Support

**Problem:** A LLM agent may issue `place_component` → `route_net` → `copper_pour` in sequence. If the copper pour fails, there's no rollback.

**Solution:** Lightweight snapshot-based undo:

```python
class DesignTransaction:
    """Context manager for undoable design operations."""

    def __enter__(self):
        self._snapshot = deepcopy(self._design)
        self._tx_id = str(uuid4())
        return self._tx_id

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._design = self._snapshot  # rollback
        # else commit
```

**MCP tools:**

- `begin_transaction()` → tx_id
- `commit_transaction(tx_id)`
- `rollback_transaction(tx_id)`

**Implementation target:** `zaptrace.mcp.transaction`

---

## 5. MCP Resources

Register design elements as MCP resources for LLM context injection:

```
mcp://zaptrace/design/{design_id}
mcp://zaptrace/component/{component_id}
mcp://zaptrace/net/{net_id}
mcp://zaptrace/template/{template_name}
mcp://zaptrace/library/{category}
```

**Implementation:**

```python
@mcp.resource("design://{design_id}")
def get_design_resource(design_id: str) -> str:
    design = load_design(design_id)
    return design.model_dump_json(indent=2)
```

---

## 6. MCP Prompts (Workflow Templates)

Pre-built prompts that guide LLMs through common PCB workflows:

| Prompt Name | Purpose |
|-------------|---------|
| `new_design` | Create a new PCB from scratch (project → schematic → layout) |
| `auto_design` | End-to-end autopilot pipeline |
| `fix_drc` | Diagnose and fix DRC errors |
| `add_component` | Add a component, find footprint, place, wire |
| `export_all` | Generate all manufacturing outputs |
| `review_design` | Systematic design review checklist |

---

## 7. Implementation Plan

### v0.2.0 (Next release)

1. Add `@mcp.tool` category metadata to all tools (`category: str` field)
2. Implement `zaptrace/mcp/transaction.py` with snapshot undo
3. Add `begin_transaction`, `commit_transaction`, `rollback_transaction`
4. Add `preview_placement`, `preview_route` read-only tools

### v0.3.0

1. Register MCP resources for design, components, nets
2. Implement 3 MCP workflow prompts (`new_design`, `fix_drc`, `auto_design`)
3. Add tool usage examples to tool descriptions
4. Publish `zaptrace-mcp` PyPI extras

### v0.4.0+

1. Streaming export via async generators
2. Multi-user design isolation
3. MCP server auto-discovery via mcp.json
4. Plugin-based tool extensions (see `docs/strategy/plugin-strategy.md`)

---

## 8. Testing Strategy

| Test Type | Coverage | Tool |
|-----------|----------|------|
| Unit: tool registration | All tools registered | `pytest` |
| Unit: transaction rollback | Snapshot fidelity | `pytest` |
| Integration: MCP client | Happy path each tool | `mcp_test_client` |
| E2E: LLM workflow | Full `new_design` prompt | `pytest + httpx` |
| Snapshot: response schema | JSON Schema match | `pytest + deepdiff` |

**Target: 90%+ coverage on `zaptrace/mcp/` module by v0.2.0.**
