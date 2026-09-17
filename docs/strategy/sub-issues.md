# Executable Sub-Issue Specifications for ZapTrace Roadmap Epics

This document breaks down broad roadmap epics into independently mergeable, machine-verifiable sub-issues with explicit acceptance criteria.

---

## Epic #27: Physical Proof Program

### Sub-Issue 27.1: Physical Validation Evidence Schema & Unit Registration
- **Objective**: Implement Pydantic v2 schemas and CLI tools for physical hardware unit registration and test conditions (`zaptrace/evidence/physical.py`).
- **Why**: Physical hardware evidence must be cryptographically bound to frozen design SHA256 hashes without faking lab results.
- **Scope**: Data models for board serial number, fab lot, test equipment, environmental conditions, and measurement results.
- **Non-goals**: Faking physical lab measurements or claiming automatic hardware sign-off.
- **Dependencies**: None.
- **Acceptance Criteria**:
  1. `PhysicalVerificationRecord` computes canonical SHA-256 hash digest.
  2. Test equipment calibration dates and ambient conditions are recorded.
  3. Fail-closed handling when mandatory measurement thresholds are violated.
- **Verification Command**: `uv run pytest tests/test_physical_evidence.py`
- **Required Evidence**: Pydantic schema validation report and unit test output.
- **Security Impact**: Low (metadata integrity).
- **Release Impact**: Unblocks v0.4.0 milestone exit criteria.
- **Human Review Requirement**: Required before physical unit data registration.
- **Size Estimate**: S
- **Affected Paths**: `zaptrace/evidence/physical.py`, `tests/test_physical_evidence.py`

### Sub-Issue 27.2: Hardware Bring-Up & Measurement Evidence Manifest Tooling
- **Objective**: Build CLI tools to generate hardware bring-up checklists and ingest measurement evidence files.
- **Why**: Field engineers require structured CLI templates to record oscilloscope/multimeter measurements bound to test points.
- **Scope**: CLI command `zaptrace physical record` to generate and sign physical test records.
- **Non-goals**: Autonomous hardware testing without human operator.
- **Dependencies**: Sub-Issue 27.1.
- **Acceptance Criteria**:
  1. Command outputs valid `PhysicalVerificationRecord` JSON.
  2. Binds raw waveform/log SHA256 digest to record.
- **Verification Command**: `uv run pytest tests/test_physical_validation_plan.py`
- **Required Evidence**: Executed test record JSON artifact.
- **Security Impact**: Low.
- **Release Impact**: v0.4.0 physical proof requirement.
- **Human Review Requirement**: Mandatory human operator signature required.
- **Size Estimate**: M
- **Affected Paths**: `zaptrace/cli/`, `zaptrace/evidence/physical.py`

---

## Epic #28: Governed Component Qualification

### Sub-Issue 28.1: Cohort A Human Review Packet Generator
- **Objective**: Implement `build_human_review_packet` in `zaptrace/library/qualification.py`.
- **Why**: Machine readiness must prepare structured packets for human review without setting fake approval flags.
- **Scope**: Generate review packets for Cohort A (`esp32-c3-mini-1`, `usb-c-16p`, `ap2112k-3.3`, `bme280`, `atecc608b`).
- **Non-goals**: Setting `verified=True` or `reviewed_by` automatically.
- **Dependencies**: Governed component library schema v2.
- **Acceptance Criteria**:
  1. `HumanReviewPacket` contains 5 mandatory human review checklist items.
  2. Machine-blocked components reflect open machine blockers; review-ready components list remaining human items.
- **Verification Command**: `uv run pytest tests/test_component_qualification_readiness.py`
- **Required Evidence**: Component qualification report JSON.
- **Security Impact**: High (prevents unverified component promotion).
- **Release Impact**: v0.4.0 milestone gate.
- **Human Review Requirement**: Mandatory human reviewer sign-off.
- **Size Estimate**: S
- **Affected Paths**: `zaptrace/library/qualification.py`, `tests/test_component_qualification_readiness.py`

### Sub-Issue 28.2: Qualification Scaling for Cohorts B & C (10 to 50 Components)
- **Objective**: Expand governed qualification evaluation across 25 additional core passives and ICs.
- **Why**: Board families require verified component candidates across power, MCU, sensor, and RF domains.
- **Scope**: Ingest datasheets and footprint proofs for Cohort B components.
- **Non-goals**: Unreviewed bulk import.
- **Dependencies**: Sub-Issue 28.1.
- **Acceptance Criteria**:
  1. 100% of Cohort B components pass machine readiness checks.
  2. Human review packets generated for all 25 components.
