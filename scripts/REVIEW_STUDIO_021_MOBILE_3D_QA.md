# Review Studio 0.1.21 — source-verified narrow-screen 3D controls

This is a local-only, **unsigned** pre-release prototype. The native 3D view remains **KiCad 10-rendered source geometry**, and 10/12 present STEP links do **not** prove model completeness, mechanical fit or fabrication readiness.

At 320/390 CSS pixels, the five camera controls form two readable rows: **Isometric / Top** and **↶45° / exact ORBIT index / 45°↷**. The native eight frame sequence, DRC, source SHA and PCB/schematic navigation are unchanged. The fixed 5-column grid made the orbit angle difficult to read on a narrow phone.

`tests/test_review_studio_021_mobile_3d.py` verifies the mobile source constraints and byte-for-byte reproducible `.deb`. `scripts/review_studio_021_mobile_3d_browser_smoke.mjs` verifies 320/390/1440 Chrome DOM geometry, actual source digest, eight frames, two-row alignment, 44px minimum narrow-screen button dimensions, true angle legibility, non-overlap with the main PCB toolbar, no horizontal overflow and no JavaScript exceptions. The smoke is invoked with an owned Chrome CDP target using `CDP_PORT` and optional `ZAPTRACE_MOBILE_3D_QA_DIR`.

This does not resolve the remaining 16 source DRC violations, incomplete copper, missing models, live KiCad IPC or unsigned approval flow. No GA or fabrication approval.
