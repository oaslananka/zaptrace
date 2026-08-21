# Validation environment parity

ZapTrace has one authoritative full release environment: the GitHub-hosted
Ubuntu runner executing `.github/workflows/quality.yml` and
`.github/workflows/release.yml`. The workflows pin action revisions, validate
the committed lock, install the declared toolchain, and retain machine-readable
evidence.

## Environment roles

Run the parity gate with an explicit role:

```bash
python scripts/ci_validation_environment.py \
  --role authoritative-release \
  --strict \
  --output validation-environment.json
```

For local developer workstation diagnostics where optional simulation tools like ngspice provide degraded guidance rather than blocking development:

```bash
python scripts/ci_validation_environment.py \
  --role developer \
  --strict \
  --output validation-environment.json
```

A VPS or workstation is a `diagnostic-only` validator unless the strict report
passes every required tool and command:

```bash
python scripts/ci_validation_environment.py \
  --role diagnostic-only \
  --output validation-environment.json
```

Diagnostic-only hosts may reproduce subsets, investigate failures, and prepare
patches. They must not originate release artifacts or replace a failed gate with
an unrecorded local result.

## Required baseline

The authoritative role requires:

- Python 3.12 or newer and Astral `uv`;
- Rust compiler, Cargo, and project-provided maturin;
- KiCad CLI 9 or newer;
- Docker Engine and Docker Buildx;
- ngspice for release simulation evidence;
- the exact committed `uv.lock` state.

The JSON report records tool paths and versions, the exact `uv.lock` SHA-256,
locked MCP/FastMCP versions, environment role, and a deterministic policy hash.
Tool installation sources are the pinned GitHub Actions plus Ubuntu/KiCad
repositories declared in the workflows.

## Release validation command sequence

```bash
uv lock --check
uv sync --locked --all-extras --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest --cov=zaptrace --cov-report=term-missing
cargo fmt --manifest-path zaptrace_core/Cargo.toml --check
cargo clippy --manifest-path zaptrace_core/Cargo.toml -- -D warnings
cargo test --manifest-path zaptrace_core/Cargo.toml
uv run python scripts/ci_kicad_oracle.py --strict-skips --output kicad-oracle-summary.json
uv run python scripts/ci_generated_board_release_gate.py \
  --risky-package-reviewed \
  --risky-package-approval-id "GENERATED-BOARD-BASELINE-REVIEW-2026-07-22" \
  --strict \
  --output generated-board-release-gate.json
uv run python scripts/ci_kicad_roundtrip_scorecard.py --strict --output kicad-roundtrip-scorecard.json
```

## Drift detection

The scheduled Quality workflow runs daily and is the automated environment drift
check. A changed tool version, missing required binary, lock mismatch, or policy
fingerprint change produces new parity evidence and fails strict validation when
it breaks a required gate.

## Emergency release and rollback

Emergency releases still use a reviewed `v*` tag and the authoritative GitHub
Release workflow. A diagnostic VPS may help identify or prepare a fix, but it
cannot bypass the workflow. Rollback deploys an already attested GitHub Release
artifact and verifies its checksum/provenance; rebuilding the same version on an
unverified VPS is not an approved rollback procedure.

## Skip policy and non-claims

Release validation must not treat a missing external tool as a pass. Approved
oracle skips require explicit approval evidence; the default authoritative path
uses strict skips. Passing parity proves only that the environment can execute
ZapTrace validation. It is not evidence of electrical correctness, fabrication
readiness, manufacturer approval, production readiness, or certification.
