# Review Studio 0.1.29 — native KiCad design-rule state in human decisions

**Local unsigned engineering pre-release, not a hardware design signoff.**

The previous 0.1.28 decision screen bound the original and proposed PCB bytes and DRC counts, but did not bind `.kicad_pro`/`.kicad_dru` contents. A PCB could remain byte-identical while a changed custom clearance rule changed its engineering meaning. The original 0.1.28 Debian candidate remains immutable.

This 0.1.29 screen now verifies the SHA-256 digests of **both** copies of every applicable KiCad project/rule sidecar against native ECO evidence. It also rejects missing/unexpected/symlinked sidecars, mismatch between claimed rule mode and loader probe, and inconsistent native project/custom-rule combinations. The exact rule hashes and evidence-source mode become part of the human decision's `state_hash`; imports from another rule context fail. Rule sidecars are rechecked after native DRC and SVG rendering to detect changes while processing. The UI distinguishes defaults, project-only, and verified custom-rule loading, while explicitly saying independent full effective-rule verification and fabrication approval have not been performed.

**Acceptance:** real KiCad project + custom rules original/candidate DRC context, GUI source/proposed SVG inspection on desktop/mobile, original-state SHA preserved, stale/forged decisions rejected, custom rules and project SHA present in exported review state, local exact `.deb` deterministically reproducible, no unauthorized publication/merge.

**Remaining:** full effective rule semantics, schema/ERC/PCB synchronization, routed-copper/high-speed quality, 3D fit, external supplier and board fabrication approvals, signed reviewers and production identity. GitHub issue #31 only partially complete.
