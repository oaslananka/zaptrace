# ZapTrace Review Studio — local native KiCad engineering preview

**Local-only prototype. No commit, push, PR, production order or manufacturing approval.**
Requires KiCad 10.0.7 (`kicad-cli`, distro `/usr/bin/python3` + `pcbnew`), Node + Chrome for
optional browser smoke, and this local worktree's Python venv for the canonical pipeline.
All generated output lives under ignored `build/`.

## Open the current improved review

```bash
xdg-open build/native-review/index.html
```

To rebuild from the pinned original real PCB and the matching Issue #91 source design,
including the **improved, native KiCad A3 schematic layout**, use:

```bash
bash scripts/review_studio_native_local_build.sh
xdg-open build/native-review/index.html
```

The script reads `build/source-reference-readonly/issue91-design.yaml` (local source
copy, SHA-256 `eb04820edf793b8833dd6cf23a9c531402f52cf5af91c57c4f1a411787928c47`)
and the separately pinned real partial-copper PCB
`build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb`
(SHA-256 `fb3a0acbcafcdfe260a11eb6db216701c1b5ebf4eb57af4a6e46ce1e6b1eb2ce`).
The original generated schematic is also preserved unchanged alongside them
(SHA-256 `94320325897c18912cc841f4e80031df6b6b540e7e4d1917815cc24d8d52f00c`).
`build/source-reference-readonly/checksums.sha256` checks the original PCB + schematic.

**Provenance:** The PCB and schematic reference originated from a separate local
checkout of Issue #91/Draft PR #119 (`8e6429bd906146567d8121c615d4cc25e4f93471`);
portable project context includes the matching `fp-lib-table`, `sym-lib-table`,
`ZapTrace.pretty/`, `ZapTrace.kicad_sym` and `.kicad_pro`. These are necessary: the
board alone triggers 14 additional footprint-library errors unrelated to copper.
The reference copper contains 25 pad-to-pad reviewed connections / 61 native
segments, **12 unconnected items**, **12 drill-out-of-range** and **4 hole-clearance**
violations. The baseline generated PCB is *not* fully routed. No process rule
has been waived or relaxed.

## Compare actual engineering snapshots (not simulated progress)

The local **Projects** catalog has a **Compare snapshot** checkbox on each
native review card. Select exactly two sources to open the side-by-side
**Evidence delta** panel. It presents source-linked SHA summaries, independent
review and evidence-report links, physical pad/copper item counts, native
unconnected item counts, PCB-rule findings, footprint-library consistency
findings and actual enabled-rule ERC counts. Each value comes from that
snapshot's independent `evidence.json`, and `NOT RUN` stays explicitly
unknown rather than becoming zero. The delta is labeled **B − A**; it does
not assume a better design or even the same topology. Unrelated third project
selection does not silently overwrite an existing comparison.

**Essential DRC warning:** board DRC counts are subject to the original KiCad
`.kicad_pro`/`.kicad_dru` settings and library resolution. The comparison
highlights mismatched rule-file presence as **DIFFERENT KICAD RULE CONTEXTS**;
matching presence is still *not* proof of equivalent rules. For the two local
ESP32 evidence snapshots, the copper variant has 61 native copper items, 12
open items, 16 non-open PCB rule findings and no detected footprint-library
findings. The generated unrouted baseline has zero copper items, 37 open items,
28 non-open PCB rule findings **plus 14 footprint-library mismatch findings**
under its different KiCad project context. Both have zero enabled-rule ERC
findings. These are **separate observed counts**, not evidence of a fully
qualified improvement, DFM acceptance or permission to manufacture.

The pure `file://` dashboard and localhost server both support comparison;
the comparison is local and read-only and never changes `*.kicad_pcb`,
schematic files or project approval. Real Chrome regression coverage includes
desktop and 390px mobile layouts, genuine source report links, category counts,
clear-selection behavior and rejection of a third selected snapshot.

## Direct native GUI: open KiCad files without copying commands

Launch the local workspace with **one command**:

```bash
bash scripts/review_studio_local_launch.sh
```

