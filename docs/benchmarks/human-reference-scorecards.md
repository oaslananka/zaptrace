# Human Reference Scorecards

ZapTrace keeps two benchmark evidence classes separate:

- the 12 built-in starter fixtures are **synthetic regression evidence** for deterministic repository tests;
- the corpus in `benchmarks/human-reference-corpus/manifest.json` records real human-engineered upstream open-hardware designs.

An upstream design being human-engineered does not mean ZapTrace reviewed, approved, manufactured, or certified it. Every initial reference is `pending-human-review`, and no qualified ZapTrace human approval is recorded.

## Initial reference corpus

The corpus pins one project, schematic, and PCB artifact for each design. Four older
KiCad-format projects are reference-only hash-pinned metadata (not locally executable).
Sixteen original source projects are locally vendored byte-for-byte: the earlier
two external-benchmark boards, three MIT-licensed KiCad 10 learning projects,
and eleven newly pinned licensed projects (ten educational sensor/control
circuits plus an independent ESP32-S3 development board). The original
LICENSE text is vendored with the new projects. None of these references
is a ZapTrace-qualified hardware approval.

| Reference ID | Domain | Upstream repository | Exact revision | Hardware license | Source verification |
|---|---|---|---|---|---|
| `sparkfun-qwiic-navigation` | I2C/SPI expansion | `sparkfun/SparkFun_Qwiic_Navigation_Switch` | `b64c0dac2134d69963bf28120305bd79aad3c8ac` | `CC-BY-SA-4.0` | `vendored-byte-exact` |
| `mitayi-pico-d1` | MCU development board | `CIRCUITSTATE/Mitayi-Pico-RP2040` | `8411224b5795dd74843ff87e8ead096f1e13e11d` | `MIT` | `vendored-byte-exact` |
| `olimex-ice40hx1k-evb-revb` | FPGA expansion board | `OLIMEX/iCE40HX1K-EVB` | `91f3b5aff50258ddb40c021a21d4fd871633fc80` | `Apache-2.0` | `reference-only-hash-pinned` |
| `olimex-esp32-devkit-lipo-revd` | Battery-powered MCU | `OLIMEX/ESP32-DevKit-LiPo` | `1ebbbb5ceaa84b1d67631d8d542d7f6128c19fc1` | `Apache-2.0` | `reference-only-hash-pinned` |
| `olimex-bb-pwr-3608-reva` | Power converter | `OLIMEX/BB-PWR-3608` | `fbd5d7a62807edf2343c445dd1cd43e81bbbb84e` | `Apache-2.0` | `reference-only-hash-pinned` |
| `olimex-tuxcon-kitty-reva` | LED interactive badge | `OLIMEX/TuxCon-Kitty` | `64cba773ca8a0d9f5a3612d73fa627ddeef0312d` | `Apache-2.0` | `reference-only-hash-pinned` |
| `nitu-555-blinker` | 555 timer demonstrator | `nitu2126/kicad-learning-path` | `856b0daf1d358504cd035724f5ec9d1e6bfe3ad7` | `MIT` | `vendored-byte-exact` |
| `nitu-npn-transistor-switch` | Transistor switching | `nitu2126/kicad-learning-path` | `856b0daf1d358504cd035724f5ec9d1e6bfe3ad7` | `MIT` | `vendored-byte-exact` |
| `nitu-linear-regulator` | Linear regulation | `nitu2126/kicad-learning-path` | `856b0daf1d358504cd035724f5ec9d1e6bfe3ad7` | `MIT` | `vendored-byte-exact` |

### Additional licensed native KiCad references (11 projects)

These are exact byte copies of project, schematic and PCB originals from
the listed pinned Git commits, with original MIT LICENSE files. The table
records **KiCad's native netlist**, not ZapTrace's imported graph or an
electrical correctness verdict. All eleven original schematics exported
under native KiCad CLI 10.0.8 on 12 November 2026.

