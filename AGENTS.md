# AGENTS.md

## Scope and precedence

This file defines repository-wide instructions for automated coding agents working in ZapTrace.

- Apply these instructions to the entire repository unless a closer `AGENTS.md` exists.
- A nested `AGENTS.md` adds or narrows rules for its subtree. When rules conflict, follow the closest applicable file.
- Do not use a nested file to weaken repository security, evidence, release, or product-claim constraints unless the underlying project policy is intentionally changed.
- Repository documentation and executable policy remain authoritative. If this file drifts from verified repository behavior, follow the verified behavior and update this file.

Nested instruction boundaries:

- `zaptrace_core/AGENTS.md` — Rust/PyO3 native security boundary.
- `data/AGENTS.md` — governed component data, provenance, and trust tiers.
- `.github/AGENTS.md` — CI, release, and supply-chain automation.

## Project identity

ZapTrace is a pre-1.0, agent-native, verification-first EDA kernel. Its core flow is design intent -> normalized design -> schematic -> ERC -> placement -> routing -> DRC -> manufacturing/export artifacts -> auditable proof evidence.

Primary repository surfaces include:

- the Python SDK and domain model under `zaptrace/`;
- the `zaptrace` CLI;
- MCP and REST interfaces;
- ERC/DRC and deterministic placement/routing/export paths;
- component-library governance and manufacturing/KiCad output;
- proof/evidence tooling;
- the optional Rust/PyO3 acceleration core in `zaptrace_core/`.

For architectural rationale, use `docs/ARCHITECTURE.md`. Do not duplicate that document here.

## Product and evidence boundary

ZapTrace evidence is verification evidence, not unconditional hardware approval.

Do not introduce or strengthen claims of:

- guaranteed fabrication readiness;
- manufacturer approval;
- formal verification;
- qualified-safety status;
- solver-grade sign-off;
- correctness without qualified human engineering review.

Preserve documented non-claims unless the underlying evidence and accepted project policy are explicitly changed. A passing schema, test, proof pack, or CI gate proves only the scope that artifact is defined to prove.

## Repository map

Use the owning domain rather than creating parallel abstractions:

- `zaptrace/core/` — canonical design models and parsing.
- `zaptrace/ee/` — electrical-engineering domain logic, constraints, DRC, routing knowledge, and presets.
- `zaptrace/erc/` — electrical rule checking.
- `zaptrace/algo/` — placement and routing algorithms.
- `zaptrace/export/` — manufacturing and interchange output.
- `zaptrace/synthesis/` — intent-to-design synthesis.
- `zaptrace/pipeline/` — design-flow orchestration.
- `zaptrace/mcp/` — MCP transport/server surface.
- `zaptrace/api/` — REST transport/server surface.
- `zaptrace/cli/` — command-line interface.
- `zaptrace/agent/` — agent tool implementations and declarative registry.
- `zaptrace/library/` — component-library loading, schema, selection, and governance.
- `zaptrace/proof/` — proof/evidence manifests and packs.
- `zaptrace/plugins/` — plugin loading boundary.
- `zaptrace_core/` — optional native Rust/PyO3 core.
- `data/` — governed component/library data.
- `scripts/` — repository automation, policy, validation, generation, and evidence tooling.
- `tests/` — centrally classified test lanes.
- `.github/` — CI, security, release, dependency, and repository automation.

## Environment and setup

The canonical Python environment is managed with `uv`.

```bash
uv sync --all-extras --all-groups
```

The project requires Python 3.12 or newer. Rust tooling is required when working on the native core or native packaging boundary.

Useful repository entry points:

```bash
task doctor
task lint
task typecheck
task test-fast
task test-lane-policy
```

Use `Taskfile.yml`, `pyproject.toml`, and `docs/development/validation-environment.md` as the source of truth for current commands and toolchain requirements.

## Change discipline

- Keep changes narrowly scoped to the requested behavior.
- Follow existing architecture, naming, and public contracts before introducing new abstractions.
- Prefer existing helpers and domain modules over parallel implementations.
- Avoid unrelated refactors, generated churn, mass formatting, or opportunistic rewrites.
- Keep deterministic behavior deterministic.
- Preserve backward compatibility where the repository currently promises it; make intentional contract migrations explicit.
- Do not delete, weaken, skip, or broadly exempt a failing check merely to obtain a green build.
- Do not claim a command, test, gate, or workflow passed unless it was actually executed or reported by the authoritative system.

Before changing a policy-sensitive area, identify the invariant, its owning implementation, its tests, the CI gate that enforces it, and any evidence artifact it emits.

## Python engineering standards

Follow `docs/development/coding-standards.md` and the configuration in `pyproject.toml`.

In particular:

- use Python 3.12+ syntax;
- type public interfaces and non-trivial internals;
- preserve Pydantic validation boundaries rather than bypassing them;
- propagate errors with useful context instead of swallowing them;
- use `pathlib.Path` for filesystem paths and validate untrusted paths before writes;
- avoid TODO/FIXME placeholders in shipped code;
- add or update tests when behavior changes.

