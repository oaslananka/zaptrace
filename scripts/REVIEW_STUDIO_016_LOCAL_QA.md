# ZapTrace Review Studio 0.1.16 — Local Engineering and UI/UX Acceptance

**Target:** Ubuntu 24.04 LTS, KiCad 10.0.7, real Chrome 155. **Candidate only:** unsigned, noncommercial, not generally available and not approved for fabrication.

## Why v0.1.16?

- v0.1.13 proved the supported native Review Studio package workflows, but did not expose individual 3D model file deficiencies.
- v0.1.14 added actual source-linked 3D model path diagnostics (14 footprints, 12 declared models, 10 installed files present; J1/U1 unresolved, TP1/TP2 no model reference), yet the 390px Chrome visual screenshot caught an unreadable, single-grid-column warning. This is preserved as rejected local QA evidence.
- v0.1.15 fixed full-row warning readability and proved 390px keyboard operation. An additional **320px real Chrome visual audit** then found 3D controls overlapping the primary PCB toolbar by **40.2 px**; automated horizontal-overflow checks had not caught the occlusion. This package and its source SHA are preserved as historical **rejected** QA evidence; it must never be relabelled accepted.
- v0.1.16 caps the 3D status overlay height for screens ≤380px and allows independent scrolling. **Real Chrome reports exactly 0 px overlap at 320px**, 390px full-row warning, reliable model disclosure interaction, untouched original source and uninterrupted fabrication blocker. All fixed-package views remain subject to full QA.

## Source and browser gates

```sh
/usr/bin/python3 -B scripts/review_studio_build_deb.py --candidate-version 0.1.16
/usr/bin/python3 -B scripts/review_studio_build_deb.py --candidate-version 0.1.16 --output-dir build/distribution/repro-016
cmp build/distribution/zaptrace-review-studio_0.1.16_all.deb build/distribution/repro-016/zaptrace-review-studio_0.1.16_all.deb
bash scripts/review_studio_016_release_gate.sh
bash scripts/review_studio_016_installed_viewer_modes_qa.sh
bash scripts/review_studio_016_exact_package_browser_qa.sh
bash scripts/review_studio_016_installed_lifecycle_qa.sh
```

The browser gate uses the **actual SHA-checked installed Debian application template** with read-only KiCad source-backed payloads, eight real KiCad camera frames, two hierarchical schematic pages, native source SVG, local preferences, accessibility and keyboard controls, plus a 320px **geometry-based occlusion stop** (not merely CSS string lint). It captures 320/390 screenshots and logs their separate SHA-256 digests. In addition to those extremes, actual Chrome intersects the 3D toolbar and popup at 340, 360, 375, 380, 381, 385 and 390 pixels to reject viewport overflow and controls overlap at breakpoint boundaries. Any toolbar/3D overlap aborts acceptance. The exact-package suite covers native board/DRC, physical pin/UUID mapping, compare, safe read-only schematic↔PCB parity, guarded ECO and multi-net via copper; the standalone installed-package lifecycle suite tests import/ZIP backup, DELETE/cancel and restored ERC/DRC with source preservation.

An isolated, disposable `ubuntu:24.04` Docker QA system must install KiCad 10 from the **signed** PPA with valid CA certificates, prove an original 0.1.13 APT baseline, upgrade to this exact SHA-verified 0.1.16 package, exercise the real installed server with Chrome and native KiCad then remove the package while preserving separate QA-private data SHA. **Never** run APT provisioning against the host to conduct release tests. The container is removed only after all logs are saved and verified.

The following command is intentionally **fail closed** until every exact-package, real-Chrome, real-APT and full nine-stage source gate has exit code zero, required distinct success markers, original board source digest, two separate mobile screenshot hashes and unmodified previous version archives:

```sh
/usr/bin/python3 -B scripts/review_studio_016_assurance_kit.py
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.16_ubuntu24.04-local-RC.zip.sha256)
```

**Critical remaining boundaries:** 16 native physical KiCad DRC findings and incomplete electrical routing on the example board (**12 drill_out_of_range** violations: observed 0.2000 mm via holes versus 0.3000 mm configured minimum; **4 hole_clearance** findings: observed 0.1944 mm versus 0.2500 mm configured minimum; sampled from original SHA-bound KiCad 10 evidence). No rule threshold was lowered to obtain a pass; two unresolved native 3D model links and two footprints without model links; no mechanically verified replacement STEP placement/clearance, full net parity or authoritative bidirectional KiCad editor, supplier signoff, lab test, independent physical clean-host acceptance, official signing or public release. File-presence observation is **not mechanical or fabrication certification**. Actual KiCad path variables can be configured by the user; reported file presence reflects this test environment's default model installation, not all possible user library configurations.
