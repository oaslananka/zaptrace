# Testing Policy

## Required gates

Before merging non-trivial changes, run the relevant subset of:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
task test-fast
task test-lane-policy
cargo fmt --manifest-path zaptrace_core/Cargo.toml --check
cargo clippy --manifest-path zaptrace_core/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path zaptrace_core/Cargo.toml
```

## CI coverage

The `Quality` workflow runs linting, type checking, centrally classified Python 3.12 lanes, three duration-weighted coverage-enabled unit shards, fast uninstrumented unit/integration compatibility lanes on Python 3.13 and 3.14, combined coverage, Rust checks, package build, Docker smoke, benchmark acceptance, generated-board release gates, and KiCad oracle evidence. See [Bounded test lanes](test-lanes.md).

Native/PyO3 changes are high-risk changes and always select the full supported Python matrix plus heavy CI. The Rust job builds a wheel, installs that exact wheel into a clean virtual environment, and runs `scripts/ci_native_boundary.py` with `ZAPTRACE_REQUIRE_NATIVE=1`. A missing extension, source-tree extension, rejected evidence check, or missing evidence artifact fails the job rather than becoming a skip.

## Native extension testing

Direct Rust tests cover valid, invalid, boundary, deterministic, extreme-finite, and resource-limit behavior without depending on Python wrappers. Installed-wheel boundary tests separately verify list-length preflight before PyO3 element extraction, Python exception conversion, derived-value overflow rejection, and same-process survival after rejected calls. Every release-wheel matrix target repeats the installed-wheel verification before its wheel upload step.

The tested limits, supported targets, evidence schema, and non-claims are documented in [Native Rust and PyO3 Boundary](../security/native-extension-boundary.md).

## Coverage threshold

The Python coverage threshold is configured in `pyproject.toml` with `coverage.report.fail_under = 75`. Raising the threshold is encouraged only after the suite is stable enough to avoid blocking useful maintenance work.

Rust/PyO3 assurance is not represented as Python line coverage. It is evidenced by direct `cargo test`, warning-free Clippy, installed-wheel boundary checks, and retained per-target JSON/Markdown artifacts.

## Critical runtime coverage

Security-critical MCP, transaction-safe isolated execution, REST transport/authentication, object authorization, capability policy, release evidence, and REST release-export modules have exact owner-approved floors in `config/critical-runtime-coverage.json`. The strict validator and exception process are documented in [Critical Runtime Coverage](critical-runtime-coverage.md). Protected modules cannot be hidden by broad omit rules or unreviewed `pragma: no cover` directives.

## Component-library trust gates

Every committed component YAML is parsed through strict schema v2 with unknown-key rejection and mandatory per-field provenance. Quality CI enforces zero schema errors and compares current trust declarations against `config/component-trust-baseline.json`; component removal, trust downgrade, or an unsupported stronger claim fails the gate.

For any component declared `verified`, Quality CI additionally requires a matching `config/component-evidence-manifest.json` entry. `scripts/ci_component_evidence_gate.py` validates exact component identity, source identity/version/hash bindings for every critical field, matching review metadata, current lifecycle/sourcing evidence, the committed footprint-proof digest, semantic package/footprint/pin-map compatibility, and the existing risky-package policy. A verified component without valid bound evidence fails CI; heuristic records do not need placeholder evidence entries.

The repository gate permits honest `heuristic` records for bounded synthesis. Release and proof workflows must use release-eligibility evidence: `heuristic` and `curated` records require policy-scoped release and fabrication approval, while `placeholder` records always block. Component-level verification is not complete-board release evidence. The dated full-library snapshot is `docs/reports/component-library-audit-2026-07-27.json`.

## Evidence tests

For EDA behavior, tests should prefer observable evidence:

- ERC/DRC results;
- generated artifact snapshots;
- KiCad oracle evidence;
- benchmark reports;
- proof-pack records;
- manufacturing export manifests;
- installed native-wheel boundary reports;
- Cargo advisory reports bound to the exact Cargo.lock digest.

## Slow/external tests

Tests requiring external tools such as KiCad or ngspice must clearly distinguish pass, fail, and approved skip. The `external_tool`, `benchmark`, `hardware`, and `native` lanes retain skip counts in JSON evidence and fail when required execution is empty or entirely skipped. CI installs the declared external prerequisites and builds the native extension before those lanes. Required native tests additionally use `ZAPTRACE_REQUIRE_NATIVE=1` at the installed-wheel boundary, so an unavailable extension cannot become passing evidence.

## OpenSSF evidence

This document supports criteria requiring public documentation of when and how tests are run. A concise quality policy version is available at [Testing and Quality Policy](../quality/testing-policy.md).
