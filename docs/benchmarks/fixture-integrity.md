# Benchmark Fixture Integrity

Benchmark fixture coverage proves required files exist. Benchmark fixture integrity proves the committed fixture files are internally consistent enough to use as regression evidence.

The integrity gate validates every board family in the benchmark manifest for:

- requirements JSON shape, release-blocking requirements, unique IDs, and visible non-claims;
- proof-pack manifest validity, required checks, and limitations/non-claims;
- golden KiCad fixture hash comparison;
- manufacturing export manifest warnings and non-claims.

## Generate integrity evidence

```bash
python scripts/ci_benchmark_fixture_integrity.py \
  --output benchmark-fixture-integrity.json \
  --markdown benchmark-fixture-integrity.md \
  --strict
```

The Quality workflow publishes the current identity-bound result in the `benchmark-evidence` artifact. Static committed reports are intentionally not used as current evidence.

Current expected result:

```text
Passed families: 12/12
Failed checks: 0
```

## Negative coverage

The test suite intentionally mutates fixture files to ensure the gate fails when:

- a release-blocking requirement is weakened;
- proof-pack limitations are removed;
- a golden KiCad file hash drifts;
- manufacturing export non-claims are removed.

## Non-claims

Fixture integrity is regression evidence only. It does not mean a board is electrically correct, fabrication-ready, manufacturer-approved, certified, production-ready, or safe to use without qualified human engineering review.
