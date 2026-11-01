# Review Studio — native schematic visuals and local proposal alternatives

Scope: Issue #31 source-only development. This is not a signed engineering approval, public release, automated merge, or hardware-fabrication authorization.

## Source-linked schematic review

Run the existing `review_studio_change_diff.py` with the required original/proposed PCB and ECO evidence paths plus optional `--schematic-source` and `--schematic-candidate` paths. Both schematic paths must be given together. KiCad 10 exports actual single-sheet SVG plots, netlists and ERC reports. The viewer offers current/proposed/side-by-side/overlay, image zoom, a native symbol position highlight and keyboard-accessible ERC rule/reference details.

All source and project/custom-rule SHA inputs, exported netlist identity, native ERC findings and DRC semantics are checked. Unrecognized ERC report grammar, ambiguous source/target, symlinked rule files and plotting beyond one verified sheet are rejected. The viewer does not claim pin-level PCB ↔ schematic electrical parity, electrical approval, or an authenticated reviewer.

The `state_hash` uses stable source, rule and semantic evidence (`native_source_and_semantic_evidence_v2`). Raw SVG, netlist and ERC export bytes and their own digests remain in the offline evidence but may contain KiCad creation timestamps. Identical sources and semantic evidence therefore retain the same decision identity across repeated exports.

## Multiple independent proposals

To compare two to eight existing native reviews, invoke:

```sh
python3 scripts/review_studio_proposal_comparison.py \
  --review-state <option-a.state.json> \
  --review-state <option-b.state.json> \
  --output <fresh-alternatives.html>
```

The saved-state navigator checks matching original PCB, schematic and rule contexts; distinct proposal identities; canonical state hashes; corresponding embedded HTML data; and explicit unsigned/no-fabrication conditions. It shows DRC and schematic value differences with separate links to each independent native review. It does NOT freshly re-run KiCad, prove imported snapshots authentic, modify copper, apply multiple ECOs to one board, select a winner, or merge alternatives.

## Local acceptance and outstanding risks

Real KiCad 10.0.7 source fixture: R1 4.7k original, 10k and 2.2k alternative values; each isolated candidate retains 0 native ERC errors and 28 warnings. Source/real-Chrome/screenshots and SHA evidence reside in the ignored local `build/qa-031-schematic-visual/` directory. See automated `test_review_studio_change_diff.py` and `test_review_studio_proposal_comparison.py` for negative cases.

Remaining Issue #31 work: authenticated/signed accountable engineering review, true synchronized pin/net cross-probe, in-place multi-footprint ECO validation, independent hardware-user accessibility and time-to-trustworthy-decision tests, and complete exact-source Ubuntu package acceptance. The actual ESP32 board still has unresolved physical DRC/routing/3D/manufacturing blockers; clean isolated fixture checks must never be substituted for those results.
