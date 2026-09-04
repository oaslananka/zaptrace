# Changelog

## [Unreleased]

### Changed

- Advanced the development line to Python `0.3.6.dev0` / Cargo `0.3.6-dev.0` after the immutable `v0.3.5` tag and PyPI publication. The `v0.3.5` tag workflow is retained as partial-release evidence because its container-security gate failed before GitHub Release creation; the tag/version will not be reused.
- Hardened the release DAG so TestPyPI/PyPI publication cannot proceed unless the tagged container-security gate succeeds.

## [0.3.5] - 2026-09-03

### Changed

- Synchronized package identity to final `0.3.5` across Python (`pyproject.toml`), Rust (`zaptrace_core/Cargo.toml`), lockfiles (`uv.lock`, `Cargo.lock`), runtime surfaces, and public-facts documentation for release-preparation review.
- Updated CHANGELOG and public-facts for release-preparation state (`mode=release-preparation`, `published=false`) without claiming publication before the tag workflow succeeds.
- Preserved immutable failed `v0.3.4` evidence at tag `v0.3.4` (commit `76ecc97bdd93292e0901fc6a3d03f705d2ab7916`) without deletion, movement, rewrite, or reuse.

## [0.3.4] - 2026-09-02

### Changed

- Recorded `v0.3.4` (annotated tag at `76ecc97bdd93292e0901fc6a3d03f705d2ab7916`) as an aborted/failed release candidate whose workflow failed before public PyPI upload or GitHub Release creation. Preserved immutably as failed-release evidence without deletion, rewriting, or reuse.
- Marked `v0.3.3` explicitly as a legacy PyPI-only baseline without public Git provenance; `v0.3.5` is the intended first fully public-repository-traceable release.
- Added `[project.urls]` metadata table (Homepage, Repository, Issues, Documentation, Changelog) to `pyproject.toml`.

## [0.3.3] - 2026-08-18

### Fixed

- Isolated TestPyPI/PyPI publisher inputs to wheel and source-distribution files only, while retaining release dependency evidence in the GitHub release artifact set. This recovers from the immutable `v0.3.2` tagged attempt, which stopped during publisher metadata validation before any TestPyPI/PyPI upload or GitHub Release creation.

## [0.3.2] - 2026-08-18

### Changed

- Selected `zaptrace-eda` as the registry distribution identity while preserving the `zaptrace` import package and CLI names, and added tokenless GitHub OIDC staging/publishing gates for TestPyPI and PyPI with exact registry hash and clean-install verification.
- Advanced post-release development identity to Python `0.3.2.dev0` / Cargo `0.3.2-dev.0` after the successful `v0.3.1` tagged release, including synchronized agent/plugin manifests and active plugin compatibility ceilings.

## [0.3.1] - 2026-08-18

### Fixed

- Updated the tagged-release checkout action to the upstream annotated-tag-preserving implementation so release identity validation sees the signed tag object instead of a lightweight commit ref.
- Fixed tagged-release dependency bootstrap to defer project installation until the native `maturin develop` step, preserving the locked no-build dependency environment.
- Hardened KiCad PPA bootstrap across release, validation, hardware, and oracle CI with bounded PPA/apt retries, suppressed implicit package-cache refreshes, and a canonical Ubuntu mirror fallback for slow GitHub runner Azure mirrors.
- Stabilized tagged-release Python quality gates by deferring the global coverage floor until shard aggregation and isolating the no-live-simulation corpus test from host ngspice availability.
- Isolated tagged-release external-tool and native prerequisites to their dedicated lanes so unit and integration contracts remain deterministic regardless of host tool availability.
- Matched tagged-release source-tree import semantics to regular Quality by exposing the repository root through `PYTHONPATH` without reinstalling the project globally.
- Made the committed version-policy consistency test honor tagged-release context so an exact release tag is validated as a release rather than rejected as release-preparation tag reuse.
- Kept tagged-release identity gates clean after test execution by treating uploaded release evidence outputs as transient generated files instead of source-tree modifications.
- Allowed locked third-party source builds only in native-wheel clean-install smoke environments so supported macOS Intel wheels remain verifiable after upstream `cryptography` stopped publishing x86_64 macOS binaries.
- Fixed tagged-release startup by propagating the reusable container scan's required `security-events: write` permission from the release caller while keeping duplicate SARIF publication disabled.
- Added a bounded release-preparation version context so exact `release/v<version>` pull requests can validate RC/final identities without weakening normal development-version enforcement or tagged-release checks.
- Reconciled the public current-state audit with machine-derived component, KiCad-import, and release evidence; removed internal implementation-plan material from published docs; and extended docs drift checks to cover revision identity and release capabilities.
- Replaced the deleted Sonar debt tracking issue reference with an explicit nullable policy field while retaining closed issue #338 as historical implementation evidence.
- Added strict MkDocs validation for documentation pull requests while restricting GitHub Pages deployment to pushes on `main`.
- Synchronized public repository documentation and the docs-status drift guard with the enabled GitHub Discussions channel, bounded SPICE evidence, the current solo-maintainer review model, and the absence of open maturity-tracking issues.
- Restored source-tree imports in the no-build Hardware workflow by exposing the checked-out repository through `PYTHONPATH`.
- Corrected the IPC-2581 schema-location test assertion ordering so static analysis treats the exported value as actual and the named contract value as expected.

### Security

- Completed MCP OAuth Slice 5 evidence and migration: real ephemeral RS256/JWKS integration tests now enforce required expiration and not-before semantics across the negative credential matrix, Compose forwards the versioned OAuth profile with profile-aware health checks, and CI emits redacted packaged OAuth discovery/denial evidence without storing signing material.
- Completed the MCP OAuth Slice 4 authorization boundary: the supported `oauth-jwt` launcher now enforces per-request RFC 6750 `403 insufficient_scope` responses before tool/object execution, preserves structured `OBJECT_NOT_AUTHORIZED` session-ACL denials, and records OAuth audit actors with redacted pair-bound principals.
- Added the bounded MCP OAuth scope/principal adapter: authority now comes only from FastMCP-validated `AccessToken.scopes`, unknown scopes grant nothing, OAuth ignores environment/session capability grants, `(iss, sub)` becomes a deterministic redacted principal, and scope denial was staged before object claim while the supported OAuth listener was still disabled pending Slice 4.
- Added bounded FastMCP `RemoteAuthProvider(JWTVerifier(...))` construction for the staged MCP OAuth profile, RFC 9728 protected-resource metadata, stable/redacted missing-vs-invalid bearer `401` challenges, and a valid-token fail-closed guard while keeping the supported OAuth listener disabled until scope/principal integration.
- Added versioned, mutually exclusive MCP HTTP auth-profile resolution with fail-closed legacy/OAuth conflict checks, HTTPS and same-origin validation, preserved local/static-bearer compatibility, and an explicit pre-listener denial until the later OAuth authorization slices are complete.
- Defined the versioned remote MCP HTTP OAuth/JWT resource-server contract, including fixed scope mapping, audience binding, discovery/challenge behavior, migration from controlled static bearer, threat controls, and bounded implementation sequencing.
- Made plugin admission cryptographically fail closed by requiring a trusted Ed25519 public key, verifying the canonical manifest signature before permission evaluation, rejecting unknown manifest fields, and redacting invalid-schema audit details.
- Updated the Zizmor workflow-audit pin from the yanked v1.27.0 release to v1.29.0, which includes the upstream credential-logging fix.
- Ratcheted the exact-main Sonar historical-debt baseline from 50 to 49 after simplifying MCP parameter validation, with the 0.5.0 ceiling tightened to 45.
- Ratcheted the exact-main Sonar historical-debt baseline from 51 to 50 after simplifying the EasyEDA Standard reader, with the 0.5.0 ceiling tightened to 46.
- Ratcheted the exact-main Sonar historical-debt baseline from 52 to 51 after simplifying architecture feature compilation, with the 0.5.0 ceiling tightened to 47.
- Ratcheted the exact-main Sonar historical-debt baseline from 54 to 52 after the AC stability and KiCad courtyard refactors, with the 0.5.0 ceiling tightened to 48.
- Ratcheted the exact-main Sonar historical-debt baseline from 55 to 54 after reducing copper-pour stitching-via complexity, with the 0.5.0 ceiling tightened to 50.
- Ratcheted the exact-main Sonar historical-debt baseline from 63 to 55 after eliminating the remaining GitHub Actions runtime findings, with the 0.5.0 ceiling tightened to 51.
- Hardened the proof-pack, KiCad-oracle, security-scan, and source-distribution workflows by disabling project builds during locked sync and running Python tools only from the pre-synced environment.
- Ratcheted the exact-main Sonar historical-debt baseline from 80 to 63 after hardening the hardware workflow runtime, with the 0.5.0 ceiling tightened to 58.
- Hardened the hardware workflow Python boundary by disabling project builds during locked dependency sync and executing tests and CI scripts directly from the pre-synced virtual environment.
- Documented the canonical IPC-2581D HTTP namespace and schema-location identifiers as non-dereferenced XML metadata, with focused network-free export coverage and exact-line Sonar dispositions.
- Excluded terminal Sonar issue statuses from unresolved historical-debt counts when the upstream `resolved=false` API response still contains recently closed records.
- Constrained BOM-risk JSON/CSV inputs and failure-comment outputs to the trusted repository root, rejecting traversal, absolute-path, and symlink escapes before filesystem access.
- Constrained generated-board artifact directories to an explicit trusted root, rejecting traversal, symlink escapes, and destructive selection of the root directory itself before cleanup.
- Constrained KiCad Oracle summary outputs to the trusted repository root and rejected traversal, absolute-path, and symlink escapes before writing JSON evidence.
- Constrained KiCad round-trip corpus inputs to the trusted repository root and rejected traversal, absolute-path, and symlink escapes before reading YAML.
- Constrained PR review YAML config inputs to the trusted repository root and rejected traversal, absolute-path, and symlink escapes before reading configuration.
- Constrained correctness-fixture corpus inputs to the trusted repository root and rejected traversal, absolute-path, and symlink escapes before reading YAML.
- Constrained checksum-manifest CLI inputs and outputs to the trusted workspace and required the manifest to remain inside its artifact directory.

