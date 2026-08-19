# ZapTrace Architecture

## Overview

ZapTrace is designed as a layered EDA kernel with a deterministic core, AI-assisted workflows, and multiple interface surfaces.

```
┌─────────────────────────────────────────────────────────────┐
│                      Interfaces                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │   CLI    │  │ MCP Server│  │REST API  │  │ Python SDK │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬─────┘  │
├───────┴──────────────┴────────────┴────────────────┴───────┤
│                      Agent Layer                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Tool Registry (93 agent-facing tools)           │  │
│  │  Pipeline Autopilot                                   │  │
│  └──────────────────────────────────────────────────────┘  │
├────────────────────────────────────────────────────────────┤
│                      Core Layer                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │  Models  │ │  Parser  │ │  Diff    │ │  Exceptions  │  │
│  │(Pydantic)│ │  (YAML)  │ │  Engine  │ │  (framework) │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
├────────────────────────────────────────────────────────────┤
│                      Domain Layer                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │EE Knowl- │ │ Classi-  │ │Footprint │ │  Constraints │  │
│  │edge Base │ │ fier     │ │Engine    │ │  & Presets   │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
├────────────────────────────────────────────────────────────┤
│                  Verification Layer                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ERC Engine│ │DRC Engine│ │  Patches │ │   Rules      │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
├────────────────────────────────────────────────────────────┤
│                  Algorithm Layer                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │  Placer  │ │  Router  │ │GridRoute │ │  Copper Pour │  │
│  │(grid+fd) │ │(Manhattan│ │   r      │ │(flood-fill)  │  │
│  │          │ │   MST)   │ │          │ │              │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
├────────────────────────────────────────────────────────────┤
│                  Export Layer                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │  Gerber  │ │ Excellon │ │   BOM    │ │  KiCad       │  │
│  │(RS-274X) │ │  (Drill) │ │(CSV/JSON)│ │  (Schematic) │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │  SVG     │ │  Pick    │ │Manufact. │ │  Proof Pack  │  │
│  │Schematic │ │  & Place │ │  Bundle  │ │  (ZIP+meta)  │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
├────────────────────────────────────────────────────────────┤
│                  Extension Layer                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Synthesis│ │  Library │ │  Plugin  │ │  Rust Core   │  │
│  │(template)│ │  Loader  │ │  Manager │ │  (optional)  │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
└────────────────────────────────────────────────────────────┘
```

## Package Structure

