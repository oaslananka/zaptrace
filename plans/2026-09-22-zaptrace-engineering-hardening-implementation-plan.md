# ZapTrace Engineering Hardening Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Convert the 2026-09-22 engineering audit into a reviewable, test-driven hardening program that closes security, trust-boundary, determinism, release-integrity, least-privilege, maintainability, EDA-fidelity, and physical-validation gaps before major feature expansion resumes.

**Architecture:** Treat this document as a program-level master plan. The work is decomposed into independent workstreams that must land through small pull requests with their own tests, evidence, rollback boundaries, and release notes where applicable. Security and reproducibility blockers land first; product breadth and architectural cleanup follow only after the P0/P1 gates are green.

**Tech Stack:** Python 3.13, Rust/PyO3, uv, Hatchling, GitHub Actions, Docker/Alpine, Trivy, KiCad tooling, pytest, Ruff, Pyright, MkDocs, JSON evidence artifacts.

**Spec:** Embedded audit contract in this file under "Audit Contract and Coverage Matrix", grounded in main@e29ecba26c70c19f0317b690a25c765a0d43e01b and the repository's current governance, security, release, and documentation contracts.

## Global Constraints

- Baseline revision is main@e29ecba26c70c19f0317b690a25c765a0d43e01b as observed on 2026-09-22.
- Preserve current safe network defaults: REST/MCP loopback by default and fail-closed authentication requirements for non-loopback exposure.
- Preserve the active main-branch ruleset and required aggregate checks.
- Preserve Rust's current production boundary: no unnecessary unsafe code and panic-to-Python error conversion at the PyO3 boundary.
- Preserve critical per-module coverage floors; do not replace them with a single global percentage target.
- Preserve PyPI Trusted Publishing/provenance and immutable historical release metadata.
- Do not rewrite the historical MIT metadata of v0.3.5; the later PolyForm transition applies to current project-authored code.
- Keep generated-hardware non-claims explicit: software validation is not fabrication approval, manufacturer approval, or physical correctness.
- Every implementation PR must be narrow, independently reviewable, independently revertible, and include evidence appropriate to its risk.
- New major EDA formats, new heuristic analyzers, and new public MCP tools remain frozen until Phase 1 through Phase 4 exit criteria are met.
- The repository intentionally forbids docs/superpowers in public documentation; this plan therefore lives under top-level plans/ and must not be added to MkDocs navigation.
- All new tracked files remain covered by the repository-wide REUSE.toml annotation.

## Review Focus

1. **Untrusted plugin and worker inputs:** malformed, hostile, oversized, or boundary-crossing input must fail closed without gaining filesystem, process, network, or code-execution authority.
2. **Reproducibility across clean processes:** identical canonical design input must generate byte-identical canonical artifacts when source, locks, and toolchain are identical.
3. **Release partial-failure states:** no irreversible public release step may happen before all mandatory validation required for that release state has passed.
4. **Privilege surface defaults:** an unset or minimally configured server must expose the smallest safe capability set, never the broadest mutation-capable surface.
5. **Evidence drift:** generated facts, package metadata, documentation, registry state, and physical-validation evidence must identify their source revision and must not silently contradict one another.

---

## Program Operating Model

- [ ] Create one issue or pull request per task below; do not combine unrelated workstreams.
- [ ] Start every code-changing task with a failing regression or contract test.
- [ ] Run the smallest relevant test during development, then the repository's required quality gates before review.
- [ ] Record exact source revision, dependency lock identity, and toolchain identity for release/evidence changes.
- [ ] For security findings, record exploitability/reachability separately from severity; absence of proven reachability is not permission to leave a blocking repository gate red.
- [ ] Merge in phase order unless a later task is strictly documentation-only and cannot invalidate an earlier invariant.
- [ ] Use conventional commits and squash-merge after required checks pass.
- [ ] Keep the implementation branch/worktree until review feedback is resolved.

## Audit Contract and Coverage Matrix