### Maintainability debt reduction

- Refreshed the exact-main Sonar historical-debt baseline from 49 to 27 unresolved findings and tightened the v0.5.0 ceiling to 25 while preserving the 6.5% reduction commitment.
- Reduced plugin-admission cognitive complexity by extracting signature-policy evaluation and removed a redundant exception subclass catch without changing denial codes or audit behavior.
- Reduced MCP tool-parameter validation cognitive complexity by separating registry type checks from sandbox path-policy checks while preserving error order and accepted values.
- Reduced EasyEDA Standard reader cognitive complexity by separating root decoding, metadata handling, supported-record population, and degradation recording while preserving deterministic import results.
- Reduced architecture-compiler cognitive complexity by moving feature population into a bounded draft helper while preserving deterministic artifacts.
- Extracted KiCad courtyard line, rectangle, and polygon point collection into focused helpers without changing footprint extents.
- Reduced AC stability check cognitive complexity by separating crossover, gain-threshold, phase-margin, and crossover-threshold evaluation while preserving result order and fallback semantics.
- Reduced copper-pour stitching-via cognitive complexity by extracting boundary, occupancy, and clearance helpers while preserving deterministic via placement.
- Refreshed the exact-revision Sonar debt baseline from 82 to 80 unresolved findings after resolving the two IPC-2581 XML-identifier findings, tightened the 0.4.0 ceiling to 80, and set the 0.5.0 ceiling to 74 while preserving the 6.5% reduction commitment.
- Refreshed the exact-revision Sonar debt baseline from 90 to 82 unresolved findings after eliminating open `pythonsecurity:S8707` findings, tightened the 0.4.0 ceiling to 82, and set the 0.5.0 ceiling to 76 while preserving the 6.5% reduction commitment.
- Refreshed the exact-revision Sonar debt baseline from 91 to 90 unresolved findings after checksum-manifest path hardening in #485, tightened the 0.4.0 ceiling to 90, and set the 0.5.0 ceiling to 84 while preserving the 6.5% reduction commitment.
- Refreshed the exact-revision Sonar debt baseline from 93 to 91 unresolved findings after bounded remediation through #483, tightened the 0.4.0 ceiling to 91, and set the 0.5.0 ceiling to 85 while preserving the 6.5% reduction commitment.
- Contained the benchmark specification, proof-pack, BOM-risk, and committed-artifact inputs within the repository root while splitting scoring validation into focused helpers.
- Refreshed the exact-revision Sonar debt baseline from 94 to 93 unresolved findings after bounded remediation through #480, tightened the 0.4.0 ceiling to 93, and set the 0.5.0 ceiling to 86 while preserving the 6.5% reduction commitment.
- Normalized tuple-based and trace-attached via measurements through shared DFM limit helpers without changing violation order or readiness output.
- Refreshed the exact-revision Sonar debt baseline from 95 to 94 unresolved findings after bounded remediation through #478, tightened the 0.4.0 ceiling to 94, and set the 0.5.0 ceiling to 87 while preserving the 6.5% reduction commitment.
- Extracted direct and inductor-mediated ERC power-source discovery into focused helpers without changing rail classification.
- Refreshed the exact-revision Sonar debt baseline from 96 to 95 unresolved findings after bounded remediation through #476, tightened the 0.4.0 ceiling to 95, and set the 0.5.0 ceiling to 88 while preserving the 6.5% reduction commitment.
- Extracted Specctra DSN parser, structure, placement, library, network, and wiring rendering into focused helpers without changing serialized output.
- Refreshed the exact-revision Sonar debt baseline from 103 to 96 unresolved findings after bounded remediation through #474, tightened the 0.4.0 ceiling to 96, and set the 0.5.0 ceiling to 89 while preserving the 6.5% reduction commitment.
- Extracted shared Excellon hole collection and deterministic drill rendering helpers, reducing both public exporters while preserving byte-for-byte output.
- Extracted connected-pin collection and component/power fallback classification into focused helpers without changing net classes.
- Extracted schematic pin-position collection and orthogonal wire segment generation without changing routed SVG geometry.
- Extracted schematic SVG primitive rendering into focused command handlers without changing serialized SVG output.
- Replaced canonical net-name branching with focused pure generators and a typed dispatch table without changing generated names.
- Extracted ERC patch rule dispatch and computed LED/I²C patch construction into focused helpers without changing suggestions.
- Extracted trace and via net-identity normalization into focused helpers without changing canonical IDs or unknown-reference evidence.
- Refreshed the exact-revision Sonar debt baseline from 111 to 103 unresolved findings after bounded remediation through #461, tightened the 0.4.0 ceiling to 103, and set the 0.5.0 ceiling to 96 while preserving the 6.5% reduction commitment.
- Extracted known-failure mutation application into focused class-specific helpers without changing mutated designs.
- Extracted Ethernet controller, control-net, decoupling, and RJ45 front-end construction into focused synthesis helpers.
- Extracted placer grid initialization, spring attraction, repulsion, and bounded position updates into focused helpers.
- Extracted per-record integrity, duplicate identity, and clean-count evaluation into focused LCSC manifest helpers.
- Extracted passive, diode, and unsupported-device SPICE card construction into focused helpers.
- Extracted differential-pair suffix matching and parallel-offset direction geometry into focused helpers.
- Extracted nearest-edge selection from grid-router Prim decomposition into a focused helper.
- Refreshed the exact-revision Sonar debt baseline from 115 to 111 unresolved findings after bounded remediation through #453, tightened the 0.4.0 ceiling to 111, and set the 0.5.0 ceiling to 103 while preserving the 6.5% reduction commitment.
- Refreshed the exact-revision Sonar debt baseline from 455 to 115 unresolved findings after bounded remediation through #448, tightened the 0.4.0 ceiling to 115, and set the 0.5.0 ceiling to 107 while preserving the 6.5% reduction commitment.
- Extracted solder-mask threshold selection, trace-pair classification, and violation construction into focused DRC helpers.
- Extracted fillet-chain endpoint indexing and next-segment selection into focused helpers without changing trace ordering.
- Extracted rail-load deduplication, per-rail budget calculation, and status decisions into focused helpers without changing evidence.
- Extracted KiCad STEP skip, output, command, execution, and evidence construction into focused helpers while keeping default generated STEP outputs readable after return.
- Extracted DFM trace-clearance pair and drilled-pad bound classification into focused helpers without changing violations.
- Extracted nested, bare, and malformed KiCad symbol-pin coordinate parsing into focused helpers.
- Extracted library dashboard part loading, alternate mapping, conflict classification, and aggregate counters into focused helpers without changing evidence.
- Unified KiCad ERC and DRC process execution, metadata capture, report parsing, and cleanup in focused oracle helpers.
- Extracted basic-router component lookups and pad-aware net escape positions into focused helpers without changing routing results.
- Extracted placer reference indexing and pair/star spring construction into focused helpers without changing connection graphs.
- Extracted power-source, system-path, and per-rail regulator planning into focused helpers without changing architecture plans.
- Extracted hierarchical KiCad sheet reading, diagnostics, and child-queue construction into focused traversal helpers.

- Extracted board-edge outline, rectangular distance, and per-trace violation construction into focused DRC helpers.
- Extracted KiCad footprint pad/net parsing and component construction into focused importer helpers without changing imported designs.

- Extracted KiCad ERC/DRC result rendering into a focused CLI helper without changing oracle output.

- Extracted MCP tool categorization, grouping, reference rendering, and error appendix generation into focused documentation helpers.

- Extracted high-current minimum-width and per-net IPC-2152 trace evaluation into focused DRC helpers without changing findings.

- Extracted EasyEDA Pro project metadata, schematic, and PCB ZIP loading into focused helpers without changing degradation records.

- Extracted Eagle layer, outline, component, signal, via, and unsupported-note export into focused helpers without changing XML output.

- Extracted standalone proof-pack manifest, rendering, and bundle writing into focused CLI helpers without changing exit behavior.

- Extracted MCAD component position, rotation, and row construction into focused helpers without changing exports.

