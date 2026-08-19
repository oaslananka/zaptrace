# Release Verify/Repair Convergence

ZapTrace includes a bounded, evidence-first verify/repair orchestrator for release decisions. It coordinates existing engineering checks rather than replacing them with a second verification engine.

## Release policy

`VerifyRepairPolicy.release_default()` enables these domains:

- ERC
- native DRC
- KiCad ERC/DRC oracle
- manufacturer-aware DFM
- strict simulation evidence
- component and package supply-chain coverage
- baseline Proof Pack checks

The release policy allows at most three repair iterations. Only registered, code-owned ERC repair handlers may mutate the candidate automatically. DRC, DFM, simulation, KiCad, and supply-chain failures remain explicit blocking or human-review evidence.

Every run works on a deep copy of the supplied design. Gate adapters also receive copies so verification cannot silently alter the candidate. Each accepted repair records:

- before and after design-state SHA-256 values;
- semantic design diffs;
- typed patch and decision provenance;
- blocking-finding counts before and after;
- whether measured progress occurred.

## Deterministic stop reasons

A run ends with exactly one machine-readable reason:

| Stop reason | Meaning |
|---|---|
| `all-gates-passed` | Every configured gate passed and no applicable automatic repair remains. |
| `human-review-required` | The remaining failure can only be resolved or approved by a person. |
| `non-repairable` | A high-risk or unsupported failure has no safe automatic repair path. |
| `no-progress` | A repair produced no state change or did not reduce blocking evidence. |
| `iteration-budget-exhausted` | The configured repair budget ended before convergence. |
| `gate-execution-error` | A gate was missing, raised an exception, returned the wrong domain, or returned evidence for the wrong design state. |
| `repair-execution-error` | A repair adapter raised an exception or mutated state without returning typed repair evidence; the attempted state is discarded. |

Anything other than `all-gates-passed` blocks autonomous release.

## Proof Pack integration

The final JSON report is hashed before it is attached to a Proof Pack. The manifest `verify_repair` evidence contains:

- report path and SHA-256;
- policy version and SHA-256;
- initial and final design-state hashes;
- enabled domains;
- convergence status and final stop reason;
- gate-history and repair counts;
- blocking and human-review status.

A non-converged run creates both release-blocking `verify-repair` evidence and a separate `verify-repair-human-review` handoff record.

## Four-family automated benchmark

The Quality workflow runs four generated architecture candidates:

1. ESP32 USB sensor node
2. STM32 RS-485 industrial node
3. nRF52 BLE multisensor
4. RP2040 CAN node

The benchmark uses `VerifyRepairPolicy.automated_convergence()`. This policy intentionally enables **ERC only** and verifies that the bounded software repair loop converges from the pre-repair generated candidate. Each family retains its own `verify-repair.json`, including gate history and before/after repair evidence, plus a compact `repair-scorecard.json` bound to the verify/repair report SHA-256. The scorecard records iteration count, patch count, improving repair count, and initial/final blocking counts.

Run it locally:

```bash
python scripts/ci_release_verify_repair.py \
  --trusted-output-root . \
  --artifact-dir release-verify-repair-artifacts \
  --output release-convergence-report.json \
  --markdown release-convergence-report.md \
  --strict
```

The aggregate report is identity-bound to the source commit, dependency lock, policy implementation, schema, proof integration, and Quality workflow. Artifact, JSON, and Markdown paths are resolved inside `--trusted-output-root` before filesystem access; the benchmark refuses to clean or write outside that root.

## Non-claims

A four-family benchmark pass is not a release pass. The benchmark does not run or waive DRC, DFM, simulation, KiCad oracle, supply-chain, manufacturing, physical, EMC, safety, or qualified engineering-review gates. Those remain enabled and fail closed in the default release policy.
