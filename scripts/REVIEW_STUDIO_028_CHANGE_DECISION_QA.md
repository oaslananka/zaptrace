# Review Studio 0.1.28 — source-bound native PCB ECO decision review

This is a limited, **unsigned, local** slice of GitHub issue #31, not a
manufacturing design approval or general copper/schematic diff.

## Genuine engineering flow

1. In the local Review Studio workspace, upload a real unrouted KiCad PCB,
   select a footprint, translate it without rotation, run native KiCad DRC,
   and leave the original source unchanged.
2. If actual source and resulting PCB match the KiCad ECO evidence, the app
   exposes **Download source-bound decision review**. It fetches authenticated
   CHANGE_REVIEW.html and verifies the SHA-256 digest before saving it.
3. Open the downloaded standalone HTML offline. It has real native KiCad
   F.Cu/F.SilkS/Edge.Cuts SVG renderings plus current/proposed/overlay/
   changed-only physical anchor modes, measured movement, DRC evidence,
   original and proposed file SHA values, and state hash.
4. A reviewer may export or re-import **defer**, **request repair**, or
   **reject proposal** with an evidence note. Stale state hash, different
   original/proposed source, unknown fields, and fabricated approval are
   rejected atomically. The hardware approval button is disabled.
5. The old Preview and copied native PCB project ZIP remain intact. Nonzero
   rotations and unsupported geometry still work in the old ECO flow, but
   cannot claim a validated source-bound change-decision screen.

## Verification

- Real KiCad 10.0.7: original PCB SHA
  02c2c344d730b48d465e79208d2ba760cf673aed26f7e84162123542d46ead76;
  real ECO copy SHA 1e281473f6cf4f429c204c93039148da13ac8e50a21944552d336a0d658e635d.
- Native R1 translated 1.00 mm X / 0.50 mm Y, pad net/identity and copper
  unchanged, DRC 0→0, with **five ignored KiCad checks** explicitly visible.
  These facts are not PCB manufacturing or electrical approval.
- Unit and server integration tests ensure strict geometry, rule/context
  checks, source SHA validation, authenticated/private downloads and discard.
- Real Chrome at 320, 390 and 1440 CSS pixels tests four views, actual KiCad
  vector plots, no page overflow, stale/forged import denial, disabled
  approval and zero JS exceptions.
- The release candidate package must include BOTH the Python renderer and
  HTML template, and must be built reproducibly as a new immutable version.

## Remaining #31 gaps

No schematic/ERC semantic diff, routed-copper geometry/EMC risk classification,
multi-change transactions, signed and verified human identity, independent
manufacturer/STEP qualification, or remotely trusted approval system.

Local generated HTML is a fixed snapshot: it cannot monitor changes to
external files after download. Regenerate from current original and proposed
PCB files to revalidate hashes. No push, PR merge, public GA or fabrication
authorization follows from this review.

### Rule-context integrity: next local candidate (0.1.29)

The decision state's hash now binds the exact matching `.kicad_pro` and
`.kicad_dru` file SHA-256 digests from the original native ECO proof, and
verifies both copies **before and after** the real native KiCad rendering. An
unexpected, missing, altered, or symlinked rule sidecar fails closed; defaults
without a project are explicitly distinguished. The UI shows rule provenance,
file hashes, and whether KiCad custom-rule loading was demonstrated.

**This is not effective-rule or fabrication certification.** The native ECO
attests that custom-rule loading occurred but does not independently establish
every effective rule. No external rules, supplier libraries, schematic/ERC,
STEP fit, electrical or physical approval may be inferred. Original local
0.1.28 bytes are frozen; this change requires a new immutable candidate.
