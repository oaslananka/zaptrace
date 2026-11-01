# Issue #31: Native multiple-footprint ECO acceptance (source-only)

## Objective and boundary

Run 2–4 distinct unrouted native KiCad footprint translations in isolated copy-on-write steps. Never alter the original PCB, project rules, the live GUI or immutable accepted Debian. This is not interactive copper routing, pin/net parity, electrical approval, signed review or fabrication authorization.

## Native invocation

Use system KiCad Python, with arguments:

- Program: /usr/bin/python3 -B scripts/review_studio_multi_pcb_eco.py
- Source: --board path/to/existing.kicad_pcb
- Fresh output: --output path/to/new-folder
- Two moves: --move R1,1,0.5 --move R2,-1,-0.5

Each existing one-footprint editor step checks pad-adjacent routed copper, locked footprint state, zones, the original and destination pad envelopes, exact native pad identities and save/reopen roundtrip, custom project/rule hashes, independent DRC and unconnected counts. The final source-to-proposal roundtrip checks all footprint UUIDs, pads/nets, geometry, track and zone inventory. A two-to-four-element ordered SHA chain is recorded and checked by the independent offline reviewer. Any failed step blocks publishing the candidate.

## View

Use review_studio_change_diff.py with --source, --candidate, --evidence and --output pointing to the original, output PCB, evidence manifest, and new local HTML. It regenerates native DRC, two KiCad SVGs, and displays every changed footprint. Each item is separately accessible by keyboard, without replacing legacy one-footprint or unsigned v1 decisions. Source and project/custom rule SHA are bound in state. Real pad/net electrical schematic parity is NOT established.

## Real QA / known limits

Ignored local evidence: build/qa-033-multieco/. Native KiCad 10.0.7 test fixture: R1 (20,20) to (21,20.5) mm, R2 (35,20) to (34,19.5) mm, four original pads total. Custom-rule loader probe successful; original/final DRC 0 to 0, open copper 0 to 0, no new violations. Real Chrome at 320/390/1440 px confirmed Current/Proposed/Overlay/Changed Only views, selection of both references, no overflow or runtime exceptions, source-verified SVGs and unsigned review decisions rejecting forgery. Python tests cover fabricated identities, rule/DRC/chain/geometry changes. No browser simulation can replace independent human acceptance.

The actual ESP32 board remains blocked by 16 unwaived physical DRC findings, incomplete routing and absent STEP/assembly/supplier review. Unrouted source fixture cleanliness cannot be presented as production release evidence. Connected copper edits, footprint rotations, pin-level schematic crossprobe and authenticated reviewer signatures remain pending.
