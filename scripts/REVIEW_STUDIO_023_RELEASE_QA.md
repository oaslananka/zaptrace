# ZapTrace Review Studio 0.1.23 — local engineering UI acceptance

0.1.23 is an **unsigned local QA candidate**, never a fabrication approval or public GA. This immutable revision combines the previously exercised source-bound issue triage and 3D camera UX improvements. It supersedes **rejected 0.1.21 local acceptance**: the 381px viewport exposed 9.4px overlapping native KiCad controls when its model-file diagnostics was open. The Debian builder refused to overwrite a same-version candidate and that invariant is retained. 0.1.22 was only a local isolated review-focus proof, also never published.

## Essential acceptance lanes

- `scripts/review_studio_023_release_gate.sh` is the native KiCad 10 + Ubuntu 24.04 9-step source, Python/JS, Ruff/Pyright, SHA, deterministic package and dependency contract; the 0.1.20 accepted historical regressions and 0.1.21/0.1.22/0.1.23 new regressions are included.
- `scripts/review_studio_023_installed_viewer_modes_qa.sh` extracts **the exact 0.1.23 Debian package** and tests genuine native 3D 8-orbit rendering, model file diagnostics, 320–420px open-disclosure breakpoints, root/empty-child real KiCad hierarchical schematic, click/keyboard, local source-scoped layout, and explicit session human-note export/import, tamper rejection. All screenshot SHA values are bound to this package and KiCad source.
- `scripts/review_studio_023_exact_package_browser_qa.sh` exercises original-project import, comparator/readiness evidence, real native PCB/schematic/3D views, guarded schematic and placement ECO, authenticated reversible copper routes including two-net+via, actual independent pre/post KiCad DRC, source preservation, original project ZIP download, and 8/8 Chrome acceptance with zero JS exceptions.
- `scripts/review_studio_023_installed_lifecycle_qa.sh` proves native project import, private ZIP backup, cancellation/DELETE/restore and immutable physical source SHA using actual packaged server and real Chrome file chooser.
- Disposable Ubuntu 24.04/KiCad 10.0.7 strict signed-APT install, `0.1.20 → 0.1.23` APT upgrade, actual installed native server + host Chrome PCB/schematic/copper E2E, QA-fixture SHA preservation after APT remove.
- `scripts/review_studio_023_assurance_kit.py` fails closed if any exact-package/Ubuntu/UI gate or SHA evidence is missing; it embeds the **real `.deb` bytes**, not a similarly named PNG (historical bug guard), and enforces source-bound/mobile Chrome evidence.

## Active engineering limitations

**The referenced physical KiCad sample still has 16 unwaived manufacturing DRC violations and incomplete copper routing.** Neither UI triage notes nor successful local software tests clear those issues. The 3D model inventory has unresolved J1/U1 references and absent TP1/TP2 model links; 3D electrical/mechanical source geometry, STEP assembly collision and supplier qualification remain incomplete. KiCad GUI IPC transaction parity, signed reviewer approvals, independent physical-host UAT, complete routing/DFM and actual hardware engineering sign-off remain open. No public release, hardware production, or commercial product acceptance is asserted by the local suite.
