# Version Policy

ZapTrace uses one explicit release line across Python metadata, runtime reporting, REST/MCP surfaces, the Rust extension, lockfiles, tags, and release evidence. `pyproject.toml` is the authoritative version source. Other surfaces are derived from it or checked deterministically in CI.

## Active development identity

The active `main` identity after the immutable `v0.3.5` tag published to PyPI but stopped before GitHub Release creation is:

| Surface | Version |
|---------|---------|
| Python distribution, CLI, REST API, MCP server | `0.3.6.dev0` |
| Rust crate and Cargo lock package | `0.3.6-dev.0` |
| Current source ref | `main` |
| Latest published baseline | `v0.3.5` (PyPI; GitHub Release absent) |
| Distribution state | `unreleased-development` |

The `v0.3.3` release remains the legacy PyPI baseline without public Git provenance. The immutable `v0.3.2` and `v0.3.4` tags remain failed-release evidence. `v0.3.5` published verified Python artifacts to PyPI, but its tagged workflow failed the container-security gate before GitHub Release creation; it is retained immutably as partial-release evidence and must not be reused. The active `0.3.6.dev0` tree is unreleased snapshot evidence (`mode=snapshot`, `published=false`).

## Lifecycle transitions

ZapTrace distinguishes development, release preparation, and tagged publication:

1. **Development:** Python `0.3.5.dev0`; Cargo `0.3.5-dev.0`. Branch and pull-request evidence is unreleased snapshot evidence.
2. **Release preparation:** a repository-owned branch named exactly `release/v<version>` may carry an RC or final package identity before its tag exists. Quality records this as `release-preparation` with `published=false`; development versions, mismatched branch names, and already-used release tags are rejected.
3. **Release candidate:** Python `0.3.5rc1`; Cargo `0.3.5-rc.1`; annotated tag `v0.3.5rc1`. The report state is `tagged-release-candidate`.
4. **Final release:** Python and Cargo `0.3.5`; annotated tag `v0.3.5`. The report state is `tagged-final-release`.

Immediately after a final release attempt publishes immutable registry artifacts, `main` receives a post-release bump to the next patch's `.dev0` line. After `v0.3.5`, development advances to Python `0.3.6.dev0` and Cargo `0.3.6-dev.0` before unrelated changes are merged.

## Synchronization rules

`scripts/ci_version_consistency.py` checks:

- `pyproject.toml` and the root `zaptrace-eda` distribution entry in `uv.lock`;
- `zaptrace_core/Cargo.toml` and the root `zaptrace-core` entry in `Cargo.lock`;
- runtime `zaptrace.__version__`;
- REST `API_VERSION` and MCP `SERVER_VERSION`;
- Python PEP 440 to Cargo SemVer mapping;
- development trees use `.devN` and do not reuse an already released final line;
- release refs exactly match `v<package-version>`;
- release tags resolve to the exact checked-out source commit;
- future release tags are annotated Git tag objects.

The Quality workflow publishes `version-consistency.json` and `version-consistency.md`. The tag workflow publishes `version-consistency-release.json` and `version-consistency-release.md`. Both reports embed the shared evidence identity.

## Tag trust policy

Future release tags must be annotated. The historical `v0.3.0` lightweight tag is retained as a grandfathered historical record; it is not the template for future releases.

The repository records that cryptographic tag verification is not currently required because the repository does not yet contain a reviewed maintainer trust root and key-rotation policy. The machine-readable policy records this as `require_cryptographic_tag_verification=false`; reports must not imply a verified signature. Enabling signature enforcement requires a separate reviewed change that documents trusted identities, key rotation, revocation, and CI verification behavior.

## Release preparation

A release PR must use the exact `release/v<version>` branch name, synchronize all version surfaces, and change the package stage deliberately. Quality evaluates that PR with the bounded `release-preparation` context while all ordinary pull requests remain in `development` context. The resulting non-development identity is also accepted for the single `main` push transition before tagging; scheduled/manual main validation remains development-only, so a final identity cannot remain parked on `main`. The release tag is created only after the release PR is merged; the tag workflow then re-verifies the exact tagged commit in `release` context. The tag workflow rejects:

- a development version;
- a tag/package mismatch;
- a lightweight future tag;
- a tag pointing to a different commit;
- Python, runtime, API/MCP, Rust, or lockfile disagreement.

## Local verification

```bash
.venv/bin/python scripts/ci_version_consistency.py \
  --context development \
  --source-ref "$(git symbolic-ref -q HEAD || echo detached)" \
  --source-commit "$(git rev-parse HEAD)" \
  --output version-consistency.json \
  --markdown version-consistency.md \
  --strict
```

A passing version report proves identity consistency only. It does not prove functionality, security, package correctness, fabrication readiness, or release quality.
