# Path-injection alert disposition

Status: issue #264 remediation evidence
Scope: open CodeQL `py/path-injection` findings present on `main` in July 2026

## Policy

ZapTrace separates two path trust boundaries:

1. **Network and agent surfaces** must resolve caller-selected paths through the configured workspace policy or avoid request-derived filesystem paths entirely.
2. **Low-level SDK APIs** may accept an explicit trusted filesystem root when selecting an output or input location is part of the documented library contract.

A CodeQL alert is dismissed only when the sink belongs to the second category or the reported line is the containment sanitizer itself, and regression tests demonstrate the boundary.

## Alert-to-control traceability

| Alerts | File / sink | Disposition | Control and test evidence |
|---|---|---|---|
| 40, 42, 43, 44, 48, 49, 50 | `zaptrace/api/storage.py` | Code fix | REST artifact paths now use server-generated opaque object directories and fixed `payload.txt` / `manifest.json` names. Session IDs, filenames, kinds, and delete selectors are compared only as metadata. Existing pre-opaque manifests remain accessible through fixed-root enumeration; new writes use only opaque directories. Covered by `tests/test_api_hardening.py`, `tests/test_object_authorization.py`, and `tests/test_path_injection_regressions.py`. |
| 39 | `zaptrace/core/session_store.py` | Code fix | Persistent session and design directories are server-generated opaque identifiers. Session IDs and design names are stored in manifests and matched during fixed-root enumeration. Version filenames are server-generated. Existing pre-opaque session layouts are discovered by fixed-root manifest enumeration without joining the requested session ID into a path. Covered by `tests/test_session_store.py` and `tests/test_path_injection_regressions.py`. |
| 4, 5 | `zaptrace/agent/tool_impls/runtime.py` | False positive: sanitizer implementation | `_validate_path` resolves the candidate to a canonical absolute path, requires it to be relative to the resolved workspace root, and returns the canonical path rather than the original selector. Traversal, absolute escape, prefix-sibling, symlink escape, and symlink-swap behavior are covered by `tests/test_path_traversal.py`, `tests/test_fuzz_untrusted_inputs.py`, and `tests/test_path_injection_regressions.py`. |
| 9 | `zaptrace/core/parser.py` | False positive: trusted SDK input path | `parse_file` is a low-level SDK function for a caller-selected trusted path. REST/MCP/agent entry points call `_validate_path(..., must_exist=True)` before invoking it. The trust boundary is documented in the function docstring and tested through agent path-containment tests. |
| 23, 24, 25, 28, 29 | `zaptrace/export/kicad.py` | False positive: trusted SDK output root | The public exporter intentionally accepts a caller-selected trusted output directory. Generated filenames are reduced to a restricted stem, candidates are resolved and checked relative to the resolved output root, and the canonical path is returned. Agent-facing exports validate the output directory against the workspace first. Traversal, suffix rewriting, and symlink-swap behavior are covered by `tests/test_path_injection_regressions.py` and existing KiCad export tests. |

## CI enforcement

GitHub CodeQL analysis runs on pull requests and the branch code-scanning check fails when a pull request introduces a new high-severity alert. Security workflow analysis, the PR alert check, and release-gate summary must all pass before merge.

## Residual risk

- Trusted SDK callers remain responsible for selecting an appropriate parser input path or exporter output root.
- Filesystem containment does not defend against a privileged local attacker who can modify the configured storage root or process environment.
- Persistent storage remains process/file based and is not a multi-process transactional database.
