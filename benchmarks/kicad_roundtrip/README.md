# KiCad Round-trip Fidelity Corpus

This corpus defines the measurable KiCad fidelity categories used by the ZapTrace release gate:

- schematic fidelity;
- net connectivity fidelity;
- footprint fidelity;
- constraint fidelity;
- board geometry/routing fidelity;
- manufacturing artifact fidelity.

Run the deterministic scorecard harness:

```bash
uv run python scripts/ci_kicad_roundtrip_scorecard.py --strict --output kicad-roundtrip-scorecard.json
```

Known unsupported features must be recorded under `unsupported_features` with a degradation explanation. They are never silently hidden.
