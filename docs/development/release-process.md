# Release Process

ZapTrace uses PEP 440 package versions, Cargo-compatible SemVer mappings, and `v<package-version>` release tags. The active development identity and synchronization rules are defined in [Version Policy](version-policy.md).

## Release checklist

1. Create a repository-owned branch named exactly `release/v<version>`, update `CHANGELOG.md` with a human-readable summary, and move the target release out of `[Unreleased]`.
2. Change `pyproject.toml` to the intended RC/final version and synchronize the Cargo/lockfile forms.
3. Run the strict `release-preparation` version-consistency check plus the required Quality and Security workflows on the release PR. Ordinary pull requests continue to use the stricter development-only context.
4. Confirm direct Rust tests, pinned Cargo advisory evidence, installed-wheel native boundary evidence, and all [distribution clean-install evidence](../installation/distribution-support.md) are green.
5. Squash-merge the fully green release PR, then create an annotated `v<package-version>` tag pointing to the resulting exact `main` commit. The merge push may use the same bounded `release-preparation` context for that final identity; the tagged-release workflow then re-runs release identity and artifact gates on the commit. Scheduled/manual main validation remains development-only until the mandatory post-release bump. Cryptographic signing is optional until a reviewed trust-root policy is configured.
6. Push the `v*` tag to trigger `.github/workflows/release.yml`.
7. Verify version evidence, release artifacts, SBOM, checksums, provenance/attestation, Cargo advisory, and per-target native boundary steps complete.
8. Review generated GitHub release notes before public announcement.
9. Open and merge the post-release development bump to the next patch `.dev0` line before unrelated development continues.

## Post-release development bump

The post-release development bump is mandatory. After publishing or candidate abort, `main` advances to Python `0.3.6.dev0` and Cargo `0.3.6-dev.0`; it must not continue presenting the final `0.3.5` identity. The Quality workflow rejects a final version on the development branch and rejects a development line whose corresponding final tag already exists.

Future release tags must be annotated and resolve to the exact checked-out commit. The historical `v0.3.0` lightweight tag is grandfathered and remains historical evidence only. Cryptographic tag verification is not currently required; reports state this explicitly and do not claim a verified signature.

## Evidence modes

Release-critical reports use one shared identity schema.

- `snapshot` evidence is produced for pull requests, branch pushes, schedules, and local validation. It records the exact commit/ref, dirty state, package version, lock hash, source-input hash, generation time, and toolchain, but cannot be represented as a tagged release.
- `release` evidence is accepted only for `refs/tags/v<package-version>`. A dirty tree is rejected unless a non-empty policy override identifier is recorded in the evidence.
- The deterministic identity hash includes all identity fields except `generated_at`, so repeated generation times do not change the identity while source, lock, ref, mode, or toolchain changes do.

The Quality workflow uploads `snapshot-gate-summary.json`. The tag workflow uploads `tagged-release-evidence.json` and includes it in the GitHub Release assets and checksum manifest.

## Native-wheel verification

Each supported Rust wheel target has a fail-closed sequence:

1. build the target wheel;
2. create a clean target-compatible virtual environment;
3. install the exact `dist/*.whl` artifact;
4. run `scripts/ci_native_boundary.py` with `ZAPTRACE_REQUIRE_NATIVE=1`;
5. upload `native-boundary-<target>.json` and Markdown evidence;
6. upload the wheel only after verification succeeds.

The verifier rejects dirty source and source-tree extensions while a wheel is being claimed, records the wheel SHA-256 and actual extension path, and checks deterministic valid calls, controlled invalid-input exceptions, pre-extraction resource limits, extreme-finite overflow rejection, and same-process survival. See [Native Rust and PyO3 Boundary](../security/native-extension-boundary.md).

## Release workflow

The release workflow:

- checks that the tag matches the package version;
- creates identity-bound tagged release evidence and rejects dirty or mismatched source context;
- runs Python and Rust quality gates;
- requires direct Rust tests and installed-wheel PyO3 boundary evidence;
- builds the supported source distribution and native-wheel targets from the [distribution support matrix](../installation/distribution-support.md);
- clean-installs each claimed artifact and exercises CLI, SDK, REST API, MCP HTTP, and native-extension expectations;
- downloads every `distribution-smoke-*` report before release aggregation;
- generates an SPDX SBOM;
- attests release artifacts;
- creates a GitHub Release.

The Security workflow also publishes raw and normalized Cargo advisory evidence using a pinned `cargo-audit` version. A clean advisory report is evidence about the exact lockfile, not proof that the native extension is vulnerability-free.

## Publishing policy

The Python registry distribution is `zaptrace-eda`; the import package and CLI remain `zaptrace`. TestPyPI and PyPI publishing use GitHub OIDC Trusted Publishing from this workflow with the `testpypi` and `pypi` environments, so no long-lived registry token is stored. A manual dispatch on `main` is TestPyPI-only staging. Tagged releases must stage the exact built artifacts on TestPyPI, verify registry filenames/SHA-256 values and a clean install, publish the same artifacts to PyPI, repeat registry verification, and only then create the GitHub Release. GHCR publication remains disabled until its registry ownership and support policy are completed; see the [distribution support matrix](../installation/distribution-support.md).

### Registry rollback and yanking

Registry files are immutable release evidence and are never overwritten in place. If TestPyPI staging reveals a bad artifact, hash mismatch, or clean-install failure, do not promote it: keep the failed workflow evidence, correct the source, advance the package version, and stage a new version. A successful staging exercise may be yanked from the TestPyPI project release-management page when exercising rollback; record the yank reason and confirm normal unpinned resolution no longer selects that release before treating the exercise as complete.

For a production PyPI defect, prefer a **yank** over deletion so pinned users retain an auditable recovery path. Yank the entire affected release from the `zaptrace-eda` project release-management page, record the reason, leave the Git tag and existing evidence unchanged, and publish a new patch release through the normal TestPyPI → PyPI verification chain. Deletion is reserved for exceptional cases where policy or legal/security requirements demand removal; never reuse a deleted version number or retag a different commit. A registry rollback does not rewrite or silently replace an existing GitHub Release.

## Non-claims

A release does not certify that generated boards are fabrication-ready, manufacturer-approved, production-ready, formally verified, or safe without human review. Successful Rust/PyO3 tests do not establish immunity from denial-of-service or platform-specific native defects.

## Debug symbols

Native debug symbols and linker outputs are never tracked in the source tree and
are never included in wheels or source distributions. When a release needs
debugging support, maintainers produce symbols from the same reviewed release
build, bind them to the release commit and binary checksums, and upload them as a
separate release artifact with restricted retention or access appropriate to the
incident. Publishing symbols does not change or replace the verified package
artifacts.

## Container security gate

Before a GitHub Release is created, the release workflow builds the exact
Docker image for the tag and calls the reusable Container Security gate. The
release is blocked by Critical findings immediately and by unexcepted High
findings after the documented baseline date. The retained evidence includes the image digest, CycloneDX SBOM, Trivy
JSON/SARIF, policy summary, dependency-lock consistency report, embedded build
provenance, and exact-image provenance verification. The provenance binds the
release source commit, pinned base digest, locally built wheel digest, and
committed Python/Alpine dependency-manifest digests; see
`docs/security/container-vulnerability-management.md`.
