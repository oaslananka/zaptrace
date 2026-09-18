# ZapTrace

**Agent-native electronics design core** — PCB EDA via LLM agents and MCP.

ZapTrace is a Python-first EDA engine designed to be driven by AI agents through the Model Context Protocol (MCP). It provides a full stack of electrical design automation: schematic synthesis, ERC/DRC/DFM rule engines, BOM management, manufacturing export, and proof-pack signoff — all accessible through a clean, versioned API.

---

## Quick Links

<div class="grid cards" markdown>

- :material-rocket-launch: **[Getting Started](GETTING_STARTED.md)**
  Install, configure, and run your first design in minutes.

- :material-book-open: **[Architecture](ARCHITECTURE.md)**
  How ZapTrace components fit together.

- :material-api: **[API Reference](api-rest-production.md)**
  Full REST API documentation.

- :material-shield-check: **[Safety & Non-claims](SAFETY.md)**
  What ZapTrace guarantees — and what it explicitly does not.

- :material-connection: **[MCP Integration](mcp/quickstart.md)**
  Connect ZapTrace to Claude, Cursor, or any MCP client.

- :material-factory: **[Manufacturing](manufacturing/bom-export.md)**
  BOM export, Gerber generation, and DFM checks.

</div>

---

## What ZapTrace Does

| Capability | Description |
|---|---|
| **ERC** | 29 electrical rule checks, from floating pins to PDN headroom |
| **DRC** | PCB layout checks: clearance, drill, via-to-via, courtyard |
| **[DFM](reference/glossary.md#design-for-manufacturability-dfm)** | SMD, footprint, pick-and-place manufacturability checks |
| **BOM** | Line-item export, supply risk scoring, distributor adapters |
| **Manufacturing** | Gerber RS-274X, IPC-2581, IDF 2.0, SES, Eagle XML |
| **Synthesis** | Testpoint insertion, RF trace width, net naming, placement AI |
| **Agent Runtime** | Budget sandbox, prompt-injection detection, replayable session log |
| **Review Studio** | Panel aggregation, human checklist workflow, signoff decisions |
| **MCP** | Full tool suite exposed via Model Context Protocol |

---

## Non-claims

!!! warning "ZapTrace is a heuristic engine, not a signoff tool"
    - All ERC/DRC/DFM outputs are **best-effort heuristics**, not certified signoff.
    - Electrical analysis uses **closed-form approximations**, not field solvers.
    - BOM risk scores are **indicative only** — always verify with your distributor.
    - Agent decisions are **subject to human review** before tape-out.

---

## License

MIT License — see [GitHub](https://github.com/oaslananka/zaptrace) for full text.
