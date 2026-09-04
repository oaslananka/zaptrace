# Sonar Historical Maintainability Debt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate all 15 unresolved historical Sonar S3776 cognitive-complexity findings on `main` without changing public behavior.

**Architecture:** Preserve each public/entry-point function and extract cohesive parsing, validation, rendering, and accumulation helpers. Helpers remain module-private and consume/return existing model types so callers and serialized outputs remain stable.

**Tech Stack:** Python 3.12+, pytest, Ruff, Pyright, SonarCloud, OSV Scanner, pre-commit.

**Spec:** SonarCloud API issue set for `oaslananka_zaptrace` on 2026-09-04 (`resolved=false`, 15 S3776 findings).

## Global Constraints

- Do not change public function signatures unless the function is private and all callers/tests are updated.
- Preserve deterministic output ordering and error/warning strings.
- Add no runtime dependency.
- Keep `main` untouched; work only in `fix/sonar-historical-debt-20260904` worktree.
- Every batch must pass its focused pytest suite, Ruff, and Pyright before commit.
- Final gates: full pytest, pre-commit, OSV=0, SonarCloud new/unresolved issue checks=0.

---

### Task 1: CI script complexity

**Files:**
- Modify: `scripts/ci_examples.py` (`validate_example`)
- Modify: `scripts/ci_kicad_oracle.py` (`_validate_pcb`, `main`)
- Modify: `scripts/ci_kicad_roundtrip_scorecard.py` (`_check_cases`)
- Test: `tests/test_hardware_workflow_security.py`, `tests/test_ci_kicad_oracle.py`, `tests/test_kicad_oracle.py`, `tests/test_kicad_roundtrip_scorecard.py`

**Interfaces:**
- Consumes: current design/export/KiCad helper APIs.
- Produces: unchanged exit codes, check records, console summaries, and scorecard errors/warnings.

- [ ] **Step 1: Capture characterization baseline**

```bash
uv run pytest -q tests/test_ci_kicad_oracle.py tests/test_kicad_oracle.py tests/test_kicad_roundtrip_scorecard.py tests/test_hardware_workflow_security.py
```

Expected: PASS before refactor.

- [ ] **Step 2: Extract example pipeline stages**

Keep `validate_example(name, entry)` as orchestration only; extract proof-path resolution, optional ERC/classification/placement/routing stages, export invocation, and result-report formatting into private helpers. Preserve current allow-missing behavior and exception text.

- [ ] **Step 3: Extract KiCad PCB validation stages**

Split `_validate_pcb()` into SVG export validation, project-file preparation, DRC execution/fallback, DRC finding classification, and report recording helpers. Split `main()` into argument/output-path validation, CLI availability/version gate, smoke-design export, validation, and final-status rendering helpers.

- [ ] **Step 4: Extract roundtrip case validators**

Split `_check_cases()` into per-case mapping validation, score validation, source-path validation, and degradation validation helpers returning error/warning lists.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest -q tests/test_ci_kicad_oracle.py tests/test_kicad_oracle.py tests/test_kicad_roundtrip_scorecard.py tests/test_hardware_workflow_security.py
uv run ruff check scripts/ci_examples.py scripts/ci_kicad_oracle.py scripts/ci_kicad_roundtrip_scorecard.py
uv run pyright scripts/ci_examples.py scripts/ci_kicad_oracle.py scripts/ci_kicad_roundtrip_scorecard.py
git add scripts/ci_examples.py scripts/ci_kicad_oracle.py scripts/ci_kicad_roundtrip_scorecard.py
git commit -m "refactor: simplify CI validation flows"
```

### Task 2: Core parser and regulator analysis

**Files:**
- Modify: `zaptrace/analysis/regulator_margin.py` (`_entry_for_regulator`)
- Modify: `zaptrace/core/parser.py` (`_build_design`)
- Test: `tests/test_regulator_margin.py`, `tests/test_parser.py`, `tests/test_constraint_dsl.py`

**Interfaces:**
- Consumes: `Component`, `Design`, schema model constructors.
- Produces: byte-for-byte equivalent model field values/status messages for equivalent inputs.

- [ ] **Step 1: Baseline tests**

```bash
uv run pytest -q tests/test_regulator_margin.py tests/test_parser.py tests/test_constraint_dsl.py
```

- [ ] **Step 2: Refactor regulator computation**

Extract input resolution, required-field collection, dissipation calculation, thermal calculation, and status selection into private helpers. Keep rounding precision and missing-field names unchanged.

- [ ] **Step 3: Refactor design construction**

Extract components, nets, placement, net classes, and copper-pour parsing helpers; `_build_design()` only assembles helper results plus simple optional fields.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest -q tests/test_regulator_margin.py tests/test_parser.py tests/test_constraint_dsl.py
uv run ruff check zaptrace/analysis/regulator_margin.py zaptrace/core/parser.py
uv run pyright zaptrace/analysis/regulator_margin.py zaptrace/core/parser.py
git add zaptrace/analysis/regulator_margin.py zaptrace/core/parser.py
git commit -m "refactor: simplify core parsing and regulator analysis"
```

