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

- The **packaged 0.1.7** overlap guard examines track endpoints only: a segment
  can cross a pad between endpoints, or newly touch a destination pad. Do not
  rely on that package for general PCB placement. A post-0.1.7 **local source
  hardening patch, not yet packaged or installed**, uses native KiCad bounding
  boxes for tracks, arcs and vias at both source and destination pad locations.
  This fails closed on intersecting copper but is deliberately conservative:
  a bounding-box intersection is not exact shape clearance, drag-routing, or
  complete physical/electrical continuity certification.
- The **packaged 0.1.7** browser ECO accepts `.kicad_pcb` only, and may fall
  back to KiCad defaults without a matching project. The newer **local source
  branch** accepts an optional hash-bound matching `.kicad_pro`, puts it in
  both DRC workspaces and bundles the PCB plus project in a ZIP. Actual use of
  each rule is **not independently attested**; the local evidence explicitly
  records `effective_rules_independently_verified=false`. Selecting
  `.kicad_dru` custom rules blocks the browser ECO rather than ignoring them.
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

**Immediate next implementation target:** independently attest native KiCad
custom-rule loading and applied project-rule semantics; then safely introduce
custom-rule-aware browser editing, native route-aware footprint drag and
full source-to-layout ECO synchronization. Keep immutable source hashes and
manufacturer DFM gates.

## 0.1.8 source branch · custom DRC loader probe and guarded PCB ECO

The 0.1.7 Debian package and offline kit listed above remain unchanged.
The new local 0.1.8 version has passed its complete nine-stage local release
gate, deterministic .deb build and disposable Ubuntu 24.04.1 real APT
0.1.1→0.1.8 upgrade, native KiCad 10.0.7 custom-rule/PCB/schematic/3D,
genuine 0.1.1 private ZIP restore and apt remove with source protection.
The exact .deb extraction passed live Chrome desktop/390px PCB+SCH ECO and
authenticated ZIP/download/discard, but **the browser ran on MSI**, not as a
GUI browser inside the Docker container. This is a locally qualified unsigned
release candidate, not independent physical user-machine GA acceptance.
Exact 0.1.8 .deb SHA-256:
`e78cf78c6cba3829aa3335793c5dba1ca4c77a311a9b9ae26a4e5f356953e1ec`.
Offline local RC ZIP SHA-256:
`a90ceaf9132af00bdfc3f4e7f571d485dc061aed3fc7d7ed488e74e69819f9d3`.

Native KiCad 10.0.7 confirmed a measurable rule-loading differential:
a two-footprint PCB has 0 courtyard violations without a special rule, and
a named 100 mm custom courtyard constraint yields 1 named violation.
A deliberately invalid custom file instead produced a misleading successful
CLI exit with no evidence that the invalid rule was enforced. Therefore, every
PCB ECO with a matching `.kicad_dru` runs an isolated **loader probe**:
a uniquely named 1000 mm courtyard rule is appended to a temporary copy only,
then native DRC must explicitly report its violation. The original rules are
never edited. Missing/ignored/invalid rule loads fail closed. This requires
an observable courtyard pair, and may reject otherwise valid small projects.
The probe does **not** certify all supplied rule semantics, GUI/CLI parity,
electrical adequacy or fabrication readiness. The evidence retains
`effective_rules_independently_verified=false` while separately recording
`custom_rule_loader_probe_passed=true` when observed.

The local PCB engine rejects track/arc/via geometry intersecting source or
destination pad bounding boxes. DRC comparisons also include violation
descriptions, not only type/severity/UUID, so an existing clearance violation
getting worse is rejected. Source, project, rules and KiCad plots use separate
copy-on-write folders and SHA-256. Unrouted footprint placement is still the
only PCB authoring operation; routed copper movement, zones, MCAD, schematic-
PCB synchronization and manufacturing signoff remain blocked.

The authenticated localhost editor accepts the original PCB and optional
same-basename project and custom-rule files, validates names, sizes and SHA
checksums, and returns a downloadable private ZIP containing exactly the
native PCB, supplied project/rules and evidence. The browser explicitly
distinguishes KiCad defaults, project context and verified custom loader
probe, with warnings about unverified effective rules. Native HTTP, actual
Chrome desktop/390px and browser discard tests were run in the local source
working tree. A verified SHA-bound packaged Ubuntu release needs separate QA.
