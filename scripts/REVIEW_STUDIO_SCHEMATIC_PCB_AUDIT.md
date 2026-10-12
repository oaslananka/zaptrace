# Review Studio: native schematic ↔ PCB association audit

## Scope and evidence

This is a **read-only** engineering preflight, **not** KiCad F8
forward-annotation or an automatic PCB updater. The source-only implementation
was introduced after the hash-verified 0.1.8 package and is now included
in the separately versioned **0.1.9 unsigned local release candidate**,
with a complete nine-stage gate, reproducible package verification, exact
package Chrome tests and real APT 0.1.1→0.1.9 upgrade/restore/remove QA.
Package SHA-256: `cabe24ffa4d5a6138c8fd1abec2c5bb0ab73b2d5fcccea774a9712bf8005b11d`.
It is NOT general availability or an independently user-certified release.

The native KiCad 10 executable exports the supplied schematic to an actual
KiCad XML netlist. Independently, the installed native `pcbnew` 10 binding
opens the supplied PCB and enumerates exact footprint references, values,
library IDs, UUIDs and pad identifiers. A separate, authenticated localhost
form accepts the two explicitly chosen source files, checks both SHA-256
digests, runs the audit in an isolated disposable directory, returns the
evidence JSON, then deletes the temporary copies. Neither source is edited.

A report always distinguishes:

- Verified source SHA-256s and exact counts of components on each side.
- Missing/extra references, changed component `Value` and footprint
  library IDs, with exact before/after strings. Reference equality alone
  **does not** prove the footprint is linked to that schematic symbol.
- A strict pin/net correlation indicator. This comparison can only be
  called *exact label agreement* when every schematic pin identifier exactly
  matches a single PCB pad number and each native net label is identical.
  Duplicate physical pad numbers, renamed root nets, missing/ambiguous pin
  labels or changed ID associations remain **NOT VERIFIED**. Even exact label
  agreement does not constitute UUID linkage or continuity assurance.
- A permanently false automatic synchronization, electrical approval and
  fabrication approval field. No source update or fabrication export can be
  triggered through this audit.

The real ESP32 source pair currently returns 14 schematic components,
14 PCB footprints, 14 shared reference names and five source-backed
`Value` differences: `J1`, `TP1`, `TP2`, `U2`, `U3`. PCB pads
include repeated pin numbers (a physically valid native geometry choice).
KiCad also names its schematic pins differently from the PCB pads.
No association is guessed: UUID linkage and pin/net correspondence remain
explicitly unverified. This diagnostic does **not** say which representation
is electrically correct and does not write proposed corrections.

Native command with a **new** destination for the report:

    /usr/bin/python3 -B scripts/review_studio_schematic_pcb_parity.py \
      --schematic build/source-reference-readonly/ESP32_I2C_Sensor_Board.kicad_sch \
      --board build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb \
      --output /tmp/new-native-parity-evidence.json

Do not use an existing output file: audit will refuse to overwrite it.
The output contains source metadata and should be treated as private
engineering data. Never publish it in a public issue without review.

## Validation

- Real KiCad 10 CLI XML netlist and native `pcbnew` PCB extraction.
- Source-preserving SHA checks, mismatch detection on modified test copy,
  non-native source refusal and existing-output refusal.
- Localhost bearer+origin required; bad SHA-256, bad native type, invalid
  base64 and unknown action parameters fail without retaining uploaded data.
- Real Chrome verified native file-pickers, five truthful discrepancies,
  explicit UUID/net/production block, 390px reflow and zero script errors.

**Not supported:** F8/forward-annotation execution, re-link by reference,
automatic pin-number guesses, sheet-path/UUID topology attestation,
hierarchical re-authoring, differential/copper continuity signoff,
project-wide KiCad DRC rule semantics or manufacturing release. For real
forward annotation, use KiCad's original Editor action and review its changes
before applying.

Official KiCad documentation:

- https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html
- https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/
- https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/

## Post-0.1.9 source-only milestone: actual KIID association and pin evidence

