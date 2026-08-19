# ZapTrace Review Studio Product Spec and UX Contract

Status: v0.3 product contract
Primary goal: human-in-the-loop review of agentic EDA changes, not a full schematic or PCB editor.

## Product Positioning

Review Studio is the surface where a person reviews evidence before accepting a design mutation, release export, or manufacturing handoff. It should make hidden state impossible: every agent proposal must be connected to a semantic diff, validation result, proof-pack record, BOM risk finding, and explicit approval or rollback action.

Review Studio is deliberately narrower than KiCad, Altium, or a browser PCB editor. It is a verification and approval workbench for agent-generated work.

## Target Users

| User | Primary need | Review Studio job |
|---|---|---|
| Hardware engineer | Confirm proposed schematic, PCB, DFM, and BOM changes | Review semantic/visual diffs, inspect violations, approve or reject transactions |
| Firmware engineer | Confirm pinout, boot/debug, buses, and power assumptions | Inspect net-level changes, connector maps, generated docs, and validation evidence |
| Founder/prototyper | Understand readiness and risk without becoming an EDA expert | See release blockers, non-claims, estimated risk, and next actions |
| CI reviewer | Review pull request artifacts and release gates | Open a static bundle with scorecards, proof-pack hashes, and blocking failures |
| Enterprise reviewer | Audit provenance, approvals, and security boundaries | Trace decisions, approvals, tool outputs, and local/hosted data boundaries |

## Non-Goals for v0.1/v0.2

Review Studio must not try to be:

- a full interactive PCB editor;
- a manual routing environment;
- a full schematic capture replacement;
- a fabrication approval authority;
- a no-human-review autonomous signoff system;
- a clone of KiCad or Altium in the browser.

When editing is needed, Review Studio should send users back to the source EDA tool or to a controlled agent transaction rather than allowing free-form hidden mutation.

## Core UX Principles

1. **Evidence before approval.** Approval controls are disabled until required gates are visible.
2. **Diff-first review.** Every proposed write starts from “what changed?” rather than “what was generated?”.
3. **No hidden mutation.** UI state reflects committed transaction state, pending proposal state, and rollback targets separately.
4. **Risk is explicit.** Unsupported features, stale cache, skipped external tools, and non-claims are displayed as first-class review items.
5. **Static artifacts are first-class.** A CI reviewer should be able to open a static bundle without running ZapTrace services.
6. **Authenticated identity only.** Reviewer identity comes from the authenticated request principal; client-supplied reviewer names are never trusted as sign-off identity.
7. **Automated pass is not human approval.** `automated_gate_status` and `fabrication_status` are separate fields and must remain visibly distinct.

## Core Screens

### 1. Project Overview

Purpose: summarize current design state, release readiness, open blockers, and latest agent proposal.

Required widgets:

- project metadata and design hash;
- active branch/session/transaction id;
- release gate status;
- proof-pack status;
- latest ERC/DRC/DFM/BOM/KiCad oracle result;
- non-claims and required human-review warnings.

### 2. Agent Plan and Transaction Timeline

Purpose: show what the agent intended, what it changed, and where rollback is possible.

Required widgets:

- agent plan steps;
- transaction timeline with pending, validated, approved, committed, rejected, and rolled-back states;
- per-transaction state hash;
- approval id and approver metadata;
- rollback target selector.

Alignment with the canonical hardware-IR and agent-permission-model work:

- write operations appear as transactions;
- commit requires explicit approval id;
- release-export actions require permission-scoped capability and validation evidence;
- rejected or failed transactions remain visible as audit evidence.

### 3. Schematic / Design Semantic Diff

Purpose: make logical changes reviewable without requiring PCB-editor expertise.

Required widgets:

- added/removed/changed components;
- net connectivity changes;
- pin/function changes;
- constraints and variant changes;
- generated explanation from the agent;
- machine-readable diff artifact link.

### 4. PCB / Layer Visual Diff

Purpose: show board-level change evidence without building a full PCB editor.

Required widgets:

- board outline and layer preview;
- copper/layer change overlays where available;
- placement changes;
- routing changes;
- unsupported visual fidelity degradations;
- link to native KiCad artifacts.

### 5. ERC / DRC / DFM Panel

Purpose: show whether design correctness and manufacturing constraints block release.

Required widgets:

- ERC summary and violations;
- DRC summary and violations;
- DFM summary by fab profile;
- severity filter;
- blocker/warning classification;
- external tool skip reasons.

### 6. BOM and Supply-Chain Risk Panel

Purpose: prevent release confidence when required parts are unavailable, obsolete, stale, or risky.

Required widgets:

- BOM table with ref, MPN, manufacturer, distributor part number, lifecycle, stock, and price break data;
- provider and cache provenance;
- stale/offline/cache-miss indicators;
- alternates;
- risk score and release-blocking flags;
- compliance flags where available.

### 7. Fab Profile / Manufacturing Export Panel

Purpose: connect outputs to manufacturing evidence, not just file generation.

Required widgets:

- selected fab profile;
- Gerber/Excellon/BOM/pick-and-place/stackup/manifest artifacts;
- artifact hashes;
- Gerber/Excellon smoke validation;
- ODB++ and IPC-2581 evidence attachment status;
- retained GLB mechanical-review link and explicit model-coverage limitations when available;
- run-bound ODB++/GLB artifact hashes plus bounded structural rerun-comparison digests and byte-determinism limitations;
- manufacturing non-claims.

### 8. Proof-Pack Viewer

Purpose: present audit evidence as the release review source of truth.

Required widgets:

- manifest metadata;
- input record;
- environment/tool versions;
- artifact list with hashes;
- check records;
- KiCad oracle evidence;
- transaction history;
- BOM provenance;
- manufacturing evidence;
- limitations and non-claims.

### 9. Approve / Reject / Request Repair / Accept Risk / Rollback Controls

Purpose: make human intent explicit.

Required controls:

- approve the exact current design state with a rationale;
- reject the state with a rationale;
- request repair with a concrete reason and no approval identifier;
- accept a documented risk only after an explicit checklist waiver and rationale;
- rollback to a selected transaction hash;
- commit an approved transaction;
- export a proof bundle;
- copy the generated approval identifier for an `approve` or `accept-risk` decision.

Controls must show why they are disabled, such as missing validation evidence, failed blocker, missing approval id, or insufficient capability.

### 8. Benchmark Readiness Panel

Purpose: surface benchmark and release-readiness evidence before a human approves a design, export, or release candidate.

Required widgets:

- benchmark family/status summary;
- known-failure mutation caught/missed count;
- blocking benchmark failures and missed expected detectors;
- golden KiCad fixture comparison status where available;
- links to benchmark reports and release gate summaries;
- non-claims that make clear benchmark pass is regression evidence, not fabrication approval.

## UI Data Contract

Review Studio consumes generated artifacts and normalized JSON records. It should not infer release readiness from screenshots or raw EDA files alone.

| UI area | Source artifact / API record | Required fields |
|---|---|---|
| Project overview | release gate summary JSON | status, blocked, blocking gates, non-claims |
| Transaction timeline | transaction runtime records | transaction id, state hash, status, approval id, operation, timestamp |
| Semantic diff | design diff JSON | added, removed, changed, severity, path, summary |
| PCB visual diff | visual diff manifest | layers, previews, unsupported features, diff artifacts |
| ERC/DRC/DFM | validation reports | check name, source, severity, status, violation count, details path |
| BOM risk | BOM risk report | provider, cache policy, lifecycle, stock, alternates, risk score, flags |
| Manufacturing | manufacturing evidence JSON | artifact kind, path, size, sha256, smoke validation status, fab profile |
| Proof pack | proof manifest | inputs, environment, artifacts, checks, oracle evidence, transaction history, limitations |
| Benchmark readiness | benchmark summary / mutation corpus / golden fixture reports | passed, caught_count, missed_count, blocking failures, non-claims |
| Assumptions | architecture artifact | assumption id, text, risk level, confirmation requirement, related requirements |
| Approval controls | authenticated principal and review session | actor, capability, review status, decision, rationale, approval id, state hash, disabled reason |
| Release status | release gate | automated_gate_status, fabrication_status, engineering_review, evidence identity, approval binding |

## Implemented Review Decision Contract

Interactive Review Studio sessions use an immutable terminal state machine:

| Decision | Preconditions | Approval ID | Fabrication status |
|---|---|---:|---|
| `approve` | Every blocking checklist item is approved or explicitly waived; no item is rejected; rationale is non-empty. | Generated | `human-approved` |
| `reject` | Authenticated reviewer and non-empty rationale. | None | `rejected` |
| `request-repair` | Authenticated reviewer and non-empty repair rationale. | None | `repair-requested` |
| `accept-risk` | Blocking items are resolved, at least one explicit checklist waiver exists, and rationale is non-empty. | Generated | `risk-accepted` |
| `rollback` | Authenticated reviewer and non-empty rationale. | None | `rolled-back` |

Every terminal decision records the review-session ID, exact release-relevant design-state hash, authenticated reviewer principal, ISO-8601 timestamp, rationale, checklist results, and optional waiver notes. A finalized review session is immutable. A changed design therefore requires a new review session; a matching approval ID from an older state is rejected as stale.