This starts an ephemeral `http://127.0.0.1:PORT/` server, launches the system
browser and keeps the KiCad engine available until the terminal is closed. The
service is loopback-only and requires a random per-session capability plus a
same-origin request for every state-changing operation. It does **not** upload
to the internet or touch the source PCB. Port selection is automatic, so two
local users do not need to fight for a reserved port.

In **Add a KiCad board**, the GUI now has actual OS-backed file pickers for
`*.kicad_pcb`, optional root `*.kicad_sch`, the original `*.kicad_pro` and
optional `*.kicad_dru` custom rules. For a hierarchical schematic, choose the
**Schematic hierarchy folder** containing the root and nested `*.kicad_sch`
files as well. Folder selection transmits only the selected schematic files,
with their safe relative paths, to the same local server; it refuses traversal,
duplicates, missing referenced sheets or cycles. It accepts up to 32 files/16
MiB of subordinate sheets. A separate real two-page KiCad fixture was checked
with the system CLI and a true Chrome folder selection: its ERC runs against
the complete hierarchy, and the viewer's **Native sheet page** selector shows
both KiCad-rendered SVG pages. Page choice persists across local reloads.

**Schematic parity boundary:** root page cross-probing uses only real root
KiCad symbols/pins. Child-page SVGs can be inspected, but pin-net mapping and
PCB/net parity over child sheets are **NOT VERIFIED**; the viewer hides root
symbol/pin hotspots on child pages rather than inferring connections. A search
for a verified root symbol returns to the root page. The analysis context hash
includes original PCB, project rules, root schematic and every supplied child
sheet; changing any of these invalidates its registered review. It transmits the explicitly selected files over
the local `127.0.0.1` connection only, creates separate copies under
`build/review-studio-workspace/local-imports`, performs a true independent
native KiCad DRC / schematic ERC, then displays the new board's real DRC and
connectivity results. A progress/error indicator reports only actual engine
states, never guesses. The original files are not overwritten. Native KiCad
SVGs populate preview cards when screenshots are unavailable. During local
analysis the import panel displays an **observed-artifact checklist**:
F.Cu plot, native DRC report, Eeschema netlist and ERC report are marked only
when KiCad writes the corresponding file in that import's fresh UUID-named
report directory. Board-only imports leave netlist/ERC steps **unmarked**,
even when the review is successfully indexed. No guessed completion percentage,
no fabricated pass claim and no manufacturing approval is shown. Each GUI
import uses a separate UUID-suffixed report directory so old output artifacts
cannot be mistaken for current progress. While a local
analysis runs, Review Studio displays a native artifact checklist based solely
on files actually produced by that specific KiCad run (F.Cu plot, DRC report,
netlist, ERC report), without fake percentages, fabricated pass states or
fabrication approval. Board-only imports leave schematic/netlist/ERC entries
unmarked even after the review is registered. A fresh UUID-specific report
folder is used for each GUI import, so old results cannot be shown as new work. Users can open
individual native reviews directly from the new card.

**Important manufacturing context:** supplying only the `.kicad_pcb` is not
necessarily sufficient to reproduce original DRC outcomes. Select the
corresponding `.kicad_pro` and any `.kicad_dru` for the most faithful local
manufacturing rule set. When absent the UI and evidence report explicitly say
**project settings NOT supplied**; counts are context-specific and may change
if project and schematic files are copied out of their original library tree.
Neither result is an electrical or fabrication sign-off, even if KiCad reports
zero issues. During local GUI validation, the **same PCB SHA** produced 16
PCB-rule DRC findings and 12 gaps without a matching KiCad project file;
adding a selected `.kicad_pro` produced **30 total KiCad DRC findings**:
16 PCB-rule items (12 drill, four hole clearance) plus **14 library/footprint
consistency items**, and 12 open gaps. This is a rule/library context difference,
not an unexpected 14 new copper violations. The project cards now show both
the full native DRC finding count and its PCB-rule versus library breakdown.
The project settings SHA is registered with the PCB SHA, so the review library
rejects changed rule contexts on later refresh rather than confusing analyses.
Multi-sheet schematics and project libraries may require their
full supporting context; this native import intentionally does not claim
standalone assembly or manufacturing qualification.

For an optional desktop shortcut without installing anything in the operating
system's application menu:

```bash
/usr/bin/python3 scripts/review_studio_desktop_entry.py
```

