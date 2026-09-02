# ZapTrace Current State Audit

This page is the **current, evidence-backed repository snapshot**. It intentionally avoids historical plan language and hard-coded facts that cannot be checked from the repository. Dated strategy snapshots remain historical records and must not be read as current capability inventories.

The CI guard `scripts/ci_docs_status_sync.py` validates selected public claims and writes the exact Git revision into its JSON report. A change to one of the governed source facts must update this page in the same pull request or the documentation gate fails.

## Source-of-truth map

| Public fact | Repository source |
|---|---|
| Package/version identity | `pyproject.toml`, `config/version-policy.json` |
| Component inventory and trust tiers | `config/component-trust-baseline.json`, enforced by `scripts/ci_component_metadata_gate.py` |
| ERC/DRC counts | `zaptrace/erc/runner.py`, `zaptrace/ee/drc/engine.py` |
| MCP design/admin tool counts | `zaptrace/agent/tool_impls/registry.py`, `zaptrace/mcp/server.py` |
| KiCad project import | `zaptrace/kicad/project_importer.py` plus KiCad corpus tests/gates |
| Release automation, SBOM, checksums, attestations | `.github/workflows/release.yml` |
| Main-branch ruleset contract | `config/github-main-ruleset.json`, checked by `scripts/ci_repository_ruleset.py` |
| Documentation fact guard | `scripts/ci_docs_status_sync.py` |
| Public distribution facts | `config/public-facts.json`, validated by `scripts/ci_docs_status_sync.py` |

The generated docs-status report records the source revision, the selected capability booleans, the component-library profile, and navigation drift. Those machine-derived values are evidence about repository state, not proof of electrical correctness or fabrication readiness.

## Current repository facts

- Python distribution identity: `zaptrace-eda` `0.3.4.dev0`, with import package and CLI identity `zaptrace`, Python 3.12+, in `unreleased-development`; the latest published baseline is `v0.3.3`, whose tagged workflow completed TestPyPI, production PyPI, and GitHub Release verification. The immutable `v0.3.2` tag remains failed-release evidence and was not reused.
- Verification rules: 29 ERC rules and 16 DRC rules, derived from the registered rule lists.
- Agent surface: 93 design tools plus 3 session-administration tools, for 96 MCP-exposed tools total.
- Component library baseline: **504 component records**, schema version 2.0, with trust tiers currently `{"heuristic": 504}` in `config/component-trust-baseline.json`.
- The component metadata CI gate validates the shipped library against that committed baseline with zero error/warning budget. The all-heuristic baseline still requires human review; it is not a manufacturer-approved library.
- KiCad import is implemented for PCB, schematic, and hierarchical project flows. Round-trip and external-oracle coverage remain bounded and do not imply complete KiCad feature parity.
- EasyEDA Standard import/export and EasyEDA Pro import-oriented interoperability are implemented with explicit degradation evidence where supported.
- Altium ASCII schematic **import** is supported. ZapTrace does not claim a native Altium binary writer or complete Altium project parity.
- GitHub release automation builds source/wheel artifacts, generates an SBOM and checksum manifest, attests release artifacts, and creates a GitHub release through `.github/workflows/release.yml`.
- `release.yml` carries tokenless OIDC Trusted Publishing contracts for `zaptrace-eda`: manual `main` staging is TestPyPI-only, while tagged releases require TestPyPI hash/clean-install verification before PyPI and require PyPI verification before GitHub Release creation. The `v0.3.3` tagged run completed this production path successfully, so PyPI is now a verified public distribution channel alongside GitHub Releases.
- The active main-branch contract is represented by `config/github-main-ruleset.json` and validated by repository CI evidence.

## Verification and release posture

ZapTrace is pre-1.0 and verification-first. The repository contains automated linting, type checking, unit/integration/hardware lanes, security scanning, release gates, KiCad-oracle integration, proof-pack evidence, and reproducibility/provenance checks. These gates verify configured software and artifact contracts; they do **not** prove a generated board is safe, manufacturer-approved, or physically validated.

External-tool evidence may still be environment-dependent, and physical reference-board/lab correlation remains separate work. Human engineering review is required before fabrication or deployment of generated electronics.

## Current limitations that remain intentional

- The committed component baseline is heuristic rather than independently datasheet/footprint reviewed at part level.
- Physical fabrication and lab-correlation evidence is not yet broad enough to support fabrication-readiness claims.
- External manufacturer acceptance/DFM evidence is not a universal release-blocking oracle.
- Interactive push-and-shove routing, multi-board design, and full solver-grade SI/PI/thermal verification remain incomplete.
- Plugin/runtime and network-exposed MCP deployments require deployment-specific sandboxing, authentication, and operational controls beyond repository-level evidence.

## Historical material

Documents whose titles contain explicit dates are historical snapshots. They may describe capabilities or gaps that were true at that revision but are not current claims. Completed internal implementation plans, approval scripts, and scratch execution material are intentionally excluded from the public documentation tree; durable contributor-facing decisions belong in normal architecture, development, security, or governance documentation.
