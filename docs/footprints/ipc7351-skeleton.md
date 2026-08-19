# IPC-7351-oriented land-pattern calculator skeleton

ZapTrace includes a small IPC-7351-oriented calculator skeleton for passive chip packages. This is an API and evidence foundation, not a complete IPC-7351 implementation.

## Current coverage

```text
0603 passive chip package
least / nominal / most density scaling
```

## API

```python
from zaptrace.ee.ipc7351 import calculate_ipc7351_chip

result = calculate_ipc7351_chip("0603")
footprint = result.footprint
proof = result.proof
```

The result includes:

```text
standard_family: IPC-7351-oriented
coverage: skeleton-passive-chip-only
density
fixture
footprint
proof
notes
```

## Proof requirement

Generated land patterns from this skeleton emit `FootprintProof` evidence. The proof should still be validated with `validate_footprint_proof()` and, for risky packages in future coverage, `validate_risky_package_policy()`.

## Fixture

A sample machine-readable calculator result is committed at:

```text
tests/fixtures/footprints/ipc7351_0603_result.json
```