| ID | Audit finding | Priority | Owning task |
|---|---|---:|---|
| F01 | AnyIO 4.13.0 security advisories keep scheduled Security red | P0 | Task 1 |
| F02 | Exact container image has seven HIGH Trivy findings | P0 | Task 2 |
| F03 | Container vulnerability scan has no schedule | P0 | Task 2 |
| F04 | Plugin runtime is process-isolated but not an OS sandbox | P0 | Task 3 |
| F05 | Worker IPC uses pickle deserialization | P0 | Task 4 |
| F06 | Schematic force placement uses unseeded random.uniform | P0 | Task 5 |
| F07 | KiCad exporter still emits UUID4 for some objects | P0 | Task 6 |
| F08 | Release process historically allowed partial PyPI publication | P0 | Task 7 |
| F09 | Public facts can call GitHub Releases active while no release exists | P1 | Task 7 |
| F10 | Published PyPI README for 0.3.5 contains stale install/version text | P1 | Task 7 |
| F11 | Docker builder apk packages are not exact-version pinned | P1 | Task 8 |
| F12 | Release CI floats uv on 0.11 instead of exact patch identity | P1 | Task 8 |
| F13 | Release CI floats Python on 3.13 instead of exact patch identity | P1 | Task 8 |
| F14 | Required approving reviews is zero in current solo-maintainer model | P1 | Task 9 |
| F15 | Trusted GitHub Actions updates can be too permissive for auto-merge | P1 | Task 9 |
| F16 | MCP defaults to expert tool surface | P1 | Task 10 |
| F17 | MCP exposes a very large public tool surface | P1 | Task 10 |
| F18 | Product scope is broader than current physical-validation depth | P1 | Task 13 |
| F19 | Binary Implemented labels hide import/export/round-trip fidelity | P1 | Task 13 |
| F20 | Documented size standards conflict with large modules | P1 | Task 11 |
| F21 | Architecture feature detector is a very large procedural function | P1 | Task 11 |
| F22 | CI/evidence scripts are becoming a second product | P1 | Task 12 |
| F23 | CI tooling relies on manual sys.path insertion patterns | P1 | Task 12 |
| F24 | Global 75% coverage is not the right optimization target | Guardrail | Task 12 |
| F25 | Critical release/security scripts need stronger type-check coverage | P1 | Task 12 |
| F26 | Deprecation-warning suppressions need owner/expiry policy | P2 | Task 12 |
| F27 | Wall-clock sleeps remain in tests where synchronization can be deterministic | P2 | Task 12 |
| F28 | pyproject license metadata should use modern PEP 639/SPDX form | P2 | Task 8 |
| F29 | Hatchling build backend is unbounded | P2 | Task 8 |
| F30 | Optional dependency groups duplicate membership manually | P2 | Task 8 |
| F31 | Component schema completeness is not component qualification | P1 | Task 13 |
| F32 | Physical boards should take priority over further EDA breadth | P1 | Task 14 |
| F33 | Hardware CI naming can imply physical HIL validation | P2 | Task 14 |
| F34 | Future official container publication should split runtime roles | P2 | Task 15 |
| F35 | Large immutable corpora should move out when repository cost justifies it | P2 | Task 15 |
| F36 | Multi-concern development PRs reduce reviewability and rollback safety | P1 | Task 9 |
| F37 | Security remediation needs an explicit SLA | P1 | Task 9 |
| F38 | Generated public facts need a clearer canonical/live truth boundary | P1 | Task 16 |
| F39 | Documentation freshness must cover repo, built package, and deployed site | P1 | Task 16 |
| F40 | More evidence files do not automatically mean stronger correctness evidence | P1 | Task 14 |

---

# Phase 0 — Feature Freeze and Program Controls

### Task 0: Establish the hardening execution contract

**Files:**
- Modify only when execution begins: ROADMAP.md or docs/ROADMAP.md if the maintainer decides the freeze should be public.
- Use this file as the internal execution source: plans/2026-09-22-zaptrace-engineering-hardening-implementation-plan.md.

**Interfaces:**
- Consumes: this audit contract and existing governance/release policies.
- Produces: phase ordering, pull-request boundaries, and exit criteria for all later tasks.

- [ ] **Step 1: Open tracking issues for Tasks 1-16 with one task per issue.**
- [ ] **Step 2: Mark Tasks 1-10 as blockers for major feature expansion.**
- [ ] **Step 3: Require each task PR to link its tracking issue and list exact verification commands.**
- [ ] **Step 4: Reject cross-workstream PRs unless the change is mechanically inseparable and the PR explains why.**
- [ ] **Step 5: Exit Phase 0 only when ownership and sequencing are visible in GitHub.**

**Commit:** no product-code commit required for Task 0.

---

# Phase 1 — Security Gates and Trust Boundaries

### Task 1: Close the AnyIO advisory gate

**Files:**
- Modify: uv.lock
- Modify as applicable: pyproject.toml and requirements files that carry AnyIO resolution.
- Inspect: .github/workflows/security.yml
- Test: existing dependency-audit/security tests and lock consistency checks.

**Interfaces:**
- Consumes: current dependency lock and Security workflow.
- Produces: a lock set resolving AnyIO to 4.14.2 or newer compatible fixed release without broad unrelated upgrades.