```
zaptrace/              # Main Python package
├── __init__.py        # Package metadata
├── core/              # Design models, parser, exceptions
│   ├── models.py      # Pydantic models (Design, Component, Net, etc.)
│   ├── parser.py      # YAML design file parser
│   ├── diff.py        # Design comparison engine
│   └── exceptions.py  # Domain exceptions
├── ee/                # Electrical engineering knowledge
│   ├── classifier.py  # Net classification (power, signal, analog, etc.)
│   ├── footprints.py  # Parametric footprint generation
│   ├── knowledge.py   # EE knowledge base (trace widths, clearances)
│   ├── schematic/     # Schematic rendering engine
│   ├── drc/           # Design Rule Checking engine
│   ├── constraints/   # Design constraint definitions
│   ├── routing/       # Route-specific EDA logic
│   └── presets/       # Manufacturing presets (JLCPCB, etc.)
├── erc/               # Electrical Rule Checking
│   ├── models.py      # ERC result models
│   ├── rules.py       # ERC rule implementations
│   ├── runner.py      # ERC rule runner
│   └── patches.py     # Auto-patch suggestions
├── algo/              # Placement and routing algorithms
│   ├── placer.py      # Grid + force-directed placement
│   ├── router.py      # Manhattan MST routing
│   ├── grid_router.py # Grid-based A* routing
│   ├── copper_pour.py # Flood-fill copper pours
│   ├── diff_pair.py   # Differential pair routing
│   └── fillet.py      # Trace fillet/rounding
├── export/            # Output generation
│   ├── gerber.py      # Gerber RS-274X export
│   ├── excellon.py    # Excellon drill export
│   ├── bom.py         # BOM CSV/JSON generation
│   ├── manufacturing.py # Manufacturing bundle (ZIP)
│   ├── kicad.py       # KiCad schema export
│   ├── svg.py         # SVG rendering
│   └── report.py      # Markdown report generation
├── synthesis/         # Design synthesis from intent
│   ├── engine.py      # Template-based synthesis
│   └── templates/     # Design templates
├── pipeline/          # Design flow autopilot
│   └── autopilot.py   # Multi-stage pipeline runner
├── mcp/               # MCP protocol server
│   └── server.py      # FastMCP server (96 exposed: 93 design + 3 session administration)
├── api/               # REST API
│   ├── server.py      # FastAPI server
│   ├── models.py      # API request/response models
│   └── routes/        # API route definitions
├── cli/               # Command-line interface
│   ├── main.py        # Click CLI (17+ commands)
│   └── output.py      # Rich console output helpers
├── agent/             # Agent tool definitions
│   ├── _tool_impls.py # Backward-compatible public facade
│   ├── tool_impls/    # Domain implementations and declarative registry fragments
│   └── tools.py       # Public registry helpers
├── library/           # Component library
│   └── loader.py      # Library file loader
├── proof/             # Proof pack system
│   ├── __init__.py
│   ├── manifest.py
│   └── pack.py
└── plugins/           # Plugin system
    ├── __init__.py
    ├── manifest.py
    └── loader.py

zaptrace_core/         # Optional Rust extension
├── Cargo.toml
└── src/lib.rs

data/                  # Component library data files
├── library/
│   ├── passive/       # Resistors, capacitors, inductors
│   ├── mcu/           # Microcontrollers
│   ├── connector/     # Connectors
│   ├── power/         # Power management
│   ├── sensor/        # Sensors
│   ├── rf/            # RF components
│   └── optoelectronic/# LEDs, displays, photodiodes

tests/                 # Test suite (count enforced by CI)
examples/              # Example designs
docs/                  # Documentation
```

## Key Design Decisions

### Why Pydantic?
All core models use Pydantic for validation, serialization, and schema generation. This gives us automatic JSON Schema output, type-safe construction, and clear error messages.

### Why opt-in SQLite session state?
ZapTrace keeps zero-configuration CLI usage in memory, but controlled deployments can set `ZAPTRACE_SESSION_STORE_ROOT` to enable the standard-library SQLite backend. Committed design heads, immutable version lineage, snapshots, transactions, audit/ACL records, and evidence identities then survive restart. Content is addressed by canonical SHA-256 while session ID and design name remain the isolation boundary. Isolated workers never write the database directly; the trusted parent publishes successful worker state in one SQLite transaction. See [Persistent versioned state](storage/persistent-state.md).

### Why Algorithmic Routing (not ML)?
Deterministic, repeatable routing is essential for a verification-first tool. ML-assisted routing is a future addition, but the core must always produce reproducible results.

### Why Multiple Export Formats?
Different users need different outputs: KiCad for GUI editing, Gerber for fabrication, SVG for documentation, BOM for procurement. Each export is independently generated from the same design model.

### Why Proof Packs?
Trust is earned through transparency. Proof packs let anyone verify exactly what ZapTrace generated, why, and whether all checks passed. This is essential for an AI-native EDA tool claiming "with proofs."

## Data Flow

1. **Input**: YAML file or natural language intent
2. **Parse/Synthesize**: Produces a validated `Design` model
3. **Classify**: EE knowledge enriches nets with classifications
4. **ERC**: Validates electrical connectivity and pin compatibility
5. **Place**: Arranges components on the board
6. **Route**: Connects component pins with traces
7. **DRC**: Validates physical design against manufacturing rules
8. **Export**: Generates fabrication artifacts
9. **Proof Pack**: Bundles everything with reproducibility metadata
