# AGENTS.md

## Scope

This file applies to `zaptrace_core/**` and supplements the repository-root `AGENTS.md`.

The native crate is a supported security-sensitive boundary. It accelerates placement/routing and is exposed to Python as `zaptrace._core` through PyO3. Read `docs/security/native-extension-boundary.md` before changing native validation, PyO3 wrappers, resource limits, error semantics, packaging, or installed-wheel verification.

## Boundary architecture

Preserve the intended layering:

1. pure Rust placement/routing kernels;
2. shared validation and typed native errors;
3. thin PyO3 wrappers that convert validated results and controlled failures into Python values/exceptions.

Keep Python-facing wrappers thin. Domain computation belongs in testable Rust logic; Python conversion and exception mapping belong at the boundary.

## Validation invariants

Validation must happen before expensive or attacker-amplifiable work.

Preserve these invariants unless the documented security contract is intentionally revised:

- collection/resource limits are checked before PyO3 element extraction where the public boundary requires it;
- finite-number checks reject NaN and infinity;
- dimensions and geometry constraints are validated before kernel work buffers are allocated;
- indices are validated before use;
- derived arithmetic is checked so extreme finite inputs cannot silently create non-finite output;
- rejected inputs must not corrupt subsequent calls in the same process.

Do not move allocations, element conversion, or expensive computation ahead of checks that currently protect the boundary.

## Resource limits

The authoritative limits are documented in `docs/security/native-extension-boundary.md` and enforced in native code/tests.

Do not silently raise, remove, or bypass a resource limit. A limit change is a security-contract change and must update:

- implementation;
- direct Rust boundary tests;
- installed-wheel verification/evidence;
- relevant documentation;
- any repository policy or generated evidence that records the configured limits.

## Failure semantics

Preserve the public failure contract:

- expected invalid input -> Python `ValueError`;
- unexpected Rust panic caught at the boundary -> fixed, non-sensitive Python `RuntimeError`;
- missing extension when native verification is required -> failure, not skip;
- source-tree extension while claiming installed-wheel verification -> failure;
- dirty source while binding evidence to an immutable source identity -> failure.

Never allow a Rust panic to unwind through the Python boundary. Do not expose panic internals or other sensitive implementation detail in user-facing failure messages.

## Required Rust validation

For native changes, run:

```bash
cargo fmt --manifest-path zaptrace_core/Cargo.toml --check
cargo clippy --manifest-path zaptrace_core/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path zaptrace_core/Cargo.toml
```

When packaging/build behavior is affected, also exercise the repository build path:

```bash
task build-wheel
```

Use `task test-native` for the Python-side native test lane when relevant.

## Installed-wheel evidence

A successfully compiled crate is not sufficient release evidence.

For changes to PyO3 behavior, native validation, packaging, error conversion, resource limits, or the Python/native contract:

- build the wheel through the repository-owned Maturin path;
- install the exact built wheel into a clean environment;
- run `scripts/ci_native_boundary.py` with native verification required;
- preserve source identity and wheel digest binding;
- ensure the loaded extension comes from the installed wheel rather than the source tree.

Follow the reproducible command sequence in `docs/security/native-extension-boundary.md`; do not replace installed-wheel evidence with source-tree tests.

## Dependency and advisory changes

Rust dependencies are governed by `zaptrace_core/Cargo.toml`, `zaptrace_core/Cargo.lock`, and `docs/supply-chain/dependency-policy.md`.

- Keep the lockfile synchronized through Cargo.
- Treat parser, memory/resource, serialization, FFI, PyO3, and packaging dependencies as security-sensitive.
- Preserve Cargo advisory evidence bound to the exact lockfile digest.
- Do not suppress an advisory or loosen strict mode merely to make the security workflow pass.

## Cross-boundary changes

If a native change alters behavior visible from Python, inspect and update all applicable surfaces:

- Python fallback/wrapper behavior;
- tests under `tests/`;
- package/version/build configuration;
- public documentation;
- native boundary evidence scripts;
- release/distribution support policy.

The Rust and Python paths must not silently diverge in observable contract, validation, or deterministic behavior.

## Definition of done

A native change is not complete until the relevant direct Rust checks pass and, when the boundary or packaging contract changes, installed-wheel verification demonstrates the exact artifact behavior claimed.
