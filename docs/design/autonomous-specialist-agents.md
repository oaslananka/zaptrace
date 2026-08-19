# Autonomous specialist agents and candidate scoring

ZapTrace autonomous behavior is modeled as specialist contracts plus sandbox-first candidates. The implementation does not perform blind one-shot commits. It produces candidate lineage, machine-readable scores, verification decisions, release-gate decisions, and proof-pack evidence.

Implemented files:

- `zaptrace/agent/candidates.py`: specialist role contracts, candidate scoring, verification rejection, selection, release gate, and proof evidence export.
- `examples/agent-runtime/candidate-decision-log.json`: example lineage and selection record.
- `tests/test_agent_candidates.py`: contract tests for role coverage, candidate generation, scoring, rejection, release gate, and proof evidence.

Specialist roles:

- Architect Agent: requirements to structured intent and block architecture.
- Schematic Agent: schematic graph and known-good subcircuits.
- Constraint Agent: electrical, physical, manufacturing, and supply constraints.
- Layout Agent: sandbox placement and routing candidates.
- Verification Agent: ERC/DRC/DFM/BOM/proof gates and rejection reasons.
- Supply Chain Agent: BOM risk and provider provenance.
- Release Agent: explicit validation and approval gate before manufacturing export.

Non-claims:

- Candidate generation is sandbox-first and does not commit the primary design.
- Release export is impossible without passed validation and an explicit approval ID.
- Human review remains required before fabrication.
