# ZapTrace Review Studio 0.1.20 — source-bound engineering review notebook

**Scope:** local-only, unsigned Ubuntu 24.04 + KiCad 10 candidate. This is a human PCB/schematic *review* tool, not a general EDA authoring replacement, a sign-off tool, or a fabrication approval.

## Professional engineering reviewer journey

1. Open a *real* KiCad board and inspect the source SHA, native ERC, DRC, open connections and pin/footprint map. Unknown and failed results remain visible: no synthetic proof or suppressed manufacturing errors.
2. Navigate real native PCB, original hierarchical schematic pages and KiCad-generated 3D views. Use the object command palette, keyboard finding queue and original source crossprobes to reach a particular physical design issue.
3. Select a real DRC finding or open connection. **Engineering review note** exposes a human outcome: **not reviewed**, **investigated**, or **repair required** (never “fixed”, “waived”, “passed”, or “approved”). Enter up to 600 characters of observations and save to the current browser session. The DRC list visibly labels investigated/repair-required entries. No source changes, modified DRC statuses or silent exceptions.
4. Export those session notes to a human-readable JSON artifact. `source_sha256`, native DRC state, the original finding index/rule/severity/message/object IDs/location, the chosen human status and the note travel together. The export explicitly says `fabrication_approved=false`, `source_modified=false`, `all_findings_remain_unwaived=true`. The file is **unsigned and editable by the user**; it is not evidence of the engineer's verified identity or an approval signature.
5. Re-import only a JSON snapshot whose source SHA and **all original recorded KiCad finding fields** match this view. The importer limits the file to 1 MiB and rejects duplicate indices, changed findings, altered DRC/source state, malformed notes, injected approval flags and overlong text. Validation finishes *before* any session note is restored. A failed import leaves existing notes unchanged. No localStorage persistence of review decisions. Source switching/reload starts with no notes unless explicitly imported.
6. Download a ZIP of the original project, validate backup and permanent deletion, or use guarded, copy-on-write PCB/schematic ECO and bounded two-net copper operations. These separate capabilities continue to require localhost authentication, source preservation and fresh native KiCad checks.

## Real UI/UX acceptance

- Actual installed Debian template is exercised with Chrome on **320, 390 and 1440 CSS-pixel** widths. Mobile review form expands in normal page flow; save button is reachable, no page-wide horizontal scroll or JavaScript exceptions. PNGs are SHA-bound to the exact package's browser log.
- Export, reinstate and deliberately malformed review JSON are exercised using real Chrome File/Blob APIs; never infer review completeness from a user note.
- Existing 3D model-file diagnostics, actual hierarchical schematic including the source-empty child, viewer keyboard focus/ARIA semantics, per-source layout, native PCB placement, schematic ECO, guarded multi-net copper, import/backup/delete/restore and independent native ERC/DRC remain part of the regression suite.
- QA runs from `scripts/review_studio_020_release_gate.sh`, `scripts/review_studio_020_installed_viewer_modes_qa.sh`, `scripts/review_studio_020_exact_package_browser_qa.sh` and `scripts/review_studio_020_installed_lifecycle_qa.sh`. A disposable Ubuntu 24.04/KiCad 10 APT test upgrades verified `0.1.19→0.1.20`, runs the packaged native server with real Chrome, then removes it without modifying prior data. Final SHA-bound QA kit generation must reject any missing stage or mismatched `.deb` member.

## Known incomplete product qualifications

Physical PCB **DRC: 16 unwaived violations** and outstanding native unconnected items; two-net copper path reduces only two reported opens. Full authoritative route completion, professional length/skew/high-speed constraints, verified vendor component footprint/STEP geometry and mechanical fit, bidirectional KiCad IPC transaction approval, manual hardware engineering sign-off, and clean physical-host UAT remain outstanding. The browser note file does **not** resolve these problems or confer review/production authority. No code signing, public GA, automatic GitHub PR/CI acceptance or fabrication release is claimed.
