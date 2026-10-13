# AI-native #33: native USB-C S1 copper fixture and KiCad ERC coverage

Scope: USER-APPROVED MSI LOCAL ONLY. No GitHub mutation or manufacturing approval.
This is NOT an actual placed/routed board. Source candidate remains unchanged.

## Four physically separate USB-C shield pads

GCT USB4105-15-A-120 has four distinct S1 plated-through shield pads.
The 52/52 prior crossprobe result compared logical net/pad IDs; it did not
establish physical copper continuity. The source candidate has no finished PCB.

The new system pcbnew 10.0.7 script first checks source manifest SHA and the
original pinned GCT vendor asset SHA. It compares all 22 original physical pad
IDs, coordinates and dimensions with the candidate's physical geometry.
It then produces two connector-only PCB fixtures, saving and reopening both
with native KiCad. J1 has four distinct S1 UUIDs, all on GND.

- Same GND name, zero tracks: 3 unconnected items from native pcbnew AND
  independent kicad-cli PCB DRC JSON.
- Three synthetic B.Cu tracks joining the four S1 centers: 0 unconnected
  items from both native verification mechanisms.
- The synthetic fixture still has other serious KiCad DRC violations
  (clearance, holes, mask, missing outline), so PCB DRC is BLOCKED.
  A reduction in connectivity violations is NOT production readiness.
- This is a connector-only experiment, NOT copper on the actual full source
  candidate board. Actual candidate S1 routing remains NOT VERIFIED.

Run from MSI checkout using system KiCad Python:

    /usr/bin/python3 -B scripts/ai_native_pilot_shield_pcb_oracle.py \
      --candidate-dir build/qa-038-physical-pin-source/candidate \
      --output-dir build/qa-039-usb-shield/new-shield-fixture

The target must not exist. Malformed/tampered candidate/footprint geometry and
output overwrite requests fail closed.

## Four previously disabled KiCad ERC checks

Original KiCad 10 default ignored-check entries:
single_global_label, four_way_junction, simulation_model_issue and
footprint_filter. A separate strict KiCad project copy now sets all four to
WARNING rather than IGNORE, then re-runs genuine kicad-cli ERC with full
severity and violations-exit-code flags. Source project is untouched.

Measured strict-copy native ERC:
- 0 ignored checks; 0 reported error/warning/exclusion findings
- KiCad 10.0.7 CLI exit code 0
- Explicitly ENABLING checks, not waiving errors or hiding findings.

The ordinary default ERC remains separately marked BLOCKED due to its four
ignored rules. The strict-copy scoped ERC is clean, but independent SPICE is
still NOT CHECKED because ngspice and validated device models are missing.
The review schematic exporter does not encode complete manufacturer electrical
pin direction semantics (it uses passive symbol pins), so a clean KiCad ERC
does NOT prove actual hardware correctness, supplier/device approval or PCB DRC.

## Reproducible local artifacts

- Original SHA-bound source: build/qa-038-physical-pin-source/candidate/
- Strict independent ERC: build/qa-039-usb-shield/candidate-strict-oracle/
- Real connector-only KiCad PCB fixture:
  build/qa-039-usb-shield/strict-geometry-fixture/
- Evidence files are oracle-evidence.json and evidence.json respectively.
- KiCad actual .kicad_pcb, ERC/DRC JSON and tracked copper are available
  under local fixture subdirectories.

Next: obtain a real same-candidate PCB layout with grounded connectivity,
realistic shield routing, DRC, full pin/power constraints and independent
manufacturer review. This fixture is not a shortcut to #35 acceptance.