This generates `build/Review Studio.desktop` (checked with
`desktop-file-validate`). **Only** the separately invoked `--install` option
would change `~/.local/share/applications`; it is never run by build/test.
This is a convenient shortcut into the installed local KiCad/Python engine,
not yet a dependency-free application bundle for a new workstation.

A static `file://` dashboard still provides a command-generation fallback when
the localhost GUI bridge is not running. The bridge's file staging endpoint is
not available to other websites: only the exact localhost host, random token
and same-origin requests are accepted. Uploaded source PCB/ project settings
are never served via the HTTP public asset route.

## Open the multi-project workspace (local only)

The recommended entry point is now the *native Review Studio project library*:

```bash
bash scripts/review_studio_native_local_build.sh
xdg-open build/review-studio-workspace/index.html
```

The reproducible build creates **two genuinely separate KiCad source snapshots**:

- Original Issue #91 61-copper-item review PCB: 16 reported native manufacturing
  DRC items, 12 physical unconnected items, source SHA shown on its card.
- Current generator's unrouted KiCad PCB: 42 native manufacturing DRC items,
  37 unconnected items and zero copper items. It is a distinct **board file and
  source hash**, not an automatically routed candidate or a claim of production.

Both project cards open the correct native geometry and local HTML evidence;
the review has a **← Projects** backlink. The project grid and search work
without network access and never convert unrun checks into green badges.

To review your own existing KiCad PCB without altering it:

```bash
/usr/bin/python3 scripts/review_studio_workspace.py \
  --workspace build/review-studio-workspace add \
  --name 'My PCB design' --board /absolute/path/to/my_board.kicad_pcb \
  --schematic /absolute/path/to/my_board.kicad_sch
```

`--schematic` may be omitted; then the schematic and ERC remain **NOT RUN**.
`--design-source` may be supplied only with a native schematic to check the
explicit authored package-pin map. `--no-drc` deliberately marks DRC and
physical gaps **NOT RUN**, never zero. A third real KiCad fixture was imported
through this workflow in a separate local QA workspace and correctly remained
fab-blocked. The browser dashboard does **not** yet offer a native file picker:
new source processing goes through `/usr/bin/python3` and the installed native
KiCad CLI/pcbnew oracle, not an unsafe fake in-browser DRC.

Workspace manifest entries include the actual output path and original board
SHA. If a registered viewer's evidence changes later, rendering **fails
closed** rather than silently accepting stale findings; re-register after
re-running the native checks. All edits and exports occur under the separate
`build/` review area. Neither the input PCB nor schematic is rewritten.

## Session-scoped layout preferences

The viewer saves **layout preferences only** in the local browser, namespaced
by original PCB SHA-256. This includes PCB/schematic view, inspector tab, KiCad
layer visibility, inspection marker toggles and side-panel widths. Layout
preferences persist on a real Chrome reload and can be cleared with
**Reset layout**. They never store or override copper, DRC, ERC, pin mapping,
manufacturing approval or source data. Missing/restricted storage falls back
to the current session. Invalid or malicious persisted values are constrained;
the production block remains independent.

## Professional review workspace

The local interface now uses a responsive engineering workspace layout, with a
**native evidence overview strip** across the top. Those four numbers are
pulled from the same verified local KiCad payload as the inspector, not
hard-coded or guessed. Selecting a status navigates to the native DRC list,
open connections, mapped pins or the actual schematic. `NOT RUN` is not
shown as success; fabrication approval always remains blocked.

The header and board toolbar now expose **Search workspace** (`Ctrl+K` or
`Cmd+K`) to navigate real footprint references, physical pad numbers, native
nets, Eeschema pin endpoints, reported DRC items and KiCad-confirmed open
pairs. Arrow keys, Enter, Escape and keyboard Tab/Shift+Tab work inside the
search dialog. When a category is not actually checked (e.g., DRC disabled),
the missing findings are *not* indexed. An unmatched search never implies a
DRC result or creates an object. Native board-source values are text-only;
this dialog does not accept commands that can edit or route copper.

