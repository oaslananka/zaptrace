# ZapTrace Review Studio 0.1.19 — real UI/UX and native engineering acceptance

**Scope:** unsigned local QA candidate, Ubuntu 24.04.5 + KiCad 10.0.7 + actual Chrome 155. Not public GA, not signed, not mechanically/fabrication approved.

## Why a source-backed empty-sheet state?

KiCad 10's native SVG exporter plots the authoritative schematic sheet image. The actual hierarchical fixture's root SVG has **5,715 drawable SVG elements**; its distinct source child “Power supply” page has **zero**, despite valid page dimensions. Older Review Studio rendered the authentic blank page but offered no explanation, allowing it to be mistaken for a failed renderer. The new `schematic_svg_drawn_elements` derives counts from KiCad-exported SVG nodes; metadata flows into the rendered source page. Only a genuinely zero-content page gets a keyboard/screen-reader accessible “No drawings on this original KiCad sheet” status. It vanishes on nonempty root sheets and outside schematic mode. No fake components, netlist, parity evidence or DRC status are introduced. Source PCB SHA-256 stays unchanged.

## Actual narrow-phone input ergonomics

The 320px device audit found tiny ± zoom touch buttons (~24px width). They now reserve **38×38 CSS-pixel targets** for the active mobile toolbar. That grew the control bar and surfaced a **2px** overlap with the 3D model diagnostics in the rejected v0.1.18 package. v0.1.19 reserves 12 additional vertical pixels for independently scrolling 3D controls, retaining the 38px targets; actual packaged Chrome verifies **zero overlap**. Native hierarchical schematic child-page stepper remains separate from its lower engineering caution at 320–390px. All prior 0.1.17/0.1.18 package hashes remain immutable.

## QA workflow

```sh
python3 -B scripts/review_studio_build_deb.py --candidate-version 0.1.19
python3 -B scripts/review_studio_build_deb.py --candidate-version 0.1.19 --output-dir build/distribution/repro-019
cmp build/distribution/zaptrace-review-studio_0.1.19_all.deb build/distribution/repro-019/zaptrace-review-studio_0.1.19_all.deb
bash scripts/review_studio_019_release_gate.sh
bash scripts/review_studio_019_installed_viewer_modes_qa.sh
bash scripts/review_studio_019_exact_package_browser_qa.sh
bash scripts/review_studio_019_installed_lifecycle_qa.sh
```

Exact `0.1.19` binary SHA-256: `fe5c7d5a5d89a3ac6167a47dd9cec0bf550a7f4359aaa9361f3afc92a34f1683`. The viewer QA rehydrates **only disposable copies** of older native KiCad fixture HTML from its original base64 SVG using the exact installed native extractor; it refuses contradicting cached counts, and never edits source KiCad boards. Real Chrome tests ensure 320px empty state and nonempty root, mode changes, proper 320–390px child navigation/toolbar occlusion, original eight-camera 3D, and 3D model file completeness blockers.

The installed-package Chrome test proves source project selection and comparison, native PCB/schematic/3D navigation, read-only parity, PCB placement and schematic ECO, guarded two-net copper and backed-up rollback. The browser lifecycle test proves original source import/download/DELETE/cancel/restore and ERC/DRC readbacks.

A disposable *owned* `ubuntu:24.04` Docker QA container must install KiCad 10 via its signed PPA, install verified 0.1.17 first, upgrade to the exact `0.1.19` package, execute `scripts/review_studio_019_ubuntu_apt_chrome_qa.sh` with real Chrome, and then `scripts/review_studio_019_ubuntu_apt_lifecycle.sh` to verify real APT `0.1.17 → 0.1.19 → removed`, private data SHA preservation and zero package leftovers. Never install a QA package on the host.

Only **after every gate succeeds** with source SHA, exact `.deb` hash, immutable prior versions, 320/390px PNG evidence hashes and reproducible output: `python3 -B scripts/review_studio_019_assurance_kit.py`. The unsigned local QA ZIP is not a release authorization.

## Honest remaining engineering boundary

The fixture still has **16 genuine KiCad physical DRC errors** (12 drill diameter below 0.30mm configured minimum, four hole clearances below 0.25mm), **12 initially open connection pairs**, missing source 3D models (J1/U1 unresolved, TP1/TP2 unmodeled), unverified vendor STEP geometry/thermal/mechanical fit, unqualified package pinout, and no full authoritative bidirectional schematic↔PCB synchronization. Neither the guarded two-net DRC improvement nor an empty-page explanation resolves source electrical/manufacturing shortcomings. Independent physical Ubuntu host testing, code signing, public CI PR and GA publication are out of scope of this unsigned local QA candidate.
