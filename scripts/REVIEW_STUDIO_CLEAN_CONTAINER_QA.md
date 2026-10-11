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

## 0.1.4 — end-to-end native KiCad 3D acceptance (local, unsigned)

The **exact** local 0.1.4 package SHA-256 is
`dc1a93cd2f4c6f0fb647ac0d857fb70462060c68ea74b6f982d3da3a2dabd025`.
The offline kit SHA-256 is
`33afdb05df4ceae36d5adddc9e9c7ea25b1f81f9eaf67506ffa30b6c6764aaea`.
Those two checksums are independent; do not reuse this acceptance report for a
changed `.deb`. The local artifact receipt is
`build/distribution/CLEAN_UBUNTU_2404_014_QA.txt`, with the SHA-bound
`RELEASE_MANIFEST.json` and `zaptrace-review-studio_0.1.4_ubuntu24.04-local-RC.zip`.

In the disposable Ubuntu 24.04 / KiCad 10.0.7 environment, actual system APT
reinstalled legacy **0.1.1** and upgraded to the exact **0.1.4**. Hashes of
all previously saved ERC, DRC, evidence and project-manifest files were
checked byte-for-byte. Local headless `xvfb`/`xauth` was installed explicitly
for native OpenGL; its availability is **optional**, and the application
shows an unavailable 3D state when not configured.

The installed 0.1.4 generated **two authentic KiCad 10 camera PNG renders**
(isometric, top) and two native Eeschema hierarchy page previews without
editing the source PCB. Its source PCB SHA was verified. After discovering
that the first 0.1.4 candidate enabled 3D for the direct CLI but **not** for
native project imports, the `review_studio_workspace.py add` flow was fixed.
The corrected package was rebuilt, all tests rerun and a new SHA generated;
**only the corrected package** passed the final local release manifest gate.

The final corrected package restored a legacy 0.1.1 backup via the actual
localhost import endpoint. The restored review regenerated KiCad ERC, DRC,
two genuine schematic SVG sheets and both 3D images. Real Chromium desktop
and 390px-mobile inspection of **that restored review's HTML** tested the
camera switch, schematic sheet navigation, source-linked placeholders and
fabrication warnings. A true `apt remove` afterward preserved four user
review directories and their native ERC/DRC, the backup ZIP and original
sources; the installed app executables were removed. The disposable Ubuntu
container was then removed.

**Important:** The 3D view is a real KiCad-rendered *image*, not full
interactive 3D CAD. Component 3D model availability/completeness, enclosure
fit, mechanical clearance and fabrication signoff are NOT verified. Native
DRC counts change with supplied project/rule context: a deliberately
incomplete context reported 30 rule findings where the separate fully
scoped Issue #91 design review had reported 16. Chrome tests check the
actual native DRC source data rather than assuming either context is
interchangeable. The package is still unsigned, not public GA, and has not
passed independent physical-device or unassisted external-user acceptance.

## Ubuntu clean-install / real 3D orbit acceptance for 0.1.5

Exact package SHA-256:
`138acff992665ed8168584ab2c8f6dfb61491cfd93c69c66c8b97304b09aaae1`.
Exact local QA kit SHA-256:
`5292a2ce6a600c13c0f2773a5279978ca97836c567afefc9c63258dda3e15d1a`.

A separately created clean Ubuntu 24.04.1 LTS disposable Docker container
started without KiCad or Review Studio. Actual APT installed KiCad 10.0.7,
`xvfb`/`xauth`, and legacy Review Studio 0.1.1. A native two-sheet KiCad
review with real DRC/ERC was generated and its original report hashes frozen.
Actual APT upgraded the very same environment to the SHA-pinned 0.1.5 `.deb`.
The pre-existing review/evidence SHA-256 values were unchanged.

The **installed 0.1.5** generated original Eeschema plots and **ten real KiCad
OpenGL PNG camera views**: two fixed angles plus eight 45-degree frames.
Chromium tested real pointer drag, camera angle indicator, source-bound PNG
selection, 390px mobile single-row camera controls, no horizontal overflow,
and return to source PCB with DRC unchanged. Through installed localhost
backup restoration, a legacy 0.1.1 ZIP was restored to a new separate project:
actual KiCad 10 ERC/DRC, two source sheets and all ten 3D camera images were
regenerated. A second real Chrome run tested the final recovered user's HTML.
Actual `apt remove` deleted app files but preserved both user reviews, native
ERC/DRC reports, backup ZIP and original PCB inputs; KiCad remained installed.

This is a finite source-backed camera turntable, **not** continuous 3D CAD,
not a proof of complete vendor models, not production approval. See
`REVIEW_STUDIO_FULL_EDA_ACCEPTANCE.md` for missing full-editor capabilities.
No signing identity, independent physical-machine acceptance or public GA
approval has been represented as passing.

## Ubuntu 24.04 real APT / native schematic ECO acceptance 0.1.6

The reproducible, unsigned local 0.1.6 package is SHA-256
`fd3f89e2c770b413d9fb94c92a003d6af460377695a014abb2d663bc683da983`.
The five-file offline installer/evidence kit is SHA-256
`bf40305b042039bd54b04c197d2cbe3731be096c468b7e1d3aed3293cf77f25e`.
These are different artifacts; acceptance **must not** transfer to other bytes.

New disposable Ubuntu 24.04.1 started with no KiCad/Review Studio installed;
APT update, KiCad 10.0.7, `xvfb` and legacy app 0.1.1 succeeded. The installed
0.1.1 generated an actual native two-sheet Eeschema/PCB review and its user
manifest and ERC/DRC report SHA-256 values were frozen. Real APT upgraded this
same environment to 0.1.6 using **the identical .deb** to the nine-stage
release-gate output. The pre-existing user review reports remained byte
identical. The installed localhost app accepted actual KiCad schematic ECO
`R1: 4.7k → 10k`; KiCad preserved component inventory and net connectivity,
native ERC was unchanged, two genuine KiCad SVGs were displayed and the private
edited `.kicad_sch` was downloaded. A verified discard deleted this isolated
draft without modifying the original schematic or project library. A separate
real Chromium test used **the package-extracted installed Python and HTML**, not
only the developer source, and passed end-to-end file selection, authenticated
ECO upload, iframe preview, source download, discard and 390px mobile.

Installed 0.1.6 localhost restored the old 0.1.1 private ZIP, regenerated real
native ERC/DRC, both schematic sheets, two fixed and eight true KiCad 3D orbit
frames. Its output was also tested in real Chrome for 3D drag controls and
hierarchical SVG navigation. Real `apt remove` left both review folders and
old reports, input KiCad sources and the private ZIP untouched. The disposable
container was removed. The separate system source checkout was never changed.

**Not equivalent to a full EDA product or a manufacturing signoff.**
Editing is a single safe Value property per one-unit, one-page KiCad schematic
copy. Electrical effects, BOM/PCB synchronization, complex hierarchy and
vendor part qualification require independent review. 3D vendor model coverage,
physical device user acceptance, authorized publisher signing, and public GA
have not been verified or asserted.