**Source branch only — NOT in the hash-bound 0.1.9 .deb or offline ZIP.**
The existing tested 0.1.9 archive is immutable. Any new package must receive
a separate version and its own exact-package acceptance.

The audit now derives KiCad schematic KIID paths from the **native KiCad 10
XML netlist**, concatenating the real sheet-instance UUID path with each
symbol-unit UUID; multi-unit symbols are explicitly supported. It compares
each such full KIID path with the actual `pcbnew.FOOTPRINT.GetPath().AsString()`
read from the user-selected native board. Ref/name equality alone never
counts. Empty/malformed PCB paths, wrong or reversed hierarchical sheet
instances, UUIDs assigned to the wrong component, repeated PCB paths,
duplicate schematic symbol UUID paths and unsupported timestamp structures
all block the linkage proof. Individual findings and validated reference
counts are returned without modifying either source. The graphical UI
displays **actual UUID KIID path proof** separately from pin/net safety.
An exact native UUID match proves the serialized symbols and footprints
share a KiCad linkage identifier; it does **not** prove the underlying
electrical circuit, copper integrity, rule semantics or production release.

The native ESP32 source pair contains **14 schematic references and 14 PCB
footprints**, but the original PCB has **zero linked KiCad symbol paths**.
On a **disposable native KiCad PCB test copy only**, assigning all 14 actual
exported KiCad symbol UUID paths through KiCad's own `pcbnew.KIID_PATH`
produced **14/14 strict linked reference matches**. Replacing/swapping/
duplicating/removing those paths in separate copies causes explicit failure.
The same full-UUID-positive copy still has five `Value` mismatches and
unresolved pin/pad net association: **no automatic F8 sync is authorized**.
No production source was changed.

Additional pin-number/net-label diagnostics report unambiguous, literal
information without inferring aliases: actual schematic connected-pin IDs,
PCB pad IDs, physical-pad count, matching identical `(ref, pin)` pairs,
source-only/PCB-only pin labels, identical-ID/different-net labels, and
duplicate-number pads with conflicting native net labels. A bounded interactive
list prioritizes direct pin/net contradictions, with full findings in a
private SHA-linked JSON report. On the genuine ESP32 sources:

- 37 connected schematic pin identifiers;
- 112 physical PCB pads, but only 86 unique footprint/pad-number pairs;
- **0** literal `(reference, pin number)` matches;
- 37 schematic-only pin identifiers and 86 PCB-only pad identifiers;
- 123 literal identifier discrepancies;
- repeated physical pad identifiers, with 0 observed conflicting-net
  repetitions on the original PCB.

KiCad symbol pins labelled `P1`/`P2` cannot safely be guessed to
correspond to the PCB pads labelled `1`/`2`. Likewise, native schematic
net names such as `/VCC_3V3` are not assumed equivalent to `VCC_3V3`
without a proven KiCad source mapping. The UI explicitly refuses
synchronization or manufacturing approval in both UUID-positive and
UUID-negative states.

Regression tests construct real linked native KiCad PCB copies on demand,
using the actual schematic netlist (not hardcoded UUID assertions); verify
positive, negative, hierarchical/multiunit and repeated-UUID cases; and
alter pad labels/nets in **temporary copies only** to prove the diagnostic
catches same-number/different-net and repeated-number/different-net failures.
Real Chrome tests cover both original and linked copies, the full diagnostic
summary, mobile 390px display and zero JavaScript errors. In addition, the
user-facing **Download source-hashed audit JSON** control was exercised via
real Chrome's download manager and the resulting JSON was checked against the
original schematic and PCB SHA-256, native counts, unverified linkage, and
explicit no-auto-sync/fabrication gates. The disposable download was deleted
with the test browser profile.

The authoritative editor behavior is documented by KiCad:
https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html
https://dev-docs.kicad.org/en/file-formats/sexpr-schematic/
The proof is **not** KiCad Update PCB from Schematic (F8), not live routing
and not equivalent to certified electrical or DFM verification.
