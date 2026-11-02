# ZapTrace Review Studio 0.1.15 — Local engineering/UI acceptance

**Scope:** Ubuntu 24.04 + native KiCad 10.0.7 + real Chrome. This is an **unsigned, noncommercial, local QA release candidate**. It is NOT a generally available, production-signoff EDA editor.

## Why 0.1.15 (not 0.1.14)

0.1.14 added actual per-footprint native 3D model source diagnostics, but its real 390px screenshot exposed unreadably narrow warning text within the 3D grid. That candidate was **visually rejected**, even though scripted interactions passed. Its evidence is preserved in `build/qa-014-release-20261012/REJECTED_VISUAL_AUDIT.md` and corresponding 390px image. The frozen package must not be relabelled as accepted. **0.1.15** changes the mobile grid layout to keep the critical model/assembly warning on a full row and adds a real Chrome pixel-geometry assertion plus screenshot SHA binding.

## New engineering value

The native PCB extractor reads KiCad's actual footprint model links without changing the source. Every native review includes `board.model_assets`, with counts, unresolved footprint references, models not declared, and exact-stem STEP alternatives. The UI exposes this in an expandable, keyboard-accessible 3D status panel and the source-linked standalone evidence report. In the sample, **14 footprints, 12 declared references, 10 present files, unresolved J1/U1, unmodelled TP1/TP2**. An alternative STEP file *is not* an approved replacement; vendor alignment, geometry, assembly and DFM remain unqualified.

## Local QA commands and gates

```bash
python3 -B scripts/review_studio_build_deb.py --candidate-version 0.1.15
python3 -B scripts/review_studio_build_deb.py --candidate-version 0.1.15 --output-dir build/distribution/repro-015
cmp build/distribution/zaptrace-review-studio_0.1.15_all.deb build/distribution/repro-015/zaptrace-review-studio_0.1.15_all.deb
bash scripts/review_studio_015_release_gate.sh
bash scripts/review_studio_015_installed_viewer_modes_qa.sh
bash scripts/review_studio_015_exact_package_browser_qa.sh
bash scripts/review_studio_015_installed_lifecycle_qa.sh
```

The viewer smoke suite includes 3D 8-frame native KiCad orbit, orthographic/isometric views, 390px model warning full-row extent and zero horizontal overflow, two-page schematic/gallery and source-scoped layout preferences. The rootless exact package Chrome suite checks workspace navigation, interactive DRC and native pad/net, source-specific comparison, PCB placement and schematic ECO, source-only parity, guarded two-via and multinet copper, and safe rollback. The isolated lifecycle suite exercises actual browser file selection, import, ZIP backup/download, typed destructive DELETE and restored native ERC/DRC. No input KiCad file is overwritten.

For disposable **Ubuntu 24.04 APT** acceptance, create a dedicated Docker QA container with the signed KiCad 10 PPA and trusted system CA certificates. Provision 0.1.13 as the baseline, then 0.1.15 with real `apt-get`, execute `scripts/review_studio_015_ubuntu_apt_chrome_qa.sh` and `scripts/review_studio_015_ubuntu_apt_lifecycle.sh` against that explicitly owned QA container. They must never run an APT install against the user's real workstation. Verify removal preserves separately checksummed test-user data; stop and remove the disposable container after saving the evidence.

The local candidate's unsigned deterministic ZIP can **only be built if every source, browser, real APT and visual screenshot QA result is successful and SHA-bound**:

```bash
python3 -B scripts/review_studio_015_assurance_kit.py
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.15_ubuntu24.04-local-RC.zip.sha256)
```

The previous accepted 0.1.12/0.1.13 .deb/ZIP files remain immutable; a new source change after QA requires a separate new version and fresh acceptance, not an overwritten SHA.

## Non-negotiable remaining boundaries

- **16 real native physical DRC findings** and incomplete board connectivity exist on the sample; guarded two-net DRC improvement is not board fabrication approval.
- The 3D inventory is a **file-presence check**, not a STEP mesh validation, mechanical envelope/interference check, thermal/RF simulation, or qualified supplier part footprint/pinout.
- No full validated, authoritative *bidirectional* KiCad schematic↔PCB synchronization, independent manufacturing/assembly output signoff, production autorouting or electrical lab testing is claimed.
- No separate clean physical host UAT, source/code signing, or public GA authorization occurred in this local acceptance.

These restrictions must remain visible in product UI and manifest, even when all applicable software gates pass.
