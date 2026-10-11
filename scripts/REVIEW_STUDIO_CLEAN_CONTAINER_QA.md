# Clean Ubuntu 24.04 disposable container acceptance — Review Studio 0.1.1

In a fresh Ubuntu 24.04.1 container with **no** KiCad or Review Studio installed,
KiCad's signed release-10 Ubuntu Noble APT repository was configured. APT
completed `apt update` and installed the exact `zaptrace-review-studio_0.1.1_all.deb`
plus the KiCad 10.0.7 native dependency chain (`update=0 install=0`).

The installed program passed `zaptrace-review-studio --doctor`, then a real
`.kicad_pcb` plus hierarchical two-page `.kicad_sch` analysis generated native
KiCad DRC/ERC reports, validated its source PCB SHA-256 and continued to show
**NOT FABRICATION APPROVED**. The installed `zaptrace-review-studio
--no-browser` started an isolated localhost session, initialized an empty
private user workspace and shut down with the authenticated Stop endpoint.

The same disposable container then performed **real** `apt-get remove
zaptrace-review-studio`, and verified that application files disappeared while
independent KiCad and user review/source data remained available. The ephemeral
test container was subsequently removed; host packages were unchanged.

The independent proof record is
`build/distribution/CLEAN_UBUNTU_2404_CONTAINER_QA.txt`, which binds its
conclusions to the *tested package SHA-256*. To emit a release manifest that
includes this QA evidence without modifying the tested package, run:

```sh
/usr/bin/python3 scripts/review_studio_release_manifest.py \
  --gate-log /tmp/zaptrace-011-publish-ready-final-gate.log \
  --container-qa-log build/distribution/CLEAN_UBUNTU_2404_CONTAINER_QA.txt
```

This is a clean **container** test, not acceptance on another physical machine.
The package remains unsigned; SHA-256 does not establish publisher identity.
A broader external customer acceptance test and original project approval are
separate before making a public General Availability claim.

## Ubuntu 24.04 clean-container upgrade evidence for 0.1.2

A separate fresh Ubuntu 24.04.1 Docker container installed the **0.1.1**
local Review Studio package plus KiCad **10.0.7** with real APT resolution.
KiCad generated native ERC/DRC from a source-verified PCB and a two-sheet
hierarchical schematic, registered as a user review. The manifest, ERC report,
DRC report and `evidence.json` SHA-256 values were recorded. The same
container then performed **real `apt-get install` upgrade to 0.1.2**, after
which those four original SHA-256 digests matched exactly.

The upgraded 0.1.2 application then restored a legacy 0.1.1 private ZIP (which
contains obsolete KiCad `.kicad_prl` session data). The application ignored
archive HTML/evidence and the obsolete `.kicad_prl`, validated the source PCB
SHA-256, and reran native KiCad 10 ERC/DRC to produce a second two-sheet
review. Both independent evidence sets and the original project/source files
survived `apt remove` of 0.1.2. The entire container was disposable and must
be removed after tests.

See `build/distribution/CLEAN_UBUNTU_2404_012_QA.txt` for the evidence record
bound to the exact 0.1.2 package SHA256. This is a **real APT container test**,
not human acceptance on a separately administered physical device, and not a
publisher signature or manufacturing approval.

## Publisher-signature pipeline (not yet publicly signed)

The opt-in signing helper (`scripts/review_studio_sign_release.py`) verifies
the exact GPG signer fingerprint, signed `.deb`, release-manifest signature and
public key export. QA uses only an ephemeral throwaway key confined to its
temporary GNUPG home. No actual publisher key is selected automatically, and
none of the QA signatures constitute trusted publisher identity.

## Authenticated publisher signatures (optional, publisher-controlled)

The local `.deb` is **not** publicly publisher-signed. When a real publisher
identity and existing trusted private signing key are authorized, produce
**detached, armored GPG signatures** over both the exact `.deb` and final
`RELEASE_MANIFEST.json` using this opt-in workflow:

```sh
/usr/bin/python3 scripts/review_studio_sign_release.py \
  --package build/distribution/zaptrace-review-studio_0.1.2_all.deb \
  --manifest build/distribution/RELEASE_MANIFEST.json \
  --fingerprint FULL_TRUSTED_UPPERCASE_GPG_FINGERPRINT
```

The command **does not generate, select or invent** a publisher signing key,
refuses missing/incorrect keys, checks the exact package SHA-256 against the
release manifest and verifies each generated detached signature using the
**full specified fingerprint** before emitting the signatures and public key.
The publisher must communicate their trusted key fingerprint through an
independent established channel. A newly generated test key or self-signature
alone does not establish real publisher identity or GA approval. Never copy a
private key into the release artifacts, and do not sign older evidence for a
new package hash. Do not publish anything before independent key ownership,
license rights and user acceptance are established.


## Release manifest with actual 0.1.2 clean Ubuntu QA evidence

After running the nine-stage local gate, add the separately kept exact-package
container verification record without modifying the already APT-tested package:

```sh
/usr/bin/python3 scripts/review_studio_release_manifest.py \
  --gate-log build/distribution/RELEASE_GATE.log \
  --container-qa-log build/distribution/CLEAN_UBUNTU_2404_012_QA.txt
```
