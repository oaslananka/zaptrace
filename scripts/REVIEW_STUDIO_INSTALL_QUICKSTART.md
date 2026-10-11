# ZapTrace Review Studio 0.1.7 — Ubuntu installation and acceptance kit

**Distribution status: local release candidate, unsigned. NOT public GA.**

This kit contains a source-verified engineering design review application for
**Ubuntu 24.04 LTS (amd64) and native KiCad 10.x**. It is not a PCB autorouter,
engineering design approval or fab-signoff system. Current software use is
licensed under **PolyForm Noncommercial 1.0.0**; commercial rights are **not**
automatically granted.

## Installation

1. Install **KiCad 10.x** from the KiCad team's Ubuntu Noble release
   repository. Ubuntu 24.04's default repositories can supply KiCad 7.x,
   which **cannot** satisfy this application. Verify the Launchpad publisher
   and the repository signing key shown by `add-apt-repository` before consenting
   to add any third-party software source. On Ubuntu 24.04 the tested setup is:

   ```sh
   sudo apt update
   sudo apt install software-properties-common
   sudo add-apt-repository ppa:kicad/kicad-10.0-releases
   sudo apt update
   sudo apt install kicad
   kicad-cli version
   ```

   The final command must report **KiCad 10.x**. Do not disable APT signature
   checking or change the dependency requirement to make KiCad 7/11 appear
   compatible. These commands require user approval; Review Studio does not
   silently add external repositories or install system packages.
2. Verify this kit's `.deb` before installation:

   ```sh
   sha256sum -c zaptrace-review-studio_0.1.7_all.sha256
   ```

3. Install in a terminal in the folder containing the `.deb`:

   ```sh
   sudo apt install ./zaptrace-review-studio_0.1.7_all.deb
   zaptrace-review-studio --doctor
   ```

4. Open **ZapTrace Review Studio** from the Ubuntu application launcher.
   Or run `zaptrace-review-studio` to open its localhost interface in your
   default browser. If it cannot open a browser automatically, use
   `zaptrace-review-studio --no-browser` and copy the local URL.

5. Choose your **real** `.kicad_pcb`. Include original `.kicad_pro` design-rule
   settings, root `.kicad_sch` and its nested sheets, and `.kicad_dru` when
   present. The software always reports DRC/ERC and explicit missing evidence;
   it never approves fabrication.

## 3D board preview and feature limits

Click **3D** inside a native KiCad PCB review to see locally rendered KiCad 10
isometric and top views of the actual board, plus **eight 45-degree source-rendered camera views**.
Drag sideways on the 3D canvas or use the rotation buttons to turn the board
through these actual KiCad views; Shift+drag pans the image and pinch/wheel
zooms. This is an interactive **camera turntable**, not a freely editable 3D
CAD mesh. If the graphics context is absent,
the button is disabled; PCB/Sch/ERC/DRC reviews still work. The 3D image is
read-only, and some components may not have an installed STEP/WRL model.
**3D model completeness, enclosure/assembly fit and fabrication approval are
not verified.** The 3D preview is not an interactive 3D CAD editor.

## Controlled PCB footprint placement draft

Select **Draft a PCB move**, a real `.kicad_pcb`, one unrouted footprint such as
`R1`, and an X/Y offset in millimeters. KiCad 10 checks both boards' copper,
pads/nets and DRC before allowing download of a **separate native `.kicad_pcb`
working copy**. The native before/after PCB preview is source-linked. Routed
footprints, copper zones, locked components, and any new design-rule findings
are blocked. **Discard** erases the local draft and never overwrites the
original PCB. Electrical function, live drag-routing, BOM/EDA synchronization
and manufacturing acceptance are not guaranteed or supported here.

## Experimental component-value ECO authoring

Inside the **local Review Studio workspace**, choose **Draft a schematic ECO**,
select the original single-sheet `.kicad_sch`, enter a real component reference
(e.g. `R1`) and a new value (e.g. `10k`). The app performs native KiCad netlist
and ERC checks and opens two real KiCad before/after drawings. Download only the
new **separate working-copy `.kicad_sch`** after reviewing the evidence. The
original file, PCB design and BOM are NOT modified or synchronized. Choose
**Discard local ECO draft** to erase the copy from the local workspace.
Do not treat this as general hierarchical editing, engineering suitability,
new ERC certification or manufacturing approval.

## Backup, restore and deletion

Use **Export private ZIP backup** on an imported project. It contains your
copied KiCad source PCB, matching schematic/project files and native review
reports, and therefore can expose confidential circuit data. Keep it private.

Use **Restore a Review Studio ZIP** to move an exported project to a new
installation. Review Studio checks the backed-up PCB SHA-256, ignores archived
HTML and old ERC/DRC outputs, and **reruns native KiCad** for the new snapshot.
It never silently overwrites an existing project name. Older 0.1.1 archives
including KiCad's temporary `.kicad_prl` are supported without trusting or
restoring that temporary file.

**Delete local review…** requires typing `DELETE` and only removes Review
Studio-owned copies. Original files outside Review Studio stay unchanged.
`sudo apt remove zaptrace-review-studio` removes the app but **does not erase
user projects**. Those are normally at:

`~/.local/share/zaptrace-review-studio/workspace`

## Evidence and real installer QA

- `RELEASE_MANIFEST.json` names the exact package SHA-256, its bundled files,
  real local release-gate status and any *unverified* launch requirements.
- `CLEAN_UBUNTU_2404_017_QA.txt` records **real Ubuntu 24.04 APT installation
  of 0.1.1 and in-place upgrade to 0.1.7**, native two-sheet KiCad ERC/DRC,
  authentic offscreen KiCad 3D isometric/top renders,
  successful restore of an older ZIP, and `apt remove` preserving review data.
- `zaptrace-review-studio_0.1.7_all.sha256` checks the exact `.deb` bytes.

**Unsigned:** A SHA-256 match is an integrity check, **not** a publisher
signature. `PUBLISHER_PUBLIC_KEY.asc` and verified detached signatures are
absent until a real publisher explicitly authorizes the existing full GPG
fingerprint and signs this exact package. No throwaway QA key is included.

**Still not tested:** an independent physical Ubuntu machine controlled by a
third-party evaluator, unassisted end-user acceptance, Windows/macOS native
installation, publisher trust, and commercial distribution license rights.
These checks are necessary before claiming a public General Availability
release. Unsupported KiCad 11 and older KiCad versions cannot be silently
accepted by this package.
