# Review Studio -> full EDA product acceptance contract

**Target**: a consistently professional, accessible electronic-design suite,
with trustworthy engineering results, user control over authored artifacts,
interoperability, and independently validated native release paths. A polished
read-only screenshot does not meet this goal. This is a local engineering
scope/acceptance document; it is **not** a promise of GA or fabrication safety.

## What is demonstrated in local 0.1.5

| Capability | Current state | Acceptance context |
| --- | --- | --- |
| PCB native engineering inspection | Verified preview and source-linked pads, nets, layers | Real KiCad 10 evidence; geometry not editable |
| Multi-sheet schematic inspection | Verified page gallery, root-only cross-probe | Source KiCad SVG plots; child-pin linking not falsely inferred |
| 3D board inspection | Source-linked 2 fixed + 8 orbit frames from native KiCad | Eight-step drag turntable, **not** continuous mesh inspection or MCAD |
| Evidence and warnings | Native KiCad ERC/DRC shown, unconnected items identified | Missing source rules change findings; no fab authorization |
| Project library and private backup | Authenticated localhost import/export/restore/delete | No overwrite; fresh ERC/DRC; preserve originals |
| Ubuntu 24.04 package | Exact .deb, true legacy upgrade/restore/uninstall QA | Unsigned local candidate, noncommercial license |

## First KiCad-authored ECO milestone (tested locally in 0.1.6; not full EDA)

A tightly scoped KiCad-verified **single-component-value ECO** has now been
implemented in `review_studio_schematic_eco.py` and exposed behind an
explicitly experimental, authenticated localhost authoring panel. It writes an entirely separate
native `.kicad_sch` copy and shows before/after KiCad schematic SVG views in a
responsive synchronized zoom-and-pan comparison. ERC and net topology are
checked independently on real native KiCad 10 before any new edit copy is
issued. It does not edit the main workspace source, PCB, BOM or libraries.
Hierarchy, multi-unit symbols, complete EDA object editing and full design
sync **remain blocked**. This is a value-only browser editor, not full CAD.
See `REVIEW_STUDIO_SCHEMATIC_ECO_EXPERIMENT.md` for reproducible local and
installed-package native KiCad acceptance evidence. The tested 0.1.6 release
introduces a *value-only* authoring surface; earlier 0.1.5 package artifacts
remain byte-for-byte unchanged. This does not certify arbitrary wire/PCB edits.

## First native PCB placement authoring milestone (0.1.7; not complete PCB CAD)

`review_studio_pcb_eco.py` adds a genuine KiCad 10 source-copy footprint
translation, verified native pad identity and before/after DRC, responsive
KiCad-generated PCB SVG comparison and private localhost download/discard.
The exact 0.1.7 Debian package was independently installed in a disposable
Ubuntu/KiCad container, upgraded from the old product and tested in real
Chromium. This works for carefully bounded unrouted geometry, but **does not**
provide production rule context upload, dragged connected copper, board zones,
via routing, complete footprint editing or full schematic/PCB synchronization.
See `REVIEW_STUDIO_PCB_ECO_EXPERIMENT.md` for the exact SHA-bound proof, safety
gaps and engineering acceptance plan. `fabApproved` and full EDA signoff remain
false; the release is still unsigned and local only.

## Post-0.1.7 isolated local engineering hardening (not packaged)

A guarded PCB placement follow-up uses native KiCad track/arc/via bounding
geometry at both the source and destination pad positions; this blocks
crossing and unintended landing copper cases missed by endpoint-only checks.
Existing routed-pad and DRC-regression refusals remain active.

The browser can now optionally import a same-basename, SHA-256-verified
`.kicad_pro` with the original `.kicad_pcb`, compare the native design with
that project file present in both validation workspaces, and download a
private ZIP with the checked PCB, project snapshot and evidence. The live
Chrome flow was tested with and without that sidecar, including a 390px
viewport and explicit deletion. Custom `.kicad_dru` rules are **blocked**
because a deliberately invalid rule file was observed passing KiCad CLI
without proving application. A present project file **does not attest** all
effective rules; evidence records
`effective_rules_independently_verified=false`.

