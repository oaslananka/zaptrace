# ZapTrace Review Studio 0.1.8 — Ubuntu 24.04 / KiCad 10 edition

A locally installed KiCad PCB and schematic engineering *review* workspace.
This product is **not** a PCB autorouter, fabrication approval, manufacturing
DFM sign-off, a CAD editor, or a safety certification.

## Install

Preconditions: Ubuntu 24.04 LTS, KiCad **10.x** with its system `pcbnew` Python
binding, `/usr/bin/python3` 3.12+, and `xdg-open`. Dependencies are declared
in the Debian package. Obtain KiCad 10 from a trusted packaging source compatible
with Ubuntu 24.04 before installing. Do not weaken native DRC to bypass errors.

```sh
sudo apt install ./zaptrace-review-studio_0.1.8_all.deb
zaptrace-review-studio --doctor
zaptrace-review-studio
```

You may also open **ZapTrace Review Studio** from your desktop's app menu.
The menu entry does not require a terminal. If the browser cannot be opened,
run `zaptrace-review-studio --no-browser` in a terminal to read the local URL.

## PCB, schematic and genuine KiCad 3D inspection

The installed read-only engineering workspace contains a PCB copper/layers
viewer, actual multi-sheet Eeschema SVG preview with source-rendered sheet
thumbnails and safe cross-probing, and a third **3D** inspection mode with
**KiCad 10 native isometric and top PNG renders** of the selected real PCB,
plus **eight 45-degree native camera images** for source-bounded drag-to-orbit
and keyboard-focusable turn controls. This is a finite eight-view turntable,
NOT a continuously rendered editable 3D CAD model.
This is an offscreen/local 3D model *preview*, not an interactive MCAD editor.
The renderer uses only `.step` and `.wrl` geometry available in the user's
installed KiCad libraries. **Missing models are not synthesized**, completeness
and mechanical fit are not verified, and 3D rendering does not authorize DRC,
DFM, assembly, fabrication, routing or enclosure fit. If graphics support is
absent, 3D remains disabled without blocking PCB/ERC/DRC review. For a headless
machine, optional `xvfb` and `xauth` with a software OpenGL driver may allow
KiCad CLI rendering; desktop systems can use their existing graphical display.

The viewer offers native PCB inspection, not geometry-authoring CAD. The native
ERC/DRC findings and NOT FABRICATION APPROVED warning remain visible even in
3D mode. The 3D images are local engineering data and stay private.

## Native PCB footprint placement — controlled copy-on-write ECO

Use **Draft a PCB move** in the authenticated local workspace. Select a native
`.kicad_pcb`, one existing **unrouted** footprint reference, and grid-snapped
X/Y movement within ±5 mm (0.05 mm increments). Installed KiCad 10 writes a
separate working-copy PCB, checks tracks, all footprint and pad identities,
net assignments, orientations, positions and original copper, and compares
genuine before/after DRC report violation object IDs. Any *new* rule violation,
increased unconnected count, locked footprint, filled copper zone or existing
pad-attached track **blocks the change**. The user sees two real KiCad SVG
copper/silkscreen drawings with synchronized zoom/pan; the new board is
separately downloaded or explicitly discarded.

This is NOT a route/drag-router, footprint library manager, electrical-design
approval or manufacturing signoff. No original KiCad source is overwritten.

## Experimental native schematic value editing — controlled ECO

The source-protected local workspace now includes an opt-in **Draft a schematic
ECO** action. It accepts a single-sheet, one-unit original `.kicad_sch` via
local file picker and edits only an existing component's `Value` in a **separate
working copy**. KiCad 10 verifies the component inventory, all electrical net
memberships, component metadata and native ERC before the edited copy can be
downloaded. A modern before/after KiCad SVG preview opens in a sandboxed,
opaque-origin iframe; it supports linked zoom/pan. The output draft is stored
privately until explicitly discarded. Original PCB, schematic and BOM are
never overwritten. OAuth, cloud accounts and internet upload are not involved.

This is **not** general schematic layout editing, PCB routing, complete
hierarchical ECO, electrical performance validation or component sourcing.
Changing a resistance/capacitance/value can be unsafe even when ERC does not
change. No automatic PCB/BOM synchronization or fabrication approval is made.
Only the experimental subset of safe native component value strings is
accepted; unsupported projects fail closed. Source copies stay private on
localhost and protected by origin + an ephemeral session token.

## First use and privacy

