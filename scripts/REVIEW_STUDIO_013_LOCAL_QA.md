# Review Studio 0.1.13 — Local Engineering Acceptance

This is an **unsigned, noncommercial, local-release candidate**, not a generally available EDA editor, electrical approval or fabrication signoff. The source-only experimental native KiCad copper features are bounded by real KiCad net/pad UUIDs, source SHA-256 and new/old DRC evidence.

## Scope of this candidate

- Improved mobile project navigation, form accessibility and error announcements across the native workspace.
- Source-labelled PCB DRC/continuity inspector with keyboard-operable, accessible DRC/Open/Parts/Nets/Pins tabs.
- Strict physical USB-C J1 pin↔pad navigation: four VBUS pads are never equated by net/function text alone.
- Source-linked multi-page schematic/gallery, native PCB/3D viewer and guarded PCB/schematic ECO and copper tools.
- Explicit release source/package version in the executable, Debian metadata and workspace documentation.

## Reproducible package

Build separately from the frozen 0.1.12 release:

```bash
python3 -B scripts/review_studio_build_deb.py --candidate-version 0.1.13
python3 -B scripts/review_studio_build_deb.py --candidate-version 0.1.13 --output-dir build/distribution/repro-013
cmp build/distribution/zaptrace-review-studio_0.1.13_all.deb build/distribution/repro-013/zaptrace-review-studio_0.1.13_all.deb
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.13_all.sha256)
```

The original `0.1.12` package/manifest/kit must never be rewritten or relabelled. The versioned builder refuses to overwrite a release artifact containing different bytes.

## Mandatory source and real-browser acceptance

```bash
bash scripts/review_studio_013_release_gate.sh
bash scripts/review_studio_013_exact_package_browser_qa.sh
bash scripts/review_studio_013_installed_lifecycle_qa.sh
bash scripts/review_studio_013_installed_viewer_modes_qa.sh
/usr/bin/python3 -B scripts/review_studio_013_3d_asset_audit.py
```

Only disposable local test workspaces are used. The exact package checks cover project library/compare, responsive and keyboard accessibility, native PCB/DRC/open connections, native schematic and crossprobe, guarded copper two-net/via changes, schematic/PCB ECO and read-only parity, actual ZIP backup/DELETE/restore, native 3D orbit, multi-sheet gallery and persisted UI preferences. Every tool remains distinct from original design files.

The real **Ubuntu 24.04 APT acceptance** uses a separate, disposable `ubuntu:24.04` container with the signed KiCad 10 PPA and system trust certificates; **never** install testing package versions into a user's actual workstation merely to run QA. After provisioning the container with native KiCad 10 and the SHA-verified `.deb`, use:

```bash
bash scripts/review_studio_013_ubuntu_apt_chrome_qa.sh
bash scripts/review_studio_013_ubuntu_apt_lifecycle.sh
```

Both require an explicitly configured QA container (`ZAPTRACE_UBUNTU_QA_CONTAINER`), not the local workstation. The latter verifies in-container APT version `0.1.12 → 0.1.13 → removed` while preserving checksums of private app user data. Dispose of the container after recording the evidence.

A fail-closed, deterministic **unsigned ZIP** may be created **only when every SHA-bound acceptance log is successful**:

```bash
python3 -B scripts/review_studio_013_assurance_kit.py
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.13_ubuntu24.04-local-RC.zip.sha256)
```

The QA manifest explicitly records source/hardware boundaries, and the kit contains **no personal project files**. Packaging and acceptance are not signing, publishing or merge authorization.

## Remaining blockers

1. The source PCB has **16 real KiCad DRC violations**; copper link success does not imply fully routed or fabrication-ready copper. No manufacturing signoff.
2. The canonical sample declares 12 three-dimensional model links over 14 footprints; 10 resolve to the installed KiCad 10 model library. J1 USB-C and U1 ESP32 legacy `.wrl` references are unresolved; identical-stem `.step` alternatives exist but **must be independently qualified before substitution**. TP1/TP2 have no model links. Camera screenshots are **not** mechanical or DFM qualification.
3. Full authoritative bidirectional schematic–PCB update, zone refill, all-net autorouting, electrical simulation/signoff, manufacturing files and assembly/3D clearance analysis remain outside the proven product scope.
4. The package is unsigned and has not been independently accepted on a separate physical clean host. Licensing remains PolyForm Noncommercial 1.0.0.

No source-parity or custom-rule validation should be silently converted into an approval for fabrication, supplier models or complete electrical connectivity.