**Inspection markers** can be independently hidden for native pads, DRC
finding locations and footprint selection points. This changes visual clutter
only: every reported finding, the original source board, proof gates and the
Fabrication blocked status remain untouched. Inspection marker toggles are
hidden while viewing the schematic. The 1024px layout was adjusted to keep
board metadata clear of the viewport toolbar.

The engineering sidebars can now be **resized like a docked desktop EDA tool**:
mouse-drag either separator, use Left/Right arrow keys on the focused separator
(or Shift for larger steps), then use Home/double-click to reset. The
independent PCB canvas remains at least 450 pixels wide on supported desktop
screens. Resizers disappear on narrow/mobile layouts, where the canvas is
prioritized. Resizing changes only browser presentation, not KiCad geometry. The
locally dragged widths reset when switching responsive viewport tiers so a
narrower laptop cannot strand the PCB in a cramped 388px canvas. The
1280px/1024px desktop views retain three columns without title/tool overlap;
on 820px tablets, the layout stacks the full-width actual PCB first, native
Inspector second and evidence sidebar third. All widths were inspected in
real headless Chrome, including the 390px touch screen.

Selected **DRC** and **Open** findings now offer a source-indexed,
previous/next review queue. `J` moves to the next native finding and `K` to
the previous when not typing or in a modal. The review sequence respects the
active inspector search filter and never silently advances beyond the
filtered result set. KiCad-open items continue to use inspection-only dashed
airwires, not autorouted or clearance-checked tracks.

The PCB canvas has a **Focus** mode (hides side inspectors to maximize the
native plot). Keyboard controls: `/` inspector-only search, `F` fit, `1` native PCB,
`2` native schematic when available, `M` pad-centre measurement, `Q` focus,
`?` shortcuts and `Esc` clear/close. A keyboard shortcuts panel is accessible
through the header; narrow screens put the PCB above the evidence sidebar.
Cursor coordinates are a visual plot readout in mm, not a calibrated physical
measurement. The native `pcbnew` two-pad measurement remains source-based.
On touch screens, one finger pans, two fingers pinch to zoom about their actual
midpoint, and fixed-size 24px native pad hit targets remain touch-selectable at
fit-to-board zoom; the board/schematic plotting itself is never rescaled in
source units. Chrome CDP gesture tests exercise real touch events rather than
only programmatic `.click()` simulation.

## What is actually supported

- **Authentic physical PCB**: KiCad-plotted SVG layers, 14 native footprints,
  112 actual pad objects, 61 native copper tracks, layer visibility, mm coordinates,
  native DRC fault markers and source-provenance hashes.
- **Real, improved schematic**: the local schematic exporter now sizes/arranges
  schematic symbols on an explicit A3 page and gives each connected logical pin
  KiCad-native label stubs. No pin/net assignment changes: old and new Eeschema XML
  netlists agree on **7 named nets / 37 logical pin nodes**, and the revised
  schematic gets **0 findings under enabled native ERC rules**.
- **Real review interactions**: symbol ↔ footprint and **native logical pin
  endpoint** ↔ physical pad crossprobe. Actual KiCad embedded-library
  coordinates and Eeschema XML pin references ground **37 interactive pin
  markers**; this is fail-closed for unsupported rotated/mirrored symbols.
  A logical J1.VBUS pin can lead to four real USB-C VBUS pads, avoiding a
  fabricated one-to-one relationship. DRC rule grouping and object navigation
  use pad number **and coordinate** to disambiguate ESP32 thermal-via duplicates.
  Search, pan/zoom, layer toggles, pad info, physical copper/net overlays and
  mobile layout have been tested in Chrome.
- **Real native open-item inspector**: all **12 KiCad open-connection findings**
  are uniquely resolved to **24 source copper objects** (pads or copper segments)
  by net, layer, length and native mm coordinates. Dedicated **Open** tab
  groups them under GND / VCC_3V3 / VCC_5V / I2C_SCL; click to frame the two
  endpoints or inspect each. The dashed straight segment is strictly a
  **visual airwire**, not a suggested route, short-free path or copper export.
- **Pad-center measurement tool**: choose any two actual `pcbnew` pad objects
  under **Measure**. Displays Euclidean centre-to-centre distance,
  ΔX/ΔY and real board millimetre coordinates, with a native-coordinate SVG
  overlay. Duplicate selection is rejected and Clear resets the state. This
  does NOT measure copper clearance, trace length, routing safety or DRC.
