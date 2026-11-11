# Human Reference Scorecards

ZapTrace keeps two benchmark evidence classes separate:

- the 12 built-in starter fixtures are **synthetic regression evidence** for deterministic repository tests;
- the corpus in `benchmarks/human-reference-corpus/manifest.json` records real human-engineered upstream open-hardware designs.

An upstream design being human-engineered does not mean ZapTrace reviewed, approved, manufactured, or certified it. Every initial reference is `pending-human-review`, and no qualified ZapTrace human approval is recorded.

## Initial reference corpus

The corpus pins one project, schematic, and PCB artifact for each design. Four older
KiCad-format projects are reference-only hash-pinned metadata (not locally executable).
Two original projects reuse byte-exact vendored external-benchmark files; three
additional MIT-licensed KiCad 10 educational source projects are independently
vendored with their original licenses. These references are not hardware approvals.

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
KiCad net name. On the five current source-pinned KiCad 10 references,
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