- Extracted benchmark evidence selection, item normalization, blocking classification, and summary rendering into focused review helpers.
- Replaced repair-track fault-class branching with focused schematic detectors while preserving benchmark outcomes.
- Extracted per-component BOM risk line, provenance, highest-risk, and blocking decisions into focused helpers without changing reports.
- Extracted USB-C inrush analytic measurements and threshold construction into focused helpers without changing gate decisions.
- Extracted proof-run JSON, summary, and verbose-detail rendering into focused CLI helpers without changing exit behavior.
- Extracted Markdown report summary, component, net, violation, and coverage-gap rendering into focused helpers without changing output.
- Extracted per-project KiCad import and EasyEDA conversion corpus evaluation into focused CI helpers without changing gate reports.
- Extracted library-part summarization, threshold evaluation, and load-warning rendering into focused integrity helpers without changing reports.
- Extracted manufacturing artifact suffix and filename classification into focused helpers without changing evidence kinds.
- Extracted copper-pour flood-fill neighbor selection into a focused helper without changing eight-way connectivity or obstacle handling.
- Extracted Review Studio DFM item flattening and severity precedence into focused helpers without changing panel output.
- Extracted LCSC cache, search, record-fetch, and cache-write orchestration into focused helpers without changing importer results.
- Extracted Freerouting JAR discovery, hashing, and version probing into focused helpers without changing skip evidence.
- Replaced package-family footprint dispatch branches with a focused ordered generator table without changing supported packages.
- Extracted KiCad netlist node and per-net evidence construction into focused helpers without changing parity reports.
- Extracted MCU power and interface pin assignment into focused helpers while preserving synthesized connectivity.
- Extracted EMC switcher detection and package loop-area scoring into focused helpers without changing report findings.
- Extracted CycloneDX hardware-BOM grouping and component rendering into focused helpers without changing output.
- Extracted drilled-hole collection and IPC-2221 clearance classification into focused DRC helpers without changing findings.
- Extracted USB-C inrush reference, waveform, and gate-decision orchestration into focused helpers without changing evidence states.
- Extracted KiCad schematic component, net, and import-loss construction into focused helpers without changing import evidence.
- Reused the canonical component-footprint resolver during grid obstacle blocking while preserving courtyard behavior.
- Extracted validation-tool execution and minimum-version decisions into focused helpers while preserving parity statuses.
- Extracted DFM trace-width classification into a focused helper while preserving signal warnings and power errors.
- Extracted via-stub data-rate, risk, and note classification into focused helpers while preserving SI guidance.
- Extracted per-component footprint resolution into focused helpers while preserving parametric, package, vendored, and unresolved outcomes.
- Replaced the final super-linear DCO sign-off pattern with linear parsing and bounded ERC rail-voltage tokens without changing accepted engineering formats.
- Extracted convergence CI interop and failure reporting into focused helpers while preserving gate output and exit codes.
- Bounded ERC regulator current parsing tokens and whitespace while preserving supported ampere and milliampere values.
- Extracted corpus-owned simulation output cleanup into a focused helper while preserving symlink-safe deletion.
- Extracted simulation gate status classification into a focused decision helper while preserving risk and blocking semantics.
- Extracted proof-pack simulation model path resolution into a focused existing-artifact helper.
- Adopted canonical lowercase ERC rule function names while preserving legacy mixed-case imports and registry behavior.
- Refactored the seven highest-complexity ERC rule entry points into focused helpers without changing rule IDs, severities, or findings.
- Hardened numeric extraction patterns against regex backtracking while preserving supported engineering formats.
- Bounded datasheet and SQL-injection content patterns to prevent regex backtracking on untrusted text.
- Removed redundant shell exception catches and unused shell/fillet parameters without changing command or routing behavior.
- Documented explicit OpenAPI error responses for design, ERC, export, library, and pipeline routes.
- Centralized remaining EasyEDA archive, architecture ground-net, CLI proof-manifest, and intent-rationale literals.
- Centralized repeated KiCad, Specctra DSN, and Excellon serialization literals without changing exported files.
- Centralized repeated component-library vendor names and recommended-operating provenance labels.
- Centralized object-authorization denial and missing-delegate messages across security and MCP surfaces.
- Centralized benchmark-readiness and semantic-diff review panel titles while preserving public review bundle output.
- Centralized synthesis proof-pack artifact filenames across generation, manifest evidence, and artifact records.
- Centralized synthesis-template YAML discovery across scoring, no-match diagnostics, and template listing.
- Centralized topology provenance tool identity across schematic, component-decision, and block-placement application records.
- Centralized the built-in synthesis benchmark description for zero-error ERC acceptance while preserving weights and public corpus output.
- Centralized the fabrication-readiness non-claim across architecture artifacts, board generation intents, validation, and derived handoffs.
- Centralized RF positive-frequency validation and the shared 2.4 GHz module band label without changing calculator or catalog outputs.
- Centralized E-series positive-value validation while preserving nearest, ceiling, and floor calculator errors.
- Centralized the strict-mode blocking suffix across DC, transient, and AC simulation skip evidence.
- Centralized the documentation guard reason for stale hard-coded test totals while preserving every banned reference.
- Centralized proof-pack metadata archive paths while preserving manifest, results, and stable-ID bundle entries.
- Centralized golden KiCad fixture suffix classification and discovery while preserving supported project, schematic, PCB, and symbol-library files.
- Centralized shared RoHS and REACH standard names across compliance checklists and product-class profiles.
- Centralized shared SPICE end-line and missing-engine reason literals while preserving control injection and skip-aware simulation behavior.
- Documented explicit 400 and 404 responses for Review Studio bundle, diff, and session routes in the generated OpenAPI contract.
- Documented explicit 413 and 404 responses for artifact creation and deletion in the generated OpenAPI contract.
- Documented explicit 403 and 404 responses for agent session, sandbox, and replay routes in the generated OpenAPI contract.
- Split composite synthesis and ERC assertions so connectivity, realization, warning, and generated-value failures identify the exact violated condition.
- Split composite CI contract assertions so loader, distribution-channel, and documentation failures identify the exact violated condition.
- Split composite behavioral assertions so persistence, artifact, parser, geometry, and mutation regressions identify the exact failed condition.
- Simplified case-insensitive regular-expression character classes in SPICE frequency, current parsing, and secret redaction while preserving uppercase and lowercase input support.
- Bound runtime proof results to declared checks and preserved emergency-stop reasons in sandbox status and audit evidence, eliminating two unused parameters.
- Replaced nested conditional expressions in authorization, benchmark status, repair summaries, placement scoring, and requirement trace selection with explicit branches.
- Extracted nested conditional expressions from BOM labeling, IPC-2581 stackup sides, and power-tree input selection without changing output contracts.
- Replaced repeated ASCII character ranges with explicitly ASCII-scoped regex shorthands across import, export, analysis, security, and net-naming utilities.
- Validated and resolved DCO base/head revisions to immutable commit SHAs before invoking Git, rejecting option-like and revision-expression inputs.
- Removed three unused parameters from private reroute and AC stability helpers while preserving their public entry points and routing outputs.
- Simplified prefix classification and preserved exception tracebacks in pad escape, MCP documentation generation, and LCSC import fallbacks.
- Simplified exception-focused tests and replaced manual global-state restoration with pytest monkeypatch fixtures across simulation, benchmark, transport, EasyEDA, KiCad corpus, and agent-tool coverage.
- Simplified collection iteration and test exception assertions across Altium import, benchmark mutation, KiCad schematic import, audit redaction, and fixture tests without changing behavior.
- Split the complex role-impersonation detector into deduplicated bounded patterns and require token boundaries for the `DAN` marker, preventing opaque approval IDs from triggering prompt-injection false positives.
- Updated the audit API session dependency to FastAPI’s `Annotated` form while preserving header resolution and endpoint behavior.
- Removed redundant subclass entries from exception handlers across CI, KiCad, benchmark, analysis, and proof utilities while preserving the same caught exception sets.
- Simplified seven small Sonar findings across router ordering, placement closures, collection construction, and benchmark suppression syntax without changing public behavior.
- Reduced the library expansion helper signature by removing an unoverridden lifecycle parameter while retaining explicit active lifecycle output for every generated part.
- Consolidated equivalent fail-closed branches, removed a redundant exception rethrow, simplified conflict-map construction, and made DC source-card zero detection tolerance-aware.
- Removed six unused local bindings and simplified an always-true initial blocking-stage guard in the multi-domain pipeline and LCSC manifest CLI.
- Removed empty type-check scaffolding and seven unused parameters from private Altium, synthesis, routing, schematic, and MCP helpers while preserving their observable behavior.
- Enforced the MOSFET SOA thermal power ceiling from ambient temperature, junction limit, and junction-to-ambient resistance instead of ignoring those inputs.
- Simplified equivalent control-flow branches and removed dead assignments in drill export, SES import, DRC geometry, schematic placement, and repair-track result documentation without changing public behavior.
- Refreshed the exact-revision Sonar debt baseline from 498 to 455 unresolved findings after the first bounded remediation batches, tightened the 0.4.0 ceiling to 455, and retained the 0.5.0 absolute cap at 425.

### Agent plugin publication contract

- Added the product-owned `zaptrace` Claude Code plugin manifest, portable source-checkout MCP configuration, and three verification-first skills for design validation, proof-pack review, and bounded benchmark evaluation.
- Documented stable versus experimental workflows, local-file and network boundaries, artifact validation requirements, and exact marketplace activation gates while keeping `agent-tools` as the catalog only.
- Added contract tests that bind plugin versioning, skill paths/front matter, public MCP tool references, secret-free portable launch configuration, and the 93-design-plus-3-session exposed tool count.

### Temporary-workspace hardening

- Replaced shared-directory `HOME` fallbacks in CI toolchain and KiCad oracle subprocesses with atomically created, process-owned mode-`0700` temporary homes.
- Added path-boundary, symlink, ownership, permission, exception-cleanup, and replacement-race tests; cleanup unlinks a substituted symlink instead of traversing it.
- Preserved caller-provided `HOME` values and kept the hardening scoped to fallback execution without changing release-gate semantics.
- Refreshed the revision-bound Sonar historical-debt baseline after the hardening: unresolved findings decreased from 500 to 498 and the critical security/reliability budget decreased from 2 to 0 without weakening the absolute release targets.

### Historical Sonar debt ratchet

- Added a revision-bound, redacted SonarQube Cloud historical-finding baseline grouped by severity, type, rule, component, age, ownership area, and remediation class without committing issue messages or exact line locations.
- Added a schema-validated policy that binds the baseline revision, report SHA-256, and reviewed counts to no-growth budgets for total, BLOCKER, and critical security/reliability findings.
- Added measurable 0.4.0 and 0.5.0 reduction targets plus a secret-bounded main-push, weekly, and manual workflow that retains JSON/Markdown evidence and waits for the exact main analysis revision.
- Kept the existing strict new-code quality gate unchanged and prohibited blanket suppression, file-wide exclusion, quality-profile weakening, and unreviewed bulk false-positive closure.

### Simulation-backed sign-off evidence

- Added a unified, design-state-bound report for DC, transient, AC, power-integrity, signal-integrity, thermal, and current-density evidence while retaining the underlying producer result and evidence method separately.
- Added governed model provenance, input/netlist hashes, assumptions, confidence, explicit skip/risk states, mandatory repair hints for failures, report integrity hashes, and fail-closed human-review escalation for analytical, degraded, unsupported, or low-confidence results.
- Added Proof Pack `simulation_signoff` evidence and a four-family corpus with golden pass/fail fixtures, retained input models and results, a committed JSON Schema, and trusted-root CI artifacts.
- Added a strict Quality gate that installs `ngspice` and requires at least one live solver-backed simulation pass without treating analytical or degraded evidence as autonomous release approval.

