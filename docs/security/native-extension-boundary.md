# Native Rust and PyO3 Boundary

ZapTrace's `zaptrace_core` crate accelerates placement and routing and is loaded by Python as `zaptrace._core`. The crate and its PyO3 interface are supported security-sensitive code. This document defines the tested boundary, mandatory evidence, limits, and non-claims.

## Supported native targets

The release workflow currently builds and tests these wheel targets. The authoritative support levels, source fallback, and unsupported guidance are in the [distribution support matrix](../installation/distribution-support.md):

| Runner | Rust target | Python ABI |
|---|---|---|
| Ubuntu latest | `x86_64-unknown-linux-gnu` | CPython 3.13 |
| macOS 15 Intel | `x86_64-apple-darwin` | CPython 3.13 |
| macOS latest Apple Silicon | `aarch64-apple-darwin` | CPython 3.13 |

A wheel is not eligible for upload merely because it compiled. The exact built wheel must be installed into a clean virtual environment, pass the mandatory native boundary verifier, and pass the broader distribution smoke contract before the wheel upload step runs.

## Boundary architecture

The native code is divided into:

1. pure Rust placement/routing kernels;
2. shared validation and typed native errors;
3. thin PyO3 wrappers that convert valid results and controlled failures into Python values/exceptions.

Public PyO3 collection parameters accept concrete Python `list` values. Their lengths are checked against the documented limits before PyO3 converts any element into a Rust `Vec`, so an oversized list cannot force a second native allocation or trigger element conversion first. Kernel working buffers are allocated only after the remaining finite-value, geometry, and index validation succeeds. Unexpected Rust panics are caught at the wrapper boundary and converted to a fixed `RuntimeError` rather than unwinding through Python. Expected invalid inputs become `ValueError`.

## Explicit resource limits

| Resource | Maximum |
|---|---:|
| Components per placement call | 1,000 |
| Placement connections | 10,000 |
| MST points | 2,000 |
| Shove connections | 10,000 |
| Shove obstacles | 2,000 |

Inputs above these limits are rejected before PyO3 element extraction and before the corresponding result/working buffers are allocated. Floating-point coordinates, board dimensions, spacing, and clearance must be finite. Dimensions must be positive, spacing/clearance must be non-negative, and connection indices must refer to existing components. Derived routing values are checked again so arithmetic overflow from extreme but finite inputs cannot produce `NaN` or infinity in native outputs.

## Mandatory verification

### Direct Rust tests

The crate test suite covers:

- deterministic placement, MST routing, and shove routing;
- finite outputs and board-bound invariants;
- invalid indices and degenerate geometry;
- NaN/infinity rejection and derived-value overflow rejection;
- empty/single-item behavior;
- exact resource-limit boundaries;
- panic containment in the shared boundary guard.

The required commands are:

```bash
cargo fmt --manifest-path zaptrace_core/Cargo.toml --check
cargo clippy --manifest-path zaptrace_core/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path zaptrace_core/Cargo.toml
```

### Installed-wheel boundary evidence

`scripts/ci_native_boundary.py` must run against the installed extension from a clean environment. When a wheel is supplied, the verifier rejects an extension loaded from the source tree. It records:

- source commit/ref/dirty state, with dirty source rejected;
- wheel filename, size, and SHA-256;
- actual extension path;
- configured limits;
- valid/deterministic placement and routing checks;
- negative-input exception checks;
- pre-extraction resource-limit rejection for concrete Python lists;
- same-process survival after rejected calls;
- deterministic evidence digest and explicit non-claims.

`ZAPTRACE_REQUIRE_NATIVE=1` marks native verification as mandatory. A missing extension is a failure, not a skip.

## Cargo advisory evidence

The Security workflow installs `cargo-audit` at the pinned version declared in `.github/workflows/security-scan.yml`, scans `zaptrace_core/Cargo.lock`, and retains:

- raw `cargo-audit.json`;
- normalized `cargo-audit-evidence.json`;
- a human-readable Markdown summary.

The normalized evidence binds the result to the Cargo.lock SHA-256 and tool version. Vulnerabilities fail strict mode. Warnings are counted and remain visible for maintainer triage.

## Failure semantics

| Condition | Result |
|---|---|
| Expected invalid input | Python `ValueError` |
| Unexpected caught native panic | Python `RuntimeError` with fixed non-sensitive message |
| Missing required extension | CI failure |
| Dirty source tree while binding evidence to a commit | CI failure |
| Source-tree extension used while claiming wheel verification | CI failure |
| Wheel verification check fails | CI failure; wheel is not uploaded |
| Cargo advisory found | Security workflow failure with retained evidence |

## Reproducing locally

```bash
cargo test --manifest-path zaptrace_core/Cargo.toml
maturin build --manifest-path zaptrace_core/Cargo.toml --out /tmp/zaptrace-native-dist
uv lock --check
UV_PROJECT_ENVIRONMENT=/tmp/zaptrace-native-smoke \
  uv sync --locked --all-extras --all-groups --no-install-project --no-build \
    --python 3.12
wheel="$(realpath /tmp/zaptrace-native-dist/*.whl)"
wheel_hash="$(sha256sum "$wheel" | awk '{print $1}')"
printf 'zaptrace-eda @ file://%s --hash=sha256:%s\n' "$wheel" "$wheel_hash" \
  > /tmp/zaptrace-native.requirements.txt
uv pip install \
  --python /tmp/zaptrace-native-smoke/bin/python \
  --no-deps \
  --require-hashes \
  -r /tmp/zaptrace-native.requirements.txt
cd /tmp
ZAPTRACE_REQUIRE_NATIVE=1 /tmp/zaptrace-native-smoke/bin/python \
  /path/to/zaptrace/scripts/ci_native_boundary.py \
  --wheel "$wheel" \
  --source-root /path/to/zaptrace \
  --target x86_64-unknown-linux-gnu \
  --output /tmp/native-boundary-evidence.json \
  --markdown /tmp/native-boundary-evidence.md \
  --strict
```

## Non-claims

This boundary does not establish formal verification, constant-time behavior, real-time guarantees, qualified safety, or immunity from denial-of-service. It does not prove that all platform/toolchain combinations are safe. Native evidence is one layer alongside code review, SAST, dependency review, fuzzing, release provenance, and human engineering review.