### Task 3: EDA and external-format importers

**Files:**
- Modify: `zaptrace/eda/altium.py` (`read_altium_ascii_sch`)
- Modify: `zaptrace/eda/eagle.py` (`_parse_root`)
- Modify: `zaptrace/ee/imports/lcsc.py` (`parse_easyeda_footprint`)
- Modify: `zaptrace/io/ses.py` (`parse_ses`)
- Test: `tests/test_altium_importer.py`, `tests/test_altium_corpus.py`, `tests/test_eagle_roundtrip.py`, `tests/test_lcsc_importer.py`, `tests/test_ses_import.py`

**Interfaces:**
- Consumes: existing text/XML/S-expression inputs.
- Produces: same component/net/pad/track/via models, warning/error lists, and coordinate conversions.

- [ ] **Step 1: Baseline importer tests**

```bash
uv run pytest -q tests/test_altium_importer.py tests/test_altium_corpus.py tests/test_eagle_roundtrip.py tests/test_lcsc_importer.py tests/test_ses_import.py
```

- [ ] **Step 2: Refactor Altium passes**

Extract input validation/token bucketing, component creation, pin attachment, connectivity/union-find construction, net assembly, and final design/result assembly into private helpers. Preserve record counts, unsupported records, net IDs and warnings.

- [ ] **Step 3: Refactor Eagle passes**

Extract layers, packages, components/elements, signals/nets, vias/outline, and unsupported-record collection into helpers operating on `EagleImportResult`.

- [ ] **Step 4: Refactor EasyEDA footprint parsing**

Extract PAD/TRACK/CIRCLE parsing and courtyard calculation helpers. Invalid numeric shapes must continue to be skipped, not fail the import.

- [ ] **Step 5: Refactor SES parsing**

Extract resolution scaling, padstack/via definition parsing, wire-segment parsing, via parsing, and per-net accumulation helpers. Preserve total length, layer set and routed-net counting.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest -q tests/test_altium_importer.py tests/test_altium_corpus.py tests/test_eagle_roundtrip.py tests/test_lcsc_importer.py tests/test_ses_import.py
uv run ruff check zaptrace/eda/altium.py zaptrace/eda/eagle.py zaptrace/ee/imports/lcsc.py zaptrace/io/ses.py
uv run pyright zaptrace/eda/altium.py zaptrace/eda/eagle.py zaptrace/ee/imports/lcsc.py zaptrace/io/ses.py
git add zaptrace/eda/altium.py zaptrace/eda/eagle.py zaptrace/ee/imports/lcsc.py zaptrace/io/ses.py
git commit -m "refactor: simplify EDA import pipelines"
```

### Task 4: Tokenizer, schematic placement, and Gerber export

**Files:**
- Modify: `zaptrace/io/sexp.py` (`tokenize`)
- Modify: `zaptrace/ee/schematic/placement.py` (`place_schematic`)
- Modify: `zaptrace/export/gerber.py` (`generate_gerber`)
- Test: `tests/test_sexp_codec.py`, `tests/test_kicad_sexp_migration.py`, `tests/test_schematic.py`, `tests/test_schematic_wire_routing.py`, `tests/test_export.py`, `tests/test_export_regression.py`

**Interfaces:**
- Consumes: current S-expression strings, `Design`, routing/footprint models.
- Produces: same token line/column metadata, placement bounds/gap behavior, and Gerber layer contents/file mapping.

- [ ] **Step 1: Baseline tests**

```bash
uv run pytest -q tests/test_sexp_codec.py tests/test_kicad_sexp_migration.py tests/test_schematic.py tests/test_schematic_wire_routing.py tests/test_export.py tests/test_export_regression.py
```

- [ ] **Step 2: Refactor tokenizer state handling**

Extract whitespace/comment skipping, quoted-string consumption, and bare-atom consumption helpers that return updated cursor state. Preserve every `SexpParseError` message and token location.

- [ ] **Step 3: Refactor force-directed placement**

Extract connectivity graph creation, initial-grid state, per-component force calculation, wall force, velocity clamping, and one-iteration update helpers. Preserve random calls/order and final `_enforce_min_gap` invocation.

- [ ] **Step 4: Refactor Gerber layer rendering**

Extract pad collection, per-layer render helpers (outline/copper/mask/paste/silk), and output storage. Keep layer order, filenames, aperture insertion, and content bytes unchanged.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest -q tests/test_sexp_codec.py tests/test_kicad_sexp_migration.py tests/test_schematic.py tests/test_schematic_wire_routing.py tests/test_export.py tests/test_export_regression.py
uv run ruff check zaptrace/io/sexp.py zaptrace/ee/schematic/placement.py zaptrace/export/gerber.py
uv run pyright zaptrace/io/sexp.py zaptrace/ee/schematic/placement.py zaptrace/export/gerber.py
git add zaptrace/io/sexp.py zaptrace/ee/schematic/placement.py zaptrace/export/gerber.py
git commit -m "refactor: simplify serialization placement and Gerber export"
```