This branch is **not** an installed 0.1.8 release candidate. The previously
tested 0.1.7 artifact hashes remain untouched; all clean-install, migration,
restore, uninstall and signed-package gates must be re-run on a new,
independently versioned package before claiming its acceptance.

## Required milestones for full-featured EDA

1. **Authentic schematic authoring.** Real component/library selection, net and
   bus wiring, multi-page hierarchical navigation, reversible edits and
   deterministic KiCad `.kicad_sch` round trips. The rendered netlist must
   exactly match the source; orphan or ambiguous pins block save/approval.
2. **PCB authoring tools.** Controlled footprint placement, copper routing,
   layer selection, vias, zones, keepouts and board outline editing with grid,
   snapping, undo/redo and stable identifiers. Every saved change must be
   measurable against a native KiCad DRC/ERC run, without waiving active rules.
3. **Schematic↔PCB synchronization.** Explicit approved ECO diff, part/pin/net
   mapping and independently checked electrical continuity. No automatic
   footprint or vendor-pin guesses presented as fact. Protected source
   changes must have preview/confirm/rollback and deterministic replay.
4. **True interactive 3D CAD.** Import/render genuine vendor STEP/WRL with a
   model-coverage report; continuous rotate/pan/zoom, selection, isolation,
   mechanical distance/collision checks and optional enclosure assembly.
   The existing eight-view KiCad camera turntable is a stepping stone only.
5. **Professional information architecture.** Unified visual language across
   import, library, PCB, schematic, 3D, BOM, fabrication diagnostics, report
   export and settings. Include keyboard accessibility, visible focus,
   contextual help, responsive inspection panes, search and error recovery.
6. **Supply chain and build artifacts.** Verified component libraries, traceable
   BOM sourcing, explicit production capability profile, ERC/DRC/DFM signoff
   and reproducible Gerber/drill/position outputs. Manufacturing gates must
   remain blocked while any applicable engineering check is incomplete.
7. **Product-grade engineering assurance.** Persistent native project
   round-trip fixtures, provenance, atomic saves, large-design performance
   tests, accessibility audit, security review, independent clean-machine
   installation and human acceptance. Publisher identity and permitted
   commercial licensing must be independently established before GA.

## Immediate next implementation stage

- Investigate KiCad's safe native API for **copy-on-write schematic edits**;
  prohibit writing original source files until native ERC and rollback tests
  prove no accidental data loss.
- Validate a bounded **continuous 3D geometry** format/viewer against the
  actual source model hashes. No fabricated part bodies or guessed enclosure
  dimensions; an absent model must be explicitly listed as missing.
- Run visual regression on real multi-sheet, high-part-count and unusually
  sized boards at desktop, 1024px, 390px and keyboard-only. Set explicit
  acceptance thresholds for missing controls, clipped content and interaction
  latency rather than relying on an informal visual score.

## 0.1.5 exact-package evidence

- Built `.deb` SHA-256:
  `138acff992665ed8168584ab2c8f6dfb61491cfd93c69c66c8b97304b09aaae1`.
- Offline kit SHA-256:
  `5292a2ce6a600c13c0f2773a5279978ca97836c567afefc9c63258dda3e15d1a`.
- Source-bound real Ubuntu 24.04 `apt` install 0.1.1 → 0.1.5, restoration,
  native KiCad 10 DRC/ERC, 2 schematic sheets, 10 true camera PNGs, Chromium
  drag-and-mobile checks and real `apt remove`: **passed** in disposable
  Docker. See `build/distribution/CLEAN_UBUNTU_2404_015_QA.txt` and
  `build/distribution/RELEASE_MANIFEST.json` for the exact package.
- Fabrication signoff, model coverage certification, independent user-device
  acceptance, real publisher signatures and public GA: **NOT verified**.