- **Verification Command**: `uv run pytest tests/test_component_selection.py`
- **Required Evidence**: Qualification audit report.
- **Security Impact**: Medium.
- **Release Impact**: v0.4.0 component coverage target.
- **Human Review Requirement**: Required.
- **Size Estimate**: L
- **Affected Paths**: `zaptrace/library/`, `data/components/`

---

## Epic #30: KiCad Live Integration & IPC Workbench

### Sub-Issue 30.1: KiCad Toolchain Version & Capability Discovery
- **Objective**: Implement `discover_kicad_capabilities` in `zaptrace/kicad/capability.py`.
- **Why**: ZapTrace must discover KiCad CLI version and feature availability (ERC, DRC, STEP, IPC socket) dynamically.
- **Scope**: Support KiCad 7, 8, 9, 10 discovery without throwing exceptions when KiCad is missing.
- **Non-goals**: Hardcoding KiCad paths or failing CI when KiCad GUI is absent.
- **Dependencies**: None.
- **Acceptance Criteria**:
  1. Correct major/minor version parsing for KiCad 7.x - 10.x.
  2. Returns `available=False` gracefully when `kicad-cli` is not installed.
- **Verification Command**: `uv run pytest tests/test_kicad_capability.py`
- **Required Evidence**: Discovery test report.
- **Security Impact**: Low.
- **Release Impact**: Unblocks v0.5.0 KiCad workbench.
- **Human Review Requirement**: None.
- **Size Estimate**: S
- **Affected Paths**: `zaptrace/kicad/capability.py`, `tests/test_kicad_capability.py`

---

## Epic #31: Review Studio

### Sub-Issue 31.1: State Identity & Semantic Diff Evidence Contract
- **Objective**: Implement Review Studio semantic diff contract for board design state comparisons.
- **Why**: Reviewers require visual and semantic diffs showing added/removed components, nets, and DRC violations.
- **Scope**: REST endpoints and Pydantic models for design diff evidence bundles.
- **Non-goals**: Bypassing backend engineering state truth.
- **Dependencies**: Evidence Producer Protocol.
- **Acceptance Criteria**:
  1. Semantic diff identifies changed component coordinates, modified nets, and new DRC findings.
  2. Generates standalone static HTML/JSON review bundle for offline review.
- **Verification Command**: `uv run pytest tests/test_review_studio.py`
- **Required Evidence**: Static review bundle artifact.
- **Security Impact**: Medium (authorization on design state access).
- **Release Impact**: v0.5.0 Review Studio.
- **Human Review Requirement**: None.
- **Size Estimate**: M
- **Affected Paths**: `zaptrace/review/`, `zaptrace/api/routes/review.py`

---

## Epic #32: Evidence Producer Protocol

### Sub-Issue 32.1: Versioned Evidence Producer Protocol Schema (v1)
- **Objective**: Implement `zaptrace/evidence/producer.py` defining standardized `EvidenceProducerRecord`.
- **Why**: All evidence producers (KiCad CLI, SPICE, DFM checkers, solvers) must conform to a single schema.
- **Scope**: Pydantic v2 models for producer identity, execution environment, input SHA256, output digests, and authority level.
- **Non-goals**: Implicit approval without explicit authority.
- **Dependencies**: None.
- **Acceptance Criteria**:
  1. Computes canonical SHA-256 digest of record payload.
  2. Enforces fail-closed validation on invalid status or missing input design hash.
- **Verification Command**: `uv run pytest tests/test_evidence_producer.py`
- **Required Evidence**: Evidence Producer schema validation test output.
- **Security Impact**: High (tamper-evident evidence chain).
- **Release Impact**: Core contract for v0.5.0 and v1.0.0.
- **Human Review Requirement**: None.
- **Size Estimate**: S
- **Affected Paths**: `zaptrace/evidence/producer.py`, `tests/test_evidence_producer.py`

---

## Epic #33: Requirements-to-Architecture Compiler

