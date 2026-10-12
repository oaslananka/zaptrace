# Native KiCad copper link: source-only, fail-closed experimental proof

**Status:** the guarded single-layer copper UI was separately qualified in
the immutable, **unsigned 0.1.10 local candidate**. The optional
**two-through-via F.Cu → B.Cu → F.Cu extension described below is a NEW
post-0.1.10 source-only milestone**, not part of the SHA-qualified 0.1.10
Debian package or offline ZIP. It requires a **new version number and its
own exact-package/Ubuntu acceptance** before any installation or release
claims. No autorouter, KiCad F8 synchronization, independent manufacturing
review or electrical signoff.

## What is genuinely implemented

`review_studio_native_copper_link.py` makes **only an isolated, manually
specified single-net F.Cu connection** between two pad UUIDs that native
KiCad 10 independently lists as one unconnected pad pair. It accepts a
straight track or a user-specified polyline with up to **four** explicitly
supplied intermediate millimetre coordinates; each piece is a native KiCad
`PCB_TRACK` with 0.20 mm width. **New source-only extension:** on an
exactly two-copper-layer board, a user can additionally supply
`via_indices: [i,j]`, where `1 <= i < j <= number_of_waypoints`.
KiCad then writes an explicit F.Cu segment from start pad to waypoint
`i`, B.Cu tracks from waypoint `i` to waypoint `j`, and F.Cu from
`j` to the end pad. Exactly two native KiCad through-hole vias (0.60 mm
diameter, 0.30 mm drill) are placed on those two intermediate points.
All segments and both vias retain the requested original net.
`via_indices: []` or omission preserves the old all-F.Cu behavior.

No via is synthesized automatically and the route is NOT an autorouter.
A straight center-to-center route, a multi-segment polyline, and this
one F→B→F corridor are the only supported route shapes.

All preconditions and invariants fail closed:

- The project-local source assets are **immutability-hash-verified only**.
  This tool does not independently establish supplier provenance, verify
  vendor IPC manufacturing tolerances or approve downloaded footprint files.
- Real system KiCad 10 `pcbnew` and `kicad-cli`; a complete **project-local**
  `.kicad_sch`, `.kicad_pro`, `fp-lib-table`, `sym-lib-table`,
  `ZapTrace.kicad_sym`, original `ZapTrace.pretty` and its exact file hash
  evidence; each library table must contain **exactly one** respective
  project-local `KIPRJMOD` reference, with no linked inputs, additional
  external footprint libraries,
  filled copper zones, or untested custom `.kicad_dru` rules.
- Unique **physical pad UUIDs**, explicitly identical native KiCad
  `unconnected_items` endpoints; no guessed reference-only or
  name-only match. The two pads must share a nonzero KiCad net and F.Cu.
  Ordered UUID endpoints are required for user-supplied waypoints; otherwise
  KiCad's arbitrary pair enumeration might reverse a good polyline.
- Endpoints 0.2–20 mm apart; waypoint bounds inside the native board
  rectangle; no duplicate coordinates, NaN, infinity, booleans or large
  values; each segment 0.15–25 mm and aggregate length at most 60 mm.
  The via indices are two **strict integers**, ascending, between 1 and
  the actual number of intermediate waypoints; no blind user-defined
  via count, layer name, blind/buried/microvia or mixed-layer stackup.
  KiCad must report **exactly one** newly connected DRC item, never
  additional unintended connectivity.
- No original PCB/file changes. The native loaded PCB and exact asset
  hashes are captured before generating output. Identical baseline and
  post-route `kicad-cli pcb drc --schematic-parity --severity-all --format
  json` environments, KiCad engine version, ignored rules, severities,
  DRC finding signatures, input pad/footprint state, and pre-existing
  traces are required. The native DRC **unconnected count must decrease**.
  Any new physical DRC finding or schematic parity difference blocks
  publishing. Existing mechanical DRC errors are **not waived**.
- KiCad `pcbnew.SaveBoard` renumbers some internal net codes and normalizes
  mechanical NPTH layer masks even without a route. An **unmodified
  duplicate baseline is serialized and independently DRC-compared against
  the original before any route is considered**; metadata checks are then
  performed against two equally normalized native board copies.
