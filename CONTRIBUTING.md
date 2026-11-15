# Contributing to ZapTrace

Thank you for wanting to contribute to ZapTrace! This document will help you get started.

## Code of Conduct

All contributors must follow our [Code of Conduct](CODE_OF_CONDUCT.md). Be respectful, inclusive, and constructive.

## Getting Started

1. **Fork** the repository
2. **Clone** your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/zaptrace.git
   cd zaptrace
   ```
3. **Set up environment**:
   ```bash
   uv sync --all-extras
   ```
4. **Install pre-commit hooks** (recommended):
   ```bash
   pip install pre-commit
   pre-commit install
   ```

## Development Workflow

### Branch naming

```
feature/<short-description>
fix/<issue-number>-<description>
docs/<description>
refactor/<description>
```

### Before committing

1. **Run linting**:
   ```bash
   uv run ruff check .
   uv run ruff format --check .
   ```

2. **Run tests**:
   ```bash
   uv run pytest -q
   ```

3. **Run type checking** (if pyright is available):
   ```bash
   uv run pyright
   ```

4. **Run license compliance**:
   ```bash
   python scripts/ci_reuse_check.py --strict
   ```

### Commit messages

Use conventional commits:
```
feat: add BOM supply-chain enrichment
fix: correct Excellon tool sorting
docs: update MCP tool catalog
refactor: extract EE knowledge base
test: add DRC coverage tests
```

## Code Quality Standards

- **Functions**: ≤40 lines, cyclomatic complexity ≤10
- **Modules**: ≤400 lines soft limit, >600 requires split plan
- **Imports**: Organize with Ruff (automatic)
- **Types**: Use type hints everywhere (`from __future__ import annotations`)
- **Error handling**: Never swallow errors. Always propagate with context.
- **No TODOs or FIXMEs** in shipped code
- **Tests required** for all new features

## Testing

Run the test suite:
```bash
uv run pytest -q          # Quick run
uv run pytest --cov       # With coverage
uv run pytest -m slow     # Slow tests (integration)
uv run pytest -m rust     # Tests requiring Rust extension
```

We aim for ≥75% test coverage on the `zaptrace` package.

## Documentation

All public APIs must have docstrings. Major features should have:
- Python docstrings (Google style)
- CLI help text (built into Click)
- Documentation in `docs/`
- Example in `examples/`

## MCP Tools

When adding new MCP tools:
1. Implement the tool function in the owning `zaptrace/agent/tool_impls/<domain>.py` module
2. Register it in the matching declarative `registry_<domain>.py` fragment
3. Preserve or intentionally migrate the contract in `config/agent-tool-registry-contract.json`
4. Add MCP resource if applicable in `zaptrace/mcp/server.py`
5. Add to CLI in `zaptrace/cli/main.py` when applicable
6. Add tests in `tests/` and run `tests/test_agent_tool_modularity.py`
7. Regenerate the MCP tool reference and policy matrix

See [Agent Tool Architecture](docs/development/agent-tool-architecture.md) for domain ownership and dependency rules.

## Architecture Overview

```
zaptrace/
  core/          # Design models, parser
  ee/            # EE knowledge, classification, footprints
  erc/           # Electrical Rule Checking
  algo/          # Placement, routing algorithms
  export/        # Gerber, Excellon, BOM, SVG, KiCad
  synthesis/     # Design synthesis from intent
  pipeline/      # Design flow autopilot
  mcp/           # MCP server
  api/           # REST API
  cli/           # Command-line interface
  agent/         # Agent tool definitions
  library/       # Component library loader
  proof/         # Proof pack system
  plugins/       # Plugin system
```

## Review Process

1. Open a Pull Request against `main`
2. CI must pass (lint, test, build)
3. External contributions receive maintainer review. Maintainer-authored PRs rely on required CI in the current solo-maintainer model; independent approval is not yet enforced.
4. Squash-merge after the applicable review and required checks pass

## Need Help?

- Open a [Discussion](https://github.com/oaslananka/zaptrace/discussions)
- Join our community (TBA)
- Read the [docs](docs/)

## Good First Issues

New contributors should start with a small, well-scoped task. See the
[Good First Issues catalog](docs/community/good-first-issues.md) for a curated
list of newcomer-friendly work across documentation, examples, fixtures, and
tests. Open issues are labelled
[`good first issue`](https://github.com/oaslananka/zaptrace/labels/good%20first%20issue)
and [`help wanted`](https://github.com/oaslananka/zaptrace/labels/help%20wanted).

<!-- professional-oss-contribution-policy -->
## Professional Source-Available Contribution Policy

ZapTrace accepts contributions through GitHub pull requests. The project currently operates with a solo-maintainer governance model, so contributor expectations are intentionally explicit and evidence-oriented.

### Acceptable contributions

A contribution is acceptable when it is narrow, reviewable, and includes the evidence needed to evaluate it. For non-documentation changes, include tests or a written rationale explaining why tests are not applicable.

Required before requesting review:

- Run the relevant quality gates listed in the pull request template.
- Update user-facing documentation for public behavior changes.
- Update `CHANGELOG.md` for user-visible changes.
- Preserve the pre-1.0 non-claims: no fabrication-readiness, manufacturer approval, or no-human-review correctness claims.
- Avoid broad rewrites unless the issue or design note explicitly scopes them.

### Conventional commits

Use the conventional commit format documented in [commit conventions](docs/development/commit-conventions.md). Common prefixes are `feat:`, `fix:`, `docs:`, `test:`, `ci:`, `refactor:`, `chore:`, and `security:`.

### Contributor licensing

Contributions are submitted under [GNU AGPL v3.0](LICENSE) by regular GitHub
pull request. No CLA, DCO sign-off, `Signed-off-by` trailer, or copyright
assignment is required. Contributors retain copyright and should identify
any third-party components and their license.