- [ ] **Step 1: Rebase or recreate the existing AnyIO remediation from PR #49 on current main.**
- [ ] **Step 2: Update only the dependency graph required to resolve AnyIO advisories.**
- [ ] **Step 3: Run dependency resolution and inspect the lock diff for unrelated transitive movement.**
- [ ] **Step 4: Run the same uv audit command used by .github/workflows/security.yml.**
- [ ] **Step 5: Run targeted async/network/session tests that transitively depend on AnyIO.**
- [ ] **Step 6: Record advisory IDs GHSA-5p39-cfhj-2xmp and GHSA-82r6-8w77-94w6 in the PR evidence with fixed-version confirmation.**
- [ ] **Step 7: Commit as security: update AnyIO to fixed release.**

**Acceptance:** Security dependency audit is green and no unrelated dependency drift is introduced.

### Task 2: Repair exact-image container security and make it continuously observable

**Files:**
- Modify: Dockerfile
- Modify: requirements/container-apk.txt if present in the current container lock model.
- Modify: .github/workflows/container-security.yml
- Test/Create: tests or CI policy checks that validate scheduled scanning and exact package policy.

**Interfaces:**
- Consumes: pinned base-image digest and runtime APK inventory.
- Produces: a clean exact-image vulnerability gate plus scheduled rescanning independent of source changes.

- [ ] **Step 1: Add a contract test that asserts container-security.yml contains a schedule trigger.**
- [ ] **Step 2: Run the contract test and confirm it fails before workflow modification.**
- [ ] **Step 3: Update Alpine/runtime packages so the known libuuid/util-linux HIGH findings resolve to fixed package revisions.**
- [ ] **Step 4: Regenerate the exact runtime package inventory and provenance evidence.**
- [ ] **Step 5: Add a scheduled exact-image build and Trivy scan; keep pull_request, push, and workflow_call triggers.**
- [ ] **Step 6: Make scheduled failures visible through an existing alert/issue mechanism without silently downgrading severity.**
- [ ] **Step 7: Run Docker build plus the same Trivy policy command used in CI.**
- [ ] **Step 8: Commit as security: refresh container packages and schedule exact-image scans.**

**Acceptance:** source-stable images are rescanned on schedule and the current exact image has no blocking HIGH finding under repository policy.

### Task 3: Replace the plugin sandbox claim with an enforceable trust boundary

**Files:**
- Modify: zaptrace/plugin/runtime.py
- Modify: docs/design/plugin-runtime.md
- Modify: plugin development/security documentation that describes sandbox guarantees.
- Test/Create: tests/test_plugin_runtime_sandbox.py or the repository's existing plugin-runtime test module.

**Interfaces:**
- Consumes: PluginRuntimeConfig, plugin manifest/signature admission, process execution.
- Produces: either a real OS-enforced sandbox or an explicitly named process-isolation runner with no false sandbox claim.

- [ ] **Step 1: Write failing tests for workspace escape, inherited network access, descendant-process cleanup, CPU/memory/FD limits, and write access outside the allowed workspace.**
- [ ] **Step 2: Run the tests and capture the current boundary failures.**
- [ ] **Step 3: Choose one implementation mode in the PR: Linux sandbox enforcement or terminology downgrade. Do not mix a partial sandbox with a hardened-security claim.**
- [ ] **Step 4A: If enforcing a sandbox, add namespace/no-new-privileges/seccomp/resource-limit controls and explicit filesystem/network policy.**
- [ ] **Step 4B: If not enforcing a sandbox, rename HardenedPluginRuntime and all sandbox language to process-isolated execution and document deployment requirements for real containment.**
- [ ] **Step 5: Make sandbox_workspace an enforced boundary or remove the misleading configuration field.**
- [ ] **Step 6: Run plugin runtime tests plus security-focused subprocess tests.**
- [ ] **Step 7: Commit as security: enforce plugin isolation boundary.**

**Acceptance:** documentation and runtime behavior describe the same security boundary; no environment flag alone is presented as sandbox enforcement.

### Task 4: Remove pickle from worker IPC

**Files:**
- Modify: zaptrace/agent/execution.py
- Modify: zaptrace/agent/worker.py
- Modify: tests/test_agent_worker.py
- Create if useful: zaptrace/agent/ipc.py for a versioned closed-schema codec.

**Interfaces:**
- Consumes: parent-to-worker request and worker-to-parent response payloads.
- Produces: versioned JSON/MessagePack/CBOR-compatible payload validation with closed fields and fail-closed schema handling.