- **Offline evidence report**: each local build also creates
  `build/native-review/REVIEW_REPORT.md` plus the polished, standalone
  `build/native-review/REVIEW_REPORT.html` linked from the left panel.
  The HTML version is fully offline, script-free and uses a restrictive CSP. It
  identifies native source SHA-256 values, checked/not-run oracle states,
  remaining physical DRC findings, original 12 open endpoint pairs and the
  explicit fabrication-authorization boundary. This is a deterministic
  inspection record, NOT a Gerber generation, proof pack or manufacturing pass.
- **New pin-to-pad consistency check**: optional `--design-source` triangulates
  (1) authored `package_pin_map`, (2) native Eeschema logical pin/net references,
  (3) real pcbnew pad numbers/nets. For this fixture **69/112 physical pad
  instances** map to a matching logical pin/net, **0 mismatches**;
  **43/112 unmapped pad instances** have no PCB net and are **not qualified**.
  The interactive **Pins** tab groups all 112 real pad objects by component;
  it identifies mapped logical pins, pads outside the authored map, and any
  mapping mismatch. This includes USB-C connector shell/nonessential pads and unused ESP32 pads;
  it does *not* mean they are manufacturer-approved. A wrong mapping or a newly
  connected unmapped pad makes the check fail visibly.

## Known engineering boundaries (explicitly non-claims)

**Partial physical routing remains incomplete**: there are 12 native open-connection
DRC findings and 16 unwaived manufacturing-rule violations, so **fab is blocked**.
The native ERC rule set can have disabled/ignored categories. The pin-to-pad
check is agreement with *authored project mapping*, not an independently
reviewed vendor datasheet, electrical continuity oracle, antenna/thermal signoff,
Proof Pack, assembly check or final manufacturing acceptance.

Current limitations: nonzero-rotation/mirror schematic pin anchor transforms,
multi-sheet schematic navigation, DRC and mechanical measurement authoring,
true connection-aware 3D routing / routing validation (the dashed gaps are not
routes), provenance-aware AI change proposals, independent design-library
qualification and qualified user UX studies.

The old generated review is preserved under `build/native-review-original/` to
compare the initial A4-clipped schematic with the new A3 schematic. Browser
captures live under `build/native-review/` or `build/native-review-improved/`.

## Local checks

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_kicad_export.py tests/test_review_studio_native_kicad.py
.venv/bin/ruff check zaptrace/export/kicad.py scripts/review_studio_native_kicad.py \
  tests/test_kicad_export.py tests/test_review_studio_native_kicad.py
.venv/bin/pyright zaptrace/export/kicad.py scripts/review_studio_native_kicad.py
sha256sum -c build/source-reference-readonly/checksums.sha256
```

For local real Chrome E2E, start a headless Chrome with CDP on localhost:9243,
open `file://<worktree>/build/native-review/index.html` and execute:

```bash
ZAPTRACE_CHROME_PORT=9243 ZAPTRACE_EXPECT_LAYOUT=improved \
  ZAPTRACE_EXPECT_PINS=1 ZAPTRACE_SCREENSHOT_DIR=build/native-review \
  node scripts/review_studio_native_browser_smoke.mjs
```

The browser smoke covers the real native PCB and schematic, USB-C/ESP32 DRC
navigation, 14 symbol-reference crossprobes, U1.33=GPIO21=I2C_SDA, unmapped
J1.A6, 37 actual native Eeschema pin endpoints including U1.GPIO21 and
J1.VBUS (mapping to four PCB pads), the 12 real KiCad open pairs, 8 native
I2C_SDA segments and 4 pads, and 390px mobile width.
To verify the fail-closed/no-schematic/no-DRC experience, build a separate
`--no-drc` viewer, launch it in Chrome using a separate local CDP port and run
`node scripts/review_studio_native_no_oracle_browser_smoke.mjs`.

No network uploads, board writes, GitHub publishing or Gerber orders take place.
The Chrome E2E additionally exercises duplicate-pad measurement rejection,
Euclidean source-coordinate distance, Clear behavior, and local report access.