### Sub-Issue 33.1: Typed Pre-Synthesis Requirements Contract & Architecture IR
- **Objective**: Define typed requirements schema and architecture IR translation in `zaptrace/synthesis/requirements.py`.
- **Why**: Synthesis must be deterministic and traceable back to explicit requirement constraints.
- **Scope**: Pattern extraction for rails, current budget, interfaces, MCU family, and safety rules.
- **Non-goals**: Unconstrained LLM schematic generation.
- **Dependencies**: None.
- **Acceptance Criteria**:
  1. Intent text compiles deterministically to typed `Requirements` IR.
  2. Temperature ranges and current budgets enforce ordering and positive bounds.
- **Verification Command**: `uv run pytest tests/test_requirements_schema_v1.py`
- **Required Evidence**: Requirements test suite pass.
- **Security Impact**: Low.
- **Release Impact**: v1.0.0 synthesis compiler.
- **Human Review Requirement**: None.
- **Size Estimate**: M
- **Affected Paths**: `zaptrace/synthesis/requirements.py`, `tests/test_requirements_schema_v1.py`

---

## Epic #34: PCB-Bench v1

### Sub-Issue 34.1: Tool-Neutral Benchmark Submission & Scoring Contract
- **Objective**: Refine `pcb_bench/schema.py` for tool-neutral task specifications and grader evidence.
- **Why**: PCB-Bench must allow third-party tools to submit results without importing ZapTrace internals.
- **Scope**: `TaskSpec`, `Submission`, `GraderEvidence`, and `ScoreReport` schemas.
- **Non-goals**: ZapTrace-internal specific metrics.
- **Dependencies**: None.
- **Acceptance Criteria**:
  1. `Submission.compute_hash()` returns canonical SHA-256 digest independent of timestamp.
  2. Evaluates passed, failed, and skipped grader counts deterministically.
- **Verification Command**: `uv run pytest tests/test_pcb_bench.py`
- **Required Evidence**: Benchmark schema test report.
- **Security Impact**: Low.
- **Release Impact**: v1.0.0 benchmark platform.
- **Human Review Requirement**: None.
- **Size Estimate**: S
- **Affected Paths**: `pcb_bench/schema.py`, `tests/test_pcb_bench.py`

---

## Epic #35: Placement & Routing Backend Contract

### Sub-Issue 35.1: Decoupled RoutingBackend Protocol
- **Objective**: Define `RoutingBackend` protocol in `zaptrace/algo/router.py`.
- **Why**: Decouple placement and routing algorithms from built-in grid router implementation.
- **Scope**: Standardized input `Design`, board positions, and output `RoutingResult`.
- **Non-goals**: Replacing DRC or ERC verification gates.
- **Dependencies**: None.
- **Acceptance Criteria**:
  1. `RoutingBackend` protocol defined with typed `route` method.
  2. Built-in router implements `RoutingBackend` interface seamlessly.
- **Verification Command**: `uv run pytest tests/test_router.py`
- **Required Evidence**: Router test suite pass.
- **Security Impact**: Low.
- **Release Impact**: v1.0.0 router platform.
- **Human Review Requirement**: None.
- **Size Estimate**: S
- **Affected Paths**: `zaptrace/algo/router.py`, `tests/test_router.py`

---

## Epic #36: Plugin Sandboxing

### Sub-Issue 36.1: Deny-by-Default Capability Admission & Sandbox Enforcement
- **Objective**: Enforce capability checks in `zaptrace/plugin/admission.py` and `zaptrace/plugin/runtime.py`.
- **Why**: Untrusted plugins must not execute dangerous capabilities without explicit admission.
- **Scope**: Capability checks for `network:connect`, `subprocess:run`, `filesystem:write`.
- **Non-goals**: Unrestricted ambient authority.
- **Dependencies**: Plugin manifest v1.
- **Acceptance Criteria**:
  1. Dangerous capabilities denied by default unless `allow_dangerous=True`.
  2. Runtime returns status `-2` with `PLUGIN_DANGEROUS_CAPABILITY_DENIED` code.
- **Verification Command**: `uv run pytest tests/test_plugin_capability_denial.py`
- **Required Evidence**: Adversarial plugin capability denial test pass.
- **Security Impact**: Critical (sandboxing boundary).
- **Release Impact**: v1.0.0 plugin platform.
- **Human Review Requirement**: None.
- **Size Estimate**: M
- **Affected Paths**: `zaptrace/plugin/admission.py`, `zaptrace/plugin/runtime.py`, `tests/test_plugin_capability_denial.py`