- Output is a separate newly created directory containing a complete,
  exact-source-hashed portable project, pre/post native DRC JSON and an
  `EVIDENCE.json` explicitly declaring
  `automatic_complete_routing=false`, `electricallyApproved=false`,
  `fabApproved=false`. Rejected routes produce no result directory.

The previously missing vendor pad instance UUIDs are now generated uniquely
and deterministically in `zaptrace/export/kicad_verified_embed.py`, rather
than allowing KiCad to assign fresh random IDs on each load. The full
ESP32 native DRC's **74/74 reported unconnected pad UUID endpoints**
then match real `pcbnew` pad UUIDs across independent KiCad reloads.

## Actual proof (source-only ESP32 pinned vendor-geometry reference layout)

Using the SHA-pinned, freshly generated **direct** KiCad project from
`issue91-design.yaml`, *not* the separate pipeline's alternate placement,
native KiCad 10.0.7 yielded **16 manufacturing DRC violations,
37 unconnected items, zero schematic parity issues**. The following
independently checked, copy-on-write additions each have **zero newly
introduced DRC findings**:

| Exact native pad pair | Net | Verified path | Open before → after |
| --- | --- | --- | --- |
| U1.2 → U1.3 | VCC_3V3 | 1.27 mm straight F.Cu, width 0.20 mm | 37 → 36 |
| U2.7 → U2.1 | GND | short straight F.Cu, width 0.20 mm | 36 → 35 |
| R3.2 → R4.2 | GND | R3.2 → (72.51, 58.8) → (77.51, 58.8) → R4.2, width 0.20 mm | 35 → 34 |

The selected routes are **provisional review-only**; 34 links and all
**12 `drill_out_of_range` + 4 `hole_clearance`** manufacturing
violations remain. These are not secure production routes on their own,
nor do they certify circuit functionality or RF/EMC, IPC trace capacity,
drill capability or fabrication constraints. The independently generated
*alternative pipeline placement* has different KiCad DRC findings; do
not transfer the exact reference coordinates or DRC counts between layouts.

## Example isolated local source-only CLI

A `pcbnew` inspection of your exact local PCB must first establish the
native endpoint UUIDs for a physically unconnected pair. This CLI never
guesses those IDs:

```sh
/usr/bin/python3 -B scripts/review_studio_native_copper_link.py \
  --board /path/to/portable/ESP32_I2C_Sensor_Board.kicad_pcb \
  --output /different/new/review-copper-artifact \
  --start-pad-uuid EXACT-DRC-SOURCE-PAD-KIID \
  --end-pad-uuid EXACT-DRC-TARGET-PAD-KIID \
  --waypoints-json '[[72.51,58.8],[77.51,58.8]]'
```

Use `--waypoints-json '[]'` (default) for a single straight segment.
In the **new source-only** two-via mode, keep the shown intermediate
waypoints but additionally supply `--via-indices-json '[1,2]'` to
connect exactly F.Cu → B.Cu → F.Cu using two 0.60 mm/0.30 mm
native KiCad through-vias at the shown intermediate positions. This
command is **not available in the frozen 0.1.10 installed package**.
Without that extra argument (`[]` by default), the original F.Cu
polyline remains unchanged.
The guarded engine is also available in the **source-only, authenticated
localhost UI** in `review_studio_workspace_template.html`. Select the ZIP
of the *contents* of the generated portable KiCad folder (root-level
matching `.kicad_pcb`, `.kicad_sch`, `.kicad_pro`, exact
`fp-lib-table`/`sym-lib-table`, `ZapTrace.kicad_sym` and
`ZapTrace.pretty/*.kicad_mod`). The native read-only inspection gives
a list of real unconnected KiCad pad pairs; select one and optionally
enter up to four `[x_mm,y_mm]` intermediate points in JSON. The server
rechecks the original source/archive SHA, exact physical pad UUIDs, native
KiCad 10 DRC parity, old and new copper inventories and complete supplier
assets. It publishes **only a separate private project + DRC/evidence ZIP**,
containing genuine pre/post KiCad 10 `F.Cu,F.SilkS,Edge.Cuts` SVG plots
and a sandboxed, static side-by-side HTML comparison. These are native
KiCad images, not an approximate router rendering; they are visual
evidence only and cannot replace clearance, EMC or manufacturing
qualification. An authorized browser may inspect the native comparison
in its isolated preview frame and download the private evidence.
Rejected routes publish nothing; users may discard their draft.
**Un-downloadable private copper drafts are cleaned on restart**;
users must download the ZIP before closing the local server.

