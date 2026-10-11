# GridRouter: transactional net occupancy and native KiCad evidence

Part of [layout/routing backend epic #35](https://github.com/oaslananka/zaptrace/issues/35).

## Implemented, bounded behavior

- ObstacleMap retains static bodies/board-edge masks separately from **net-owned copper reservation cells**. Previously accepted foreign-net occupancy cannot be deleted when clearing a later net's component escape endpoints. Same-net copper is reusable.
- Each net's complete minimum-spanning-tree (MST) route is built on a **clone of the obstacle map**. Failure on any MST edge, unavailable endpoint or foreign-net copper clearance refuses the entire tentative net and rolls back its cells. A partial path is never counted as a routed net.
- The optional GridRouter(max_ripup_passes=1) (maximum 2) reroutes on a fresh board, prioritizing previously unrouted nets. An alternate ordering replaces the accepted result **only if more whole nets route**. It is deterministic and bounded; this is not a full push-and-shove router.
- Existing pad-based escape coordinates remain approximate for nontrivial footprint geometry. The router does **not** automatically validate physical pad contact, via antipads, multilayer pad access, hole clearances or plane return paths. Final KiCad/ERC/DRC and Proof Pack gates are independent and cannot be bypassed by a grid success count.

The ESP32-C3 physical candidate consequently exposes **2 real internal DRC-005 unrouted-net errors**, GND and SCL (previously one). Its 8 right-angle DRC-003 warnings include CC1/CC2. It stays non-fabrication-ready. These are not waived or hidden.

## Opt-in copper-pad and layer geometry (experimental)

For fully placed components with explicit **RECT, CIRCLE, or OVAL** pad definitions,
use GridRouter(pad_aware=True, resolution_mm=0.5). This is deliberately NOT enabled
for existing flows without verified physical pad geometry.

- The immutable pad-owned occupancy map is independent of dynamically routed
  copper. It conservatively rasterizes exact pad extents, local pad rotation,
  KiCad-positive footprint orientation, trace half-width and clearance, plus a
  half-cell uncertainty allowance. A net may traverse its own pad copper, never
  another net's. Conflicting or unassigned pads fail closed.
- Top-only and bottom-only SMD pads occupy only their actual respective copper
  layers; plated through-hole pads occupy the full stack; NPTH holes block
  drill clearance through all layers. GridRouter rejects missing footprint
  geometry, unsupported custom shapes and off-grid exact pad centres.
- Only a **single shared physically accessible copper layer** is used for each
  net. Cross-layer transitions are rejected rather than producing geometrically
  unverified via tracks. can_place_through_via() is a conservative multi-layer
  occupancy query, **not** a finished via padstack or via router.
- The physical **board outline**, rectangular default boundary, polygonal
  internal cutouts and mounting holes are conservatively blocked on **every
  copper layer**, including trace-clearance and grid-sampling margins. Simple
  polygons are supported (convex or concave); self-intersecting, zero-area,
  degenerate and non-finite outlines fail closed. A plated mounting hole that
  lacks a trusted electrical net is *not* treated as safe routing copper.
  This occupancy check remains an estimate until KiCad native DRC validates
  the full board profile and true copper-to-edge rules.
- This remains a reference-engine, grid-based estimate. KiCad native DRC is
  independent and mandatory. No DRC waiver or manufacturing approval is implied.

## Independently verified fixture

On a machine with **KiCad 10.x** (both kicad-cli and system pcbnew bindings) and the locked uv Python environment installed, run:

~~~bash
bash scripts/issue35_native_grid_oracle.sh build/issue35-native-grid-oracle
~~~

This creates a tiny 2-layer, four-PTH-pad, **two-net** synthetic test board. The GridRouter result must terminate **exactly at all four physical pad centers** on F.Cu. KiCad CLI is executed independently on both generated boards, with a source/candidate SHA-256 manifest and fresh reports. The command rejects anything other than:

| Native KiCad PCB DRC | Without tracks | With GridRouter tracks |
| --- | ---: | ---: |
| Unconnected pad groups | 2 | **0** |
| Other DRC violations | 0 | **0** |
| Process exit | 5 (expected) | **0** |

The temporary candidate is discarded on any failure; reports, the locked-environment GridRouter JSON plan, and source/candidate PCB files are only published after both native reports pass. This independent check also runs in the path-scoped KiCad Oracle GitHub Actions workflow, which preserves its reports and KiCad board artifacts.

**Limitations:** this is a minimal deterministic reference, not a 12-family PCB-Bench result, multilayer congestion guarantee, ESP32/USB-C manufacturing validation, impedance/EMC assessment, full pad-aware router, or fabrication approval. Next stages: real SMD pad access/rotation, footprint pad masks, layer/via/copper-clearance geometry, negotiated congestion and quality-based rip-up under native KiCad oracle and benchmark control.


### Independent rotated-SMD positive and negative controls

The same system KiCad 10 runner additionally verifies a true F.Cu rectangular
SMD-net route detouring around a foreign net's 90-degree rotated SMD pad. The
source plan includes a second footprint rotated by 90 degrees with an offset pad;
the test compares the **actual KiCad pad centre after footprint rotation** with
the GridRouter model before independent native DRC.

~~~bash
bash scripts/issue35_native_grid_oracle.sh build/issue35-smd-pad-oracle --smd
~~~

KiCad CLI accepts the pad-aware route only when native DRC reports **zero
violations and zero unconnected items** (baseline: one unconnected). Separately,
the test deliberately emits an unsafe straight route through the foreign pad
and **requires KiCad to reject it** with a short or clearance violation. Every
board, generated plan, and independent report is SHA-256-bound and retained by
the KiCad Oracle CI job only after verification. This tests one synthetic
clearance/detour case, not arbitrary production PCB routing.