### Release-grade verify/repair orchestration

- Added a versioned, deterministic orchestration policy that coordinates ERC, DRC, KiCad oracle, manufacturer-aware DFM, simulation, supply-chain coverage, and proof checks with a hard iteration budget and explicit terminal reasons.
- Added copy-on-write repair execution through the existing ERC registry, design-state SHA-256 binding, semantic before/after diffs, measured blocker reduction, atomic rollback on repair errors, trusted-root output containment, and fail-closed escalation for non-repairable, high-risk, missing, or no-progress evidence.
- Added Proof Pack `verify_repair` evidence carrying policy identity, gate history count, repair count, report hash, final stop reason, and a separate human-review handoff when autonomous release remains blocked.
- Added a strict four-family automated convergence benchmark and CI artifacts. That benchmark runs only the declared ERC software-convergence policy and explicitly does not claim DRC, DFM, simulation, KiCad, supply-chain, physical, or release readiness.

### End-to-end agent evaluation harness

- Added a versioned, secret-free corpus of twelve realistic agent project briefs covering success, blocked, human-review-required, and deterministic stop-condition outcomes.
- Added an isolated evaluator that drives agent steps through the shared secure dispatcher, captures replay and normalized trace identities, hashes generated artifacts, and cleans session/sandbox state after every scenario.
- Linked scenario results to real synthesis proof packs and benchmark scorecards, with a committed report JSON Schema and explicit non-claims around model quality and physical correctness.
- Integrated strict CI and nightly execution into the existing Quality benchmark-evidence job, including identity-bound JSON, Markdown, and retained scenario artifacts.

### Constraint-driven layout quality

- Added a versioned, SHA-256-identified layout-quality policy that combines placement, power-path/current-density, return-path, high-speed/differential, analog/digital, thermal, mechanical, and test/debug evidence without replacing existing domain analyzers.
- Added deterministic `pass`, `warning`, `human-review-required`, and `blocking` reports bound to the canonical design-state hash; missing placement or routing evidence now fails closed to explicit review instead of appearing complete.
- Added bounded copy-on-write repairs for decoupling proximity, connector edge alignment, and high-current trace width with before/after section-score deltas and no silent mutation of the approved design.
- Added known-good/known-bad fixtures, five representative board-family regressions, synthesis Proof Pack artifact hashing, and a Review Studio layout-quality panel while retaining explicit non-claims for fabrication and solver-grade sign-off.

### Manufacturer-aware DFM readiness

- Added versioned fabrication and assembly capability profiles with deterministic profile SHA-256 identity, explicit component/BGA pitch, stencil aperture, component-height, double-sided, and through-hole assembly limits.
- Added machine-readable DFM readiness reports for every manufacturing bundle, with `hard-fail`, `warning`, `approved-skip`, `human-review-required`, and `pass` states plus explicit non-claims.
- Bound readiness reports, profile identity, report digest, and manufacturing artifact hashes into evidence bundle schema 2.1 and optional synthesis proof-pack metadata.
- Added regression coverage for fabrication, assembly, profile-skip, fail-closed unprofiled exports, and three generated board families without representing CI output as manufacturer approval.

### Auditable engineering review gates

- Added authenticated, immutable Review Studio decisions for approve, reject, request-repair, accept-risk, and rollback, with explicit rationale, checklist preconditions, reviewer identity, timestamp, and release-relevant design-state binding.
- Persisted protected review sessions through the existing optional SQLite state store, including restart hydration and parent-session lifecycle cleanup, while preserving the in-memory default.
- Added assumptions and proof-artifact-hash visibility to review bundles and exposed explicit `review_status`/`finalized` session fields.
- Separated automated release pass from fabrication review through `automated_gate_status`, `fabrication_status`, and normalized proof-pack `engineering_review` evidence; arbitrary or stale approval IDs cannot be represented as current human approval.

### Persistent versioned state

- Added an opt-in standard-library SQLite backend for committed design heads, immutable content-addressed version lineage, snapshots, transactions, audit events, object ACLs, and release-evidence identity.
- Made isolated workers persistence-disabled and moved durable publication to the trusted parent process, with atomic session-head replacement and explicit durable session destruction.
- Added checksum-verified migrations, startup integrity checks, online backup/validated restore, idempotent legacy filesystem import, same-name cross-session isolation, and a bounded 100-version local regression fixture.
- Registered REST artifact metadata and active proof/release references so explicit deletion and expiration cleanup fail closed while evidence remains protected.
- Documented local single-user and controlled team deployment modes without claiming arbitrary multi-tenant SaaS safety, distributed consensus, or hardware correctness.

### Agent tool modularity

- Split the 3,773-line agent tool monolith into 11 cohesive implementation domains, shared runtime services, and declarative registry fragments while preserving all 93 public tool contracts.
- Kept `zaptrace.agent._tool_impls` as a backward-compatible facade for MCP, REST, CLI, tests, and third-party imports.
- Added a pre-refactor registry contract baseline plus blocking module-size, callable-identity, declarative-registry, and acyclic-import gates.
- Restored `board_export` against the current `BoardConfig` contract and added direct domain behavior coverage for design, routing, and pipeline tools.

### Human reference scorecards

- Added a six-design human-engineered upstream reference corpus with exact revisions, hardware licenses, selected KiCad artifact hashes, and explicit pending-human-review status without re-vendoring four upstream projects.
- Added a strict eight-dimension, 100-point scoring rubric and deterministic autonomous-attempt scorecards where missing, reported, or unreviewed evidence remains blocking regardless of numeric total.
- Added identity-bound Quality CI evidence and public reproduction instructions; qualified human review of the corpus and rubric remains pending and is not claimed by automation.

### External benchmark provenance

- Added two exact-revision, license-attributed modern KiCad open-hardware fixtures with strict offline source/hash integrity, composite source-plus-task identities, and deterministic PCB-bench reference hashes.
- Added machine-readable external corpus and clean-clone reproduction evidence to the Quality benchmark gate, plus a strict tool-neutral schema for future independent reproduction records.
- Independent third-party reproduction remains pending; repository CI, maintainer, contributor, and AI reruns are explicitly not represented as independent verification.

### Development identity

- Advanced `main` to the explicit unreleased Python identity `0.3.1.dev0` and Cargo identity `0.3.1-dev.0`, distinct from the published `v0.3.0` baseline.
- Added deterministic Python/runtime/API/MCP/Rust/lockfile synchronization and exact annotated-tag/commit verification with identity-bound CI evidence.

### Distribution support and clean installation

- Added an authoritative machine-readable support matrix separating supported, best-effort, and unsupported operating-system, architecture, Python, artifact, and native-extension combinations.
- Added source-tree-isolated clean-install verification for the Linux CPython 3.13 source distribution and all three supported CPython 3.13 native-wheel targets.
- Added identity-bound artifact evidence covering SHA-256, source commit, dependency lock, CLI, SDK, native state, REST API, and MCP HTTP startup; missing evidence now blocks tagged release aggregation.
- Kept Linux arm64 and Windows x86_64 native wheels explicitly unsupported until dedicated continuous runners exist, and documented source-distribution fallback guidance without claiming universal support.

### Container reproducibility

- Added committed, hash-complete Python runtime and exact Alpine package manifests for the container image.
- Changed image installation to require dependency hashes and install the locally built ZapTrace wheel with `--no-deps`, preventing a second unconstrained resolution during `docker build`.
- Added source-, base-image-, wheel-, and dependency-manifest-bound build provenance plus a CI gate that regenerates the lock, extracts provenance from the exact scanned image, and retains machine-readable evidence.

### Native security boundary

- Brought the Rust extension and PyO3 interface into the supported security policy with typed validation errors, panic containment, concrete-list length preflight before element extraction, finite/derived-overflow/range/index checks, and explicit resource limits.
- Added direct Rust negative/invariant tests plus installed-wheel boundary evidence that verifies deterministic behavior, controlled Python exceptions, process survival, wheel identity, and source-tree isolation.
- Made native-wheel verification mandatory in heavy Quality CI and for every release wheel target before artifact upload.
- Added pinned Cargo advisory scanning with raw and normalized evidence bound to the exact `Cargo.lock` digest.

### Repository maturity

- Granted the Scorecard job read-only access to PR check runs so the CI-Tests control can evaluate actual merged-PR test evidence.
- Hash-locked the container builder Python toolchain and bound its manifest digest into image provenance and verification evidence.
- Replaced the global Renovate validator install with a committed npm lockfile and local `npm ci` execution so every transitive package is integrity-pinned.
- Added professional open-source maturity documentation covering governance, support, maintainers, OpenSSF evidence, development policies, release integrity, and security assurance.
- Added advisory workflows for repository hygiene, OpenSSF Scorecard, secret scanning, and dependency review.
- Hardened security and container workflows with read-only token defaults, and removed duplicate release-tag SARIF publication privileges while preserving container evidence and main/PR code-scanning uploads.
- Added a CI docs status-sync gate (`scripts/ci_docs_status_sync.py`) to fail when README/docs/changelog claims drift from live ERC/DRC/tool counts.
- Added a CI validation-environment parity gate (`scripts/ci_validation_environment.py --strict`) and report artifact upload to keep release-triage prerequisites reproducible.
- Added KiCad oracle skip semantics with approval evidence (`skip-approved` / `skip-unapproved`) via `scripts/ci_kicad_oracle.py --skip-approval-id` for stricter release-gate policy enforcement.
- Added KiCad oracle report SHA-256 propagation into proof-pack evidence (`KiCadOracleEvidence.report_sha256`) so ERC/DRC records carry machine-checkable report identity.
- Added CI-workflow regression tests to keep `validation-environment` parity and release-summary gate wiring from drifting.