- [ ] **Step 1: Add a failing test proving unknown fields, malformed payloads, oversized payloads, and schema-version mismatch are rejected before callable execution.**
- [ ] **Step 2: Add a regression test that scans the production worker path for pickle.load/pickle.loads usage and fails while they remain.**
- [ ] **Step 3: Define explicit request and response models with a schema_version field and extra-field rejection.**
- [ ] **Step 4: Replace parent serialization and worker deserialization with the closed-schema codec.**
- [ ] **Step 5: Preserve existing private-directory, 0600 file, ownership, O_NOFOLLOW, containment, atomic replace, process-group, and rollback protections.**
- [ ] **Step 6: Run tests/test_agent_worker.py and execution/session isolation suites.**
- [ ] **Step 7: Commit as security: replace worker pickle IPC with closed schema.**

**Acceptance:** no production worker IPC path executes Python pickle deserialization.

---

# Phase 2 — Determinism and Reproducibility

### Task 5: Make schematic placement deterministic

**Files:**
- Modify: zaptrace/ee/schematic/placement.py
- Test/Create: tests/test_schematic_placement_determinism.py

**Interfaces:**
- Consumes: canonical component/connectivity input.
- Produces: stable placement coordinates for identical canonical input.

- [ ] **Step 1: Add a test that runs placement in two clean invocations and compares normalized coordinates.**
- [ ] **Step 2: Confirm the test can observe current entropy from random.uniform.**
- [ ] **Step 3: Prefer removing randomness; if force initialization needs entropy, derive a local PRNG seed from canonical design identity and never use module-global random state.**
- [ ] **Step 4: Make ordering explicit before seed derivation and iteration.**
- [ ] **Step 5: Run the determinism test repeatedly and across supported Python lanes.**
- [ ] **Step 6: Commit as fix: make schematic placement deterministic.**

**Acceptance:** same canonical input yields identical schematic placement independent of process-global RNG state.

### Task 6: Make KiCad export object identities deterministic

**Files:**
- Modify: zaptrace/export/kicad.py
- Test/Create: tests/test_kicad_export_determinism.py

**Interfaces:**
- Consumes: semantic design/object identity.
- Produces: deterministic UUIDs and byte-stable generated KiCad artifacts.

- [ ] **Step 1: Add a regression test that exports the same design twice from clean processes and compares canonical bytes.**
- [ ] **Step 2: Add a direct test that generated board geometry and mounting-hole IDs are stable.**
- [ ] **Step 3: Replace uuid4 generation with UUID5 or a digest-derived UUID keyed by design identity, artifact kind, object type, and semantic object ID.**
- [ ] **Step 4: Ensure identity does not depend on incidental traversal order.**
- [ ] **Step 5: Run KiCad exporter tests and the external KiCad oracle lane where available.**
- [ ] **Step 6: Commit as fix: make KiCad export UUIDs deterministic.**

**Acceptance:** identical canonical design plus identical toolchain yields byte-identical canonical KiCad output.

---

# Phase 3 — Release Integrity and Toolchain Identity

### Task 7: Make public release state atomic and truth-preserving

**Files:**
- Modify: .github/workflows/release.yml
- Modify: config/public-facts.json generation source and generator as applicable.
- Modify: scripts/ci_release_gate.py and release-evidence tooling as applicable.
- Modify: docs/development/release-process.md
- Modify: docs/strategy/current-state-audit.md only when public facts change.
- Test/Create: release DAG contract tests and built-metadata tests.

**Interfaces:**
- Consumes: built distributions, container-security result, quality gates, TestPyPI verification, SBOM/checksum/attestation evidence.
- Produces: explicit release state machine with irreversible publication as late as practical.

- [ ] **Step 1: Add a workflow contract test that proves every irreversible PyPI publication path depends on all mandatory pre-publication gates.**
- [ ] **Step 2: Add release-state values such as candidate, verified, published, failed-before-publish, and partial-legacy; avoid one boolean for configured versus actually published.**
- [ ] **Step 3: Move generation/validation of SBOM, checksums, attestations, public metadata, and distribution facts ahead of the final irreversible publication point where technically possible.**
- [ ] **Step 4: Preserve TestPyPI verification as a staging gate.**
- [ ] **Step 5: Add post-publication verification that binds PyPI artifact identity, GitHub release assets, source commit, checksums, and provenance.**
- [ ] **Step 6: Add a built wheel/sdist long-description test that rejects stale install/version text before registry publication.**
- [ ] **Step 7: Represent the v0.3.5 PyPI-without-GitHub-Release incident as historical partial-release evidence; never reuse the immutable tag/version.**
- [ ] **Step 8: Run release workflow contract tests and release-gate evidence tests.**
- [ ] **Step 9: Commit as ci: harden release transaction and public state model.**