Baseline static validation:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

## Testing and validation

ZapTrace uses centrally classified test lanes. Read `docs/development/testing-policy.md` and `config/test-lanes.json` before changing lane ownership or skip behavior.

During iteration, prefer the smallest relevant test surface. Before considering a non-trivial change complete, run the relevant repository gates for the affected risk boundary.

Common commands:

```bash
task test-fast
task test-lane-policy
task test-unit
task test-integration
task test-benchmark
task test-hardware
task test-external-tool
task test-native
```

Rules:

- New behavior requires focused tests unless testing is genuinely inapplicable; document the reason when it is.
- Required external/native lanes must distinguish pass, fail, and approved skip.
- Do not turn required execution into a passing empty/skip-only lane.
- Preserve evidence-producing tests for EDA behavior where observable evidence is the acceptance surface.
- Coverage floors and protected critical-runtime coverage are policy, not targets to bypass with omit rules or unreviewed coverage pragmas.

## MCP and agent-tool changes

The tool registry is an architectural contract, not a transport-local list.

When adding or changing an MCP/agent tool:

1. modify the owning implementation under `zaptrace/agent/tool_impls/`;
2. update the matching declarative registry fragment;
3. preserve or intentionally migrate `config/agent-tool-registry-contract.json`;
4. update MCP resources/transport integration when applicable;
5. update CLI exposure when applicable;
6. add or update focused tests, including modularity/registry tests as relevant;
7. regenerate and verify generated MCP documentation/policy artifacts.

Use:

```bash
task docs-mcp
task check-docs
```

Do not register tools directly in a transport layer to bypass the declarative registry architecture. See `docs/development/agent-tool-architecture.md`.

## Security-sensitive changes

Treat parsers, exporters, filesystem writes, MCP/API boundaries, authentication/authorization, plugin loading, native/PyO3 code, dependency tooling, CI/release workflows, and evidence identity as security-sensitive.

- Treat external input as untrusted.
- Preserve authentication, authorization, capability, path, resource-limit, and input-validation checks.
- Never commit or print secrets, tokens, private keys, credentials, signing material, or sensitive authentication headers.
- Do not weaken fail-closed behavior to improve convenience or test pass rates.
- Security-sensitive changes require explicit test coverage or a documented reason testing is not applicable.
- Follow `SECURITY.md` and the applicable documents under `docs/security/`.

## Dependencies and generated state

Dependency sources are governed by `docs/supply-chain/dependency-policy.md`.

- Python dependencies: `pyproject.toml` and `uv.lock`.
- Rust dependencies: `zaptrace_core/Cargo.toml` and `zaptrace_core/Cargo.lock`.
- Container runtime dependencies: `Dockerfile`, `requirements/container-runtime.txt`, and `requirements/container-apk.txt`.
- GitHub Actions dependencies: `.github/workflows/*.yml`.

Do not hand-edit generated lock/export state when the owning package-manager or repository generator should produce it. Preserve pinned/locked dependency behavior and review runtime-sensitive dependency changes as security-sensitive.

Generated references must be regenerated through their repository-owned generator and then checked for drift; do not manually patch generated output while leaving the generator stale.

## Version and release changes

Version identity is intentionally synchronized across Python, Rust, runtime, API/MCP surfaces, locks, and release evidence. Follow `docs/development/version-policy.md` and `docs/development/release-process.md`.

Do not:

- publish or describe a release as complete before the repository release process establishes it;
- move, rewrite, or reuse immutable release evidence/tags;
- bypass release identity, provenance, SBOM, checksum, installed-wheel, or distribution gates;
- alter a release workflow solely to make an artifact upload succeed.

## Documentation and changelog

- Update public documentation when public behavior changes.
- Update `CHANGELOG.md` for user-visible changes.
- Keep deep rationale in the existing canonical document instead of duplicating it into `AGENTS.md`.
- Keep examples and CLI/help text synchronized with behavior when they are part of the public contract.
- Do not promote implementation assumptions into claims of engineering verification.

## Git and pull requests

- Use focused branches and reviewable diffs.
- Follow the repository's conventional-commit guidance in `docs/development/commit-conventions.md`.
- Do not rewrite unrelated history or force-push unless explicitly required and authorized.
- Keep PR descriptions factual: explain scope, risk, and validation actually performed.
- Resolve the root cause of actionable CI/review findings rather than suppressing the reporting mechanism.

## Definition of done

A change is complete only when all applicable items are true:

- requested behavior is implemented within the intended scope;
- relevant tests and policy gates pass;
- lint/type/static checks relevant to the change pass;
- security/evidence invariants remain intact;
- generated artifacts and contracts are synchronized;
- public documentation and changelog are updated when required;
- no unrelated files were changed;
- validation claims in the PR accurately reflect what was executed.
