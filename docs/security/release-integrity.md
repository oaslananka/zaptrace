# Release Integrity

ZapTrace release integrity relies on GitHub Releases, workflow logs, SBOM generation, and artifact attestations.

## What to verify

For an official release, verify:

1. The release tag matches the package version.
2. The release was created by the repository release workflow.
3. Release assets are associated with the release tag.
4. SBOM/provenance or attestation artifacts are present when the workflow produced them.
5. The changelog describes user-visible and security-relevant changes.

## Verify with GitHub CLI

```bash
gh release view v0.3.0 --repo oaslananka/zaptrace
gh release download v0.3.0 --repo oaslananka/zaptrace --dir /tmp/zaptrace-release
```

## Verify artifact attestation

When GitHub artifact attestations are available, use GitHub's attestation verification tooling for the release assets. The expected repository identity is:

```text
oaslananka/zaptrace
```

The expected workflow is the repository release workflow under `.github/workflows/release.yml`.

## Hashes and checksums

Recent release automation generates a `SHA256SUMS` manifest for release artifacts. Compare local artifact hashes against that manifest using `sha256sum --check SHA256SUMS`. If an older release does not include a checksum manifest, rely on GitHub release transport security plus available attestations/SBOM and prefer upgrading to a release with checksum evidence.

## Registry publishing identity

The Python registry distribution name is `zaptrace-eda`; the installed import package and command names remain `zaptrace`. TestPyPI and PyPI authentication uses GitHub OIDC Trusted Publishing from `.github/workflows/release.yml` with environment-bound identities (`testpypi` and `pypi`), not stored registry API tokens. Tagged releases stage the exact CI-built artifacts on TestPyPI, verify registry filenames and SHA-256 digests plus a clean registry install, then publish and verify the same artifact set on PyPI before GitHub Release creation.

A manual workflow dispatch is limited to `main` and the TestPyPI staging environment; it does not publish to production PyPI or create a GitHub Release.

## Non-claims

Release integrity verifies artifact origin and tamper evidence. It does not prove that generated hardware is safe, manufacturable, compliant, or correct.

## Detailed verification guide

For commands and expected identities, see [Release Verification Guide](release-verification.md).

## Version and tag identity

The active package/runtime/Rust line and future tag policy are defined in [Version Policy](../development/version-policy.md). A future release tag must be an annotated `v<package-version>` tag and resolve to the exact checked-out release commit. The historical `v0.3.0` lightweight tag is grandfathered evidence, not the model for future releases. Cryptographic tag verification is not currently enforced because no reviewed maintainer trust root is committed; release reports must not claim a verified signature.
