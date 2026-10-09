# Dependency Management

## Tooling

ZapTrace uses standard ecosystem tooling:

- Python project metadata and dependencies: `pyproject.toml`.
- Python lockfile: `uv.lock`.
- Rust dependencies: `zaptrace_core/Cargo.toml` and `zaptrace_core/Cargo.lock`.
- Container runtime: `Dockerfile`, `docker-compose.yml`, `requirements/container-runtime.txt`, and `requirements/container-apk.txt`.
- GitHub Actions: pinned workflow actions.
- Automation: Renovate for normal updates and Dependabot for GitHub-native security alerts/security updates.

## Update policy

- Patch/minor/digest updates may be automated when CI and stability checks pass.
- Major updates require manual review.
- Docker/base-runtime updates require extra caution even when CI passes.
- Security updates should be triaged before routine feature work.

## Renovate PR admission

Renovate waits at least **five days** after a dependency release and uses
`prCreation: not-pending`, `internalChecksFilter: strict`, and
`internalChecksAsSuccess: true`. The last option allows the passing
`renovate/stability-days` check to satisfy Renovate's *pre-PR* branch check:
the repository's Actions jobs run on pull requests, not on unpublished
`renovate/*` branches. Without that option, the branch can remain pending
with no external checks, preventing PR creation indefinitely.

This does **not** authorize merging a PR from the Renovate check alone.
Regular PR validation, the six protected `main` required checks, Mergify's
low-risk scope restrictions, the maximum concurrent PR count, and manual
review requirements for major, sensitive or container changes still apply.
If branches remain pending after their release-age window, inspect the
Renovate Dependency Dashboard and actual branch checks; do not bypass
cooling-off or batch-approve all major updates.

## Container runtime locks

The container image does not resolve `.[mcp,server]` during the image build. Its Python runtime dependencies are exported from `uv.lock` into the committed, hash-complete `requirements/container-runtime.txt`; the ZapTrace wheel is then installed separately with `--no-deps`. The runtime Alpine package set is committed in `requirements/container-apk.txt` with exact package versions.

Regenerate the Python manifest from the repository root with the pinned container resolver version:

```bash
uv export \
  --frozen \
  --no-dev \
  --extra mcp \
  --extra server \
  --no-emit-project \
  --format requirements.txt \
  --no-annotate \
  --no-header \
  --output-file requirements/container-runtime.txt
```

Then run the fail-closed consistency check:

```bash
python scripts/ci_container_reproducibility.py check-lock \
  --manifest requirements/container-runtime.txt \
  --apk-manifest requirements/container-apk.txt \
  --output container-lock-evidence.json \
  --markdown container-lock-evidence.md \
  --strict
```

The workflow currently pins `uv 0.11.29`. A resolver-version update and any resulting manifest change must be reviewed together. Update the Alpine manifest only after confirming the package version against the exact pinned base image and its generated SBOM.

## Review expectations

Dependency PRs should include:

- lockfile updates when applicable;
- CI results;
- release notes or changelog review for major/runtime changes;
- explicit risk if the update affects parser, export, MCP/API, plugin, CI, or release behavior.

## License awareness

The repository uses PolyForm Noncommercial 1.0.0 for current project-authored files and explicit SPDX overrides for vendored third-party assets. Earlier MIT-licensed releases remain under their original terms. REUSE 6.2.0 is invoked through an exact, reproducible `uvx --from reuse==6.2.0` command. Run:

```bash
python scripts/ci_reuse_check.py --strict
```

The gate checks every tracked file, preserves the CC-BY-SA-4.0 attribution for vendored footprints, and fails when new files lack licensing information. Dependency-license compatibility still requires engineering and legal-context review; REUSE file coverage is not a legal opinion.

## OpenSSF evidence

This document supports OpenSSF/OSPS dependency selection, dependency ingest, and dependency tracking criteria. A concise policy version is available at [Dependency Policy](../supply-chain/dependency-policy.md).