### Test architecture

- Split the Python suite into centrally classified `unit`, `integration`, `benchmark`, `hardware`, `external_tool`, and `native` lanes with explicit runtime budgets and machine-readable inventory evidence.
- Added duration-weighted whole-module sharding for the coverage-enabled unit, benchmark, and hardware lanes, per-shard JUnit/coverage reports, combined critical-runtime coverage, and complete tagged-release lane execution.
- Made required heavy lanes fail when empty or entirely skipped, cached the expensive 12-family convergence and synthesis benchmark matrices once per pytest process, added ngspice 42 operating-point parsing, and made POSIX worker termination evidence deterministic.

### KiCad benchmark corpus

- Replaced simplified non-loadable corpus schematics with provenance-pinned KiCad 10 fixtures and deterministic root-schematic resolution.
- Added supported-major enforcement and bounded stdout/stderr, command, input, and tool-version evidence for external graders.
- Integrated the corpus gate and full JSON report into the Quality KiCad lane.

### License compliance

- Pinned REUSE 6.2.0 through a reproducible `uvx` invocation and added a strict repository-hygiene gate with retained JSON evidence.
- Added complete tracked-file SPDX coverage, explicit CC-BY-SA-4.0 overrides for vendored footprints, and the required CC0/CC-BY-SA license texts.
- Documented the exact contributor command and added a negative policy test proving that an uncovered file fails the gate.

### Component provenance and trust

- Added strict component schema v2 with unknown-key rejection, explicit `verified`/`curated`/`heuristic`/`placeholder` tiers, and mandatory provenance for MPN, datasheet, pin map, package, footprint, electrical limits, lifecycle, and sourcing.
- Migrated all 504 component records deterministically to honest heuristic provenance, corrected malformed `description"` keys, updated the expansion generator, and retained a full dated audit with repeated-pin-signature evidence.
- Added a monotonic trust baseline that blocks removals, downgrades, and unsupported stronger claims, while release/proof evidence now blocks schema-valid but non-eligible components by default.
- Made library proof dashboards trust-tier and release-eligibility aware instead of treating metadata density as engineering verification.

### Requirements architecture and traceability

- Completed the bounded requirements-to-architecture compiler with deterministic artifacts for ESP32 USB/I2C, STM32 RS-485, RP2040 CAN, battery SPI datalogger, and LoRa sensor families.
- Added strict requirement/assumption reference validation, explicit battery/wireless/USB-role/logic-voltage conflict records, and fail-closed ambiguity and unsafe-domain semantics.
- Added deterministic architecture traceability reports, a strict eight-case Quality CI corpus/schema gate, and a classified dated evidence snapshot.
- Added Proof Pack architecture artifacts and typed FAIL/WARNING/PASS autonomous sign-off evidence with stable identity bound to the canonical architecture SHA-256.

### Datasheet-backed component selection

- Added deterministic pre-layout component selection with explicit voltage, current, power, package, footprint, pin-function, datasheet-provenance, supply-risk, and release-eligibility gates.
- Added a 20-case offline prompt corpus across 12 component categories and a strict Quality CI gate requiring at least 100 records with governed datasheet and footprint evidence.
- Added proof-pack selection records with selected-part rationale, extracted constraints, decision hashes, and fail/warning/pass autonomous sign-off mapping.
- Retained trust boundaries explicitly: all 504 migrated records remain heuristic, require human review, and are not release eligible despite passing governed coverage.

### REST API abuse controls

- Added explicit trusted-proxy CIDR policy; untrusted peers can no longer rotate forged `X-Forwarded-For` values to bypass per-client controls.
- Enforced request-body limits while streaming, including chunked and missing-length requests.
- Replaced unbounded process-global rate state with a bounded, thread-safe backend contract, stale-key deletion, cardinality limits, and structured rejection evidence.
- Made memory-backed multi-worker startup fail closed unless a controlled shared backend is provided.

## [0.3.0] - 2026-07-01 — Evidence Hardening and Benchmark Readiness

### Agent tools

- **Simulation gate MCP tool** — `simulation_gate` runs the DC operating-point gate on a stored design and returns a blocking verdict. Rail references are derived from the design's power-rail net names. When ngspice is unavailable the gate is `skipped` (recorded as evidence, never a silent pass); `strict=True` makes a skip blocking. Tool catalog → 82.
- **Self-correcting synthesis MCP tool** — `synthesize_board_repair` runs the convergent ERC → patch → re-verify loop after synthesis: it assigns standard footprints to fix `ERC020` violations, re-runs ERC each round until a fixed point, and reports both what it patched and what it cannot fix (e.g. single-pin nets needing a real connector). Tool catalog → 81.
- **Board-level synthesis MCP tools** — `board_plan` composes a justified board block graph (power + interface support) from an intent; `synthesize_board` emits the full board netlist via block composition and stores it in the session; `synthesize_board_and_check` runs ERC on the result in one step. Each regulator block *provides* a rail, each interface support block *requires* one, and unrealized/unmet items are reported instead of silently dropped. Tool catalog → 80.
- **Requirements & compliance MCP tools** — `requirements_parse` extracts structured machine-readable requirements (rails, current, interfaces, MCU, USB-C, battery) from a design intent; `compliance_checklist` turns those into a product-class compliance pre-check (RoHS/REACH, USB-C, battery, etc.) flagged as evidence-ready, not certified. Tool catalog → 69.

### Analysis / verification

- **Synthesis benchmark harness** — `zaptrace/synthesis/benchmark.py` `run_benchmark()` synthesizes a fixed corpus of representative board types (ESP32 I2C sensor, datalogger, STM32 RS-485, RP2040 CAN, nRF52 multi-sensor, ESP32 ethernet) and aggregates their completeness: mean score, per-dimension pass rates, the weakest dimension, and the worst case. Deterministic, so a drop is a real regression — the first slice of the release-blocking quality gate (gap 7). The current snapshot reports the two systemic weaknesses quantitatively: electrical and manufacturability pass on no board yet (remaining ERC for review; module/custom land patterns without geometry). Surfaced via the `synthesis_benchmark` MCP tool.
- **Behavioral DC bias resolver** — `zaptrace/analysis/dc_bias.py` assigns every power net its nominal DC voltage (ground 0 V, VBUS 5 V, VBAT 3.7 V, `VDD_<v>` → `<v>`) under ideal-regulator behaviour and — what ERC cannot do — flags any rail loads depend on but no regulator drives (a floating rail, e.g. an unrealized boost). Always available, no ngspice needed. `behavioral_source_cards()` emits ideal SPICE source cards (only for actually-driven rails) which the orchestrator now injects into the netlist via the new `extra_cards` hook, so the ngspice DC operating-point can compute rails. The scorecard's electrical dimension now fails on an undriven rail, and a new `dc_bias_check` MCP tool exposes it.
- **Board completeness scorecard** — `zaptrace/synthesis/scorecard.py` turns the synthesis artifacts (block graph, repair result, footprint resolution) into a weighted 0-100 completeness score across four dimensions: functional-core (is the MCU placed/realized), composition (all planned blocks realized, no unmet requirement), electrical (did the repair loop converge to a clean ERC), and manufacturability (do parts carry footprint geometry). Surfaced via the `synthesize_board_score` MCP tool. It measures how finished the *automated* steps are — explicitly not a correctness or safety claim.
- **DC operating-point simulation gate** — `zaptrace/analysis/sim_gate.py` wraps the SPICE orchestrator as a blocking gate with two disciplines from the design note: an explicit skip (ngspice absent) is recorded as `skipped`, never a silent pass, and in `strict` mode it blocks; a run with no expected voltages is `no_reference`, distinct from a verified `pass`. `expected_rail_voltages()` derives references from the synthesis rail-net convention (`VDD_3V3` → 3.3 V). ngspice is now bundled in the container image so a skip in CI signals an environment fault, not an accepted gap. (Device models for the synthesized ICs are still pending, so rail checks currently skip even with ngspice present.)

### Placement / routing

- **Ground copper pour applied in the fab flow** — the grid router leaves the ground net for a copper plane, but nothing flooded it, so a synthesized board's ground was unconnected (0 traces, 0 pours). `synthesize_to_manufacturing()` now generates a `CopperPourGenerator` ground pour on the top copper after routing, so every ground pin connects through the fill. The ground net is identified by net class (`get_net_class(... ) == NetClass.GROUND`) — the original `n.type == NetType.GROUND` check never matched, because the classifier sets the net *class*, not the raw type field, so the pour had been silently skipped.

- **Grid router now routes boards whose parts have real footprints** — the A\* router relocates a net endpoint that lands inside a blocked component body to the nearest free cell, but the search radius was only 10 cells (2.5 mm) — too small to escape a real footprint courtyard (a 7×7 mm LQFP centre is ~14 cells from its edge), so `_nearest_free` returned `None` and **every** net failed to route once parts carried geometry. Raised the radius to 48 cells and fixed the BFS to mark cells visited on enqueue (no queue blow-up). A synthesized STM32 board went from **0/8 to 8/8 nets routed**, and its DRC errors dropped from 221 (naive fallback) to 57 (obstacle-aware). Benefits the autopilot pipeline too. (Remaining DRC errors are clearance violations from the centre-to-centre routing model — pad-level routing is the next step.)

- **Placer no longer collapses the layout** — the force-directed refinement used a spring with no rest length (`k·dx`, proportional to distance), so highly-connected parts — everything shares GND/VDD — were pulled onto a single point (a 6×5 mm cluster on a 100×80 mm board, with ICs stacked). Two fixes: the spring now has an 8 mm rest length (attract past it, push apart within it, never collapse), and power/ground nets (which fan out to nearly every part and go to copper pour) are excluded from the springs, with high-fan-out buses wired as a star instead of all-pairs. Parts now spread across the board. This benefits every consumer of the placer, including the autopilot pipeline.

