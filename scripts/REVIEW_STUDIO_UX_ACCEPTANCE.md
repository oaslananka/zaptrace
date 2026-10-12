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
