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

## Subsequent source-only milestone: KiCad itself reports zero schematic/PCB parity differences

**Local isolated source only; NOT included in the previously accepted 0.1.9
Debian package or offline kit.** We identified and fixed three independent
producer-side mismatches in `zaptrace/export/kicad.py`, without modifying the
previously accepted 0.1.9 distribution or original ESP32 source fixtures:

1. **Physical electrical pin numbers.** The generated Eeschema symbol now
   uses authoritative `Component.package_pin_map` pad IDs as actual symbol
   pin **numbers**, retaining the logical name as the symbol pin **label**.
   Multiple separate physical contacts mapped to one logical pin become
   separate KiCad schematic pins carrying the correct net. Unknown mappings
   remain unresolved (not guessed), causing native parity evidence to fail.
2. **Identity and native fields.** Every generated PCB footprint receives the
   deterministic root-symbol KIID `(path "/<schematic-symbol-uuid>")` via the
   same symbol UUID generator as the Eeschema instance. The PCB `Value`
   field now matches the schematic's explicit-or-fallback Value. A PCB
   `Description` field now mirrors the schematic's
   `ZapTrace generated connectivity symbol` description.
3. **Actual native KiCad global net names.** Generated one-sheet schematic
   wire labels are now native `global_label` objects with passive shape,
   not root-local `label` objects. Native KiCad XML then reports `GND`,
   `VCC_3V3`, etc., exactly as on the PCB. This preserves the intended
   single-sheet net names. **Important correction:** KiCad's own
   `pcb drc --schematic-parity` treats a local `/NET` and PCB `NET`
   as a **net conflict**, not a harmless alias. The read-only audit was
   tightened to retain every literal name disagreement as an explicit
   conflict and never authorize its connected-pin subset proof. A native
   deliberately-regressed local-label schematic triggers 47 such conflicts
   and must never be accepted.

The **real installed KiCad 10.0.7 CLI**, against a fresh 10-stage source
pipeline for the ESP32 design, now reports:

- Real `kicad-cli sch erc --severity-all --format json`: **0 ERC
  violations** (with the project settings used for the test);
- Real `kicad-cli pcb drc --schematic-parity --severity-all --format json`:
  **0 native schematic/PCB parity violations**;
- Independent source-only audit: **14/14 exact native hierarchical symbol
  KIID paths; 47/47 connected physical pin numbers; 0 Value/footprint
  field discrepancies; 0 native net-name differences**;
- **42 PCB physical DRC violations and 37 unrouted/unconnected items remain**
  according to KiCad. These are serious engineering work, not eliminated
  by resolving schematic/PCB data synchronization. The remaining 38 PCB-only
  pad identifiers were not assigned schematic connectivity by guesswork;
  exact copper routing/physical release must be independently verified.

KiCad's official global label semantics and file structure are described at
https://dev-docs.kicad.org/en/file-formats/sexpr-schematic/ .
The separate immutable ESP32 baseline source remains source-hash verified,
even though its *older* schematic and PCB intentionally fail identity and
pin-number checks. Golden KiCad snapshot tests were refreshed based on actual
native-generated outputs; the old schematic golden was independently proven
stale even before this work. New native tests verify deterministic exports,
true physical pin numbering, missing package mapping rejection, wrong net
rejection, and zero KiCad-native schematic/PCB parity while verifying that
physical DRC/unconnected failures **remain visible**.

The browser's source-only diagnostic was also tested using real Chrome 155
for both the untouched old source pair and the newly generated pair,
including 390px layout, verified SHA-256 private JSON download and zero
JavaScript exceptions. **Still not supported/authorized:** F8 GUI
forward-annotation, changing connected copper, arbitrary 3D CAD, validated
manufacturer constraints, or fab/electrical/commercial certification. The
local source changes require **a new versioned release candidate and
full exact-package/Ubuntu qualification** before distribution.

## Source-only: full supplier pad inventory and KiCad 10 fabrication findings

Selected implementation ideas from open upstream **PR #119** were adapted
locally without any remote PR operations. Real SHA-pinned vendor footprints
are now used for board instance artwork and plated/NPTH drilling. The
complete GCT USB-C asset contains **22 physical pad objects**: 16
electrical contacts, 4 plated oval shell slots and 2 unnumbered mechanical
NPTH pegs. The actual KiCad PCB contains 112 physical pad objects. Its
read-only audit now reports **39** distinct PCB-only pad identifiers versus
38 in the earlier pads-only export, because `(J1, "")` identifies the
mechanical NPTH peg pair. It is never assigned an electrical net or
fabrication approval on inference.

The generated Eeschema symbol and board KiCad KIID, Value, vendor BOM
attributes, and native net names match; independent
`kicad-cli pcb drc --schematic-parity` confirms **0 parity issues**.
Independent physical PCB DRC reports **16 real fabrication errors and
37 unconnected items**. Do not confuse an exact KiCad linkage or the
read-only `connected_schematic_pin_net_subset_verified` result with
qualified physical routing or manufacturing approval. Full identical
source SHA-256 evidence and private browser JSON were verified on the
unchanged original design inputs. This remains an unversioned
post-0.1.9 **local-only source milestone**.
