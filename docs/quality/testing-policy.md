# Testing and Quality Policy

This page summarizes when and how ZapTrace tests are run.

## Local developer checks

Before submitting non-trivial changes, run the relevant subset:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
```

Rust extension checks:

```bash
cargo fmt --manifest-path zaptrace_core/Cargo.toml --check
cargo clippy --manifest-path zaptrace_core/Cargo.toml -- -D warnings
cargo test --manifest-path zaptrace_core/Cargo.toml
```

Release-validation environment check:

```bash
zaptrace doctor --strict
python scripts/ci_validation_environment.py --strict
```

## CI checks

The quality workflow runs linting, formatting, type checking, Python tests, Rust extension checks, package builds, Docker smoke tests, docs-status sync, KiCad oracle evidence, benchmark acceptance, and generated-board release gates where applicable.

## Required checks on main

The protected `main` branch requires status checks before merge. Required checks include lint/typecheck, Python version matrix tests, Rust build, package build, docs status, benchmark acceptance, generated-board release gate, KiCad Oracle, release-gate summary, dependency audit, SAST, CodeQL, and Docker smoke.

## External tools and skips

Checks involving external tools such as KiCad or ngspice must distinguish pass, fail, and approved skip. Missing external tools must not be silently reported as success.

## Evidence quality

EDA behavior should be tested using verifiable evidence when practical:

- ERC/DRC findings;
- KiCad oracle JSON/text reports;
- proof-pack artifacts;
- manufacturing ZIP manifests;
- benchmark reports;
- generated files with stable hashes;
- negative/known-failure fixtures.

## Coverage

The Python package coverage gate is configured in `pyproject.toml`. Coverage is a floor, not a proof of correctness; generated electronics still require engineering review.
