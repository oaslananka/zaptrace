# Review Studio 0.1.7 · real KiCad footprint placement ECO

**Local engineering release candidate, not full-featured PCB CAD; zero production/fab signoff.**

This new opt-in, authenticated localhost workspace capability can translate
**exactly one unlocked, pad-unrouted footprint** in an existing native KiCad
10 `.kicad_pcb` by a nonzero ±5 mm offset on a 0.05 mm grid. Only a separate
native editable working copy is authored. It cannot reroute a connected pad,
resolve fabrication DRC errors, manufacture a board, or write to the original
KiCad design folder.

## User workflow

1. Open the installed Review Studio localhost workspace; select **Draft a PCB
   move**. Standalone `file://` review remains read-only.
2. Select an original `.kicad_pcb` via system file picker. Set an existing
   reference (for example `R1`) and X/Y movement in millimeters.
3. The authenticated origin-checked local browser bridge hashes and copies the
   file, using a UUID-isolated staging folder. Real `/usr/bin/python3`
   `pcbnew` 10 loads the PCB; rejects missing, duplicate or locked footprints,
   copper-zone boards and tracks with endpoints within the footprint's pad
   bounding boxes. It makes the move in memory, then saves only to a new file.
4. Native re-read verifies footprint identities, all existing copper tracks,
   unchanged net/layer/pad identities, all other footprint positions and
   exactly one move. Independent `kicad-cli pcb drc --format json` checks both
   native source and copy, requiring identical rule context, no new violation
   *identity* and no increase in unconnected items. If a check is unprovable,
   **no downloadable copy is created**.
5. The result includes two genuine `kicad-cli pcb export svg` F.Cu/F.SilkS/
   Edge.Cuts plots, synced zoom/pan, before/after DRC counts, SHA-256 manifest
   and a separately downloadable `.kicad_pcb`. The user explicitly chooses
   **Discard PCB move draft** to erase the private copy.

## Reproducible native test

```sh
/usr/bin/python3 -B scripts/review_studio_pcb_eco.py \
  --board tests/fixtures/review_studio_native_eco_placement.kicad_pcb \
  --output build/pcb-real-placement-proof \
  --ref R1 --dx 1 --dy 0.5
```

The test is not a fabricated preview: the fixture was authored in native
KiCad 10 using **two actual KiCad-library 0603 resistor footprints and one
50×35 mm Edge.Cuts rectangle**. Native `pcbnew` moves R1 from 20.0,20.0 mm
to 21.0,20.5 mm. Real KiCad 10 before/after DRC was **0 rule violations,
0 unconnected → 0 rule violations, 0 unconnected**; plot SVGs, source and copy
hashes were verified. The 61-copper-track ESP32 review board's connected R1
move was explicitly blocked. A contrived newly introduced DRC violation was
also blocked rather than called a valid layout. Invalid references and grid
values, zero moves and overwriting the source folder are rejected.

Actual localhost HTTP tests verified strict bearer/origin protection, source
hash integrity, private downloadable output, allowed file paths, independent
schematic ECO isolation and explicit result deletion. Actual Chromium
validated real local PCB file input, full native KiCad API and two authentic
copper plots, sandboxed preview (no user-origin grants or token leakage),
source-bound separate file download, 390px mobile view, no JavaScript errors,
and draft discard. **The same browser workflow was rerun using Python/HTML
extracted from the exact 0.1.7 .deb.** The exact SHA-bound `.deb` was then
real-APT-installed in a disposable fresh Ubuntu 24.04.1/KiCad 10.0.7
container, upgraded from 0.1.1. Installed native PCB *and* schematic ECO
passed; original user project SHA remained unchanged. Old ZIP restore, 3D,
multiple schematic sheets and APT removal preserved user data.

## Production and completeness limitations

- A track may cross a pad *between endpoints*; the current overlap guard only
  rejects pad-bounding-box **endpoint** touches. It is not a replacement for
  native drag-routing or a proof of copper continuity under every geometry.
  The DRC and native consistency checks are additional protections, not a
  comprehensive copper-collision certificate. More conservative segment/arc
  intersection protection is a prerequisite for general placement editing.
- Browser-based ECO accepts `.kicad_pcb` only. It does **not** yet upload the
  design's matching `.kicad_pro` or `.kicad_dru`. Therefore KiCad may use
  defaults in this workflow; the DRC comparison **must not** be represented as
  the production fab rules unless the actual rule context is independently
  established. The native CLI prototype does copy a physically adjacent
  `.kicad_pro` into both validation workspaces.
- This tool does not move existing traces, refill copper zones, edit board
  outlines, enforce antenna keepouts, sync schematic ECO, assess power/thermal
  performance, approve BOM or generate safe production outputs. A native DRC
  comparison may have pre-existing findings, and even DRC 0 alone is not
  production approval.
- The source has an explicitly noncommercial license. The unsigned local
  candidate has not passed independent physical user-machine acceptance or
  verified vendor STEP completeness. The release manifest keeps full EDA,
  publisher signing and fabrication authorizations `false`.

**Exact independently tested local artifacts:**

- `.deb` SHA-256: `e7a0d9cbe755420cccfb4c4a31ac6d6728ff3a2288dd2daebe7cd1deedec8471`
- offline local release ZIP SHA-256: `9472f1780e4a04c860dcf44c901ab22aeeeb01796d012b519dd1f5f26a04c0de`
- QA: `build/distribution/CLEAN_UBUNTU_2404_017_QA.txt` and
  `build/distribution/RELEASE_MANIFEST.json`

**Immediate next implementation target:** copy-on-write KiCad project-rule
context upload and verified use, then robust track/arc intersection rejection
and real safe native route-aware footprint drag. Keep the original and saved
manufacturer rules immutable until all independent checks pass.
