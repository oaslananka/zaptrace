# Dependency and Static Analysis Ownership

ZapTrace uses multiple independent controls rather than treating one scanner as authoritative.

## Dependency updates and SCA

- **Renovate** owns normal Python/uv, Cargo, Docker/Compose, GitHub Actions, and pre-commit update pull requests.
- **Dependabot** remains enabled for GitHub-native vulnerability alerts and security updates; ordinary version PRs are disabled to avoid duplicate automation.
- **Dependency Review** blocks critical vulnerable dependencies introduced by pull requests.
- **`uv audit`** scans the resolved Python environment in CI.

## Static analysis

- **Semgrep OSS** runs community rules plus `.semgrep.yml` in CI and the repository-specific rules in pre-commit.
- **CodeQL** publishes GitHub code-scanning results.
  - `scripts/ci_profile_test_lanes.py` renders terminal output only from explicitly selected aggregate values. Raw input-derived paths and messages remain exclusively in the JSON report artifact; `tests/test_test_lane_profiling.py` verifies that untrusted detail strings cannot enter the terminal summary.
- **SonarQube Cloud** uses its existing GitHub automatic-analysis integration. A second CI scanner is intentionally not configured because Sonar does not support running automatic and CI-based analysis concurrently for the same project.

## Risk-based Python test policy

Pull requests use four machine-classified test modes:

- `docs`: documentation-only changes keep the named Python checks green without installing the test environment.
- `targeted`: CI, dependency automation, scanner policy, and test-only changes run changed tests plus a stable compatibility smoke set on Python 3.12, 3.13, and 3.14.
- `full-312`: ordinary product changes run the complete suite with coverage on Python 3.12 and the targeted compatibility set on Python 3.13 and 3.14.
- `full-matrix`: security/runtime boundaries, core parsers/models, MCP/API/agent code, exports, synthesis, native Rust, dependency locks, main-branch pushes, scheduled runs, and manual runs execute the complete suite on all supported Python versions.

The matrix uses fail-fast behavior. Gerber and proof-pack smoke tests run once on Python 3.12 rather than being duplicated across all interpreters. The active repository ruleset requires the stable aggregate `Release gate summary`; nightly and `main` runs retain the complete compatibility coverage while path-sensitive jobs remain internal to that aggregate.

## Immutable lock and MCP compatibility policy

The committed `uv.lock` is authoritative. Every Python workflow executes
`uv lock --check` before `uv sync --locked`; metadata drift fails instead of
silently re-resolving. Release and proof evidence record the exact lock SHA-256
and resolved MCP dependency versions.

ZapTrace supports `fastmcp>=3.4,<4` and `mcp>=1.28,<2`. Patch and minor updates
within those lines may be proposed through Renovate under normal review policy.
A new major line requires a dedicated migration issue, MCP registration/stdio/
HTTP-auth/response-envelope compatibility evidence, and explicit maintainer
review. Major updates are never routine automerge candidates.