### Task 5: Datasheet extraction and proof-pack validation

**Files:**
- Modify: `zaptrace/library/datasheet.py` (`extract_datasheet`)
- Modify: `zaptrace/proof/pack.py` (`validate_proof_pack`)
- Test: `tests/test_datasheet.py` if present, otherwise datasheet/library governance tests; `tests/test_proof.py`, `tests/test_release_evidence.py`, `tests/test_claims_guard.py`

**Interfaces:**
- Consumes: raw datasheet text and proof manifests.
- Produces: same extracted values/confidences/import-loss strings and proof validation errors/order.

- [ ] **Step 1: Baseline tests**

```bash
uv run pytest -q tests/test_library_governance.py tests/test_proof.py tests/test_release_evidence.py tests/test_claims_guard.py
```

- [ ] **Step 2: Refactor datasheet field extractors**

Extract one helper per field family (identity/package, voltage, current, temperature, dropout, quiescent current, pin table) returning field updates and loss messages. Preserve regexes, confidence scores, units and loss strings.

- [ ] **Step 3: Refactor proof validators**

Extract artifact validation, runtime-check validation, check-record validation, oracle-skip validation, and limitation-warning validation helpers. Preserve error ordering and text.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest -q tests/test_library_governance.py tests/test_proof.py tests/test_release_evidence.py tests/test_claims_guard.py
uv run ruff check zaptrace/library/datasheet.py zaptrace/proof/pack.py
uv run pyright zaptrace/library/datasheet.py zaptrace/proof/pack.py
git add zaptrace/library/datasheet.py zaptrace/proof/pack.py
git commit -m "refactor: simplify datasheet and proof validation"
```

### Task 6: Repository-wide verification and Sonar enforcement

**Files:**
- No intentional production changes unless a gate exposes a regression.

- [ ] **Step 1: Full local verification**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pre-commit run --all-files
osv-scanner scan source -L uv.lock -L zaptrace_core/Cargo.lock -L .github/renovate-validation/package-lock.json
```

- [ ] **Step 2: Push and open PR**

Publish the verified tree via the GitHub App if HTTPS credentials are unavailable; verify remote tree equality before opening the PR.

- [ ] **Step 3: Enforce GitHub/Sonar gates**

Require Quality, Security, Container Security, Repository hooks/hygiene, Dependency Review, SonarCloud and exact-image scan to pass. Query Sonar API for both `sinceLeakPeriod=true` and all unresolved issues; both must be zero before merge.

- [ ] **Step 4: Merge, post-merge verify, and clean**

Squash merge; verify the same gates on the new `main` SHA; fast-forward local `main`; remove the worktree/branch and prune refs.