- **`synthesize_to_manufacturing` routes and reports DRC honestly** — the fab flow discarded the router's result (so `design.routing` was never set and the bundle had no traces); it now classifies nets, runs the obstacle-aware A\* grid router (falling back to the MST/L-shape router), assigns the routing, runs DRC, and surfaces the DRC status (`{passed, errors, warnings}`) in the result and the human-review checklist. When the algorithmic router leaves DRC errors, the checklist says so plainly — the bundle is never presented as a clean professional layout it is not. (Producing a clean route on synthesized boards is the open routing milestone.)

### Synthesis / requirements

- **Standard-package footprint resolution (bare-chip boards fully manufacturable)** — the footprint resolver now falls back to a part's standard `package` (from the library) when its custom footprint name has no generator, and the IPC-7351 generators learned the standard JEDEC packages the corpus uses: `LQFP-48/64/100` (routed to the QFP generator), `QFN-56`, and THT pin-headers / 2-pin terminal blocks (parsed by name). With this, the STM32 RS-485 and RP2040 CAN boards are **fully manufacturable** — every part carries real pad geometry. Benchmark mean 93.5 → 96.8, manufacturability pass 0% → 33% (functional-core, composition, and electrical are all at 100%). The remaining unresolved parts are genuinely part-specific land patterns — MCU modules (ESP32-C3-MINI-1), DFN/LGA sensors, aQFN, RJ45 — which need real datasheet geometry, not a guessed generator.