**Acceptance:** a normal new release cannot reach the supported published state while a mandatory container/security/metadata gate is red.

### Task 8: Pin release toolchains and modernize packaging metadata

**Files:**
- Modify: Dockerfile
- Modify: requirements/container-builder.txt
- Modify: .github/workflows/release.yml and other evidence-producing workflows.
- Modify: pyproject.toml
- Test/Create: packaging metadata and release-toolchain identity tests.

**Interfaces:**
- Consumes: builder image, APK repositories, Python interpreter, uv, Hatchling, optional dependency metadata.
- Produces: exact release toolchain identity while retaining separate rolling compatibility lanes.

- [ ] **Step 1: Add tests that release/evidence workflows reject floating uv minor-only and Python minor-only selectors.**
- [ ] **Step 2: Pin release uv to one exact tested patch version and record its identity in release evidence.**
- [ ] **Step 3: Pin release Python to one exact tested patch version; keep rolling minor versions only in compatibility CI.**
- [ ] **Step 4: Pin builder APK toolchain versions or move them into a digest-pinned builder image/snapshot repository.**
- [ ] **Step 5: Bound/test Hatchling instead of leaving build-system backend resolution unconstrained.**
- [ ] **Step 6: Change project license metadata to the modern SPDX string form for PolyForm-Noncommercial-1.0.0 and configure license-files according to current packaging support.**
- [ ] **Step 7: Remove manual optional-dependency duplication through one source of truth after validating supported installers.**
- [ ] **Step 8: Build sdist and wheels, inspect METADATA, and run clean-install smoke tests.**
- [ ] **Step 9: Commit as build: pin release toolchain and modernize package metadata.**

**Acceptance:** every release artifact can be traced to exact interpreter, package manager, build backend, builder-image, and relevant system-package identities.

---

# Phase 4 — Governance and Least Privilege

### Task 9: Strengthen review, automation, security SLA, and PR boundaries

**Files:**
- Modify as policy requires: CONTRIBUTING.md
- Modify: GOVERNANCE.md
- Modify: MAINTAINERS.md
- Modify: dependency automation configuration such as .github/renovate.json when present.
- Modify: CODEOWNERS/ruleset documentation if introduced.
- Test/Create: policy consistency tests where repository policy is machine-checked.

**Interfaces:**
- Consumes: current solo-maintainer governance, active main ruleset, dependency automation.
- Produces: explicit high-risk review policy without pretending independent review exists when it does not.

- [ ] **Step 1: Define critical path classes for workflow, release, security, plugin, MCP/API auth, worker execution, manufacturing export, and component-trust policy.**
- [ ] **Step 2: Require one non-author approval for those classes once a second trusted reviewer exists; until then, document the unmet control as a governance limitation rather than silently claiming it.**
- [ ] **Step 3: Disable auto-merge for trusted GitHub Actions updates affecting OIDC, publishing, artifacts, SARIF/security-events, containers, or attestations.**
- [ ] **Step 4: Define security remediation SLA: Critical same day, High within 24-48 hours, Medium within 7 days, Low in normal dependency cadence.**
- [ ] **Step 5: Add PR guidance that security/release/determinism changes must carry one primary invariant and an explicit rollback path.**
- [ ] **Step 6: Keep the existing active branch ruleset, force-push/deletion protections, linear history, and required aggregate checks intact.**
- [ ] **Step 7: Run governance/documentation consistency checks.**
- [ ] **Step 8: Commit as governance: tighten critical-change review policy.**

**Acceptance:** repository policy clearly distinguishes current solo-maintainer reality from the target independent-review control and prevents silent auto-merge of high-trust CI changes.

### Task 10: Make MCP least-privilege by default and reduce tool-selection surface

**Files:**
- Modify: zaptrace/agent/tool_surfaces.py
- Modify: zaptrace/mcp/server.py
- Modify: tests/test_mcp_tool_surfaces.py
- Modify: MCP quickstart/reference docs and config examples.

**Interfaces:**
- Consumes: TOOL_REGISTRY, existing inspect/design/verify/repair/release/expert surfaces.
- Produces: minimal safe default and context-appropriate tool discovery/exposure.

