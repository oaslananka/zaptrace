# Coding Standards

## General principles

- Keep changes small, typed, tested, and evidence-producing.
- Avoid broad rewrites unless the roadmap or issue explicitly scopes them.
- Do not overclaim hardware correctness, fabrication readiness, or manufacturer approval.
- Prefer deterministic behavior and explicit evidence artifacts.

## Python

- Use Python 3.12+ syntax.
- Use type hints for public interfaces and non-trivial internals.
- Run `uv run ruff check .` and `uv run ruff format --check .`.
- Run `uv run pyright` for static type checking.
- Avoid swallowing exceptions; add context and propagate.
- Use `pathlib.Path` for filesystem paths and validate untrusted paths before writing.

## Rust

- Run `cargo fmt --manifest-path zaptrace_core/Cargo.toml --check`.
- Run `cargo clippy --manifest-path zaptrace_core/Cargo.toml -- -D warnings`.
- Run `cargo test --manifest-path zaptrace_core/Cargo.toml`.

## Security-sensitive code

Security-sensitive changes include parsers, exporters, file writes, MCP/API boundaries, plugin loading, release workflows, dependency tooling, and CI credentials. These changes need explicit test coverage or a documented reason why testing is not applicable.

## Documentation

Public behavior changes should update README, docs, examples, or CLI help. User-visible changes should update `CHANGELOG.md`.