- **Ethernet subsystem (W5500 + RJ45) — electrical dimension hits 100%** — replaced the mismatched RJ45 Bob-Smith stub with a real Ethernet front-end: `instantiate_ethernet()` places a W5500 SPI Ethernet controller (powered, reset/test/PMODE strapped for all-capable auto-negotiation, with its own 25 MHz crystal — new `crystal-25mhz` part) on the MCU-mastered SPI bus, and routes its differential pairs to an RJ45 jack with integrated magnetics. The MCU now masters SPI for the `ethernet` interface just as it does for SPI flash. The ESP32 ethernet board is now electrically clean (92/100, grade A). **All six benchmark boards now pass the electrical dimension (100%); benchmark mean 93.5/100.** The only remaining dimension below pass everywhere is manufacturability (module/sensor land-pattern geometry).
- **External crystal for bare MCUs** — `instantiate_mcu()` places a 12 MHz crystal (new `crystal-12mhz` library part) with two 18 pF load capacitors across the XIN/XOUT pins of an MCU that has no internal precision oscillator (RP2040). This also exposed and fixed a case-sensitivity bug in `ERC010` (the crystal load-cap check compared against uppercase `"CAP"/"CAPACITOR"` and so never counted the lowercase `capacitor` type used everywhere in synthesis). With the crystal, an RP2040 CAN board is electrically clean — 94/100, grade A. Benchmark mean 89.5 → 92.0, electrical pass 67% → 83% (5 of 6 boards). Only the ethernet board's PHY/RJ45 wiring remains.
- **SWD debug header + severity-aware electrical scoring** — `instantiate_mcu()` now places a 1×4 SWD debug/programming header (every real board needs one) and wires the MCU's SWDIO/SWCLK pins to it, keeping them out of the interface GPIO pool. This connected the previously-floating SWD clock. The scorecard's electrical dimension was also refined: it now passes when a board has zero ERC **errors and warnings**, treating remaining info-level items (test-point / idle-pull-up *suggestions*) as advisories rather than defects — a board electrically sound but missing optional test points is not "partial". Together: benchmark mean 86.0 → 89.5, electrical pass 33% → 67% (4 of 6 boards pass). Remaining partials are a real crystal (RP2040 XIN) and the ethernet PHY/RJ45 wiring.
- **Complete MCU power and boot strapping** — `instantiate_mcu()` now ties *every* power pin (VDDA, VBAT, USB_VDD, VREG_VIN, … to the rail; VSSA/AGND to ground), not just the first — an MCU with a floating analog supply does not work. It also applies per-family boot straps (STM32 BOOT0 pulled low, RP2040 RUN pulled high + TESTEN to ground) so the part actually boots. With this, an STM32 RS-485 board reaches a fully clean ERC and 93/100 (the second board to pass the electrical dimension). Benchmark mean 83.7 → 86.0, electrical pass 17% → 33%. Remaining electrical gaps are crystals and debug headers (RP2040 XIN/SWDCLK) — separate support blocks.
- **DC power input for boards with no stated source** — when an intent gives a rail but no USB-C/battery input (e.g. "STM32 3.3V board"), the highest rail was treated as an impossible boost and left floating. Synthesis now places a 2-terminal DC power input (library `terminal-2p-5mm`) that drives that rail directly, and the DC bias resolver counts an input connector as a rail driver. This closed the systemic undriven-rail failure: benchmark mean jumped 72.7 → 83.7/100 and composition pass rate 33% → 100%, with every corpus board's rails now driven.
- **Sensor reset pins tied high** — `instantiate_sensor()` now ties a sensor's active-low reset (nRESET/nRST) to the rail so the part runs instead of being held in reset and leaving a floating input pin (ERC002). With this and the USB-C connector, a complete ESP32-C3 I2C-sensor board now converges to a **fully clean ERC** and scores 96/100 — the first board to pass the electrical dimension end to end.
- **USB-C connector synthesis** — `zaptrace/synthesis/connectors.py` places the real USB-C receptacle (library `usb-c-16p`) on a USB-C board and wires VBUS, GND, shield, and CC1/CC2 — so the board finally has a physical power input and the CC nets carry both the termination resistor and the connector instead of dangling. D+/D-/SBU are left unconnected (a power-only input doesn't use them). `architecture.py` emits it as the realized `J_USB_C` connector block alongside the CC termination. Also taught `generate_footprint_for_component` to resolve a USB-C land pattern by footprint name, so the connector carries real pads.
- **Intent → manufacturing, end to end** — `zaptrace/synthesis/fab.py` `synthesize_to_manufacturing()` chains the whole composition flow (synthesis + functional core + peripherals + repair + footprint geometry) through place, route, and the manufacturing exporter, emitting a real bundle — Gerber copper, Excellon drill, BOM, pick-and-place, manifest, ZIP — in one call. It returns the artifacts *with* their evidence: the completeness scorecard, the DC bias check, and an explicit human-review checklist of what is not finished (parts with no copper, ERC left for review, undriven rails, unrealized blocks). The bundle is never presented as fabrication-ready; the checklist is the honest hand-off. Surfaced via the `synthesize_board_manufacture` MCP tool. A one-sentence datalogger intent now yields 12 manufacturing files plus a B-grade scorecard and a review checklist.
- **SPI flash peripheral + MCU-mastered SPI bus** — the MCU now wires its SPI pins (SCK/MOSI/MISO/CS) to bus nets it creates, and `plan_storage()` places a real SPI NOR flash (Winbond W25Q128JV, new `data/library/memory/` part) for flash/storage/datalogger intents, joining the flash to that bus with WP#/HOLD# tied high. Generalizes peripheral synthesis to two buses: `plan_sensors` (I2C) and `plan_storage` (SPI), dispatched by bus. A "datalogger with SPI flash and I2C sensor" board now gets an MCU, a sensor on I2C, and a flash on SPI — all on real multi-pin buses.
- **Peripheral (sensor) synthesis** — `zaptrace/synthesis/peripherals.py` places the real I2C sensor an intent asks for and hangs it on the MCU's bus, so the board fulfils the intent instead of leaving an empty bus. `plan_sensors()` maps measurement keywords to library parts (temperature/humidity → SHT31-DIS, pressure → BMP390, accelerometer → LIS3DH, ADC → ADS1115, air-quality → BME688, bare "sensor" → BME280), deterministically and only when an I2C bus exists. `instantiate_sensor()` ties power, joins the data/clock pins (named SDA/SDI, SCL/SCK across parts) to the SDA/SCL bus nets, ties an address pin to GND, and adds decoupling. `architecture.py` adds each as a realized `SENS_*` block (provides `sensor:<fn>`, requires the rail + `iface:i2c`). A measurement with no part, or an intent with no I2C bus, is reported, never faked. A synthesized "I2C temperature sensor board" now has an actual SHT31 talking to the MCU.
- **IPC-7351 footprint geometry resolution** — `zaptrace/synthesis/footprint_resolver.py` attaches real pad geometry (`Component.footprint_def`) to every synthesized part from its footprint name, via the IPC-7351 generators in `ee/footprints.py`. The manufacturing exporters (Gerber, Excellon, DSN) emit no copper without it, so this is what makes a synthesized board fabricable. `synthesize_and_repair()` now runs it after the repair loop; a package with no generator yet (e.g. an MCU module land pattern) is reported as `unresolved`, never given invented pads. Also added the `SOT-23-3` package (the synthesized LDO) to the SOT generator.
- **Functional-core synthesis** — `zaptrace/synthesis/mcu.py` instantiates the real MCU for the requested family from the library (`esp32` → ESP32-C3-MINI-1, `stm32`, `rp2040`, `nrf52`, `atmega`, `ch32`), places it, ties its power/ground/enable pins to the logic rail, and assigns GPIOs (natural-sorted, deterministic) to the interface support nets already on the board — so I2C SDA/SCL, RS-485 control, and CAN TXD/RXD reach the MCU instead of dangling at a pull-up. `architecture.py` adds it as the realized `CORE_MCU` block (provides `core`, requires the rail), emitted last so the support nets exist. A family with no library part (e.g. `samd`), or an interface with no support net (SPI/UART), is reported honestly, never faked. First time a synthesized board is a connected system rather than support scaffolding.
- **Convergent self-correction loop** — `zaptrace/synthesis/repair.py` closes the second half of the synthesis loop: `repair_design()` maps auto-fixable ERC violations to typed `Patch`es, re-runs ERC each round, and stops at a fixed point or a hard iteration cap. Two handlers so far: `ERC020` standard-footprint assignment, and `ERC012` floating-enable tie (a 100 kΩ pull-up to the board input for an `EN_<rail>` net, so a synthesized regulator turns on). It records measured per-iteration progress (violation count before/after), never invents a footprint for an unknown part or ties a non-enable single-pin net (USB-C CC, data lines, feedback stay for a human), and escalates whatever it cannot fix as `remaining`. `synthesize_and_repair()` ties it to architecture synthesis end to end.
- **RS-485 & CAN transceiver blocks** — `instantiate_rs485_transceiver` (MAX3485, half-duplex, 120 Ω termination) and `instantiate_can_transceiver` (SN65HVD230, 3.3 V, 120 Ω termination) are now parametric blocks; `plan_architecture()` realizes the `rs485`/`can` interfaces with them instead of deferring, and the repair loop knows their SOIC-8 footprint. RF interfaces (BLE/Wi-Fi/LoRa) remain honest gaps.
- **Block-composition architecture synthesis** — `zaptrace/synthesis/architecture.py` generalizes the power-tree planner to the whole board: `plan_architecture()` builds a typed block graph where every block declares what it `provides` (rails, interface support) and `requires` (a rail to run from), composes by satisfying requires-with-provides, and reports `UnmetRequirement`s rather than emitting them silently. `build_architecture_design()` emits a deterministic netlist plus a `SynthesisDecisionLog`, with interfaces lacking a parametric block recorded as honest gaps instead of skipped. First step from template selection toward from-scratch synthesis.
- **Requirements → constraints derivation** — `requirements_to_constraints()` maps parsed `Requirements` onto the constraint-DSL `ConstraintSet` (voltage domains per rail, a 90 Ω USB differential-pair routing intent + edge-placed connector for USB-C, an I2C bus routing intent). Every emitted constraint records the requirement it came from (traceability), and a bare intent invents nothing. Surfaced in the `requirements_parse` tool output.
- **Requirements/constraints artifact emitter** — `write_requirements_artifacts()` and a new `zaptrace requirements <intent> [-o DIR]` CLI command emit deterministic, reviewable `requirements.json` + `constraints.yaml` design-contract artifacts (or print them as JSON).
- **Requirement→constraint coverage matrix** — `requirements_coverage()` traces which stated requirements produced constraints (`covered`) and which are not yet handled (`uncovered`, e.g. battery charge/protection, current budget, unmapped buses), with a `fully_covered` flag. Surfaced in the `requirements_parse` tool and `zaptrace requirements` output — a coverage matrix, not a silent pass.
- **Unspecified-assumption register** — `requirements_assumptions()` records the facts a design needs that the intent did *not* state (supply rail, current budget, MCU, USB-C power role, battery chemistry), so every downstream assumption is explicit and reviewable. Surfaced in the `requirements_parse` tool and `zaptrace requirements` output.
- **Requirement freeze gate + version diff** — `freeze_requirements()` content-addresses the extracted design contract (SHA-256 over the contract fields, excluding raw prose) so downstream synthesis can record which requirements version it ran against and detect drift; `diff_requirements()` reports field-level changes between two versions with their before/after freeze hashes. Reworded-but-equivalent intent keeps the same hash; a real requirement change always moves it. Surfaced as `freeze` in the `requirements_parse` tool and `zaptrace requirements` output.
- **Assumption approval workflow** — `review_assumptions()` turns the unspecified-assumption register into a gate: each open assumption must carry a recorded reviewer decision before the requirements are review-complete (`approved` is True only when none remain pending). Approvals are bound to the requirements freeze hash, so a later requirement change re-opens the gate. Reachable via the new `requirements_review` MCP tool (intent + an `approvals` map) and surfaced as `assumption_review` in `requirements_parse` and `zaptrace requirements` output. Tool catalog → 70.
- **Product use-case & risk classifier** — `classify_risk()` classifies a design into the risk classes that drive downstream rule-pack/standards selection (battery, wireless, high_voltage, safety_critical), each with the evidence that triggered it; a class is emitted only on concrete evidence. Surfaced as `risk` in `requirements_parse` and `zaptrace requirements`.
- **Environmental / cost / regulatory / mechanical extractors** — `parse_requirements()` now also extracts operating temperature range (Celsius-anchored so a voltage range is never misread), IP ingress rating, board dimensions (mm), the tightest stated BOM/unit cost target (USD), and regulatory targets (CE/FCC/UL/RoHS/REACH/CISPR/ATEX/EN55032/IEC61000, matched only via unambiguous forms).
- **Requirement conflict detector** — `requirements_conflicts()` flags stated requirements that cannot all hold as written: battery + a ≥60 V rail, USB-C (non-PD) + a current budget above 3 A, and Li-ion + a sub-zero operating temperature. Each conflict cites both sides and the physical/spec reason. Surfaced as `conflicts` in `requirements_parse` and `zaptrace requirements`. **Completes the requirements epic.**
- **USB-C CC termination calculator** — `usb_c_cc_termination()` resolves the CC-pin resistor for a port role: a sink (UFP) presents Rd = 5.1 kΩ to GND; a source (DFP) presents Rp advertising its 5 V current (56 kΩ default / 22 kΩ for 1.5 A / 10 kΩ for 3.0 A; above 3 A requires USB-PD). Reachable via the new `calc_usb_c_cc` MCP tool. Datasheet-grounded value for the USB-C CC resistors named in the acceptance example. Tool catalog → 71.
- **Decoupling/bypass planner** — `decoupling_plan()` plans an IC rail's decoupling: one 100 nF high-frequency cap per power pin plus bulk capacitance (≥ 10 µF), with the ceramic voltage rating derated to ≥ 2× the rail for DC-bias loss. Reachable via the new `calc_decoupling` MCP tool. Tool catalog → 72.
- **Li-ion charger sizing** — `lipo_charge_resistor()` sizes the PROG resistor for a Microchip MCP73831/2 Li-ion/Li-Po linear charger from a target charge current (`I_chg = 1000 / R_prog`, 100–500 mA), rounding the resistor up so actual current never exceeds target. Reachable via the new `calc_lipo_charge` MCP tool. Tool catalog → 73.
- **Buck converter L/C calculator** — `buck_inductor_capacitor()` sizes a synchronous buck's inductor and output capacitor in CCM from Vin/Vout/Iout/Fsw (`L = Vout·(Vin−Vout)/(Vin·fsw·ΔIL)`, `Cout = ΔIL/(8·fsw·ΔVout)`), reporting duty cycle, ripple/peak current, and E-series-snapped values (cap rounded up to hold the ripple target). Reachable via the new `calc_buck_lc` MCP tool. Tool catalog → 74.
- **Block-level power-tree planner** — `plan_power_tree()` turns parsed requirements into a justified power architecture: input sources (USB-C VBUS, Li-ion cell), battery charger + power-path, and a regulator per rail with the LDO-vs-buck choice decided by dropout dissipation (≤ 0.5 W → LDO, else buck; rail above the system rail → boost). Every source/stage carries a rationale and points at the calculator that sizes it. Reachable via the new `power_tree_plan` MCP tool. The architecture layer of real synthesis — what stages a design needs and why, before netlisting. Tool catalog → 75.
- **Power-tree netlist emission** — `build_power_tree_design()` turns the power-tree plan into a real `Design` (components + nets) via the parametric blocks: a USB-C CC termination, a regulator per rail (a computed-L/C buck via `buck_inductor_capacitor`, or a new generic LDO block), and I2C pull-ups. Deterministic; boost stages are honestly left unrealized. Reachable via the new `synthesize_power_tree` MCP tool, which stores the design in the session. Adds the `instantiate_ldo` parametric block. Tool catalog → 76.
- **Closed-loop synthesize + ERC** — the new `synthesize_and_check` MCP tool builds an intent's power-tree netlist and runs the full ERC rule set on it in one call, closing the intent → netlist → verification loop so an agent can immediately see (and later auto-repair) what its own synthesis produced. Tool catalog → 77.
- **Design-analysis MCP tools** — expose the standalone analyses as agent-reachable tools: `mechanical_review`, `security_review`, `testability_report` (test-point coverage + debug/reset access + bring-up checklist), and `electrical_analysis` (heuristic SI/PI/thermal pre-check). Brings the agent tool catalog to 67.

### Manufacturing / DRC

- **Fab-profile-aware DRC** — `DRCEngine` accepts an optional `fab_profile`; when set, a DRC run also reports the selected manufacturer's profile-specific violations (min trace/space/drill/annular-ring, via and board limits) by folding the existing `DFMChecker` results into the `DRCResult`. Without a profile, DRC behaves exactly as before (generic geometric checks only). The `drc_run` MCP/agent tool gains a `fab_profile` parameter (e.g. `"jlcpcb-2layer"`) so the profile-aware run is reachable end-to-end.

### Domain analysis

- **Mechanical / enclosure review** — `mechanical_review()` flags missing mounting holes, too few holes on a large (>50 mm) board, and holes that sit off-board or too close to the edge to be usable. Returns serializable `MechanicalFinding`s.

### Verification

- **ERC014 voltage-domain check generalised** — now flags any two distinct declared supply voltages on a power net (1.8/3.3, 3.3/5, 5/12, …) instead of only the hardcoded 3.3 V vs 5 V pair. A shared `_parse_supply_voltage()` understands `"3.3"`, `"5"`, `"5.0"`, `"3V3"`, `"5V"` and `"3.3V"`, so `"5"`/`"5.0"` are treated as the same domain and blanks are ignored.
- **ERC023 — no-connect intent** — new rule flags a `no_connect` pin that is wired to other pins (it must be left floating per the part's datasheet). Brings the ERC pack to 23 rules.
- **ERC008 series-resistor check is now connectivity-precise** — the LED current-limit rule counted a series resistor only if a resistor is *directly connected* to the LED (shares one of its nets), via the electrical graph. Previously it passed whenever any resistor existed anywhere in the design (e.g. an unrelated I2C pull-up), masking real missing-current-limit faults.
- **ERC011 USB ESD check is now connectivity-precise** — USB ESD protection counts only when an ESD/TVS part shares a net with the USB device (and the protection part itself is no longer mis-flagged as an unprotected connector). Previously any ESD part anywhere in the design satisfied the check.
- **ERC016 reset-hold check is now connectivity-precise** — a reset pin is satisfied when its net is a power rail (tied high directly) or a resistor on that net bridges to a rail (pull-up to power, via `ElectricalGraph`). The old check counted any resistor sharing the net regardless of where it led, missed direct-to-rail resets (false positives), and only matched the exact type string `"RES"` (not `"R"`/`"Resistor"`). `has_resistor_to_power()` now accepts `allowed_values=None` to mean any resistor value.
- **ERC coverage reporting** — `ERCResult` now records every check that ran (`checks_run`: rule id, title, category, violation count) and a code-owned list of known `coverage_gaps`. `coverage_summary()` reports "N checks run across M categories … K coverage gaps noted" so a passing ERC advertises its scope and limits instead of an unqualified "passed". Surfaced in the design report, `erc_validate`, and `erc_get_result`.

### Honesty / no-overclaim

- **Synthesis self-describes as template selection** — `synthesize_with_provenance()` returns a `TemplateSelection` (template id, name, match score, `method="template_selection"`); `synthesize_design` (MCP/CLI) now reports which template was loaded and notes that this is keyword-based template selection, not from-scratch circuit synthesis. Tool/CLI descriptions and the README status table no longer overclaim "schematic synthesis".

### Governance and Release Readiness

- Added verification-gate matrix and blocker policy documentation for release-critical evidence.
- Added release-gate CI summary script/test coverage and workflow artifact upload for gate PASS/FAIL/SKIP evidence.
- Reconciled README, roadmap, FAQ, and current-state audit status around the 0.3.0 evidence-hardening baseline.
- Added standardized issue templates and triage policy for epics, release gates, research tasks, bugs, and features.

## [0.2.2] - 2026-06-17 — Verification Foundation and Safety Hardening

### Proof & Evidence

- **Proof Pack v1 validation** — `validate_proof_pack()` with field coverage for version, name, design_path, artifacts (path + sha256), check_records, and limitations. CLI `zaptrace proof validate` with strict mode. 64 proof tests.
- **KiCad Oracle** — `KiCadOracle` module runs external KiCad ERC/DRC, captures results with `error`/`warning`/`violation_count` properties, integrates with Proof Pack checker. 1 new CLI command.
- **Fab profiles** — `zaptrace/fab/profile.py` with `FabProfile` model, 4 built-in profiles (JLCPCB 2/4-layer, OSH Park, PCBWay), DFM validation (`zaptrace/fab/dfm.py`) against profile constraints. Proof Pack integration.

### Library Reference Parts

- **12 seismic/IoT reference components** — W5500, WS2812B, CN3058E, TLV62569, TPS3839, TPS7A2033, USBLC6-2SC6, SX1262, ATECC608B, ADXL355, MAX-M10S, DS3231SN, RV-3032-C7. Library test coverage.

### CI & Automation

- **Export regression corpus** — Golden-file comparison test framework under `tests/corpus/goldens/` with 6 golden artifacts (BOM CSV/JSON, KiCad PCB/SCH, pick-and-place, report, schematic SVG). 1 test module.
- **Dedicated hardware CI** — `.github/workflows/hardware.yml` workflow runs hardware-level integration checks on dedicated runners.

### Agent & API Safety

- **MCP transaction safety** — Design snapshot/rollback/commit primitives in agent tools (`_snapshot_design`, `_rollback_design`, `_commit_design`). MCP `design_snapshot`, `design_rollback`, `design_commit` tools. Test coverage for agent tool lifecycle and MCP server integration.
- **REST API hardening** — Per-session rate limiting (token bucket), security headers (X-Content-Type-Options, X-Frame-Options, CSP, HSTS), session isolation via session-scoped design stores, request body size limits, robust Content-Length handling.

### Documentation & Positioning

- **Plugin runtime safety design** — Comprehensive design document (`docs/design/plugin-runtime.md`) covering manifest schema, capability permissions, read/write separation, sandbox model (3-phase), version negotiation, dependency policy, network access policy, signing/trust model, failure isolation, MCP transaction integration, Proof Pack attestation, and test strategy.
- **Verification-first positioning** — Clarified project positioning: added Verification Model section with evidence-layer table and non-claims, strengthened "What ZapTrace Is Not" with 6 new entries, removed fabrication-ready/production-ready language from FAQ, ROADMAP, and specs. Explicit Pre-1.0 banner.

### Non-Claims

This release does not claim:

- Fabrication-ready output
- Production-ready hardware generation
- Manufacturer approval
- Guaranteed correctness
- Fully automatic manufacturing

All outputs require human engineering review before fabrication.

## 0.2.1 (2026-06-10)

### Fixes

- Fixed DRC rule listing and footprint lookup tools that raised runtime errors.
- Fixed ERC component resolution by supporting both component IDs and reference designators.
- Fixed voltage-domain ERC checks and schematic SVG net rendering.
- Fixed KiCad copper-pour export when a design has no routing result.
- Added source type checking and regression coverage for the repaired paths.

### Release

- Restored deleted GitHub quality and security workflows under new workflow paths.
- Added release quality gates, immutable action pins, artifact attestations, and GHCR container publishing.
- Fixed the Docker image build and included server/MCP optional dependencies.

## 0.2.0 (2026-06-08)

### Features

- **KiCad PCB export** — Full `.kicad_pcb` output with layers (2/4-layer),
  board outline, footprints with pads, trace segments, vias, copper pours
  (zones), and mounting holes. Layer name mapping: `layer_0` → `F.Cu`,
  `layer_1` → `B.Cu` (or `In1.Cu` for 4-layer).
- **Component body blocking** — GridRouter reserves space occupied by
  component bodies via footprint courtyard dimensions, preventing traces
  from overlapping components (`_block_components`).
- **Layer-aware routing** — GridRouter assigns nets to layers based on
  their `NetClass` (power on top, analog on top, high-speed on inner
  layers for 4-layer boards, signal on bottom).
- **Excellon drill file export** — NC drill file output with plated and
  non-plated holes, tool size optimization, mounting hole support.
- **Copper pour engine** — Flood-fill based copper pour generation with
  mounting hole and trace obstacle blocking.

### CI & Quality

- **GitHub Actions** — All workflows upgraded to Node 24 compatible
  actions (`checkout@v6`, `upload-artifact@v6`, `download-artifact@v8`,
  `codecov@v6`, `codeql@v4`, `setup-uv@v8.1.0`).
- **Semgrep SAST** — Replaced archived `semgrep-action@v1` with native
  CLI (`pip install semgrep` + `semgrep scan`). SARIF upload integrated.
- **Ruff lint** — 113 auto-fixed + 23 unsafe-fixed issues across 59 files.
  Line length 100→120. 92 files reformatted. All checks passing.
- **Type checking** — Zero type errors in `grid_router.py` (down from 5).
- **Dependency groups** — `ruff`, `pytest-cov`, `maturin`, `pyright`
  added to dev/lint/test/typecheck groups.

### Documentation

- **README** — Comprehensive project README with feature matrix, quickstart,
  CLI/SDK/MCP/REST usage, architecture diagram, roadmap, limitations.
- **Community health** — `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md` added. GitHub issue/PR templates created.
- **Architecture docs** — `docs/ARCHITECTURE.md` with layer diagram,
  `docs/GETTING_STARTED.md`, `docs/ROADMAP.md`, `docs/FAQ.md`,
  `docs/SAFETY.md`.
- **Strategy docs** — `docs/strategy/` with MCP strategy, community growth,
  docs strategy, proof pack spec.
- **MCP docs** — `docs/mcp/` with quickstart, tools reference, examples.
- **Manufacturing docs** — `docs/manufacturing/` with Gerber and BOM guides.
- **Plugin development guide** — `docs/plugins/development-guide.md`.
- **Example designs** — 5 example projects in `examples/` (ESP32 I2C sensor,
  RP2040 USB HID, USB-C LiPo charger, STM32 RS-485, nRF52840 BLE sensor).

### Proof Pack System

- **`zaptrace/proof/`** — New module for self-verifying design validation bundles.
  - `manifest.py` — Pydantic models for `ProofManifest`, `CheckDefinition`,
    `ManifestModel` with categories and severity levels.
  - `checker.py` — `ProofRunner` with 6 built-in check types: DRC, ERC,
    routed, clearance, footprint_exists, net_connected. Custom check registry.
  - `pack.py` — `ProofPack` class (load, run, summary, report_json).
    `run_proof()` convenience function.
  - `__init__.py` — Clean public API.
- **CLI** — `zaptrace proof run|list|info` commands for proof pack management.
- **MCP tools** — `proof_run`, `proof_run_design`, `proof_list_checks` tools
  registered in TOOL_REGISTRY and exposed via FastMCP.
- **Proof pack example** — `.proof/` directory in the ESP32 example with 8 checks.
- **Tests** — 35 proof module tests (manifest, checker, YAML round-trip, pack
  loading, CLI integration).

### Fixes (post-release)

- **README links fixed** — `docs/MCP.md` → `docs/mcp/quickstart.md`,
  `docs/REST_API.md` → `docs/GETTING_STARTED.md`,
  `docs/PROOF_PACK.md` → `docs/strategy/proof-pack-spec.md`,
  `examples/README.md` → `examples/`.
- **Version strings** — API server (`0.1.0→0.2.0`), agent shell, test assertions.
- **Entry point** — Added `zaptrace-api` script pointing to `zaptrace.api.server:run`.
- **Ruff cleanup** — Removed unused imports, trailing whitespace in `cli/proof.py`.
- **Formatting** — `cli/proof.py` reformatted.

### Tests

- Test suite passing under CI; exact counts are enforced by automation rather than hard-coded here.
- Test count includes 43 proof module tests + 500 existing tests.
