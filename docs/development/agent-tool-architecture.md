# Agent Tool Architecture

ZapTrace exposes 93 stable agent-facing tools through MCP, REST, CLI, and the Python tool registry. The public compatibility import remains `zaptrace.agent._tool_impls`, but implementations are owned by cohesive modules under `zaptrace.agent.tool_impls`.

## Public compatibility surface

`zaptrace.agent._tool_impls` is a facade. Existing imports, tool function names, shared session access, path validation helpers, and `TOOL_REGISTRY` remain available from that module. New implementation code must not be added to the facade.

The committed registry contract in `config/agent-tool-registry-contract.json` records the exact tool order, names, descriptions, parameter schemas, capability metadata, and path policies. CI compares the assembled registry to that contract.

## Domain ownership

| Module | Responsibility |
|---|---|
| `runtime.py` | Session state, workspace/path validation, library cache, validation evidence, and release gates |
| `design.py` | Parsing, inspection, diffing, board updates, and component mutation |
| `synthesis.py` | Requirements, topology synthesis, simulation gates, scoring, and manufacture orchestration |
| `verification.py` | ERC, DRC, and engineering review adapters |
| `routing.py` | Placement, routing, net classification, and board summaries |
| `library.py` | Component and footprint lookup plus schematic rendering |
| `exports.py` | BOM, reports, SVG, KiCad, Gerber, drill, manufacturing, placement, and SPICE export |
| `interop.py` | KiCad import, EasyEDA/Altium conversion, STEP export, and 3D-model coverage |
| `pipeline.py` | Autopilot pipeline execution, stage execution, status, and patch suggestions |
| `transactions.py` | Snapshots, transactions, commits, rollbacks, and audit events |
| `proof.py` | Proof execution and proof-check discovery |
| `calculators.py` | Pure electrical calculator tools |

Registry metadata is split into matching `registry_<domain>.py` fragments. `registry.py` assembles them in the original public order, rejects duplicates or omissions, attaches capability and path-policy metadata, and owns secure dispatch.

## Dependency rules

- Domain modules may depend on `deps.py` and `runtime.py`.
- A domain-to-domain dependency is allowed only when the higher-level workflow composes a lower-level capability; currently synthesis composes verification.
- No module under `tool_impls/` may import the `_tool_impls` compatibility facade.
- Registry fragments are declarative and must not contain implementation functions.
- The internal import graph must remain acyclic.
- The compatibility facade and every implementation module must remain at or below 600 lines.

These rules are enforced by `tests/test_agent_tool_modularity.py` and `config/agent-tool-modularity.json`.

## Adding or changing a tool

1. Add or update the implementation in the owning domain module.
2. Add or update its declarative entry in the matching registry fragment.
3. Regenerate `config/agent-tool-registry-contract.json` only for an intentional reviewed public-contract change.
4. Regenerate MCP documentation and policy evidence.
5. Run the affected unit/integration lane plus `tests/test_agent_tool_modularity.py`, `tests/test_tool_policy_docs.py`, and `tests/test_docs_status_sync.py`.
6. Document any intentional schema or capability migration in the changelog and PR.

Moving implementation code between domains must not change tool names, callable behavior, response envelopes, capability metadata, or parameter schemas.
