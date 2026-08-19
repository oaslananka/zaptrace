# Critical Runtime Coverage

ZapTrace protects security-critical Python runtime boundaries with a repository-owned, module-level coverage gate. The gate supplements the repository-wide `75%` pytest threshold and Codecov trend reporting; it does not replace security review, negative-path tests, CodeQL, Semgrep, or SonarQube Cloud.

## Protected modules and approved baseline

The committed policy is `config/critical-runtime-coverage.json`. Its initial floors were measured on July 22, 2026 after issue #281 added cancellation-safe isolated execution and issue #284 added revision-bound evidence identity.

| Module | Owner | Approved floor | Protected boundary |
|--------|-------|----------------|--------------------|
| `zaptrace/mcp/server.py` | `@oaslananka` | 78.94% | MCP registration, authorization, capabilities, timeout, cancellation, audit, and session lifecycle |
| `zaptrace/agent/execution.py` | `@oaslananka` | 77.22% | Transaction-safe isolated mutators, worker termination, rollback, staged artifacts, and same-session serialization |
| `zaptrace/api/server.py` | `@oaslananka` | 91.34% | REST authentication, security headers, client address handling, rate limiting, and network startup policy |
| `zaptrace/api/routes/_session.py` | `@oaslananka` | 95.65% | REST principal resolution, session allowlists, object authorization, capability enforcement, and audit evidence |
| `zaptrace/security/objects.py` | `@oaslananka` | 99.21% | Ownership, delegation, inheritance, authorization, and cascading removal |
| `zaptrace/security/policy.py` | `@oaslananka` | 93.54% | Capability policy, dangerous-action classification, audit events, and secret handling |
| `zaptrace/security/release.py` | `@oaslananka` | 92.08% | State-bound release evidence, approval identity, component coverage, and fabrication export policy |
| `zaptrace/api/routes/release_export.py` | `@oaslananka` | 100.00% | REST release-export denial and evidence response boundary |

Floors use the unrounded Coverage.py percentage internally. The committed values are two-decimal floors just below the measured baseline so normal floating-point representation does not create false failures.

## CI behavior

Python 3.12 full-suite jobs generate both `coverage.xml` and `coverage.json`. The workflow then runs:

```bash
.venv/bin/python scripts/ci_critical_runtime_coverage.py \
  --coverage coverage.json \
  --policy config/critical-runtime-coverage.json \
  --output critical-runtime-coverage.json \
  --markdown critical-runtime-coverage.md \
  --strict
```

The `critical-runtime-coverage` artifact contains:

- `coverage.json` — the Coverage.py machine-readable input;
- `critical-runtime-coverage.json` — the identity-bound policy result;
- `critical-runtime-coverage.md` — the human-readable module table and violation list.

Tagged releases run the same strict gate and upload `critical-runtime-coverage-release` before distribution jobs can proceed.

Changes to the policy, validator, `quality.yml`, or `release.yml` force a Python 3.12 full-coverage run. Changes to MCP, API, agent execution, or security runtime code already select the full Python matrix.

## Fail-closed rules

The gate fails when:

- a protected module is absent from Coverage.py JSON;
- a module falls below its approved floor;
- `pyproject.toml` contains an omit pattern matching a protected module;
- global `coverage.report.exclude_lines` or `coverage.report.exclude_also` rules are configured;
- a protected source line uses `# pragma: no cover` without an exact active policy entry;
- an exception or source exclusion is expired, duplicated, stale, or references an unknown module;
- the policy, coverage JSON, or source identity is malformed.

The report embeds the shared [`EvidenceIdentity`](../security/evidence-identity.md), including the exact Git commit, ref, dirty state, lock hash, source-input hash, and toolchain identity. It also records SHA-256 hashes of the coverage input and policy.

## Reviewed exceptions

A temporary floor reduction must be committed in the policy's `exceptions` array and reviewed like any other security control change. Every entry requires:

```json
{
  "path": "zaptrace/mcp/server.py",
  "minimum_line_coverage": 75.0,
  "rationale": "Temporary refactor window with equivalent branch-level regression tests.",
  "approved_by": "@oaslananka",
  "tracking_issue": "https://github.com/oaslananka/zaptrace/issues/NNN",
  "expires_on": "2026-08-15"
}
```

An expired exception fails CI. Removing tests without a reviewed, time-bounded policy change cannot silently lower the approved baseline.

An exact source exclusion uses the same review fields plus `line`. Broad file, directory, or regular-expression exclusions are not accepted for protected modules.

## Responsibilities of external services

- **Repository critical-runtime gate:** exact protected-module floors, owners, exclusions, exceptions, and revision-bound evidence.
- **Codecov:** repository and patch coverage trends, annotations, and test analytics.
- **SonarQube Cloud:** new-code maintainability, reliability, security findings, and security hotspots.
- **GitHub Actions jobs:** explicit Rust/native, KiCad, container, hardware, proof-pack, and external-tool results. Missing prerequisites must be reported as pass, fail, or approved skip; they must not disappear into Python line coverage.

These controls are intentionally complementary. A green percentage is not proof that the runtime is secure, correct, fabrication-ready, or safe without qualified engineering review.

## Local verification

Run the focused negative-path suite and produce a local report:

```bash
.venv/bin/pytest -q \
  tests/test_mcp_server.py \
  tests/test_object_authorization.py \
  tests/test_transactions.py \
  tests/test_api_release_gate.py \
  tests/test_release_evidence.py \
  --cov \
  --cov-fail-under=0 \
  --cov-report=json:coverage.json

.venv/bin/python scripts/ci_critical_runtime_coverage.py \
  --coverage coverage.json \
  --policy config/critical-runtime-coverage.json \
  --output critical-runtime-coverage.json \
  --markdown critical-runtime-coverage.md \
  --strict
```

The full Python 3.12 suite remains the authoritative coverage input used by CI.
