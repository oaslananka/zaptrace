# Review Studio post-0.1.11: transactional multinet and KiCad IPC/zone policy

**Status: source-only 0.1.12 engineering milestone. Not included in the
SHA-qualified 0.1.11 Debian package or offline kit. NOT fabrication approval.**

## Transaction and native evidence

The native KiCad 10.0.7 batch processor accepts **two or three** explicitly
selected, distinct physical pad UUID pairs on different nets. Each route is
the previously bounded F.Cu-only trace or manually specified 2-via
F.Cu to B.Cu to F.Cu corridor. No copper path, net or via is guessed.
Inputs remain SHA-locked and are never overwritten.

For each route the existing 0.1.11 single-route native verifier operates
on an isolated PCB copy and independently reopens the board, preserving
pad UUIDs, footprint/trace inventory, net identity and required DRC policy.
Each subsequent step MUST use the saved output board from the previous
step with an exact SHA-256 linkage. A failed intermediate KiCad DRC,
invalid duplicate pad/net or custom-rule loader drops **every intermediate
stage**; the common publish directory does not exist until all pass.

The combined proof checks native KiCad baseline-to-final result:
N requested routes MUST reduce native unconnected count by exactly N;
schematic parity stays zero; no new physical violation is introduced,
and KiCad version, included severity and ignored-check policy stay
unchanged. Its per-step evidence and final native DRC reports are bundled
alongside the final project working copy. The proof never claims full
routing, automatic engineering validity, or fab signoff.

Authenticated localhost /api/native-copper/batch accepts exact SHA-256
portable KiCad input ZIP plus 2 to 3 explicit routes. It rechecks the
working-copy SHA chain, segment layers/vias, net uniqueness and cumulative
DRC outside the native subprocess; it delivers one private, hash-verified
project ZIP with real native KiCad before/after SVG and evidence, and
supports explicit discard. The source-only browser now provides an
accessible per-net queue and a single transactional verification action.

### Actual generated KiCad ESP32 reference result

GND: R3 pad 2 to R4 pad 2 via F.Cu / two drilled through vias / B.Cu /
F.Cu, with vias at 72.51,58.8 and 77.51,58.8 millimetres.

VCC_3V3: U1 pad 2 to U1 pad 3, single F.Cu trace.

Real KiCad 10.0.7 unconnected count is **37 to 36 to 35**. Existing
physical DRC violations are **16 to 16 to 16**, no new DRC or schematic
parity finding. The final saved PCB reopens with the exact expected two
drilled vias, one B.Cu segment and three F.Cu segments. These 16 DRC
errors and 35 open connections are still production blockers.

## Fail-closed zone handling

Real KiCad zones are not immutable metadata. Changed traces can require
zone fill recomputation, change removed islands and alter connectivity.
SWIG pcbnew.ZONE_FILLER supports Fill(board.Zones()), but a successful
call alone cannot prove native net/DRC/island stability.

The bounded 0.1.12 algorithm explicitly **rejects any PCB with at
least one native zone**, even unfilled. A test builds a genuine zone on
a KiCad BOARD, serializes it and proves the transaction rejects it
without a published copy or an edited source. Evidence explicitly records
zone_refill_verified=false.

For future zone support, establish dual original/candidate saved native
KiCad fills, polygon/island counts, per-net connectivity, before/after
custom and default DRC, persisted zone metadata/UUIDs and no original
file mutation. Without these checks, zone refill must remain blocked.

Official sources:
https://docs.kicad.org/doxygen-python-9.0/classpcbnew_1_1ZONE__FILLER.html
https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html

## KiCad IPC API feasibility / migration gate

The official KiCad add-on API documentation states that **KiCad 9 and
10 IPC requires a running GUI process**, IPC plugins target PCB Editor,
and plotting/exporting are not supported in those IPC versions.
The IPC API gained headless kicad-cli, plotting/exporting and schematic
editor support in **KiCad 11**. SWIG pcbnew was deprecated in KiCad 9
and is planned for removal from KiCad 11.

Therefore it is NOT safe to silently substitute IPC into our current
headless Ubuntu 24.04 plus KiCad 10 native worker. Continue the small,
version-pinned KiCad 10 system pcbnew + kicad-cli subprocess behind
the SHA/DRC evidence interface for this source-only milestone.
A future version-specific KiCad 11 adapter must independently verify
PCB UUID mapping, copper geometry, per-project DRC rules, zones, plot
hashes and copy-on-write before replacing that backend. An optional GUI
IPC bridge would need a separate explicit user authorization and must
not mutate an already running PCB Editor without it.

Official KiCad sources:
https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/
https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/
https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/

## Scope and release gate

Only 2–3 distinct explicitly routed net pairs, at most four points
per individual route, only one optional bounded through-via pair
per route on two-copper-layer PCB, no zone fills, shove/ripup,
stacked blind/microvias, F8 synchronization, full EDA authoring,
manufacturer provenance, electrical certificate or fabrication approval.

The 0.1.11 signed-status flag stays FALSE, and all original 0.1.11
package, offline kit, manifest and QA evidence remain unchanged.
A future separately numbered 0.1.12 installer MUST pass an entirely
new exact-package/Ubuntu-native Chrome release acceptance before it
can be described as qualified; this source-only work is not sufficient.

## Source-only validation contract and version guard

Run the repeatable native, HTTP, existing ECO, static, SHA and real
Chrome local integration suite with the executable
scripts/review_studio_source_012_gate.sh.
A successful run is **not** a 0.1.12 package/Ubuntu acceptance.

The 0.1.11 Debian packager deliberately refuses to build a package from
this newer source because it would both inherit the wrong previously
accepted 0.1.11 version and omit the new native batch worker in the
frozen 0.1.11 resource manifest. The **four frozen 0.1.11
release-packaging test modules** explicitly skip on this source-only
branch; they remain fully available in the earlier frozen 0.1.11
commit and were independently qualified in its real Ubuntu RC gate.
An additional positive test verifies the version guard creates **no**
mislabeled package in a fresh directory.

A future 0.1.12 release needs a new package version and resource
manifest containing this worker, updated real Chrome and Ubuntu
installed-package QA, and fresh signed-source acceptance. Do not claim
the existing 0.1.11 .deb is a multinet-enabled installer.