The first launch starts an **empty** projects collection in
`~/.local/share/zaptrace-review-studio/workspace` (or the user's XDG data home).
No synthetic engineering fixture is registered or included. Pick a real
`.kicad_pcb` in the Add a KiCad board panel. Supply the matching `.kicad_pro`,
`.kicad_sch`, and custom `.kicad_dru` and hierarchy folder when relevant.
Native KiCad supplies the DRC/ERC truth and read-only SVG plots. A snapshot
comparison is evidence only, not a production approval.

A randomly chosen `127.0.0.1` port is used; there is no cloud connection or
account. The user-selected files are copied to the private per-user workspace
before analysis, and the input originals are never overwritten. If you need
those local copies erased, delete the relevant workspace project **after
backing up any reviews you want to retain**. The app never wipes data on
upgrade or normal uninstall. Imported board contents should be treated as
personal/confidential engineering data.

When the app is already running, launching it again reopens the same local
session instead of starting a competing local server. Use **Stop local Review
Studio** at the bottom of the browser UI to close the server cleanly. A running
KiCad analysis must finish before stopping. Browser close on its own does not
stop the service; the explicit Stop control does.

## Private backup and review-data deletion

After opening a real KiCad project, the **Export private ZIP backup** control
is available on reviews imported by the installed application. The backup
contains the review evidence, plot/report files and **copies** of the KiCad
PCB/schematic/project inputs selected during import. Protect this archive as
confidential engineering data; never share it inadvertently or assume an
approved fab state. Export can be done before removing an old review.

**Delete local review…** is intentionally destructive and requires typing
`DELETE` in a confirmation dialog. Only a review created by a native local
GUI import can be deleted in this way. The application checks the source SHA,
review registration and the UUID-owned workspace directories. It refuses to
delete externally registered reviews, user source files outside the app or
any symlink-redirected directories. Local staged copies and the matching
review directory are removed. This action is not reversible without a backup.
An active native KiCad analysis blocks export/deletion until it completes.

The package uninstaller never silently deletes the user's review collection;
manual cleanup of the user data directory is possible if you explicitly want
to remove all remaining application data.

## Restore saved Review Studio backups on a new installation

Use **Restore a Review Studio ZIP** in the installed localhost application.
Choose a new review name and the private ZIP created earlier by **Export
private ZIP backup**. The restore process does **not** execute, display, or
trust the previous machine's HTML, SVG, DRC/ ERC reports, scripts, or design
approval. It validates the source PCB against the SHA-256 recorded in the ZIP,
rejects unsafe paths, oversized content and symlinks, and stages only the
selected native `.kicad_pcb`, `.kicad_sch`, `.kicad_pro` and `.kicad_dru`
files. The *installed local KiCad 10* reruns native geometry generation, ERC
and DRC and creates a new review snapshot; previous rule findings and
manufacturing-readiness claims do not carry over.

An existing project name cannot be overwritten by restoring a backup. Missing
hierarchical sheets, invalid archives, dangerous filenames and failed native
KiCad checks are rejected; the existing library and ZIP remain unchanged.
This ZIP import is a local restore of native evidence, **not** full application
settings migration or a way to bypass design rule checks.

## Diagnostics, uninstall and updates

```sh
zaptrace-review-studio --doctor
sudo apt remove zaptrace-review-studio
```

Removing the package does **not** remove
`~/.local/share/zaptrace-review-studio/workspace` or installed KiCad.
To remove all your Review Studio data later, use your file manager after you
have backed it up. Do not remove app data during system package removal.
Upgrade with `sudo apt install ./new-package.deb`; review files remain in user
space. Do not mix KiCad versions for the same approval decision: re-run native
DRC after changing KiCad, library tables or project-specific rules.

## Supported and unsupported environments

Validated target: **Ubuntu 24.04 LTS on amd64, system KiCad 10.0.7 and
Python 3.12**. Ubuntu's `/usr/bin/python3` is required by `pcbnew`; a Python
virtual environment cannot replace it. Other OS versions, CPU architectures,
KiCad 9/11, Windows and macOS are not qualified by this package. For each new
platform, run independent end-to-end installation and real-board tests before
claiming support.

**License: PolyForm Noncommercial 1.0.0.** See the installed full terms at
`/usr/share/doc/zaptrace-review-studio/copyright`. Do not assume commercial
usage or redistribution rights beyond that license. This package includes no
user PCB, source project, Gerber, private evidence, or development checkout.

## Build and check locally

```sh
/usr/bin/python3 scripts/review_studio_build_deb.py
sha256sum -c build/distribution/zaptrace-review-studio_0.1.8_all.sha256
sudo apt install ./build/distribution/zaptrace-review-studio_0.1.8_all.deb
```

For an **unsigned local release evidence report**, run the full gate and then
record the exact installed package file inventory, hashes and unsupported GA
claims as a machine-readable JSON manifest:

```sh
bash scripts/review_studio_release_gate.sh | tee build/distribution/RELEASE_GATE.log
/usr/bin/python3 scripts/review_studio_release_manifest.py \
  --gate-log build/distribution/RELEASE_GATE.log
```

This creates `build/distribution/RELEASE_MANIFEST.json`. It lists the exact
SHA-256 and byte size for every bundled file, the PolyForm license, target
architecture/dependencies, passed **local** validations, and remaining
conditions for public distribution (independent fresh Ubuntu APT install,
package signing and external end-user acceptance). Neither a checksum nor
this manifest is a publisher signature or external audit certification.

The build requires `dpkg-deb` and `desktop-file-validate` but **not root**.
The builder excludes caches, developer tests, compiled bytecode, synthetic
board fixtures, Git metadata and staged source PCB/schematics. Archive contents
and the exact SHA256 should be audited before external distribution. No code
signing, public update feed, or external consumer acceptance has been completed
by this local build.
