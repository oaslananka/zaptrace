# Release Verification Guide

Use this guide to verify the integrity and expected origin of ZapTrace release artifacts.

## Expected identity

Official source repository:

```text
https://github.com/oaslananka/zaptrace
```

Expected release workflow:

```text
.github/workflows/release.yml
```

Release tags use SemVer-style identifiers such as:

```text
v0.3.0
```

The [distribution support matrix](../installation/distribution-support.md) identifies which wheel, source-distribution, and container combinations are supported, best-effort, or unsupported.

## Download release assets

```bash
gh release view v0.3.0 --repo oaslananka/zaptrace
gh release download v0.3.0 --repo oaslananka/zaptrace --dir /tmp/zaptrace-release
```

## Verify evidence identity

Tagged releases include `tagged-release-evidence.json`. Inspect it before trusting the remaining assets:

```bash
jq '.evidence_identity | {mode, package_version, source_commit, source_ref, dirty, lock_sha256, source_inputs_sha256, toolchain, identity_sha256}' \
  /tmp/zaptrace-release/tagged-release-evidence.json
```

Expected properties:

- `mode` is `release`;
- `source_ref` is `refs/tags/v<package_version>`;
- `source_commit` is the full commit referenced by the tag;
- `dirty` is `false`, unless an explicit `dirty_override_id` is present and approved;
- lock, source-input, and identity hashes are 64-character SHA-256 values;
- relevant Python/Rust tool versions are recorded.

Branch and pull-request artifacts use `snapshot` mode and must not be treated as tagged release evidence.


## Verify clean-install distribution evidence

For each package artifact claimed as supported, inspect the matching `distribution-smoke-*.json` report. The report must bind the artifact SHA-256 to the release source commit and `uv.lock`, show an installed path outside the source tree, and record passing CLI, SDK, native-extension, REST API, and MCP HTTP checks.

The source distribution report is named `distribution-smoke-sdist-linux-x86_64-cp313.json`. Native reports use `distribution-smoke-<target-id>.json`. These reports are included before SBOM and checksum generation; a missing report blocks release creation.

Compare the report's target with the [public support policy](../installation/distribution-support.md). A local build on an unsupported target does not convert it into a supported project artifact.

## Verify checksum manifest

Recent releases are expected to include `SHA256SUMS` when release automation produced distribution artifacts.

```bash
cd /tmp/zaptrace-release
sha256sum --check SHA256SUMS
```

Expected result: every listed artifact reports `OK`.

## Verify GitHub artifact attestation

When GitHub artifact attestations are present, verify each downloaded artifact against the repository identity:

```bash
gh attestation verify ./artifact-name --repo oaslananka/zaptrace
```

Expected result: the attestation verifies successfully and identifies the repository as `oaslananka/zaptrace`.

## Verify release tag and changelog

```bash
git clone https://github.com/oaslananka/zaptrace.git
cd zaptrace
git fetch --tags
git tag --list 'v*'
git show --stat v0.3.0
```

Then compare the release version with `pyproject.toml`, `zaptrace_core/Cargo.toml`, and `CHANGELOG.md`.

## What this does not prove

Release verification confirms artifact integrity and origin evidence. It does not prove that generated circuit boards are safe, manufacturable, compliant, production-ready, or correct without human engineering review.
