# Interactive board viewer — mobile source-preview navigation audit

**Scope:** the offline `zaptrace view` (Python interactive) HTML generated from a genuine design, separate from the native KiCad Review Studio Debian candidate. Not a manufacturing approval.

A 390 px mobile Chrome visual inspection showed the readiness card, search and five-layer toggles filled the first viewport while the actual board was below the fold. A mobile-only **View board preview ↓** action now reveals the existing source-backed preview and shifts keyboard focus to its named `main` landmark. It leaves review readiness, DRC, proof, source objects, layers and fabrication assertions unchanged. A real design with no placed components still displays **zero placements and zero traces** and explicitly says it is an unqualified preview. A deliberately synthetic UX fixture retains example geometry, DRC blockers and its *manifest-only* proof state.

The shortcut is displayed at widths at most 650px, has a minimum 44px touch height, uses keyboard Enter activation, and is hidden on desktop. Its location complements rather than replaces the existing DRC-first action. `tests/test_interactive_viewer_mobile_board_jump.py` checks generated real and synthetic HTML/data contracts and the real source/proof separation.

Actual headless Chrome exercised **320/390/650/1440 CSS px on both source classes** with preserved original DRC/fabrication state, no horizontal overflow, keyboard Enter scroll + main focus, and no JS exceptions. The detailed local viewport geometry, screenshots and `.exit=0` are held in QA artifacts, not committed to Git. This does not cure unplaced designs, physical KiCad DRC, source model gaps, or issue #31's design-hash-bound reviewer approval.
