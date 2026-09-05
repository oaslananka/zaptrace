# Datasheet-backed component selection

ZapTrace selects component candidates before PCB layout by combining declared design constraints with governed library metadata. The selector is deterministic, explains every rejection and ranking dimension, and keeps **bounded synthesis** separate from **release or fabrication eligibility**.

A schema-valid component can be selected for exploration while still requiring human review. A heuristic record is never silently promoted to manufacturer-verified or fabrication-safe status.

Verified-trust qualification is a separate bounded workflow documented in [Verified component qualification](component-qualification.md).

## Public API

```python
from zaptrace.library.loader import LibraryLoader
from zaptrace.library.selection import (
    ComponentSelectionRequirement,
    select_component,
)

library = LibraryLoader().load_all()
requirement = ComponentSelectionRequirement(
    requirement_id="rail-3v3-regulator",
    position="U1",
    category="power",
    operating_voltage_v=5.0,
    operating_current_a=0.4,
    allowed_packages=["SOT-23-5"],
    required_footprint="SOT-23-5",
)

decision = select_component(
    requirement,
    [library["ap2112k-3.3"], library["ap2112k-3.3trg1"]],
)
```

`ComponentSelectionDecision` contains:

- the selected component id, or an empty id when every candidate is blocked;
- ranked `ComponentCandidateAssessment` records;
- hard-gate diagnostics with expected and observed values;
- score dimensions and explanations;
- extracted electrical, package, footprint, pin-count, and supply-risk constraints;
- trust tier, release eligibility, and human-review status;
- deterministic assessment and decision SHA-256 values;
- explicit non-claims.

Reversing the candidate input order does not change the selected component or decision hash. Equal scores resolve by component id.

## Pre-layout hard gates

Only candidates without error diagnostics enter the eligible ranking set.

| Diagnostic | Meaning |
|---|---|
| `category-mismatch` | Candidate category differs from the requirement |
| `voltage-limit-exceeded` | Operating voltage exceeds the configured utilization of the preferred rating |
| `current-limit-exceeded` | Operating current exceeds the configured utilization of the preferred rating |
| `power-limit-exceeded` | Operating power exceeds the configured utilization of the preferred rating |
| `package-mismatch` | Package is outside the allowed package set |
| `footprint-mismatch` | Library footprint differs from the required footprint |
| `pin-function-mismatch` | Required pin function is missing or different |
| `footprint-proof-blocked` | Attached pad/pin-map proof contains a blocking inconsistency |
| `footprint-proof-mismatch` | Attached proof belongs to another package or footprint |
| `datasheet-facts-blocked` | Datasheet facts have missing identity, stale/conflicting evidence, or another blocking validation result |
| `supply-risk-blocked` | Lifecycle, availability, provider footprint, or cache evidence exceeds the configured supply-risk ceiling |
| `release-eligibility-required` | The requirement asks for release eligibility but component governance blocks it |

Missing optional evidence produces review requirements instead of an invented pass. Missing voltage/current/power ratings are warning diagnostics; an explicit contradictory rating is a hard failure.

## Rating and derating semantics

The selector keeps these sources distinct:

1. recommended operating conditions;
2. absolute maximum ratings;
3. governed library fallback limits.

Recommended operating values are preferred. Absolute maximum values are a hard safety ceiling, not a target operating condition. Default maximum utilization is:

- voltage: 80%;
- current: 80%;
- power: 50%.

The thresholds are explicit fields on `ComponentSelectionRequirement` and can be made stricter for a design policy.

## Evidence attachments

`ComponentSelectionEvidence` can attach three existing ZapTrace contracts to one candidate:

- `DatasheetFactReport` for hashed facts, scope, confidence, and conflict validation;
- `FootprintProof` for package, pad, pin-map, pin-1, and courtyard evidence;
- `BomProviderResult` for lifecycle, stock, alternates, provider footprint, cache status, and provenance.

The selector does not fetch live web pages or parse external PDFs during CI. Tests and the representative corpus use committed offline data.

## Ranking

Candidates that pass all hard gates are ranked by these weighted dimensions:

| Dimension | Weight |
|---|---:|
| Constraint fit | 35% |
| Evidence and trust strength | 25% |
| Footprint and pin-map proof | 20% |
| Supply-chain risk | 20% |

A high score does not override a hard-gate error. Trust-tier scoring also does not change a component's declared trust tier or release eligibility.

## Representative prompt corpus

The committed corpus is `tests/fixtures/component_selection/prompts.yaml`. It contains 20 cases across 12 component categories, including two expected blocked outcomes. Every case uses explicit committed component ids, expected selection or block state, and deterministic decision-hash verification.

Run it with:

```bash
uv run pytest tests/test_component_selection_corpus.py -q
```

## Coverage gate

Quality CI runs:

```bash
uv run python scripts/ci_component_selection_gate.py \
  --corpus tests/fixtures/component_selection/prompts.yaml \
  --minimum-governed-parts 100 \
  --strict \
  --output component-selection-coverage.json
```

The dated repository snapshot is `docs/reports/component-selection-coverage-2026-07-27.json`. It records:

- 504 records with governed datasheet and footprint provenance;
- 20/20 representative prompt outcomes;
- trust-tier counts;
- verified and release-eligible counts;
- human-review counts;
- loader and corpus errors;
- non-claims.

All 504 current records are honest heuristic migrations. Their governed provenance counts toward coverage, but the report separately records **0 verified** and **0 release-eligible** records. Coverage must not be presented as manufacturer verification.

## Proof-pack evidence

`ComponentSelectionProofEvidence` stores the report path and SHA-256 plus typed `ComponentSelectionRecord` entries. Each entry includes:

- requirement and board position;
- selected component id;
- deterministic decision hash;
- human-readable rationale;
- extracted constraints;
- blocked and human-review status.

Autonomous sign-off maps the aggregate evidence as follows:

- one or more blocked selections: release-blocking `FAIL`;
- no blocked selections but human review remains: `WARNING` and human-review-required status;
- all selections eligible with no review requirement: `PASS`.

The proof evidence is runtime evidence and does not change the stable design/check identity.

## Non-claims

A passing decision proves consistency with the attached machine-readable constraints. It does not prove manufacturer approval, component authenticity, datasheet interpretation, current stock, procurement authorization, thermal adequacy, EMC/SI/PI performance, footprint geometry, assembly success, fabrication correctness, or physical board operation. Qualified engineering review remains mandatory before fabrication.