- [ ] **Step 1: Change the default-surface regression test to expect inspect or another explicitly read-only minimal surface instead of expert.**
- [ ] **Step 2: Run the test and confirm the current default fails.**
- [ ] **Step 3: Change resolve_tool_surface(None) to the selected least-privilege surface while preserving explicit expert opt-in.**
- [ ] **Step 4: Add tests proving repair/release/mutating tools are absent from the default surface.**
- [ ] **Step 5: Introduce task-oriented or lazy capability exposure so normal sessions do not advertise the entire registry when unnecessary.**
- [ ] **Step 6: Preserve authorization checks even when a tool is hidden; exposure is not a replacement for capability enforcement.**
- [ ] **Step 7: Run MCP surface, policy, session, and authorization tests.**
- [ ] **Step 8: Commit as security: default MCP to least privilege.**

**Acceptance:** an unset tool-surface configuration never exposes the broad expert registry by default.

---

# Phase 5 — Maintainability and Assurance Control-Plane Simplification

### Task 11: Split oversized runtime modules around stable responsibilities

**Files:**
- Refactor incrementally: zaptrace/generation/architecture.py
- Refactor incrementally: zaptrace/agent/execution.py
- Refactor incrementally: zaptrace/mcp/server.py
- Refactor incrementally: zaptrace/proof/pack.py
- Refactor incrementally: zaptrace/erc/rules.py
- Refactor incrementally: zaptrace/ee/drc/engine.py
- Refactor incrementally: zaptrace/cli/main.py
- Evaluate generator split: scripts/generate_library_expansion.py
- Modify: tests for each extracted unit.

**Interfaces:**
- Consumes: existing public behavior and contracts.
- Produces: smaller modules with explicit boundaries and no behavior change unless separately specified.

- [ ] **Step 1: Add characterization tests before moving code from each targeted module.**
- [ ] **Step 2: Start with zaptrace/generation/architecture.py and extract feature detectors into a registry of independently testable detectors.**
- [ ] **Step 3: Give each detector explicit applicability, evidence, produced features, conflict/precedence behavior, and confidence semantics.**
- [ ] **Step 4: Move one cohesive responsibility per PR; do not perform broad rename/reformat churn.**
- [ ] **Step 5: Keep public imports stable or add deliberate compatibility shims with expiry.**
- [ ] **Step 6: Update documented module/function-size standards if the project intentionally treats them as guidance rather than hard limits; otherwise add enforcement.**
- [ ] **Step 7: Run characterization plus domain test suites after each extraction.**
- [ ] **Step 8: Commit each extraction separately using refactor: prefixes.**

**Acceptance:** the largest risk-bearing modules no longer centralize unrelated concerns, and documented standards match actual enforcement policy.

### Task 12: Consolidate CI/evidence tooling and improve test determinism

**Files:**
- Refactor: scripts/ CI helpers into importable modules where repeated.
- Modify: pyproject.toml type-check configuration.
- Modify: warning-filter configuration.
- Modify: tests using avoidable time.sleep/asyncio.sleep.
- Preserve: scripts/ci_critical_runtime_coverage.py and its critical-module floor model.

**Interfaces:**
- Consumes: existing CI scripts and policy JSON.
- Produces: fewer duplicated policy engines, deterministic imports, stronger typing, and less wall-clock-dependent test behavior.

- [ ] **Step 1: Inventory duplicated setup, path manipulation, evidence hashing, policy loading, and report-writing logic across scripts/.**
- [ ] **Step 2: Add characterization tests for shared tooling before extraction.**
- [ ] **Step 3: Replace manual sys.path insertion with package/module entry points such as python -m for repository-owned tooling.**
- [ ] **Step 4: Expand Pyright coverage to release/security/evidence scripts that make production decisions.**
- [ ] **Step 5: Keep critical per-module coverage floors; do not substitute a higher global percentage as the only gate.**
- [ ] **Step 6: Give each deprecation suppression an owner, upstream reference, introduction date, expiry/removal condition, and a test or policy check that prevents permanent silent suppression.**
- [ ] **Step 7: Replace avoidable real sleeps with events, conditions, fake monotonic clocks, or deterministic process signaling.**
- [ ] **Step 8: Run Ruff, Pyright, critical coverage, and affected test suites.**
- [ ] **Step 9: Commit as refactor: consolidate assurance tooling.**

**Acceptance:** CI policy logic has one source of truth where practical, critical tooling is type-checked, and timing-dependent tests are reduced without weakening coverage gates.

---

# Phase 6 — EDA Product Depth and Qualification

### Task 13: Define the supported golden path, fidelity matrix, and qualified component cohort

**Files:**
- Modify: docs/ROADMAP.md
- Modify: docs/interop/cross-eda-readiness.md
- Modify: data/interop/cross-eda-support-matrix.json
- Modify: component trust/qualification policy and baseline files.
- Modify: relevant interop/component tests.