When `ZAPTRACE_SESSION_STORE_ROOT` is configured, the complete review session is stored as a protected typed `review-session` record under its parent design session. Checklist changes and terminal decisions are upserted atomically, hydrate after process restart, and are deleted with the authorized parent-session destruction lifecycle. When persistence is not configured, the existing process-local behavior remains available.

REST session responses expose `review_status` and `finalized`. The release gate exposes both:

- `automated_gate_status`: result of the automated release-evidence checks;
- `fabrication_status`: `human-review-required`, `human-approved`, `risk-accepted`, or a blocking review state;
- `engineering_review`: normalized state-bound reviewer, timestamp, rationale, decision, checklist, and approval-match evidence.

A generic external release `approval_id` does not become human-review evidence. Only a current Review Studio approval or risk-acceptance decision with the same approval ID and design-state hash changes `fabrication_status`. Current `reject`, `request-repair`, and `rollback` decisions block release export. This is auditable workflow evidence, not manufacturer authorization, regulatory approval, or a claim that physical hardware is safe or correct.

## Static Viewer Mode for CI Artifacts

The first implementation slice is a static review bundle. It should be generated by CI or CLI and opened as local files.

Minimum bundle contents:

```text
review-bundle/
  index.html
  data/
    snapshot-gate-summary.json
    proof-manifest.json
    semantic-diff.json
    validation-summary.json
    bom-risk.json
    manufacturing-evidence.json
    kicad-roundtrip-scorecard.json
    benchmark-summary.json
    known-failure-mutations.json
  artifacts/
    schematic.svg
    board-preview.svg
    gerbers.zip
    kicad-project.zip
```

Static viewer requirements:

- no backend service required;
- no network calls by default;
- all artifact paths are relative to the bundle;
- bundle displays hash mismatches and missing files as blockers;
- supports PR review and release candidate review;
- can be uploaded as a CI artifact.

## Local-First and Hosted Security Requirements

Local-first mode:

- no artifact upload unless explicitly requested;
- all EDA files remain on the user machine;
- no telemetry containing design files, BOM, or netlists;
- path traversal protections for bundle loading;
- readonly static mode by default.

Hosted mode:

- workspace and project-level access controls;
- signed artifact URLs with expiration;
- audit log for every approval, rejection, rollback, and export;
- server-side validation of capability and approval id;
- secrets redaction for provider/API credentials;
- strict separation between user-visible evidence and hidden agent scratch state.

## End-to-End Demo Scenario

Scenario: ESP32 sensor board release review.

1. Agent proposes USB-C, Li-ion charger, 3.3 V regulator, ESP32, I2C sensor, debug header, LED/button changes.
2. Review Studio opens the transaction timeline and highlights the pending proposal.
3. Hardware engineer checks the semantic diff: new power tree, new I2C nets, new BOM lines, and updated fab profile.
4. ERC/DRC/DFM panel shows no blocking electrical or manufacturing findings.
5. BOM panel flags the original BME280 as unavailable/obsolete and suggests BME688 as an alternate.
6. Engineer rejects the first proposal with reason: “replace obsolete sensor.”
7. Agent creates a new transaction replacing the part and updating constraints.
8. Review Studio shows reduced BOM risk and updated proof-pack evidence.
9. Engineer approves with an approval id.
10. Commit and release-export controls become enabled because permission scope, validation gates, and approval evidence are present.
11. CI publishes a static review bundle attached to the pull request.

## First Implementation Slice

Build static proof-pack/design review bundle generation before building an interactive app.

Milestone slice:

- CLI command or CI script writes a `review-bundle/` folder;
- bundle includes normalized JSON evidence and static HTML;
- proof-pack, semantic diff, validation, BOM risk, manufacturing evidence, and release gate summary are visible;
- approve/reject controls are shown as disabled/read-only in static mode;
- hosted/interactive approval remains out of scope until transaction and capability APIs are stable.

## Acceptance Checklist

- Review Studio is explicitly scoped as a review and approval workbench, not a full EDA editor.
- Requirements, assumptions requiring confirmation, validation/risk panels, proof checks, and artifact SHA-256 records are visible in the normalized review bundle.
- Reviewer identity is authenticated, decisions are state-bound and immutable, and configured persistence survives restart.
- Automated gate pass and human fabrication status remain separate in REST, release, and proof evidence.
- Data contract maps to proof-pack, transaction, diff, BOM, fab, validation, and release-gate artifacts.
- Static proof-pack/design review bundle is the first implementation slice.
- Approval, rollback, and commit UX depends on transaction-safe state and permission-scoped writes.
- End-to-end ESP32 benchmark review scenario is documented.
