# ZapTrace Review Studio — professional UI and EDA acceptance ledger

## Scope and version boundary

The earlier **0.1.8 exact Debian package** remains immutable,
unsigned, local-only and non-GA, SHA-256
`e78cf78c6cba3829aa3335793c5dba1ca4c77a311a9b9ae26a4e5f356953e1ec`.
These post-0.1.8 improvements are now in a separately versioned **0.1.9
unsigned local release candidate**. The new exact .deb passed all nine
release stages and a genuine Ubuntu 24.04.1/KiCad 10.0.7 APT
0.1.1→0.1.9 upgrade, native workflows, SHA-bound private backup restore,
real `apt remove`, and Chrome tests against identical package bytes.
0.1.9 .deb SHA-256: `cabe24ffa4d5a6138c8fd1abec2c5bb0ab73b2d5fcccea774a9712bf8005b11d`.
Offline 0.1.9 kit SHA-256: `6ec912dec9a61d9d3eb5343bc7e7d08ad2291d266cd771dc7e7bfbf89191002f`.
Independent physical-user, publisher signing, full EDA and fabrication
acceptance have NOT been established. Every future package revision must
again receive separate versioning and actual exact-package qualification.

## Verified workspace UX improvements after 0.1.8

- Corrected stale 0.1.7 labels in the workspace to 0.1.8 source branding.
  Clearly distinguish **offline/read-only snapshot inspection** from the
  **localhost-only guarded ECO drafting** mode; neither is fab approval.
- Added a visibly focusable *Skip to main content* link, keyboard `/` project
  search shortcut, `Escape` search reset without stealing input focus,
  accessible live search counts, a clear-filter action and no-result state.
- Increased dense PCB and evidence-card type sizes, enlarged touch targets,
  and fixed the tablet layout where search collapsed to about 65 CSS pixels.
  Measured source-backed search widths after fix: 540px at 1440, 728px at 768,
  368px at 390, and 298px at 320. No page-level horizontal overflow.
- Preserved the operating-mode warning on small phone viewports. Applied
  consistent `:focus-visible` and reduced-motion behavior; no forced
  scrolling animations for users requesting reduced motion.
- Blocked drafts with invalid inputs show a distinct error treatment and
  assertive accessible alert; completed native checks are not styled as errors.
  Neither error handling nor keyboard focus initiates an unsupported ECO.
- For externally registered *actual native reviews*, the localhost server
  now rewrites only registered evidence links to deterministic opaque URLs,
  and independently validates each GET against the approved review directory
  and a rendered-asset suffix allowlist. Native PCB/SCH files, unregistered
  siblings and directory traversal remain inaccessible. Externally registered
  HTML is served with an **opaque-origin CSP sandbox** (no same-origin, no
  connect-src and no forms), preventing access to the privileged localhost
  review application's capability. Only inherited-sandbox popups are allowed
  so the genuine KiCad evidence report can open in a separate tab without
  escaping the restricted origin; real Chrome verified this behavior. Browser tests verified that genuine
  thumbnail images and the linked independent native viewer both load,
  including 110 real pads, seven native copper/silkscreen layer controls
  and ten true KiCad-rendered images. The older native review's *Projects*
  back link is rewritten only in the served HTML bytes to the current
  localhost catalog. A real 390px Chrome mobile navigation cycle returns
  to the original two verified projects; source HTML is unchanged.
  Truly missing preview assets are explicitly reported without synthesizing
  PCB/copper artwork.

## Evidence and repeatable acceptance

`scripts/review_studio_accessibility_browser_smoke.mjs` exercises real Chrome
CDP using the caller's **local** Chrome port. The main QA used Chrome 155
on a disposable local browser session and two
previously generated, real KiCad reviews with distinct SHA-256 values:
`build/native-review-baseline` and `build/native-review`. Test coverage:
search and comparison of two real source snapshots, keyboard-only commands,
accessible control names, failure alerts, real preview image decoding,
reviewer navigation, no unexpected JavaScript exceptions, and 1440/768/390/320
CSS-pixel responsive layouts. It can also run with a zero-review workspace.
Tests execute without fabricating PCB evidence or uploading any design online.

`tests/test_review_studio_local_server.py` checks the opaque review URLs and
negative reads for unregistered private files, source `.kicad_pcb`, sibling
paths, invalid tokens and traversal. `tests/test_review_studio_workspace.py`
checks truthful workspace labeling, search/focus hooks and the unchanged
unapproved engineering posture. Native ECO integration and source SHA
regressions remain separate engineering gates.

## NOT accepted; must be verified before claiming a finished product