**Interfaces:**
- Consumes: current broad EDA surface and heuristic component library.
- Produces: explicit supported golden path, directional interop fidelity, and a smaller qualified component set.

- [ ] **Step 1: Freeze new major format breadth until the golden path exit criteria are satisfied.**
- [ ] **Step 2: Define the supported path: requirements -> architecture -> component selection -> schematic -> PCB -> KiCad export -> ERC/DRC -> analysis -> manufacturing export -> proof evidence -> physical validation.**
- [ ] **Step 3: Replace binary Implemented labels with read, write, round-trip, semantic-fidelity, unsupported-construct, corpus-size, and external-oracle dimensions.**
- [ ] **Step 4: Select a smaller golden component cohort and require exact manufacturer part, datasheet revision, pinout, electrical limits, footprint/package geometry, lifecycle/sourcing, provenance, and human qualification evidence.**
- [ ] **Step 5: Keep heuristic records available but prohibit qualification claims solely from schema completeness.**
- [ ] **Step 6: Add contract tests for support-matrix directionality and qualification-tier requirements.**
- [ ] **Step 7: Run interop and component-trust suites.**
- [ ] **Step 8: Commit as docs/feat according to whether behavior or only policy changes.**

**Acceptance:** product claims describe fidelity and qualification depth, not only the existence of parsers/exporters or populated schemas.

### Task 14: Make physical correlation the highest-value evidence program

**Files:**
- Modify: benchmark manifests and physical-validation plans.
- Modify: workflow naming currently presented as Hardware CI.
- Modify: docs/benchmarks and assurance documentation.
- Add: versioned physical measurement/result artifacts for selected golden boards.

**Interfaces:**
- Consumes: software-generated designs, external KiCad/oracle evidence, benchmark boards.
- Produces: revision-bound physical measurements correlated to software evidence.

- [ ] **Step 1: Select at least three representative golden board families, including digital/USB, bus/communications, and mixed-signal/power characteristics.**
- [ ] **Step 2: Define fabrication package identity, incoming inspection, resistance checks, first-power protocol, current draw, rail measurements, thermal observations, clocks, communications, functional tests, and failure/re-spin logging.**
- [ ] **Step 3: Bind physical results to source commit, design artifact hashes, BOM, manufacturing outputs, and test equipment metadata.**
- [ ] **Step 4: Rename Hardware CI to a term such as Hardware Design Verification or EDA Integration unless physical HIL is actually executed.**
- [ ] **Step 5: Rank evidence sources by independence: external EDA oracle, differential testing, golden reference, physical measurement, manufacturer feedback, independent review, then internal self-reports.**
- [ ] **Step 6: Require any new evidence artifact to state which uncertainty it reduces and which independent oracle validates it.**
- [ ] **Step 7: Add tests/schema validation for physical-result provenance and evidence linkage.**
- [ ] **Step 8: Commit as test/docs: establish physical correlation program.**

**Acceptance:** roadmap maturity is measured by correlation between generated artifacts and observed boards, not by the count of internal JSON reports.

---

# Phase 7 — Deployment and Repository Boundaries

### Task 15: Split runtime deployment roles and define corpus extraction thresholds

**Files:**
- Modify when official images are published: Dockerfile and/or role-specific Dockerfiles.
- Modify: docker-compose.yml and deployment docs as applicable.
- Add policy/documentation for external fixture/corpus storage only when thresholds are crossed.

**Interfaces:**
- Consumes: shared builder and current multi-entrypoint runtime.
- Produces: minimal CLI, REST, and MCP runtime images plus explicit data-boundary policy.

- [ ] **Step 1: Measure installed packages and attack surface required by CLI, REST, and MCP separately.**
- [ ] **Step 2: Create a shared digest-pinned builder stage and minimal role-specific runtime stages before official GHCR publication.**
- [ ] **Step 3: Add smoke tests proving each image exposes only its intended entrypoint/runtime dependencies.**
- [ ] **Step 4: Define repository-corpus extraction thresholds using checkout size, update frequency, review value, and immutability.**
- [ ] **Step 5: When thresholds are met, move large immutable corpora to a versioned fixture package, release asset, OCI artifact, or dedicated corpus repository with hashes pinned from ZapTrace.**
- [ ] **Step 6: Run container smoke/security scans for each role-specific image.**
- [ ] **Step 7: Commit as build: split runtime deployment roles.**

**Acceptance:** deployment artifacts minimize unnecessary runtime surface, and large data leaves the main repository only under a documented integrity-preserving policy.

---

# Phase 8 — Truth, Documentation, and Evidence Freshness

### Task 16: Make public facts generated, stateful, and cross-surface consistent