Only known KiCad input sources are extracted. Prior
`*.kicad_netlist_evidence.json` is recognized by exact root basename
and deliberately **discarded instead of trusted**; arbitrary extra ZIP
members, symlinks, path traversal, ZIP bombs, wrong SHA, user-defined
library tables and unverified `.kicad_dru` are rejected. A newly
verified result is delivered via an authenticated capability and a
**per-artifact SHA-256**; if the file changes before download, HTTP
returns 404 rather than serving forged evidence. Discard deletes only
the owned private native copper copy; on restart unreachable private
drafts are removed without deleting registered project reviews.

KiCad 10.0.7 / Chrome 155 real source-only acceptance exercised:
native 37-item inspection, precise U1.2–U1.3 link,
`37→36` unconnected, `16→16` physical DRC, zero parity,
real source-bounded project ZIP and `EVIDENCE.json` browser downloads,
two genuine independent native KiCad SVG exports compared in a
sandboxed frame (and also stored in the evidence ZIP), 390px
responsive layout, zero browser JavaScript errors, original
archive SHA unchanged, and private draft discard. Authenticated server
integration tests include unsafe ZIP paths/symlinks, hostile library
references, wrong tokens, invalid pad/waypoints and private artifact
hash tampering.

**Still missing:** interactive canvas-based copper editing, full
pad-to-track and track-to-track authoring, native route undo history,
continuous net completion, manufacturing rules/provenance approval and
independent external user acceptance. This is NOT shipped in the old
0.1.9 package and is not fabrication ready.

See KiCad 10 official CLI and interactive routing manuals:
https://docs.kicad.org/10.0/en/cli/cli.pdf and
https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html .

## Independent cross-check against open PR #119's fixed-board partial routing

A **read-only extract from PR #119's head** (commit `8e6429bd`) was
executed solely against a **temporary, same-project copy** of the
digest-pinned ESP32 direct-export board. This was not merged, pushed,
published as an installer, or treated as a generic route generator.
Before and after native KiCad DRC report signatures were independently
compared, and the routed result was *also* checked with a second
`--schematic-parity --format json` invocation using a matching read-only
schematic/project copy.

On exactly this **100 × 75 mm reference placement**, the unmodified
PR-specific candidate generated **25 independently checked electrical
links and 61 native copper track segments**. Genuine KiCad 10.0.7
confirmed **37 → 12 unconnected items**, **16 → 16 unchanged physical
DRC violations**, and **zero schematic parity issues**. Remaining
links are categorized as **3 GND, 5 VCC_3V3, 2 VCC_5V and 2 I2C_SCL**
(unrouted items include pad-to-track and track-to-track cases that
the new pad-to-pad review-only engine does not support). Manufacturer
`drill_out_of_range` (12) and `hole_clearance` (4) are still present.
The independent candidate is **not complete routing**, not an
electrical-performance certificate or independently fab-approved.
The original single-F.Cu native copper editor is present in the
QA-qualified unsigned 0.1.10 local installer; the **new optional
dual-via/layer extension exists only in subsequent isolated source**.

PR #119's particular hardcoded route coordinates may NOT be re-used
for a newly placed or otherwise altered board. In particular, our
separate **pipeline-generated** ESP32 placement has different physical
DRC signatures from the direct-source reference placement, so
cross-layout metrics are never combined. The temporary PR copy must be
regenerated and the full DRC contract rerun if the board or KiCad
version changes.
