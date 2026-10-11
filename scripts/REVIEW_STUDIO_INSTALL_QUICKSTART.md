# ZapTrace Review Studio 0.1.2 — Ubuntu installation and acceptance kit

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
   sha256sum -c zaptrace-review-studio_0.1.2_all.sha256
   ```

3. Install in a terminal in the folder containing the `.deb`:

   ```sh
   sudo apt install ./zaptrace-review-studio_0.1.2_all.deb
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
- `CLEAN_UBUNTU_2404_012_QA.txt` records **real Ubuntu 24.04 APT installation
  of 0.1.1 and in-place upgrade to 0.1.2**, native two-sheet KiCad ERC/DRC,
  successful restore of an older ZIP, and `apt remove` preserving review data.
- `zaptrace-review-studio_0.1.2_all.sha256` checks the exact `.deb` bytes.

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
