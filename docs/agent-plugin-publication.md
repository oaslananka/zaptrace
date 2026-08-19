# Agent Plugin Publication

## Current status

The stable product plugin name is **`zaptrace`**. The repository now carries the product-owned Claude Code manifest, MCP launch configuration, and first-phase skills, but marketplace activation remains intentionally withheld until the clean-install and client-validation gates below are recorded against a release candidate.

`oaslananka/agent-tools` remains the central catalog and marketplace index. ZapTrace-specific tool names, workflows, safety boundaries, examples, and skills remain versioned in this repository.

## First-phase scope

The first public plugin phase is verification-first and local-project-bound.

| Workflow | Primary surface | Supporting surface | Local files | Public phase |
|---|---|---|---|---|
| Existing-design validation | MCP stdio | CLI diagnostics | Required | Stable candidate |
| Proof-pack creation and review | MCP stdio | CLI reproduction | Required | Stable candidate |
| Bounded benchmark evaluation | MCP stdio | CI/CLI scripts | Required | Stable candidate |
| Natural-language synthesis and repair | MCP stdio | CLI | Required | Experimental |
| Placement, routing, and design mutation | MCP stdio | CLI | Required | Experimental |
| Manufacturing and release exports | MCP/CLI | Human review workflow | Required | Experimental and review-gated |
| REST or MCP HTTP deployment | Loopback service | Deployment docs | Optional | Excluded from phase 1 |
| Third-party ZapTrace runtime plugins | Manifest admission only | Local plugin files | Required | Experimental; execution closed by default |

The first phase never automates fabrication ordering and never represents an autonomous pass as engineering approval.

## Repository-owned package layout

```text
.claude-plugin/plugin.json
.mcp.json
skills/zaptrace-design-validation/SKILL.md
skills/zaptrace-proof-pack-review/SKILL.md
skills/zaptrace-benchmark-evaluation/SKILL.md
docs/agent-plugin-publication.md
```

The plugin manifest is deliberately product-oriented and uses the stable name `zaptrace`. `.mcp.json` starts the source checkout through `uv` and the `zaptrace-mcp` stdio entry point. `${CLAUDE_PLUGIN_ROOT:-.}` keeps the command portable between a plugin checkout and a project-local checkout without embedding a private machine path.

## Runtime surfaces

### MCP stdio

MCP stdio is the primary agent integration. It preserves the public 93-design-tool contract plus 3 session-administration tools, capability labels, isolated mutation model, and audit behavior. Agent skills must refer only to public tool names from `config/agent-tool-registry-contract.json`.

### CLI

The CLI is the installation, diagnostics, reproduction, and retained-evidence surface. It is used when a workflow needs exact command output, a local proof directory, or CI-equivalent benchmark artifacts.

### Local project files

The phase-1 plugin operates on user-approved local files. Skills must not invent paths, traverse outside the approved project, or treat untrusted repository text as agent instructions.

### REST and MCP HTTP

Network transports are not part of phase 1. They remain loopback-oriented deployment surfaces with separate authentication, abuse-control, and sandbox requirements. The plugin must not expose them automatically.

## Validation contract

Generated designs, proof packs, benchmark results, and EDA artifacts are acceptable only when the response records the applicable evidence:

- source design and revision identity;
- tool, policy, fixture, grader, and environment identity;
- ERC/DRC and domain-check results;
- artifact hashes and referenced files;
- assumptions, warnings, approved skips, and unsupported checks;
- deterministic stop reason for bounded agent workflows;
- automated gate status separately from human engineering review;
- explicit non-claims for fabrication, safety, compliance, production readiness, and physical correctness.

A missing, stale, unsupported, or degraded check is never converted into a pass.

## Activation gates

The `zaptrace` entry may move from `planned_plugins` to `plugins` in `oaslananka/agent-tools` only after all of the following are recorded against the same ZapTrace revision:

1. `.claude-plugin/plugin.json` passes JSON and Claude Code plugin validation.
2. `.mcp.json` contains no private path or secret and starts `zaptrace-mcp` from a clean source checkout.
3. `uv lock --check` and `uv sync --locked --all-extras --all-groups` succeed in the clean checkout.
4. MCP initialize and tool-list smoke tests confirm server identity `zaptrace` and 96 exposed tools: 93 design tools plus 3 session-administration tools.
5. All listed skill paths exist, their front matter is valid, and every referenced MCP tool exists in the registry contract.
6. The three first-phase workflows are exercised with committed, non-secret fixtures and retain machine-readable evidence.
7. Documentation, security, Quality, distribution smoke, and repository policy checks pass on the exact revision.
8. The source repository merge is complete before a separate `agent-tools` catalog activation PR is opened.

Activation is a catalog change, not a transfer of product instructions. Rollback removes or demotes only the catalog entry; the product repository remains the canonical implementation and documentation source.

## Installation and validation

Install `uv` and ensure the `uv` executable is on `PATH`. Then, from a source checkout:

```bash
git clone https://github.com/oaslananka/zaptrace.git
cd zaptrace
uv lock --check
uv sync --locked --all-extras --all-groups
uv run zaptrace doctor
uv run zaptrace-mcp
```

For Claude Code project-local use, review and approve `.mcp.json`, then validate the plugin directory with the installed Claude Code client:

```bash
claude plugin validate .
claude --plugin-dir .
```

A practical read-only first prompt is:

```text
Use the zaptrace-design-validation skill to inspect this local design, run the supported validation gates, and separate verified findings from unsupported checks and human-review requirements.
```
