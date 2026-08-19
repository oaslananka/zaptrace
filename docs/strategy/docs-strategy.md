# Documentation Strategy

> **Status:** Draft  
> **Owner:** Core team  
> **Last updated:** 2026-06-09  
> **Related:** `docs/ROADMAP.md`, `docs/strategy/community-growth.md`

---

## 1. Philosophy

**"Docs-first development."** Every feature is documented before it's implemented. Documentation is a
first-class deliverable, not an afterthought.

---

## 2. Documentation Pyramid

```
        ┌─────────────┐
        │  Tutorials   │  <-- Getting Started, Quickstarts
       ├─────────────┤
        │  How-to     │  <-- Recipes, Common workflows
       ├─────────────┤
        │  Reference  │  <-- API, CLI, YAML schema, MCP tools
       ├─────────────┤
        │  Concepts   │  <-- Architecture, Design philosophy
       ├─────────────┤
        │  Strategy   │  <-- Internal planning, Roadmap, RFCs
        └─────────────┘
```

**Current state:** We have Reference (`docs/ARCHITECTURE.md`), Concepts (`docs/GETTING_STARTED.md`),
Strategy (this directory). Missing: How-to guides and more Tutorials.

---

## 3. Doc Sites & Tooling

### Phase 1: GitHub README + Docs Directory (Current)

- All docs in `docs/` directory
- README.md links to key docs
- GitHub renders Markdown natively
- **Pros:** Zero infrastructure, versioned with code
- **Cons:** No search, no cross-linking, not discoverable

### Phase 2: MkDocs / Material for MkDocs (v0.2.0)

- Static site generated from `docs/`
- Hosted on GitHub Pages
- Full-text search, navigation, version selector
- Auto-deployed on push to main

**Implementation:**

```yaml
# mkdocs.yml
site_name: ZapTrace
repo_url: https://github.com/zaptrace/zaptrace
theme:
  name: material
  features:
    - navigation.tabs
    - navigation.sections
    - search.highlight
    - content.code.copy
plugins:
  - search
  - autorefs
  - mkdocstrings:
      handlers:
        python:
          paths: [zaptrace]
```

### Phase 3: ReadTheDocs (v0.4.0+)

- Versioned documentation per release
- PDF/EPUB downloads for offline use
- Internationalization support

---

## 4. Documentation Types

### 4.1 API Reference (Auto-generated)

| Package | Tool | Priority |
|---------|------|----------|
| `zaptrace.models` | mkdocstrings | P0 |
| `zaptrace.mcp` | mkdocstrings | P0 |
| `zaptrace.cli` | Click's `--help` → docs | P0 |
| `zaptrace.synthesis` | mkdocstrings | P1 |
| `zaptrace.algo` | mkdocstrings | P1 |
| `zaptrace.export` | mkdocstrings | P1 |

### 4.2 How-to Guides

| Guide | Priority | Est. Effort |
|-------|----------|-------------|
| "Create a custom footprint" | P0 | 4h |
| "Write a DRC rule" | P1 | 3h |
| "Build a custom exporter" | P1 | 4h |
| "Use ZapTrace as a library" | P1 | 2h |
| "Set up CI for PCB designs" | P1 | 3h |
| "Migrate from KiCad" | P2 | 6h |
| "Create a multi-board project" | P2 | 4h |

### 4.3 Tutorials

| Tutorial | Priority | Format |
|----------|----------|--------|
| "Your first PCB in 10 minutes" | P0 | Blog + video |
| "Autopilot: schematic to Gerber" | P0 | Blog + video |
| "Designing a USB-C power supply" | P1 | Blog |
| "Building an ESP32 sensor node" | P1 | Blog + example |
| "Design for manufacturing checklist" | P1 | Blog |

### 4.4 Video Content

| Video | Length | Priority |
|-------|--------|----------|
| ZapTrace in 60 seconds | 1 min | P0 |
| Full walkthrough: ESP32 board | 10 min | P0 |
| Deep dive: router algorithm | 15 min | P1 |
| Manufacturing export explained | 8 min | P1 |
| Writing your first plugin | 12 min | P1 |

---

## 5. Documentation Review Process

1. **Draft** — Author writes first version
2. **Technical review** — SME checks accuracy
3. **Editorial review** — Readability, clarity, grammar
4. **User test** — Fresh user follows docs, reports friction
5. **Merge** — Into `docs/` on `main`
6. **Publish** — Auto-deploy to docs site

**Blocking:** No doc is "done" until a user test passes without help.

---

## 6. Doc Health Metrics

| Metric | Current | Target | Method |
|--------|---------|--------|--------|
| Tutorial completion rate | — | >80% | Analytics on docs site |
| Time-to-first-PCB | — | <15 min | User survey |
| API doc coverage | ~10% | 100% | `interrogate` (docstring coverage) |
| Broken links | — | 0 | `lychee` link checker |
| Searchability | — | "First result is correct" | User survey |

---

## 7. Docstring Standards

All public APIs must have:

```python
def autoroute(
    design: Design,
    net_name: str,
    *,
    layer: Literal["top", "bottom"] = "top",
    via_cost: float = 1.0,
) -> RouteResult:
    """Auto-route a single net in the given design.

    Uses A* pathfinding with layer-specific cost heuristics.
    Curved traces are approximated as linear segments.

    Args:
        design: The PCB design to modify (in-place).
        net_name: Name of the net to route (must exist in design.nets).
        layer: Starting layer for routing.
        via_cost: Multiplier for via penalty (higher = fewer vias).

    Returns:
        RouteResult with status, trace coordinates, and any errors.

    Raises:
        NetNotFoundError: If net_name doesn't exist in design.
        RoutingFailedError: If no route could be found.
        LayerNotAvailableError: If layer isn't in design stackup.

    Example:
        >>> design = Design(name="test")
        >>> design.nets.append(Net(name="GND", ...))
        >>> result = autoroute(design, "GND", layer="top")
        >>> result.status
        'success'
    """
```

**Docstring coverage enforcement:**

```bash
# CI check
interrogate --fail-under=80 zaptrace/
```

---

## 8. Tutorial Structure Template

Every tutorial follows:

```markdown
# Tutorial: [Title]

## Prerequisites
- [ ] ZapTrace installed (vX.Y+)
- [ ] Basic Python knowledge
- [ ] [Any hardware/software needed]

## What you'll learn
- ...

## Step 1: ...
Code block with exact commands.

## Step 2: ...
...

## Expected Output
What you should see/verify.

## Next Steps
Where to go from here.
```

---

## 9. Immediate TODO

- [ ] Add docstrings to all public `zaptrace.models` classes
- [ ] Add docstrings to all MCP tools
- [ ] Run `interrogate` baseline and track to 80%
- [ ] Create MkDocs config file
- [ ] Write 3 how-to guides (P0)
- [ ] Write custom GitHub Action to auto-deploy docs
- [ ] Set up `lychee` link checker in CI
