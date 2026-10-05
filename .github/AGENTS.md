# AGENTS.md

## Scope

This file applies to `.github/**` and supplements the repository-root `AGENTS.md`.

This subtree contains repository governance, CI, security scanning, dependency automation, release automation, and evidence-producing workflows. Treat workflow changes as policy and supply-chain changes, not incidental YAML edits.

Before changing a workflow, identify:

- the invariant or policy the job enforces;
- triggering events and path/change classification;
- permissions and credentials used;
- dependency/action pins;
- scripts or tests invoked;
- produced/retained evidence artifacts;
- downstream release or merge assumptions.

## Security and permissions

- Use least-privilege `permissions:` at workflow/job scope.
- Do not broaden token permissions for convenience.
- Do not expose secrets through command output, summaries, artifacts, caches, environment dumps, or debug logging.
- Treat pull-request input, branch names, artifact contents, cache contents, and externally sourced metadata as untrusted where applicable.
- Preserve separation between untrusted execution and privileged publication/release steps.
- Do not add secret-bearing behavior to workflows triggered from untrusted fork code without an explicit secure design.

## Action and dependency integrity

GitHub Actions dependencies are part of the supply chain.

- Preserve repository pinning policy for third-party actions.
- Do not replace immutable/pinned references with floating tags solely for easier upgrades.
- Keep Renovate/Dependabot behavior aligned with `docs/supply-chain/dependency-policy.md`.
- Review major/runtime-sensitive dependency changes for release notes and security impact.

## Gate integrity

A red gate is evidence, not an obstacle to suppress.

Do not:

- convert a required failing step to `continue-on-error` merely to make CI green;
- add broad exclusions, waivers, or skip conditions that hide a real failure;
- weaken HIGH/CRITICAL vulnerability enforcement as a generic remediation;
- make a required lane pass when no required tests actually executed;
- remove evidence retention needed to diagnose or verify a gate;
- weaken branch/source identity checks to permit publication.

When a policy must change, update the policy, implementation, tests, documentation, and evidence expectations coherently and make the rationale explicit in the PR.

## Change classification

`scripts/ci_change_policy.py` determines bounded CI modes from the changed paths.

Do not special-case a file merely to obtain a cheaper CI lane. If the classification is wrong for a class of changes, change the classifier and its tests based on risk semantics.

Changes under security-sensitive/high-risk prefixes may intentionally select broader validation even when the edited file is documentation.

## Quality and test workflows

The Quality workflow is the authoritative orchestrator for repository validation.

Preserve:

- lint/format/type-check enforcement;
- centrally classified test lanes and lane-budget policy;
- required execution semantics for external/native/hardware lanes;
- coverage combination and protected critical-runtime floors;
- Rust checks and installed-wheel native verification;
- component metadata/evidence gates;
- package/distribution smoke checks;
- benchmark, generated-board, and KiCad/oracle evidence where selected.

Do not duplicate repository policy in workflow YAML when the policy is intentionally centralized in a script/config file.

## Security workflows

Preserve fail-closed behavior for applicable dependency, secret, static-analysis, container, Cargo advisory, and release-integrity checks.

- Do not add broad scanner ignore rules without a bounded, documented justification.
- Keep evidence tied to the exact source/dependency/artifact identity it claims to represent.
- A scanner/tool outage is not the same as a clean result; preserve explicit failure/approved-skip semantics defined by the owning policy.

## Release workflows

Release automation is security-sensitive.

Follow `docs/development/release-process.md`, `docs/development/version-policy.md`, and the relevant `docs/security/` release documents.

Preserve:

- exact version/commit/tag identity;
- release-preparation versus ordinary development context;
- build-before-upload ordering;
- installed-wheel/native verification;
- checksums, SBOM/provenance/attestation evidence;
- immutable artifact/tag expectations;
- failure-before-publication semantics.

Do not claim publication or release completion before GitHub/repository release evidence establishes it. Do not move or reuse a failed/immutable release tag to hide prior evidence.

## Generated and evidence artifacts

If a workflow produces JSON, Markdown summaries, manifests, attestations, reports, or proof artifacts:

- keep schema/field semantics stable unless intentionally versioned;
- bind evidence to the exact source/artifact/dependency identity required by policy;
- retain artifacts for the duration defined by the owning workflow/policy;
- do not fabricate successful evidence when a producer did not run successfully.

## Workflow validation

For workflow changes:

- inspect all affected triggers, conditions, matrices, permissions, dependencies, and artifact paths;
- run focused tests for repository scripts/config used by the workflow;
- use repository validation commands where available;
- rely on the actual GitHub Actions run for behavior that cannot be faithfully reproduced locally.

Do not state that a workflow is validated merely because the YAML parses.

## Definition of done

A `.github/**` change is complete only when the intended policy remains explicit, permissions remain least-privilege, dependency integrity is preserved, relevant policy/script tests pass, and required GitHub Actions checks report the behavior claimed in the PR.
