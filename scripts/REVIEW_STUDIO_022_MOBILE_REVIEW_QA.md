# Review Studio 0.1.22 — mobile KiCad engineering finding navigation

*Local unsigned candidate; not public GA or fabrication sign-off.*

When a reviewer selects a real KiCad DRC finding on a 320/390px phone, its engineering detail and human-only triage editor could remain far below the scroll viewport. On this candidate, **only an active selected-issue navigation** (including DRC marker, review queue or finding list) reveals the selected detail in the page and moves keyboard/screen-reader focus to the real native finding heading. A passive data update or initial render does not scroll or steal focus; the original desktop view and pan controls are unchanged. A guarded requestAnimationFrame checks whether the same original finding is still selected and its detail heading still exists, preventing stale focus callbacks.

Real Chrome 320/390/1440 test asserts original source KiCad SHA, native DRC findings unchanged, no horizontal overflow, immediate screen reader heading focus on mobile, no unwanted passive focus jump, unchanged desktop selection behavior, and zero JavaScript exceptions. The exact separately built 0.1.22 `.deb` must contain the fix and be byte-reproducible. A saved review note is still unsigned, session-only, non-authoritative and never waives a board rule; physical DRC blockers remain and require engineering fixes.