1. **Full CAD interaction:** KiCad-grade schematic symbol placement, real
   wire/net/bus editing and hierarchy; route-aware PCB copper, via, keepout
   and zone editing; coherent schematic-to-PCB updates; undo/redo at every
   editable level. Existing value-only schematic and isolated unrouted
   footprint translation/quarter-turn drafts are not equivalent.
2. **Complete product-wide UX:** keyboard and screen-reader assisted
   journeys in every PCB/schematic/3D view, verified tab/focus ordering,
   dialog restoration, nonvisual engineering details, all hover/tooltips,
   large source graphs, offline errors, and high-zoom/reflow layouts.
   The current workspace checks **do not** establish WCAG 2.2 AA conformance.
   Refer to W3C WAI for current focus visibility and target size criteria:
   https://www.w3.org/WAI/WCAG22/Understanding/focus-visible
   https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/
3. **Fidelity and performance:** full multi-hundred-device boards,
   independent KiCad copper/net/DRC/ERC/DFM evidence, 3D vendor STEP coverage,
   arbitrary camera orbit, rendering budget and responsiveness stress tests,
   and reproducible crash/recovery/undo scenarios with user fixtures.
4. **Distribution and trust:** independent physical Ubuntu user-machine
   acceptance, official publisher identity/signature, commercial license
   authority, real KiCad desktop/CLI rule parity and engineering/fabrication
   sign-off. No current test authorizes these states.
5. **Native editing architecture:** KiCad 10 pcbnew SWIG APIs work for the
   current native fixtures, but KiCad upstream has deprecated their Python
   SWIG binding and recommends the stable IPC API for future integrations:
   https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/
   A KiCad-11 migration must be explicit and tested, not assumed compatible.

All 0.1.9 acceptance results are engineering milestones. The product may be improved
iteratively, but *“professional, flawless and completely working EDA”* must
remain **NOT VERIFIED** until each outstanding acceptance item passes.


## Post-0.1.8 native schematic↔PCB preflight UI

An explicit local-only read-only analysis form now accepts a KiCad schematic
and PCB. It uses authentic KiCad netlist/PCB data, displays detailed mismatches,
and never silently associates pin/pad numbers or authorizes a source update.
Actual Chrome demonstrated 14 shared references and five source-backed
ESP32 `Value` differences, with clear `UUID linkage verified: NO`,
`Automatic sync: BLOCKED`, and `NOT APPROVED` warnings at 390px.
No evidence changes the CAD authoring/fabrication incompleteness above.

## Post-0.1.9 source-only UI: real UUID and pin/net audit

A linked native KiCad 10 board test **copy** with full schematic KIIDs shows
`UUID linkage verified: YES (14/14)`, whereas the unchanged actual ESP32
source shows `NO (0/14)` and 14 native PCB path-missing findings. An
accessible expandable evidence panel displays those precise path issues,
not a reference-name guess. A second panel shows 123 actual unmapped
pin-number identifiers and any literal net-name discrepancies, separating
112 physical pads from 86 unique pad labels. Both use real file-picker
uploads, authenticated localhost KiCad engines and Chrome 155, with 390px
no-overflow validation, no JavaScript exceptions and unchanged originals.
Even the UUID-positive test copy displays `Automatic sync: BLOCKED`,
`Pin/net ... NOT VERIFIED` and `Fabrication: NOT APPROVED`.
These are post-0.1.9 local-source improvements, NOT in the previously
QA-qualified (unsigned) 0.1.9 distribution bytes.


Actual Chrome's user-facing parity-audit **JSON download** was exercised with
native KiCad source files. The downloaded bytes contained the exact selected
source SHA-256s, the real 123 pin ID differences, and the no-auto-sync/no-fab
prohibitions. Only own temporary browser and download folders were removed.

## Further source-only: native KiCad 10 parity-positive project in Chrome

Real Chrome 155 was exercised twice: an immutable older ESP32 source pair
correctly shows 14 absent UUID links, 5 Value mismatches and 123 different
pin identifiers, while the newly generated physical-pin/UUID/global-net
project shows **14/14 source paths, 47/47 connected physical pins, zero
Value/footprint discrepancies and no literal net-name mismatch**, with
38 PCB-only pad identifiers explicitly visible. Both test actual private JSON
downloads against original file SHA-256s, mobile 390px reflow and zero JS
exceptions. Independent CLI `--schematic-parity` now proves **0 schematic
parity errors** but finds 42 PCB physical DRC violations and 37
unconnected items. GUI displays are technical review results, never F8
authorization or fab readiness. Not included in old 0.1.9 RC binary.

## Post-0.1.9 actual full vendor footprint browser regression

The previously QA-qualified but unsigned 0.1.9 SHA archive is unchanged. With selected native supplier
embedding work adapted locally from PR #119, Chrome 155 exercised the
authenticated read-only parity UI against both genuine inputs:

- Old source-bound ESP32 KiCad design: still fails closed on absent native
  KIID paths, physical pin labels and the five component field differences.
- Newly generated exact-vendor KiCad design: authentic 14/14 KIID paths,
  47/47 connected pin IDs, zero field/net differences, and **39 unbound PCB
  pad identifiers** including an anonymous unnumbered mechanical pad ID.

The Chrome test verified SHA-256 values in an actually downloaded private
JSON file for each source, 390px no-overflow layout, zero runtime JS
errors and refusal to authorize automatic sync or fabrication. The
corresponding independent KiCad DRC still has 16 physical violations
and 37 unconnected items. These results are source-only and do not
constitute an independently signed or GA 0.1.10 installer.


## Post-0.1.9 real Chrome 155 guarded native copper editing controls

Actual, authenticated localhost Chrome was used with a freshly generated
SHA-pinned full portable ESP32 KiCad ZIP. Source-only Review Studio now
reveals an **experimental native copper link** panel only in authenticated
localhost mode, with accessible file selection, a select populated from
37 genuine KiCad DRC unconnected pairs, bounded optional
`[x_mm,y_mm]` waypoints, guarded single-link submission and
private ZIP/evidence downloads plus discard. The selected U1.2↔U1.3
connection lowered KiCad unconnected from **37 to 36**, with **16
unchanged physical DRC failures, zero native schematic parity failures**
and **no manufacturing/electrical approval**. The test downloaded both
result files via real user-facing Chrome controls, checked the ZIP
evidence, then discarded the draft and re-hashed the original uploaded
ZIP; viewport 390px, no horizontal overflow, **zero JavaScript errors**.

The earlier QA-qualified unsigned 0.1.9 .deb and kit remain byte-identical
and **do not contain these newer controls**. This is an unfinished
source-only candidate, requiring a **new version**, an exact-package
browser/Ubuntu regression, and independent UX/fabrication review before
distribution.


### Real native KiCad copper visual acceptance on source-only localhost

The guarded copper page was further extended with an accessible,
sandboxed read-only **before/after native KiCad SVG comparison**.
The installed KiCad 10.0.7 CLI independently exported the original
and the route-bearing boards on F.Cu, F.SilkS and Edge.Cuts. Real
Chrome 155 exercised actual native source ZIP upload and 37-link
discovery, selected a 0.20 mm same-net route, then loaded **two genuine,
different KiCad SVGs** into a source-only iframe with an explicit
NOT FABRICATION APPROVED notice. Both plot files and their static HTML
comparison were present in the downloaded authenticated project ZIP.
390px no horizontal overflow, source ZIP SHA unchanged, successful
private download/discard and zero browser JavaScript exceptions.
The earlier 0.1.9 package/kit never had these controls and remains
unchanged.


## Source-only post-0.1.10 dual-copper via controls

The authenticated Chrome 155 native copper panel adds a bounded
`Via indices` field. `[]` means unchanged single-layer F.Cu.
The explicit `[1,2]` with two intermediate coordinates requests two
0.60 mm through-vias and one B.Cu corridor. Invalid indices are rejected
before any native KiCad invocation; the server checks them again.
On changing the selected actual native pad pair, inspecting another ZIP,
or discarding a working copy, the editor resets the prior waypoints
and via indices, preventing accidental reuse across unrelated nets.

Real Chrome exercised BOTH an actual R3.2→R4.2 2-via GND route and
the pre-existing U1.2→U1.3 all-F.Cu route consecutively. Both reduced
native unconnected 37→36 with unchanged native 16 physical DRC,
a source-byte-identical ZIP, two native KiCad F/B copper SVG snapshots,
private authenticated downloadable evidence, 390px no-overflow viewport,
and zero JavaScript exceptions. This is an **unshipped source-only**
regression, not a claim about installed 0.1.10.

## 0.1.11 exact-package authenticated native copper UX acceptance

The previously unshipped post-0.1.10 `Via indices` and safe
geometry reset controls were separately packaged under unsigned
**0.1.11**. Actual Chrome 155 exercised the exact extracted `.deb`
and an **APT-installed Ubuntu 24.04.5** localhost server. A custom
`.kicad_dru` with sentinel-proven loading and independent native
default DRC yielded one explicitly selected F.Cu/B.Cu/F.Cu corridor
(two 0.60 mm / 0.30 mm through-vias) and a legacy F.Cu route in
the same authenticated browser session. Both preserved native
DRC 16→16, reduced open copper 37→36, produced genuine KiCad
before/after SVG, verified SHA-bound private downloads and discard.
Malformed/repeated indices are blocked in Chrome before job creation.
The portable source remains byte-identical. Real 390 px browser
layout had no horizontal overflow or runtime JavaScript exceptions.
No result implies schematic synchronization or fabrication signoff.
