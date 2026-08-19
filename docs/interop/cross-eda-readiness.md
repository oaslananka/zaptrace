# Cross-EDA readiness and degradation policy

ZapTrace does not claim universal EDA compatibility. Cross-EDA support is defined by a versioned support matrix, measurable fidelity targets, and explicit degradation reports.

Machine-readable contract:

- support matrix: `data/interop/cross-eda-support-matrix.json`;
- degradation schema: `schemas/cross-eda-degradation-report-v1.schema.json`;
- example degradation report: `examples/interop/easyeda-degradation-report.json`;
- corpus plan: `docs/interop/test-corpus-plan.md`.

## Fidelity categories

The versioned categories are schematic, netlist, footprints, constraints, variants, stackup, manufacturing outputs, and metadata.

## M3 readiness gates

- Cross-EDA support claims must be `measured`, `delegated`, `degraded`, `unsupported`, or `planned_only`.
- A round-trip claim is allowed only when backed by a committed corpus and measurable target score.
- Unsupported features must appear in a degradation report rather than being silently dropped.
- Planned Altium, Eagle, and EasyEDA workflows must remain planned-only until their corpora exist.
- Release notes must not claim universal import/export compatibility.

## Non-claims

- ZapTrace is not a full GUI replacement for Altium, Eagle, EasyEDA, or KiCad.
- Planned-only adapters are roadmap items, not production support.
- Degraded imports require human review before fabrication.