**Files:**
- Modify: config/public-facts.json generator/source model.
- Modify: scripts/ci_docs_status_sync.py
- Modify: tests/test_docs_status_sync.py
- Modify: docs/strategy/current-state-audit.md
- Modify: build/release metadata validation.
- Modify: deployed-site provenance checks as applicable.

**Interfaces:**
- Consumes: canonical repository config, live release/distribution observations, built package metadata, deployed docs provenance.
- Produces: generated facts that distinguish configured, enabled, healthy, published, degraded, disabled, and historical states.

- [ ] **Step 1: Separate static repository capabilities from live platform/distribution state.**
- [ ] **Step 2: Generate public-facts.json from canonical sources and fail CI when regeneration produces a dirty diff.**
- [ ] **Step 3: Represent GitHub Releases and PyPI state with explicit state values rather than one active boolean.**
- [ ] **Step 4: Add freshness checks across repository main, built wheel/sdist long description, and deployed documentation site provenance.**
- [ ] **Step 5: Keep source revision and generated timestamp on machine-derived facts.**
- [ ] **Step 6: Ensure historical dated documents remain historical and are not interpreted as current capability claims.**
- [ ] **Step 7: Run tests/test_docs_status_sync.py plus MkDocs strict build and built-package metadata checks.**
- [ ] **Step 8: Commit as docs: make public facts generated and state-aware.**

**Acceptance:** a public status claim is traceable to its source revision and cannot silently contradict registry or deployed documentation state.

---

# Phase 9 — Program Verification and Exit

### Task 17: Run final hardening acceptance matrix

**Files:**
- No new product code is required unless a failed acceptance check identifies a defect.
- Update this plan's tracking issue set and durable public docs only with verified final state.

**Interfaces:**
- Consumes: outputs of Tasks 1-16.
- Produces: evidence that feature expansion can resume without weakening the newly established invariants.

- [ ] **Step 1: Run the full repository test suite: uv run pytest -q.**
- [ ] **Step 2: Run Ruff check and format verification.**
- [ ] **Step 3: Run Pyright over configured runtime and critical tooling scopes.**
- [ ] **Step 4: Run strict REUSE/license compliance.**
- [ ] **Step 5: Run dependency/security workflows and exact-image scans.**
- [ ] **Step 6: Run critical-runtime coverage gates.**
- [ ] **Step 7: Run deterministic schematic and KiCad clean-process regression tests.**
- [ ] **Step 8: Run release DAG/metadata/state contract tests.**
- [ ] **Step 9: Run MCP least-privilege and authorization tests.**
- [ ] **Step 10: Run strict MkDocs/docs-status validation.**
- [ ] **Step 11: Confirm at least the selected golden physical-board program has revision-bound measurements or explicitly remains a release non-claim.**
- [ ] **Step 12: Re-open major feature expansion only after Tasks 1-10 are complete and remaining P1 items have owners and dates.**

## Program Definition of Done

The hardening program is complete only when all of the following are true:

- Scheduled Security is green for the locked dependency set.
- Exact-image container security is green and scheduled.
- Plugin isolation language equals enforceable runtime behavior.
- Worker IPC has no production pickle deserialization.
- Schematic placement and KiCad identity generation are deterministic under identical canonical inputs.
- Release state prevents normal partial publication and verifies post-publish channel consistency.
- Release evidence records exact uv, Python, build backend, builder image, and required system-package identities.
- Default MCP exposure is least-privilege and broad expert access is explicit opt-in.
- Critical-change governance documents the current human-review limitation and blocks unsafe automation where review matters most.
- High-risk large modules are being split through characterized, independently reviewable refactors rather than broad rewrites.
- CI/evidence tooling has fewer duplicate policy engines and stronger type coverage.
- Interoperability claims express direction and fidelity.
- Qualified components are evidence-qualified, not merely schema-complete.
- Physical benchmark correlation is treated as stronger evidence than additional internal reports.
- Public facts are generated, revision-bound, and state-aware.
- Repository, package-registry metadata, and deployed documentation cannot silently drift on current-version/status claims.
- All 40 findings in the coverage matrix have a completed task, an accepted residual-risk record, or an explicitly documented non-action with evidence.

## Execution Handoff

Recommended execution mode: **subagent-driven development**. The work spans security boundaries, release engineering, deterministic EDA generation, governance, packaging, and physical validation; an error in one workstream can invalidate evidence from another. Each task should therefore receive a fresh implementation context and a separate review gate, followed by a whole-branch/program review at phase boundaries.

For any single bounded task, use the corresponding Superpowers implementation workflow and execute its red-green-refactor cycle before moving to the next task.
