# Review Studio · native copy-on-write schematic value ECO (engineering prototype)

**Status: included in the separately validated, unsigned 0.1.6 local Ubuntu
release candidate. The previously validated 0.1.5 `.deb` remains unchanged.
This still does not make Review Studio a full-featured schematic editor.**

### Real interactive browser workflow

The localhost-only Review Studio library now has a clearly labeled **Draft a
schematic ECO** action. The user selects a local `.kicad_sch` in the browser,
chooses an exact existing reference and a new value. JavaScript uploads a
SHA-256-bound copy to an authenticated, origin-checked local API, which holds
one native KiCad process at a time. A real result opens the source-and-edited
SVG comparison inside a **sandboxed opaque-origin iframe**; source KiCad is
only offered as a separate attachment. The experimental draft remains in the
private local workspace until its explicit **Discard** action deletes it.
The original browser-selected file, PCB and BOM are never written.

An unauthorized request, forged source SHA, path traversal, unsafe value or
ambiguous KiCad reference is refused. Source upload staging is deleted even on
failure. Tested in actual localhost Chrome on desktop and 390px mobile with
real OS file selection and native ERC/netlist conversion, plus authenticated
HTTP operation and private file deletion tests.

The `scripts/review_studio_schematic_eco.py` tool is the first **actual
source-authored KiCad change** in the local EDA roadmap. It can change one
native component `Value` (for example `R1: 4.7k → 10k`) in a new editable
copy of a **single-sheet** `.kicad_sch`. The original file is never modified.
Multi-unit and hierarchical-sheet edits are blocked until native qualification
exists. Only a restricted set of non-quoted, non-control value characters is
accepted. Existing output folders may never be overwritten.

```sh
/usr/bin/python3 -B scripts/review_studio_schematic_eco.py \
  --schematic tests/fixtures/review_studio_native_eco_sensor.kicad_sch \
  --output build/eco-local-r1-10k-review \
  --ref R1 --value 10k
```

The generated `PREVIEW.html` is a responsive, offline, side-by-side presentation
of *two genuine KiCad-generated schematic SVG plots*. It has synchronized
zoom/pan, fit reset, exact old/new component value and SHA-256 evidence. The
same output directory contains the real edited `.kicad_sch`, original and
new KiCad XML netlists, native ERC reports and `ECO_EVIDENCE.json`.

**Native gating before the edited copy exists:** the tool checks all real
component references, compares full KiCad net memberships and all component
metadata other than the requested value. The only ignored netlist field is
KiCad's *generated* `Sheetfile` path, which changes solely because the tool
places source and edited schematic in separate scratch folders. It requires
unchanged native ERC findings/counts, renders both originals with `kicad-cli`,
and verifies the original source SHA once more before authoring the new
output directory. Unexpected graph changes and new ERC findings prevent
publication of any new output. Failure doesn't create a valid ECO directory.

**Critical limits:** A resistor/capacitor/IC value change can alter electrical
behavior without changing ERC or the graph. This does **not** approve power,
thermal, electrical performance or manufacturability. The PCB footprint
values, supplier BOM, vendor qualification and Git source remain unmodified.
`fabApproved:false`, `pcbSynchronized:false` are explicit. Human ECO approval,
real PCB/BOM synchronization, native undo/redo, hierarchical edits, inline GUI
authoring and safe atomic `.kicad_pro` round trips remain future milestones.

The real KiCad 10 example `R1 4.7k → 10k` produced identical connectivity and
**28 → 28 existing ERC findings**, 0 errors/28 warnings (these are pre-existing
warnings, not an ERC clean bill of health). Its original file SHA-256 stayed
unchanged; desktop and 390px-mobile real Chrome tests verified synced pan and
zoom. This is an engineering *draft*, not a fabrication or electronics approval.

## Exact installed-package Ubuntu and browser acceptance (0.1.6)

The 0.1.6 `.deb` was verified by the nine-stage release gate and 233 automated
Python tests, format/lint and type checks. Identical package bytes were
installed by real APT in a separate fresh Ubuntu 24.04.1/KiCad 10.0.7 test
container, upgrading 0.1.1. The original user review manifest/ERC/DRC report
SHA-256 values stayed unchanged. Installed 0.1.6 localhost native ECO edited
`R1 4.7k → 10k` in a separate private copy, detected identical native net
membership and ERC counts, supplied a separate `.kicad_sch` download, then
explicitly discarded the draft. The original `.kicad_sch` SHA was unchanged.

The **exact package-extracted** browser application separately passed real
Chromium file-picker, upload, authenticated result and sandboxed visual diff,
edit download, discard, mobile 390px and zero JavaScript error checks. The
installed application also restored a legacy ZIP and regenerated native ERC,
DRC, 2 schematic SVG sheets and 10 actual KiCad 3D views; true Chromium checked
that restored document. A real `apt remove` preserved both review folders and
original sources. The clean Docker test container was destroyed afterward.

- `build/distribution/zaptrace-review-studio_0.1.6_all.deb` SHA-256:
  `fd3f89e2c770b413d9fb94c92a003d6af460377695a014abb2d663bc683da983`
- `build/distribution/zaptrace-review-studio_0.1.6_ubuntu24.04-local-RC.zip` SHA-256:
  `bf40305b042039bd54b04c197d2cbe3731be096c468b7e1d3aed3293cf77f25e`
- Reports: `build/distribution/CLEAN_UBUNTU_2404_016_QA.txt` and
  `build/distribution/RELEASE_MANIFEST.json`

**Still not verified:** arbitrary schematic wiring and multi-sheet source
editing, complete PCB editing or synchronization, electrical value suitability,
full continuous 3D geometry, mechanical assembly, commercial release rights,
code-signing publisher identity, independent physical-machine acceptance and
PCB fabrication authorization. All remain blocked or require separate review.