| Reference ID | Board purpose | Pinned upstream source | Native nets | Native pin nodes |
|---|---|---|---:|---:|
| jkc-9v-battery-indicator | 9V battery indication | [JKCadilo14-CpE/DIY-Circuits](https://github.com/JKCadilo14-CpE/DIY-Circuits/tree/1d33aaab5dca045a6a8b9da1542fb24ed2e55017) | 9 | 24 |
| jkc-hidden-wire-detector | Hidden wire detection | [JKCadilo14-CpE/DIY-Circuits](https://github.com/JKCadilo14-CpE/DIY-Circuits/tree/1d33aaab5dca045a6a8b9da1542fb24ed2e55017) | 7 | 16 |
| jkc-light-activated-switch | Light-activated switch | [JKCadilo14-CpE/DIY-Circuits](https://github.com/JKCadilo14-CpE/DIY-Circuits/tree/1d33aaab5dca045a6a8b9da1542fb24ed2e55017) | 5 | 13 |
| jkc-astable-multivibrator | Astable multivibrator | [JKCadilo14-CpE/DIY-Circuits](https://github.com/JKCadilo14-CpE/DIY-Circuits/tree/1d33aaab5dca045a6a8b9da1542fb24ed2e55017) | 6 | 24 |
| jkc-automatic-hand-sanitizer | Infrared-activated sanitiser | [JKCadilo14-CpE/DIY-Circuits](https://github.com/JKCadilo14-CpE/DIY-Circuits/tree/1d33aaab5dca045a6a8b9da1542fb24ed2e55017) | 5 | 12 |
| jkc-clap-switch | Clap-triggered switch | [JKCadilo14-CpE/DIY-Circuits](https://github.com/JKCadilo14-CpE/DIY-Circuits/tree/1d33aaab5dca045a6a8b9da1542fb24ed2e55017) | 7 | 22 |
| jkc-obstacle-detector | Optical obstacle detector | [JKCadilo14-CpE/DIY-Circuits](https://github.com/JKCadilo14-CpE/DIY-Circuits/tree/1d33aaab5dca045a6a8b9da1542fb24ed2e55017) | 6 | 18 |
| jkc-temperature-fan | Temperature-controlled fan | [JKCadilo14-CpE/DIY-Circuits](https://github.com/JKCadilo14-CpE/DIY-Circuits/tree/1d33aaab5dca045a6a8b9da1542fb24ed2e55017) | 4 | 11 |
| jkc-touch-sensor | Touch sensor switch | [JKCadilo14-CpE/DIY-Circuits](https://github.com/JKCadilo14-CpE/DIY-Circuits/tree/1d33aaab5dca045a6a8b9da1542fb24ed2e55017) | 4 | 10 |
| jkc-water-level-indicator | Water level indicator | [JKCadilo14-CpE/DIY-Circuits](https://github.com/JKCadilo14-CpE/DIY-Circuits/tree/1d33aaab5dca045a6a8b9da1542fb24ed2e55017) | 17 | 41 |
| atomic14-basic-esp32s3-dev-board | ESP32-S3 USB development board | [atomic14/basic-esp32s3-dev-board](https://github.com/atomic14/basic-esp32s3-dev-board/tree/7b4804ac3e3b1a7c06fe8769bbc428b05883af2c) | 47 | 132 |

For all eleven new boards, native KiCad 10.0.8 produced **117 named
nets and 323 pin nodes**. Ten simpler educational designs have exact
named-net/ref-pin imported graph parity, but each still has unsupported
source constructs and some PCB mismatches; therefore **none passes
full G0 import**. The historic pre-fix ESP32-S3 baseline below
independently exposes **47 native nets versus 44 imported nets**
(132 native versus 126 imported pin nodes). Source inspection showed
that three LED anodes touch resistor pins **directly without wire
segments**: D1 pin 2/R4 pin 2, D2 pin 2/R5 pin 2, and D3 pin 2/R6 pin 2.
The importer now records direct contacts at the same physical coordinate
only between distinct component references, without inventing lone-pin
or nearby-pin nets. Re-running the full independent KiCad 10.0.8
netlist comparison after this fix produces **47/47 identical named nets
and 132/132 pin nodes** for the ESP32-S3 board. All 19 other reference
graphs were unchanged. The ESP32-S3 board is **still G0 BLOCKED** because
unsupported constructs and PCB/schematic findings remain in the
historic graph-fix run. A later KiCad-native source check proved that
the 16 '#PWR' references are schematic power annotations: the embedded
library definitions contain the (power) marker and KiCad's own XML
component inventory excludes them, while retaining all 21 actual
physical component references. The project's footprint cross-check
now excludes only verified (power) annotations with empty Footprint
properties, rather than filtering any reference merely named '#PWR'
or using the on_board flag. The ESP32-S3 project therefore has
**0 false PCB/schematic footprint mismatches**, but its **8 unsupported
source constructs remain** and the project is **still G0 BLOCKED**.
Across all 20 pinned projects, the independently rerun strict result
remains **0 VERIFIED / 16 BLOCKED / 4 NOT RUN**; other proven power-symbol
false positives are reduced without silencing missing actual parts.
The original manifest SHA and historic baseline report are unchanged.
The educational repository reports its own hardware testing, which
is not independent ZapTrace physical-review authority.

### Native KiCad 10 PCB DRC before/after review (AI candidate, non-destructive)

To review an AI-proposed KiCad PCB edit without overwriting the
original source, run **one** local command:

    zaptrace kicad pcb-drc-delta path/to/original.kicad_pcb path/to/candidate.kicad_pcb --json

A matching original `.kicad_pro` is required for consistent native
design rules. The command SHA-256 pins both boards and the project,
then copies the original + project and candidate + same project into
**separate temporary folders**. It executes real `kicad-cli pcb drc`
with all severities and JSON reporting; no `--save-board` or zone
refill, so original or candidate files are **never modified**.
A missing/non-10 native KiCad CLI or unreadable/failed DRC is a hard
error. Native issue comparison preserves duplicate violations and
item UUID/coordinates, while discarding report dates and finding order.

The review reports pre-existing issues **and** newly introduced
violations/unconnected items separately. It exits **2** if the
candidate introduced any new DRC issue, so tools and AI agents cannot
silently accept a regression. No-regression is **not** a clean board
or electrical/fabrication approval when the baseline contains defects.

An actual original MIT-licensed ESP32-S3 board has **30 existing native
DRC violations and no unconnected items**. On a temporary *copy*
only, deliberately changing R4 pad `2` from
`Net-(D1-A)` to `+5V` produces **four new native violations**
(two `shorting_items`, two `solder_mask_bridge`) and
**one new unconnected item**. Its source schematic and original PCB
remain byte-for-byte unchanged. The baseline, native report
categories and error exit code are verified by executable tests.

Without `--electrical-checks` the command remains a backward-compatible
**PCB DRC-only delta**. For a **single-sheet** native KiCad project,
include real schematic–PCB consistency and ERC before/after in the same
source-safe command:

    zaptrace kicad pcb-drc-delta original.kicad_pcb candidate.kicad_pcb --electrical-checks --candidate-schematic candidate.kicad_sch --json

A matching original `.kicad_sch` is mandatory for this mode. The
optional candidate schematic is itself SHA-256 pinned and may be in
a separate directory. Without it, the candidate is explicitly
reviewed against the **unchanged** original schematic. Each native
`--schematic-parity` report is evaluated against its corresponding
board and schematic; the ERC report uses the same project rules.
The machine-readable `electrical_review` distinguishes existing
and new parity/ERC findings, with original and candidate schematic
SHA-256 identities. The CLI fails with **exit 2** for any new
native DRC, unconnected item, parity or ERC finding. Identical
schematic bytes share exact ERC evidence instead of rerunning an
unnecessary second native ERC; changing the schematic always
recomputes candidate ERC.

Independent original MIT-licensed ESP32-S3 native KiCad 10.0.8 proof:
**2 existing C4/C5 value-parity mismatches and 76 existing ERC
findings** are not hidden. Deliberately changing *only* R4's
value in a disposable candidate schematic produces **one new
`footprint_symbol_mismatch`** even when the board itself
is unchanged and PCB DRC has no new failures. Removing one
original `no_connect` marker in another disposable candidate
produces **one new `pin_not_connected` ERC violation** (76 → 77).
Both candidate edits are rejected and all original source hashes
remain unchanged.

For native KiCad **multi-sheet** projects, the same opt-in review
now follows the complete set of referenced **project-relative**
`.kicad_sch` child files. Each child is parsed and copied from an
SHA-256 recorded immutable source snapshot; the baseline and
candidate each receive their own isolated native KiCad scratch
directory. To propose an edited child, leave the real source intact
and supply its original project-relative path and new local file:

    zaptrace kicad pcb-drc-delta original.kicad_pcb candidate.kicad_pcb --electrical-checks --candidate-child-sheet auxiliary.kicad_sch=/path/to/proposed-auxiliary.kicad_sch --json

The `electrical_review` JSON includes `original_child_sha256`,
`candidate_child_sha256`, and `sheet_file_count`. **Unchanged
root schematics do not skip native candidate ERC** when a child
content SHA changes. Each sheet instance retains its original
UUID and reference, while repeated references to the same child
source are preserved. Topology edits (new/deleted sheet references
or changed sheet instance identifiers) are deliberately blocked:
adding/removing hierarchical sheets is a separate, unqualified
user operation and must not silently pass as an edit.

A **native KiCad 10.0.8** acceptance test constructs a disposable
valid two-sheet project *from* the original licensed ESP32-S3
source. The independent KiCad parser sees both root and child sheets;
adding an unconnected wire to a **candidate child only** produces
new native ERC findings, triggering exit **2**, even though the PCB
and root schematic are byte-for-byte unchanged. No upstream
licensed source is modified, and the real 20-project G0 parity
baseline is separately retained. Legacy synthetic project-import
fixtures are NOT treated as native KiCad-valid evidence.

Potentially dangerous child paths (`../`, absolute, Windows-drive
or symlink escapes), missing files, malformed trees, cycles, a
candidate SHA mismatch, unreferenced candidate sheets or
unverified hierarchy-topology changes **fail closed**. The
collector bounds recursion, file count and source bytes. Complex
external/absolute references outside the project root require
a separate qualified capability rather than silent omission.

A no-new-finding result does **not** mean the existing circuit is
ERC/DRC clean, its electrical behavior is qualified, zones are
refilled, complete footprint geometry is verified, a human
engineer has approved the design, or manufacturing may proceed.
Strict G0 remains **0 VERIFIED / 16 BLOCKED / 4 NOT RUN**.

### Native KiCad PCB physical pad-to-pin/net evidence (read-only)

An AI agent reviewing a complete original `.kicad_pro` can now
inspect `Component.pcb_pad_contacts` as a typed **list of real board
pad instances**, including the original pad number, shape/type, dimensions,
footprint-local position, source UUID, native PCB net name and (only
where the schematic net identity is unambiguous) the canonical
`schematic_net_id` and `matched_pin_number`. This is intentional:
`Component.footprint_def` is **not** populated or certified by
this source-only evidence, and no routing/placement/fabrication engine
should treat these contacts as qualified manufacturing geometry.

Original ESP32-S3 board in **independent KiCad pcbnew 10.0.8**
has **21 footprints and 145 physical pad instances**; all 145
retain native pad numbers, native net names and real footprint-local
coordinates under this import. Repeated pad numbers are never
collapsed: U2 pad `41` has **11 physical contacts** and U3 pad
`2` has **two**, while the two J1 unnamed pads are retained
as unconnected contacts. R4 pad `2` and D1 pad `2` both
resolve to the canonical `Net-(D1-A)` ID. A deliberately changed
R4 copper pad on a disposable source copy produces a
`pcb_pad_net_mismatch` warning without changing the correct
schematic pin's net. Unknown board net names, duplicate footprint
references and incomplete source pad sizes fail closed with explicit
findings, never fabricated pad or pin links.

A read-only pass over **16 pinned original KiCad projects** imported
**800 physical pad instances**, of which **564** have an
unambiguous existing schematic net ID and **763** match a
source-verified schematic pin number. Nine SparkFun pad-net names
have no exact schematic net identity and are explicitly recorded,
not guessed. Native PCB comparison uses actual `pcbnew`
coordinates/number/net tuples; ordinary tests do not require the
Python PCB binding and the independent native test is marked
SKIPPED when that separate authority is unavailable.

This still does **not** certify complete layered land patterns,
copper, physical DRC/ERC, edited KiCad round-trip, manufacturing
readiness or engineer-reviewed AI circuit changes. Strict G0
remains **0 VERIFIED / 16 BLOCKED / 4 NOT RUN**.

### Project-level pin and net identity consistency

KiCad `.kicad_sch` pin evidence alone does not establish a usable
imported `.kicad_pro` project model. In particular, per-sheet component
and net IDs are namespaced during hierarchical flattening. Before the
project importer fix, original source pins such as `R4.pins["2"].net`
still referenced the **unprefixed sheet-local** net ID, while the
project's `design.nets` dictionary used `/top/...` IDs. The
`Net.id` stored in each object could also disagree with its
dictionary key. AI consumers could not reliably follow a pin to its
project net, even though named native connectivity was correct.

The project importer now applies **one shared net-ID mapping** to the
component pins, `design.nets` dictionary keys and stored `Net.id`
properties. Per-sheet net keys keep their sheet path, while existing
name-based global-net merges stay shared across sheets. Any source pin
that references a missing net is explicitly **reported and set to
unbound**, never assigned a fabricated connection. This changes
canonical references, **not** the original KiCad source bytes,
electrical topology, source pin names or net names.

Read-only verification of all 16 locally present licensed KiCad 10
project sources found **711 referenced pin-to-net links and 231
project-level net objects, all with valid IDs**. Original ESP32-S3
`R4.pins["2"]` and `D1.pins["2"]` now both reference the same
real `/top/...` project net. A separate two-sheet fixture checks
distinct local nets; a global-net fixture checks existing shared
namespace behavior. The independent 20-reference native parity
diagnostic remains **0 VERIFIED / 16 BLOCKED / 4 NOT RUN**:
this is referential integrity for partial source-backed canonical
data, not complete KiCad hierarchy, PCB pad mapping, ERC/DRC,
or manufacturing acceptance.

### Source-proven canonical KiCad pin inventory (partial semantic import)

Users and AI tools inspecting an original KiCad schematic now receive
**source-verified electrical pin entries** under each actual component's
`design.components[...].pins`. For example, on the original atomic14
ESP32-S3 development board, `R4.pins["2"]` identifies a `PASSIVE`
pin at the original KiCad sheet coordinate and points to the same
`Net-(D1-A)` net ID as `D1.pins["2"]`; `D1`'s pin label is
`A`. `U2.pins["3"]` retains the library label `EN` and native
`INPUT` type; `U2.pins["2"]` is `POWER` with the original
`power_in` direction also recorded in `current_domain`. For
unambiguously typed symbols, original electrical type strings remain
visible under `Component.properties["kicad_original_pin_types"]`.

Only a referenced embedded-library pin number, native pin type, name
and position can populate the canonical Pin object; actual net links
come from the already independently matched named-net graph. An
unmapped KiCad type such as `unspecified` is **not** guessed as
`PASSIVE`. Instead, its raw type is retained and an
`unmapped_pin_electrical_type` finding remains visible. Ambiguous
multi-unit pin positions or net assignments also fail closed.

On the unchanged atomic14 source, **128 pin records** are now
source-typed and linked, and four `unspecified` pins remain unmapped;
the independent native topology is still **47/47 exact nets and
132/132 nodes**. Full 20-source native parity remains **0 VERIFIED /
16 BLOCKED / 4 NOT RUN**. This is *partial source-to-canonical pin
identity*, not support for native KiCad symbol drawing geometry,
electrical ERC equivalence of all pin types, editable source round-trip,
board pad mapping, physical DRC, fabrication or human signoff.

**Recorded G0 baseline (2026-11-12):**
benchmarks/human-reference-corpus/native-parity-baseline-20261112.json.
With the 20-reference manifest and KiCad CLI 10.0.8, the genuine
read-only native-source comparison yields **0 verified / 16 blocked /
4 not run**. This is a historic, machine-readable diagnostic, **not**
a passing benchmark or reviewer approval. Reproduce after making
importer changes with:

    python scripts/ci_real_kicad_reference_parity.py --output /tmp/native-parity.json

The four legacy reference-only OLIMEX projects remain NOT RUN until
their exact original bytes can be made available; no score is inferred
from provenance alone. Strict G0 hardware, fabrication, cost and
autonomous AI task gates remain unresolved.

For every row, the manifest records the selected upstream paths, file formats, byte sizes, individual SHA-256 values, total bytes, and a path-sorted artifact-set SHA-256. The upstream repository remains authoritative for reference-only source content.

## G0 native KiCad schematic-import parity diagnostic

To check the actual electrical graph against an independent KiCad 10 netlist, run:

```bash
python scripts/ci_real_kicad_reference_parity.py --output /tmp/real-import-parity.json
```

The tool verifies byte-level manifest hashes, copies each available vendored project to a temporary
directory, exports a native `kicadxml` netlist with `kicad-cli`, and compares *exact* net names
and reference/pin tuples against ZapTrace's imported graph. Original projects are not modified.
The JSON records original-source and exported-oracle hashes, graph digests, unsupported constructs,
mismatch counts, tool version, and `verified`, `blocked`, or `not_run` for each reference.
Two additional diagnostics preserve the strict gate:

- `connected_pin_topology` compares physical (reference, pin) partitions, excluding
  KiCad's explicitly unconnected pins and nonphysical `#PWR`/`#FLG` annotations.
- `name_difference_diagnostics` classifies corresponding physical groups as exact,
  possible root-sheet `/` prefix, KiCad `{slash}` escape, generated name or unexplained.
  It runs only when physical partitions actually match and produces at most 12
  representative differences. **Classification is not net-name equivalence**;
  auto-generated names and candidate mappings still require native semantic proof.
  If physical partitions differ, this diagnostic returns `not_evaluated`.

Neither diagnostic can turn a different native/imported named graph into `verified`.

The physical-source graph now handles the two true KiCad no-connect cases
independently: a symbol-library pin of type `no_connect`, and an explicit
`(no_connect (at ...))` marker on an otherwise normal, unconnected pin.
Both produce native-style singleton `unconnected-(ref-name-Padnumber)`
nets only with matching embedded library geometry and pin-name evidence.
Unmatched/ambiguous marks and electrically connected pins are flagged as
unsupported; they never become an invented NC net. `#PWR*` power symbols
and `#FLG*` ERC power flags remain source components/annotations but are
not physical pin nodes in the native KiCad XML netlist. This improves
exact-source fidelity without suppressing the separate unsupported-construct
and hardware engineering review gates.

The flat-sheet importer follows KiCad's explicit net naming precedence (global,
power, local, hierarchical), alphabetical tie-breaking for equal-priority
labels, root-sheet `/` qualification for local names, and display unescaping
of `{slash}`. When a net has no labels, it uses embedded library pin names
or pad numbers to form native-style `Net-(ref-pin)` names **only when all
connected pins have complete, unambiguous pin metadata**. Otherwise the
existing deterministic fallback remains; it is not claimed to be an exact
KiCad net name. On the five originally pinned KiCad 10 references,
105 connected pin-group names now match independent native XML. This does not
verify no-connect handling, complete project import, PCB equivalence, or
hardware sign-off; `--strict` remains a separate fail-closed gate.

The four reference-only records remain `not_run` until their pinned bytes are available; a missing
KiCad CLI or identity mismatch cannot become a successful check. The default command records
baseline evidence even when its verdict is `blocked`; use `--strict` for a failing exit status
until *all* references meet the declared evidence contract.

**Interpretation:** this is a deliberately strict *schematic import* comparison, not a
round-trip/fabrication or AI-autonomy score. Different names (e.g. KiCad hierarchical-path
prefixes versus imported labels) are counted as mismatches until mapping is independently
verified. They must not automatically be labeled copper shorts or electrical design errors.
The older `benchmarks/kicad_roundtrip` scorecard uses source-less contractual scores and
cannot substitute for this diagnostic or a real design-edit benchmark.

## Reversible source evidence for schematic review

The KiCad schematic importer now returns an **in-memory source snapshot**
(\`KiCadSchematicImportResult.source_snapshot\`) that retains the original
UTF-8 byte sequence and SHA-256. Its \`paper\`, \`title_block\`,
\`embedded_fonts\` and top-level construct counts are readable through the
small \`source_evidence\` summary. \`snapshot.nodes("text")\`,
\`snapshot.nodes("polyline")\`, \`snapshot.nodes("image")\` and
\`snapshot.nodes("netclass_flag")\` recover parsed original items on demand.

Hierarchical project imports retain these snapshots independently by sheet
path in \`KiCadProjectImportResult.source_snapshots\`. This includes imports
from temporary source directories after those directories are removed.
The normal \`to_dict()\` summaries contain only counts, page/title fields
and hashes, **not the complete source bytes**.

Source retention is **not** lossless conversion into the editable \`Design\`,
does not guarantee an edited KiCad export, and does not resolve electrical
netclass attributes or drawing rendering. Unmapped source constructs remain
visible as \`unsupported_construct\` findings and \`import_losses\`; the G0
strict complete-import gate is unchanged. This source-backed review path
lets future user interfaces show original material without pretending it was
interpreted or approved.

### Controlled original-source annotation edit

An AI workflow can now change **one original top-level KiCad text annotation**
without rewriting the remainder of the original schematic. Given a source
snapshot, use the function replace_kicad_source_text(snapshot, annotation_uuid,
new_text, expected_sha256=snapshot.sha256) from zaptrace.kicad.source_edit.
The helper requires an exact source SHA-256 match and a unique text UUID,
validates the resulting complete KiCad syntax tree, and returns UTF-8 bytes
**without writing the source file**. Save the result to a separate review copy.
Unchanged source bytes (including graphical objects, netclass flags and CRLF)
remain byte-exact.

An independent KiCad CLI 10.0.8 export of the original and a source-only
annotation edit on the pinned SparkFun schematic yielded the same **32 native
named nets and 99 total netlist pin nodes**. This validates only the scope of
that one text edit, not arbitrary component/net edits, editable canonical
Design round-tripping, semantic netclass rules, ERC/DRC or manufacturing.
The strict G0 completeness gate remains blocked where required source
constructs are not fully mapped.

### Controlled passive-component value editing (local G0 task)

The source editing API supports a narrowly scoped **resistor/capacitor Value
property edit** using replace_kicad_source_passive_value(snapshot,
symbol_uuid, expected_reference, expected_old_value, new_value,
expected_sha256=snapshot.sha256). It requires the exact original SHA,
unique top-level symbol UUID, a matching physical R/C reference and old
value, and a generic KiCad Device:R, Device:R_Small, Device:C or
Device:C_Small library symbol. It rejects no-op edits, mismatched library
types, missing/duplicated lib_id and all vendor-specific symbols where
the physical component value can be embedded in the library identity.
No source input is overwritten; other source bytes and AST nodes remain
unchanged. BOM, electrical suitability and PCB acceptance are **not**
verified.

A specific risk was discovered and blocked: the genuine licensed
SparkFun Qwiic R14 uses library ID SparkFun-Resistor:2.2k_0603.
Changing only its displayed Value from 2.2k to 4.7k would leave that
fixed-value library identity inconsistent. An earlier standalone CLI
probe proved that the Value field could change with unchanged netlist
topology (32 nets/99 pins), **not** that this was a safe part
substitution. The production helper now refuses that edit.

Actual native KiCad 10.0.8 before/after XML netlist verification confirms
the intended Value property update and exact graph invariance on:
Mitayi C17 30pF to 33pF (64 nets, 231 netlist pin nodes);
Nitu 555 Blinker R1 4.7k to 5.1k (7 nets, 24 nodes);
Nitu NPN Transistor Switch R1 390 to 470; and
Nitu Linear Regulator R1 330 to 470.
Original boards remain untouched. Native KiCad 10 ERC is compared by
finding type, severity, symbol UUID and location; baseline findings
remain and are **never** presented as cleared. SparkFun pre-existing
ERC findings (2 errors, 108 warnings) were unchanged in its earlier
probe, Mitayi had 7 errors and 378 warnings unchanged, and 555 Blinker
had no findings. The additional native tests explicitly skip if KiCad 10
is unavailable rather than reporting an independent verification PASS.

These are source-bound, human-selected draft component value edits, not
autonomous, qualified engineering revisions. Circuit simulation,
requirements verification, sourcing/BOM checks, PCB DRC, physical review
and full G0 task acceptance remain outstanding.

#### One-command passive ECO preview with native verification

Previously a developer had to find a schematic UUID, separately edit
the schematic and PCB footprint, compare the graphs, and manually run
independent KiCad validation. For a **single-sheet generic Device:R/C**
source project with a corresponding PCB footprint, a user or AI
operator can now request a synchronized, source-preserving candidate:

    zaptrace kicad passive-eco-preview original.kicad_pcb --reference R1 --from-value 4.7k --to-value 5.1k --output-dir /path/to/new-review-folder --json

The CLI resolves the real source UUID, requires exactly the matching
old value in both the schematic and the PCB footprint, changes only
their targeted `Value` properties, and proves the canonical net objects
unchanged. It then runs genuine native KiCad 10 PCB DRC, native
schematic–PCB parity and ERC **before** publishing draft artifacts.
A new native finding, stale source, wrong component, vendor fixed-value
symbol, ambiguous reference or reused output folder **fails closed**.
Inputs and original project files remain byte-exact. The new directory
contains the modified `.kicad_sch`, `.kicad_pcb`, the unchanged
`.kicad_pro`, and a SHA-256-bound `eco-review.json` record.

In one **operator-specified**, nonautonomous task on the MIT-licensed
original Nitu 555 Blinker (R1 `4.7k → 5.1k`), independently checked
native KiCad **10.0.8** found **0 DRC, 0 ERC and 0 schematic–PCB
parity issues before and after**, and the imported canonical nets
remained unchanged. A user still needs to confirm the modified
resistor's actual timing and power specifications, BOM/sourcing,
functional simulation and independent engineering review. No circuit
operation or manufactured outcome has been approved.

The generated record explicitly uses
`attempt_status=human-review-required`, `g0_verified=false`,
`manufacturing_approved=false`, an unknown intervention count, and
`functional_timing_validation=not_run`. It is **one source-backed
tooling/engineering-edit attempt**, not proof of autonomous AI
engineering, a scored human-reviewed design, or the G0 benchmark's
required 20 successful independent tasks. Only safe single-sheet ECO
publication is in scope; multi-sheet reference edits still require
a separate source-complete ECO producer, even though the native
read-only multi-sheet reviewer supports checking candidates.

#### G0 task 001 — AI-suggested NE555 nominal period ECO (not a G0 pass)

The versioned first pilot task and observed native result are in
\`benchmarks/g0-ai-engineering-tasks/ne555-period-plus-ten-percent.json\`.
The prompt was chosen for this **agent-assisted test** (not requested
individually by an end user and not independently scored by a second AI
provider). The licensed original Nitu 555 blinker has a native net graph
that matches TI's NE555 astable connections: R1 \`4.7k\` is RA, R2
\`68k\` is RB, and C1 \`10uF\` is the timing capacitor. Using the
[March 2026 TI NE555 datasheet](https://www.ti.com/lit/ds/symlink/ne555.pdf),
the nominal period is \`0.693*(RA+2*RB)*C\`. The proposed R2
\`68k → 75k\` gives \`0.975051s → 1.072071s\` (about **+9.95%**).

Run the source-safe CLI on the pinned original to independently reproduce
the draft, without mutating the source tree:

\`\`\`bash
zaptrace kicad passive-eco-preview \
  benchmarks/external/nitu-555-blinker/source/02_555_blinker.kicad_pcb \
  --reference R2 --from-value 68k --to-value 75k \
  --output-dir /path/to/new-555-eco-draft --json
\`\`\`

Native KiCad **10.0.8** reported **0 ERC, 0 PCB DRC, 0 schematic–PCB
parity** both before and after the synchronized source edit; original
and proposed KiCad net graphs have the same 7 nets and identical pin
connections. The separately generated draft has exact source and output
SHA-256 values recorded in the task. The observed CLI wall time was
27.893s, specific to that run. Model/API inference cost, operator
interventions and independent AI repeatability were **not attested**.

This is **an AI-assisted attempted engineering change with tool proof**,
not an independently scored success. Real timing, component tolerance,
BOM qualification, physical review and an independent qualified human
review remain \`not_run\`. G0 is still **0 VERIFIED / 16 BLOCKED /
4 NOT RUN** for historical source parity and is **not 1/20 accepted AI
engineering tasks**. Do not infer fabrication approval from a clean
native rule check.

#### G0 task 002 — L7805 indicator LED current ECO with inherited KiCad issues

The second [versioned pilot record](https://github.com/oaslananka/zaptrace/blob/main/benchmarks/g0-ai-engineering-tasks/linear-regulator-led-current-minus-thirty-percent.json)
uses the original MIT-licensed Nitu L7805 regulator schematic and PCB.
It is an **AI-assisted, agent-selected pilot**, not an independently
commissioned or competitively scored electronics design task.

Native KiCad's XML netlist confirms U1 output pin 3 on +5V, R1 pin 1
on +5V, R1 pin 2 and the red D2 anode pin 2 on /LEDA, and D2 cathode
pin 1 on GND with U1 pin 2. The suggested change is **R1 330 Ω to 470 Ω**.
At fixed 5.0 V output and unchanged (assumed, unqualified) 1.8–2.2 V
red LED forward drop, the Ohm's-law estimate for this *indicator branch*
is **8.48–9.70 mA before to 5.96–6.81 mA after**, about **29.79%**
lower at fixed Vf. The actual LED Vf varies with current, and
brightness/output regulation and real part qualification were not measured.

On the real KiCad 10.0.8 source, the one-command preview produced
matching separate schematic and PCB candidate Value changes while
leaving all original bytes and all five native pin/net groups intact.
Native KiCad DRC stayed **0 to 0**, ERC **0 to 0**, but **10 preexisting
schematic–PCB parity issues remain 10 to 10**, including 2 net_conflict,
4 missing_footprint and 4 extra_footprint findings. These originate
in the reference board and are NOT introduced by the proposed ECO.
The candidate is **NOT electrically clean**. The CLI now shows the
remaining issue counts and types, rather than suggesting that zero
new errors equals clean. The JSON evidence includes
native_candidate_clean=false and baseline/candidate parity-type totals.

No current/voltage/LED brightness measurement, SPICE, verified LED
component/datasheet, BOM qualification, tolerance analysis, independent
human review or fabrication acceptance was performed. The task remains
human-review-required-existing-native-findings, and neither task
001 nor 002 counts as a completed independently scored G0 task.

#### G0 task 003 — source-pinned L7805 parity repair preview

The [third assisted pilot record](https://github.com/oaslananka/zaptrace/blob/main/benchmarks/g0-ai-engineering-tasks/l7805-parity-ten-to-zero.json)
starts from the **unchanged MIT-licensed original** Nitu L7805
schematic/PCB, not task 002's proposed R1=470 resistor value.
Native source analysis identifies four original PCB testpoint footprint
Reference labels (VIN, VRAW, +5V, GND) that still point to
schematic UUIDs TP1–TP4, plus a PCB LED net alias Net-(D2-A)
whose schematic label is /LEDA.

The explicit-mapping CLI creates a separate draft and refuses stale
SHA-256, wrong schematic symbol UUID, mismatched TestPoint library,
existing PCB net collisions, unexpected S-expression changes,
multi-sheet sources, original source overwrites and native regressions.

~~~sh
zaptrace kicad parity-repair-preview \
  benchmarks/external/nitu-linear-regulator/source/05_linear_regulator.kicad_pcb \
  --reference-map VIN=TP1 --reference-map VRAW=TP2 \
  --reference-map +5V=TP3 --reference-map GND=TP4 \
  --net-map 'Net-(D2-A)=/LEDA' \
  --output-dir /path/to/a-new-separate-draft --json
~~~

A real **KiCad 10.0.8** run on original and proposed source files
returned schematic–PCB parity **10 → 0**, ERC **0 → 0**,
PCB DRC **0 → 0** and unconnected **0 → 0**. The command took
18.139 seconds in that local execution; source/candidate SHA-256s
are recorded in the versioned pilot. The source schematic/project
bytes and PCB pad/track/zone/copper geometry were unchanged.

**Important user-facing limitation:** The four F.SilkS footprint
Reference text values change from human-readable measurement
net labels to TP1–TP4. That may make physical bench service
harder and requires qualified silkscreen and functional review.
All such reviews are NOT RUN; manufacturing is NOT approved.
The native parity improvement is **not** 1/20 independent AI
electronics engineering successes. Task 002 retains the
historical original ten native issues, while task 003 is a
separate unapproved candidate. G0 remains **0 VERIFIED /
16 BLOCKED / 4 NOT RUN** on the strict original reference baseline.

### Native KiCad 10 netclass directive preview (bounded G0)

AI-assisted project review must not silently equate KiCad custom netclasses
with ZapTrace's narrower internal NetClass enum. In KiCad 10, a net may
receive multiple classes through project patterns, directive labels or net
labels, and project priority affects the effective result. A source-only
text substitution does not establish a real class assignment.

The preview_native_netclass_reassignment function provides a **separate
draft source-byte result only after native verification**, with an exact
SHA-256 for both source .kicad_sch and sibling .kicad_pro, one unique
top-level directive UUID, a matching original class and a new class already
defined in the native project. It rejects unsupported hierarchical
projects, unchanged/malformed/ambiguous directives and missing KiCad 10 CLI.

The proof copies original source and project into disposable directories
and uses native KiCad 10 XML netlist plus ERC JSON **before and after**. It
must prove identical names and all (reference, pin) connectivity, exactly
one changed effective netclass equal to the requested new class, and exact
ERC finding identities and severities. If pattern assignment, rule-area
directives or priority prevent the intended result, produce an aggregate
class, or change multiple nets, the preview is refused. The original files
remain untouched and the returned summary omits raw source.

Independent verification against licensed Mitayi Pico D1 original: the
VBUS netclass flag was reassigned to GND, and separately to 3V3; both runs
preserved 64 native nets and 231 connected pin nodes. Native XML reported
one changed net (VBUS), with no other changed effective class. Existing
native ERC findings remain (not an ERC cleanup). These are narrow source
draft proofs, **not** full editable Design round-trip, PCB netclass
propagation, DRC clearance review, routing approval or qualified hardware
signoff. Strict G0 full acceptance remains unchanged.

### Native KiCad 10 sheet page/title/revision review

The original source snapshot retains KiCad's page geometry and title
block evidence without claiming full editable graphical Design parity.
To review **one exact existing** metadata value and get independent
native netlist/ERC evidence without changing any original files:

    zaptrace kicad sheet-metadata-preview path/to/board.kicad_sch --field paper --expected-value USLetter --new-value A4 --json

Supported fields are paper, title and rev. The command resolves the
original source + sibling .kicad_pro hashes automatically, verifies
the target is unique (and an unchanged value fails closed), and runs
KiCad CLI **10** on temporary source copies before returning success.
All named native nets, pin nodes, effective netclasses and ERC finding
identities must be identical before and after the change. For an
editable review copy **outside the original project** add:

    --output-dir path/to/new-sheet-review-folder

The destination must not exist. It receives only review.kicad_sch and
the byte-identical matching review.kicad_pro. Original schematic, PCB,
library assets and project files are never overwritten. An absent
title/revision, hierarchical sheet, stale hash, unsupported paper size,
native KiCad failure or ambiguous source field is an explicit error.
This is a *source-only review draft*, not a canonical Design round-trip,
validated PCB geometry, DRC, manufacturing or human acceptance.
Merely retaining KiCad source constructs in a snapshot never closes a
G0 unsupported semantic construct gate.

### Terminal review workflow

Users and automation can run the same native proof without writing Python,
supplying source SHA values, or looking up a UUID when the old class is
unambiguous:

    zaptrace kicad netclass-preview path/to/board.kicad_sch --from-class VBUS --to-class GND

This defaults to **read-only**. Add --json for a machine-readable summary
or --output-dir path/to/new-review-folder to create a separate schematic
and matching project named review.kicad_sch and review.kicad_pro.
The destination directory **must not already exist**. If several directives
use the same old class, choose exactly one with --flag-uuid; otherwise the
command stops rather than guessing. Originals and PCB files remain untouched.
Output is an unapproved design-review draft, not an edited/validated PCB.
No network access or paid provider is required for the local KiCad proof.

## Review boundary

The fields are deliberately independent:

- `engineering_origin: human-engineered-upstream` identifies the upstream origin;
- `source_verification` describes how source identity is pinned;
- `zaptrace_review_status: pending-human-review` states that qualified ZapTrace review is absent;
- `review_record: null` prevents an implicit approval claim.

A future `reviewed` status requires an identity-bound review record with reviewer name, organization, engineering role, UTC date, decision, HTTPS evidence URL, and notes. The following identities cannot satisfy human review: `zaptrace`, `ci`, `github actions`, `example-only`, `chatgpt`, `openai`, or `ai agent`.

## Scoring rubric

The rubric in `benchmarks/human-reference-corpus/rubric.json` has eight mandatory release-blocking dimensions totaling 100 points.

| Dimension ID | Weight | Minimum score | Accepted authority | Reviewer required |
|---|---:|---:|---|---|
| `requirements-coverage` | 15 | 80 | `verified` or `reviewed` | no |
| `erc-drc-oracle` | 15 | 100 | `verified` | no |
| `schematic-parity` | 15 | 85 | `verified` or `reviewed` | no |
| `component-evidence` | 10 | 80 | `verified` or `reviewed` | no |
| `layout-quality` | 15 | 75 | `verified` or `reviewed` | no |
| `dfm-readiness` | 10 | 80 | `verified` or `reviewed` | no |
| `simulation-analysis` | 10 | 70 | `verified` or `reviewed` | no |
| `human-review` | 10 | 80 | `reviewed` only | yes |

For each dimension:

```text
weighted_points = score × weight ÷ 100
```

A numeric total alone cannot produce a pass:

- `missing` or `reported` evidence makes the dimension `blocked`;
- an authority outside the rubric makes the dimension `blocked`;
- the `human-review` dimension without an approved real reviewer makes the dimension `blocked`;
- accepted evidence below the dimension threshold makes it `fail`;
- accepted evidence meeting the threshold makes it `pass`.

Overall status follows this order:

```text
blocked dimension present  → overall_status: blocked
otherwise failed dimension or total below 80 → overall_status: fail
otherwise → overall_status: pass
```

The committed `attempt.example.json` is intentionally non-authoritative, has eight missing zero-score dimensions, and must produce `overall_status: blocked` with total score zero. CI success means the schema and deterministic scoring contract work; it does not mean the example passed engineering review.

## Attempt evidence

A submitted attempt must bind:

- a real tool name and version;
- a nonzero exact 40-character source commit;
- a corpus reference ID and matching artifact-set SHA-256;
- exactly one evidence row for each rubric dimension;
- score, evidence authority, evidence paths or immutable HTTPS URLs, and notes;
- a qualified reviewer record for `reviewed` evidence.

A positive score without evidence references is invalid. `missing` evidence must have score zero. Reviewers cannot be represented by CI, project self-identity, an AI system, or an example placeholder.

## Run the contract gate

The repository-controlled gate validates the committed manifest, rubric, blocked example, identities, and deterministic scorecard:

```bash
git clone https://github.com/oaslananka/zaptrace.git
cd zaptrace
SOURCE_COMMIT="$(git rev-parse HEAD)"
git checkout --detach "$SOURCE_COMMIT"
uv lock --check
uv sync --locked --all-extras --all-groups
.venv/bin/python scripts/ci_human_reference_scorecard.py \
  --output /tmp/human-reference-scorecard.json \
  --markdown /tmp/human-reference-scorecard.md \
  --strict
```

`SOURCE_COMMIT` captures the exact clone HEAD before detaching. To reproduce another revision, set it to that exact 40-character commit before checkout.

## Score a real attempt

Copy the template, replace every placeholder identity and all eight evidence rows with real evidence, then run:

```bash
cp benchmarks/human-reference-corpus/attempt.example.json /tmp/my-attempt.json
.venv/bin/python scripts/ci_human_reference_scorecard.py \
  --attempt /tmp/my-attempt.json \
  --output /tmp/my-scorecard.json \
  --markdown /tmp/my-scorecard.md \
  --strict
```

The gate validates and reports the attempt; it does not create missing engineering evidence. A submitted scorecard remains blocked until every release-blocking dimension has accepted evidence and the human-review dimension carries qualified identity-bound review.

## Independently compare reference-only sources

For a reference-only entry, clone the upstream repository, check out the exact revision in the table, and compare the three selected artifact hashes with `manifest.json`. CI intentionally does not fetch mutable network content. A mismatch is provenance drift and must be investigated rather than normalized away.

## Non-claims

- A score is not fabrication approval.
- A hash match is not electrical validation.
- Upstream publication is not ZapTrace review.
- The corpus does not relabel the 12 starter fixtures as human-engineered.
- CI, maintainers, contributors, and AI agents cannot self-create qualified human-review evidence.
