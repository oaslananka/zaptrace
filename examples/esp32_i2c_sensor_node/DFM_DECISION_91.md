# Issue #91 — physical DFM decision record (ESP32-WROOM-32 / USB4105)

**Record date:** 2026-10-11. **Disposition:** BLOCKED — engineering options only;
**no fabricator DFM acceptance, board release, or production authorization.**
**Owner direction (2026-11-02): internal engineering only.** No supplier
inquiry, external contact, fabrication quote, or order is part of this work.
The engineering path is to repair the default routing/export pipeline and
investigate geometry-correct, independently verifiable footprint/component
and board-layout alternatives without weakening native DRC or source proofs.
An internal clean DRC is necessary engineering evidence, not fabrication or
RF/electrical sign-off.

## New independent routing evidence — 2026-11-02

System KiCad **10.0.8** reproduced the existing 25-link / 61-segment
partial review, then independently checked an additional genuine
**U1.36 → U2.4 I2C_SCL** connection. The single-layer proposal failed
tracks_crossing and was rejected. A two-layer alternative with
**two 0.30 mm-drilled, 0.70 mm-diameter through-vias** and five segments
passed the independent native KiCad DRC comparison: **26 actual
connections, 66 tracks, 2 vias, 37 → 11 unconnected**, with the same
16 manufacturability defects by exact rule, object and position.
The original D1/D2 geometry, constraints, engineering/DFM hold and
no-fabrication decision are **unchanged**.
A second independent native two-layer R1.1→R2.1 VCC_3V3 review route
was verified on the same source, adding 3 tracks and two vias: **27
connections, 69 tracks, 4 vias and 37→10 unconnected**. The 16 defects
are still identical by native DRC signature. Rejected J1 VBUS attempts
introduced a short or new pad/hole/soldermask DRC errors and are excluded.
A third independently native DRC-checked C2.1→U2.8 VCC_3V3 route
adds 3 copper segments and two vias: the combined review now has **28
connections, 72 segments, 6 vias and 37→9 unconnected**, preserving
the original 16 manufacturing DRC signatures. There is no production
permission or copper completion.

An additional independently checked C1.2→U1.15 GND 2-layer route adds
three copper segments and two vias: the combined review has **29
connections, 75 tracks, 8 vias, 37→8 unconnected**, preserving all sixteen
individual physical DRC defect signatures without introducing new errors.
No manufacturing approval is implied.

Further real KiCad 10.0.8 native acceptance for U2.2→U2.8
VCC_3V3 with two vias and three tracks brings the opt-in review
to **30 authentic pad/net connections, 78 tracks, 10 vias and
37→7 unconnected**, without changing any of the original sixteen
physical DRC defects. Both full continuity and fab approval stay open.

A subsequent KiCad 10.0.8 verified B.Cu stitch connects two
already verified VCC_3V3 net/via terminals, without a new via:
**30 pad-connected routes plus one via stitch, 79 copper segments,
10 vias and 37→6 unconnected**. All original sixteen physical DRC
findings remain unchanged; this is not full PCB continuity or
manufacturing approval.

A further KiCad 10.0.8 verified U3.2 VCC_3V3 pad-to-existing-via
link requires one new drilled via and two segments. The opt-in review
now contains **30 pad-to-pad routes + one via stitch + one pad-to-via
connection, 81 copper segments, 11 vias and 37→5 unconnected**.
The same 16 native DRC defects remain; manufacturing approval is
still blocked.

Another independent KiCad 10.0.8 DRC acceptance links the two
real USB-C J1 VCC_5V contacts A4→B4 through three lower two-layer
tracks and two vias. Combined review: **31 pad-to-pad routes,
one via stitch, one pad-to-via connection, 84 tracks, 13 vias
and 37→4 unconnected**. Original sixteen manufacturability
violations persist identically, especially all four J1 NPTH
clearances; no production sign-off or copper completeness.

Four more system KiCad 10.0.8 verified lower-connector/ground/
I2C routes (VCC_5V source track→J1 via; J1 GND A1→B1;
J1 GND→board ground track; R2.2 I2C_SCL→existing back
track) complete the opt-in native net connectivity:
**37 physical copper joins, 92 segments, 18 vias and
37→0 KiCad unconnected items**, while the exact sixteen
original DRC defects remain **unchanged**. No electrical
measurement, qualified RF/thermal/ESD validation, official
manufacturer exception or fabrication authorization was obtained.
The *default* PCB export is still an intentionally unrouted
zero-copper design and source Proof Pack remains blocked.

All routing remains experimental review-only copper.

The table below is the original dated 2026-10-11 decision baseline.

## Reproduced source baseline — KiCad 10.0.8 (2026-11-02)

The default pipeline was regenerated from the unchanged design.yaml at
PR #119 head 7ec1e8a. The report now exposes **7 unresolved routed nets**:
VCC_5V, VCC_3V3, GND, USB_CC1, USB_CC2, I2C_SDA and
I2C_SCL. Ground is intentionally not poured (copper_pour_gnd=false), so
GND is not eligible to disappear from the routing-completeness denominator.

System KiCad 10.0.8 independently reproduced the source board baseline:

| Native check | Result |
|---|---:|
| Schematic ERC | **0 violations** |
| PCB DRC | **16 errors** |
| PCB unconnected items | **37** |
| Default exported copper tracks | **0** |
| Physical acceptance | **BLOCKED** |

The 16 DRC findings are exactly 12 drill_out_of_range violations on
U1 pad 39 PTH drills (0.2000 mm actual vs 0.3000 mm board minimum) and
four hole_clearance violations between J1's two 0.65 mm NPTH locating
holes and duplicated A/B GND contacts (0.1944 mm actual vs 0.2500 mm
board rule). The four entries describe two physical peg locations and
four overlapping contact-pad observations; they are not four separate
mechanical holes. No rule was waived, and no footprint or board geometry
was altered during this baseline reproduction.

This verifies the current blocker identity; it does not make the board
production-ready or qualify assembly, thermal, RF, ESD or USB behavior.

## Opt-in geometric pad-fanout candidate — native KiCad 10.0.8 (2026-11-02)

The pad-aware GridRouter review candidate now has a real geometric pad-exit
path for the two-terminal USB-C CC nets. Each pad-centre-to-grid stub is
checked against actual rotated pad shapes, unassigned connector contacts,
NPTH holes, board hard obstacles and the route width/clearance. The unassigned
J1 B7/B8/A8/A9 contacts remain physical obstacles. No endpoint cells are
opened and no width reduction is applied.

On the unchanged ESP32 source, the opt-in router now proposes **4 of 7 nets**:
USB_CC1, USB_CC2, I2C_SCL and the four-terminal I2C_SDA tree; **47 copper
segments, 0 vias**. Multi-terminal fan-out is deliberately bounded: one
nearest legal geometric escape anchor per terminal and one deterministic
MST attempt (no Cartesian candidate expansion). The default source
pipeline/export contract is unchanged: **0 accepted source tracks**, seven
unresolved nets, and physical preflight still fails. This candidate is not
a complete board route.

For an independent native check, the 47 tracks were added to a temporary
copy of the regenerated default KiCad PCB using KiCad 10.0.8 Python
bindings. Native result:

| Native check | Source baseline | Pad-fanout candidate |
|---|---:|---:|
| Schematic ERC | 0 | 0 |
| PCB DRC violation records | 16 | **16 (exact same 16 records)** |
| New DRC records | — | **0** |
| Unconnected items | 37 | **29** |

The candidate removes eight native unconnected relations while preserving
the two physical DRC groups exactly: twelve U1.39 drill-size errors and
four J1 NPTH-to-GND clearance observations. No electrical/physical rule was
waived and no DRC was hidden. The remaining routing nets and U1/J1 DRC
blocks remain unresolved; this is a review-only candidate, not fabrication
acceptance or permission to release the source PCB.

The route candidate and temporary KiCad copy are not the default pipeline
output. Strict source physical preflight remains false and fabApproved
remains false.

## Power-net pad-width qualification — 2026-11-03

The current POWER_MED routing rule is 0.50 mm trace width / 0.20 mm
clearance. This is correctly rejected by the pad-aware geometric fan-out
guard when a source pad is narrower than the constant-width trace; it is not
a missing grid anchor.

| Net / endpoint | Physical pad copper | POWER_MED trace | Consequence |
|---|---:|---:|---|
| VCC_3V3 / U2 BME280 VDD, VDDIO, CSB | 0.50 × 0.35 mm | 0.50 mm | No constant-width pad escape is geometrically valid |
| VCC_5V / D1 IO | 0.60 × 0.45 mm | 0.50 mm | No constant-width pad escape is geometrically valid |
| VCC_5V / J1 VBUS | 0.60 × 1.15 mm | 0.50 mm | Pad width itself is sufficient; complete net still fails because D1 and board-wide obstacles remain |

The BME280 manufacturer's datasheet lists typical consumption up to
3.6 µA at 1 Hz for humidity, pressure and temperature. That supports
treating the BME branch as a low-current branch only after the actual
operating mode and pull-up loads are included; it does **not** justify
narrowing the shared VCC_3V3 trunk. The ESP32-WROOM-32 datasheet specifies
0.5 A minimum current delivered by the external 3.3 V supply. Therefore the
shared regulator-to-ESP32 trunk must be qualified separately from the
sensor/logic branches.

At 5.0 V input and 3.3 V output, a linear AMS1117 dissipates
(5.0 - 3.3) × I. At the ESP32 module's 0.5 A supply figure that is 0.85 W
before considering input tolerance, regulator dropout, board copper and
ambient temperature. The current schematic does not contain a verified
thermal calculation or exact production-grade regulator qualification;
the regulator/power tree remains an independent electrical/thermal blocker.

Decision: do not reduce the 0.50 mm POWER_MED width globally, do not route a
0.50 mm line into a 0.35/0.45 mm pad, and do not add a blind via-in-pad.
The next legitimate implementation is a topology-aware power tree: preserve
a qualified wide trunk for the high-current path; allow a narrower branch
only where its branch current is bounded by the connected loads; represent
the width transition as real copper geometry (not merely a width metadata
change); verify pad and track clearances along the complete transition; and
validate the exported board with native KiCad DRC. No branch-width values
are approved by this analysis. The relevant official references are the
[Espressif ESP32-WROOM-32 datasheet](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html)
and [Bosch BME280 datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf).

## Power-budget and regulator qualification — 2026-11-03

This is a source-level budget, not a measured current profile. The source
has no exact BOM MPNs for U1, U3 or C1/C2/C3, no defined input supply/cable
limits, and no operating-mode duty-cycle specification. Consequently, the
following are constraints and calculations, not a power sign-off.

| Load / constraint | Evidence in source or vendor data | Engineering interpretation |
|---|---|---|
| U1 ESP32-WROOM-32 | Espressif recommends an external power supply capable of delivering at least 0.5 A | This is a supply-capability requirement, **not** a claim that the module continuously consumes 0.5 A. The 3.3 V source must maintain voltage during radio/CPU transients. |
| U2 BME280 | Typical 3.6 µA at 1 Hz with H/P/T; separate measurement-current figures are 340 µA humidity, 714 µA pressure and 350 µA temperature under different extreme-temperature conditions | The sensor is not the dominant 3.3 V load. Do not add the separate maxima as though they were simultaneous. |
| R1/R2 I²C pull-ups | Two 4.7 kΩ pull-ups from 3.3 V | Ideal upper bound when both lines are low: 2 × 3.3 V / 4.7 kΩ = **1.40 mA**. Actual current is lower when VOL is nonzero. |
| U3 AMS1117-3.3 | Generic type only; no manufacturer part number | Exact electrical limits, thermal characteristics, capacitor stability requirements and low-load behaviour cannot yet be bound to the fitted component. |
| C2 output capacitor | 10 µF, 0805; no MPN, dielectric, voltage rating, tolerance or DC-bias data | Effective capacitance and ESR at 3.3 V are unknown. A value-only entry is insufficient for regulator stability proof. |
| C3 input capacitor | 100 nF, 0402; no MPN or voltage/ESR specification | Input transient response and cable/source impedance still need analysis; the source does not define a bulk input capacitor. |

### Linear-regulator thermal envelope (illustrative, not approved)

For a linear regulator, use the first-order estimate PD = (VIN − VOUT) × IOUT.
At 3.3 V output and a 0.5 A **supply-capability sizing point**:

| Assumed U3 input | Calculated U3 dissipation |
|---:|---:|
| 5.0 V | **0.85 W** |
| 5.5 V | **1.10 W** |

The Advanced Monolithic Systems AMS1117 reference datasheet lists a SOT-223
junction-to-ambient reference of 90 °C/W, while explaining that board copper
and mounting can move the actual value from about 46 °C/W to above 90 °C;
its application notes say about 45 °C/W is possible with a suitably sized
copper-spreading board. At 0.85 W, 90 °C/W implies about **76.5 °C** junction
rise; at 1.10 W it implies about **99 °C**. For example, 0.85 W at 50 °C
ambient gives a simple estimate of 126.5 °C, above the datasheet's 125 °C
operating junction range. At 85 °C ambient, even the optimistic 45 °C/W
case gives about 123.3 °C at 5.0 V input and 0.5 A; at 5.5 V input it gives
about 134.5 °C. The datasheet's 1.2 W SOT-223 dissipation figure is
not available across the full input/output range and does not replace a
board-specific thermal calculation. Actual temperature depends on real load,
copper area, enclosure, airflow and nearby heat sources.

That reference datasheet also calls for 22 µF solid tantalum at the output to
ensure stability under all operating conditions; it notes that smaller
values may work in the configuration without an adjustment-pin bypass.
Current C2 is only described as 10 µF ceramic/0805 by value and footprint,
with no exact dielectric, effective capacitance or ESR. Since U3 itself has
no exact MPN, neither a definite stability failure nor a pass can be claimed.
The fitted regulator and output capacitor must be identified before this is
qualified. The same AMS1117 reference specifies guaranteed regulation above
10 mA load under the stated differential; low-load/deep-sleep behaviour also
needs checking against the actual fitted variant.

### USB-C source-current availability

The source schematic connects R3/R4 (5.1 kΩ) from CC1/CC2 to GND, providing
the sink Rd terminations. It contains no CC voltage measurement/current-
advertisement detector or USB-PD sink controller. ST AN5225 distinguishes
sink identification (Rd) from detection of the source's advertised current:
a 5.1 kΩ ±20% Rd does not detect power capability, while accurate CC voltage
monitoring is required to determine whether the source advertises default,
1.5 A or 3 A. Thus the board must not assume 1.5 A/3 A availability from the
resistors alone. The 0.5 A ESP32 supply-capability point is already at the nominal USB 2.0
default-current level; the regulator's own current, other loads, cable drop
and design margin are additional. Since the schematic neither measures the
source advertisement nor constrains system load to a lower value, the source
may not be able to support the required transient supply capability. This is
a system-level power compatibility blocker, not a reason to silently draw
more current.

### Decision / next engineering step

Do not assign narrower power-branch widths from sensor current alone and do
not change the global POWER_MED rule. First identify exact U1/U3/capacitor
MPNs; determine the intended USB source class and add/validate CC current
capability detection or explicitly constrain the permitted source; obtain
actual ESP32 worst-case/transient and sleep currents; include the I²C pull-up
loads; and calculate regulator loss/temperature with the real SOT-223 copper
and enclosure conditions. A buck regulator may be the simpler thermal
architecture if the 5 V → 3.3 V / 0.5 A operating point is required, but no
replacement part is selected in this change. Any power-trunk/branch width
transition still requires real tapered copper geometry and native KiCad DRC.

References: [Espressif ESP32-WROOM-32 datasheet](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html),
[Bosch BME280 datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf),
[Advanced Monolithic Systems AMS1117 datasheet](https://datasheet.lcsc.com/lcsc/1811142212_Advanced-Monolithic-Systems-AMS1117-3-3_C6186.pdf),
and [ST AN5225 USB Type-C current detection](https://www.st.com/content/ccc/resource/technical/document/application_note/group1/38/94/1d/41/0e/ba/49/21/DM00536349/files/DM00536349.pdf/jcr%3Acontent/translations/en.DM00536349.pdf).

## Current module identity and low-friction power architecture — 2026-11-03

### U1 orderable module identity correction

The previous starter-library value ESP32-WROOM-32(16MB) was not an
Espressif orderable part number: it mixed the original ESP32-WROOM-32 family
name with a flash size that the official base-module datasheet does not offer.
The original ESP32-WROOM-32 datasheet specifies **4 MB** and is marked
**NRND**. The source design's existing 16 MB intent is now identified by the
real orderable part **ESP32-WROOM-32E-N16**, listed in Espressif's official
ESP32-WROOM-32E/32UE Datasheet v2.1.

This is a metadata/part-identity correction, not a new footprint design:

- ESP32-WROOM-32E-N16: 16 MB QSPI flash; module dimensions **18.0 × 25.5 ×
  3.1 mm**; 38 numbered perimeter pins and ground thermal land.
- The manufacturer pin table confirms GND/3V3/EN at pads 1/2/3, GND at
  15/38, GPIO21 at 33 and GPIO22 at 36. These match the source net map.
- The 32E recommended land pattern uses the same 18.0 × 25.5 mm module
  outline and 38 × 1.5 × 0.9 mm perimeter lands. The retained, hash-pinned
  footprint already has those 38 perimeter contacts plus the repeated pad-39
  ground/thermal copper regions. **No footprint geometry, pad map, RF keepout,
  drill or DRC rule was changed.**
- The 32E-N16 orderable identity is now explicit in the source and starter
  library. Starter-library provenance remains heuristic and distributor
  stock/authorized procurement are not verified by this work.
- The current v2.1 datasheet Table 16 gives (3.3 V, 25 °C) Wi-Fi TX average /
  peak current: 802.11b 1 Mbps at 19.5 dBm **239 / 379 mA**; 802.11g
  54 Mbps at 15 dBm **190 / 276 mA**; 802.11n MCS7 at 13 dBm **183 / 258 mA**.
  RX is **112 mA** (20 MHz) or **118 mA** (40 MHz). These are mode-specific
  characterization points, not a universal maximum for every firmware,
  temperature or simultaneous peripheral load. Use 379 mA as a documented
  RF transmit sizing point, then add other loads and design margin; do not
  equate the previous 0.5 A supply-capability recommendation with continuous
  draw.

### Power architecture recommendation — keep Type-C simple, replace the LDO candidate

The current USB-C connector has only the two 5.1 kΩ Rd sink terminations.
ST AN5225 Rev 7 lists **5 V / 500 mA** as USB 2.0 default current, with
1.5 A and 3 A as separate Type-C current advertisements. Therefore:

- The passive-Rd implementation may use only the current actually advertised
  by the compliant source; it must not assume 1.5 A or 3 A without detecting
  the corresponding CC advertisement.
- A CC controller is **not automatically required** for this fixed 5 V sink.
  If the complete board is qualified to remain within the USB 2.0 default
  current budget, the existing two Rd resistors are the simpler architecture.
- Only if the product truly needs more than default current should a CC
  detector be considered. TI TUSB320LAI is an active sink-capable CC
  controller that detects default/medium/high current; it includes the UFP
  Rd pulldown, so adopting it would mean removing the separate R3/R4 Rd
  implementation and wiring the detector's output. It is not selected here.
  USB PD / higher VBUS voltage is not required for this option.

For U3, the strongest simple buck candidate found in the current vendor
documentation is **TI TPSM82901**. It is active, accepts 3–17 V, supports
1 A continuous output, integrates a 1 µH inductor in a **3.0 × 2.8 ×
1.6 mm** MicroSiP, and has 4 µA typical power-save quiescent current.
Its VSET table provides 3.3 V using 249 kΩ or larger/open. This is a
candidate for evaluation, **not an approved BOM substitution**.

The TPSM82901 datasheet's typical application uses 10 µF input and 22 µF
output capacitance. Its recommended effective input capacitance is 3–10 µF;
effective output capacitance is 10–100 µF at 2.5 MHz (6–50 µF at 1 MHz),
with 22 µF nominal used in the reference application. It lists example
TDK 0805 parts: **C3216X7R1E106K160AB** (10 µF, 25 V input) and
**C2012X7S1A226M125AC** (22 µF, 10 V output). Actual effective capacitance
under DC bias/tolerance must be checked. The present source has only C3
100 nF at the 5 V input and C2 10 µF at the 3.3 V output, so a buck
conversion would require a real input/output capacitor review and a layout
redesign around the selected converter. Do not merely swap the U3 footprint.

At the documented 379 mA ESP32 Wi-Fi TX peak, the module alone is
approximately **1.25 W** at 3.3 V. Adding the BME280 typical H/P/T load and
the two I²C pullups puts the known-load estimate close to 1.26 W before
regulator quiescent current, other GPIO loads and design margin. Under
illustrative buck efficiencies of 75–85%, the idealized 5 V input current
for 1.26 W is about **296–336 mA**. These are arithmetic scenarios, not
claimed TPSM82901 efficiency values at 5 V. The TPSM82901's published 3.3 V
efficiency curves begin at 6 V input, so 5 V efficiency, transient response,
board thermal derating, USB cable drop and complete load current must be
validated. At the same 379 mA output sizing point, an AMS1117 linear
regulator would dissipate approximately **0.64 W at 5.0 V in** (and 0.83 W
at 5.5 V), before additional loads. A buck can therefore leave materially
more 5 V input-current and thermal headroom than a linear regulator whose
input current is approximately its output current. The source must still
stay within its Type-C current advertisement and include operating margin.
A 500 mA USB2 default limit should not be treated as a target to consume
fully.

### Decision

The preferred next architecture to prototype is **fixed 5 V Type-C sink at
default advertised current + integrated-inductor 3.3 V buck**, retaining the
existing Rd behavior and not adding a CC controller unless a measured
system power budget demonstrates a need above default current. Keep the
existing 0.50 mm high-current power-trunk rule until actual load/transient
current and temperature are qualified. No narrower branch width is approved.

No U3/C2/C3 replacement or power routing has been performed in this change.
Before choosing TPSM82901, build a small, reviewable candidate schematic
and footprint, validate VSET=3.3 V, input/output effective capacitance,
soft-start/EN, power-good handling, RF noise coupling, placement, native
KiCad DRC and thermal conditions. Compare it to the AMS1117 baseline using
the actual ESP32 transient profile. The candidate must not be enabled in the
default pipeline before those checks pass.

References: [Espressif ESP32-WROOM-32E / 32UE datasheet v2.1](https://documentation.espressif.com/esp32-wroom-32e_esp32-wroom-32ue_datasheet_en.html),
[Espressif original ESP32-WROOM-32 v3.8 datasheet](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html),
[TI TPSM82901 datasheet](https://www.ti.com/lit/gpn/TPSM82901),
[TI TUSB320LAI product and datasheet](https://www.ti.com/product/TUSB320LAI),
and [ST AN5225 Rev 7](https://www.st.com/resource/en/application_note/dm00536349.pdf).

## Isolated TPSM82901SISR power-stage candidate — 2026-11-03

A separate review-only KiCad project now exists at
examples/esp32_i2c_sensor_node/power_candidate_tpsm82901/. It does not
replace U3 in the active ESP32 source design and is not connected to its
routing pipeline.

- Exact TI production MPN: TPSM82901SISR (11-pin SIS/uSiP; TI package
  addendum dated 2026-02-06 lists Active / Production).
- Pin mapping follows TI datasheet Table 5-1: 1/2 VIN, 3 EN,
  4 MODE/S-CONF, 5 SS/TR, 6 PG, 7 FB/VSET, 8 SW/NC, 9/10 VOUT,
  11 exposed GND. Pin 8 intentionally has no net or copper; pad 11 is GND.
- Electrical configuration follows TI TPSM82901EVM BSR188-001:
  113k/24.9k external FB divider, 7.15k MODE/S-CONF to GND,
  22pF optional feed-forward, 3.3nF SS/TR, and 1M PG pull-up.
  Nominal divider target is 3.3229V; this is a resistor calculation, not
  a measured output.
- Candidate caps: TDK C3216X7R1E106K160AE (10uF/25V X7R input) and
  C2012X7S1A226M125AC (22uF/10V X7S output). They remain candidates pending
  effective-capacitance-at-bias, tolerance, temperature and aging checks.
- A local, explicitly DRAFT 11-pad footprint follows the TI SIS0011A
  nominal geometry (10 perimeter lands at 0.55×0.25mm / 0.5mm pitch and
  0.9×2.1mm center thermal land). It is not in the verified-footprint
  registry; solder-mask/paste details and exact assembly tolerances remain
  subject to review. The generated symbol is connectivity-only and still
  emits ERC warnings; it is not yet a typed electrical library symbol.
- Native KiCad 10.0.8 on the isolated four-copper-layer candidate:
  schematic ERC **0 errors / 20 warnings** (9 symbol/footprint-library
  mismatches, 11 off-grid endpoints); PCB DRC **0 violations**;
  **22 unconnected items** because no copper tracks or vias have been
  routed. This does not constitute electrical, EMI, thermal or fabrication
  acceptance.
- TI recommends at least four copper layers with 1oz copper for improved
  thermal behavior, large GND planes, and thermal vias on GND/VIN/VOUT.
  The candidate has four copper layers but has **no** ground planes,
  thermal vias, power-current loops or finalized placement/routing yet.
- Selected contract tests lock the production MPN, pin mapping, pin-8 NC,
  pin-11 GND pad, EVM values, and draft footprint dimensions.

Decision: keep this as an isolated review candidate. Do not replace the
active AMS1117 placeholder or route power nets until the official footprint,
symbol electrical types, capacitor DC-bias, current budget, 5V efficiency,
RF behavior, thermal layout and routed-board native DRC are all reviewed.

References: [TI TPSM82901 datasheet](https://www.ti.com/lit/ds/symlink/tpsm82901.pdf),
[TI TPSM8290x EVM user's guide](https://www.ti.com/lit/ug/snvu796/snvu796.pdf),
[TI product/orderable details](https://www.ti.com/product/TPSM82901).

## Exact evidence and applicability

Evidence baseline: Draft [PR #119](https://github.com/oaslananka/zaptrace/pull/119)
source commit `89e0328263e2e907a690e09f1ba8e7819b42b1e4`,
provisional 100 × 75 mm, 2-layer ESP32 I²C sensor reference. System KiCad
**10.0.7** was run independently on a newly generated schematic and default
PCB, and against the separately opted-in native copper review. No physical
footprint or rule was modified to obtain the evidence below.

| Evidence | Default exported PCB | Separate opt-in review PCB |
|---|---:|---:|
| Native schematic ERC | 0 | Same unchanged source |
| Native PCB manufacturability DRC | **16 errors** | **16, identical individual defects** |
| Native physical `unconnected_items` | **37** | **12** |
| Routed F.Cu segments | 0 | 61, representing 25 net/pad-matched links |
| Strict source Proof Pack | **6 PASS / 2 FAIL** | Not a separate production Proof Pack |

The two Proof Pack failures are `drc-clean` and `min-clearance`; the source
verdict is `blocked-insufficient-evidence`. The optional review manifest
records `fabApproved=false` and `physicalContinuityComplete=false`.
The 16 defects were compared by complete native KiCad rule, severity,
offending object and location signatures, not merely by category count.
**CI and successful partial copper routing do not waive these defects.**

### Blocker D1 — ESP32 module thermal ground vias (12 native errors)

- KiCad rule: `drill_out_of_range`; twelve genuine U1 pad-39 plated holes.
  **Measured drill 0.2000 mm; project minimum 0.3000 mm** (0.1000 mm short).
  Existing nominal via copper diameter is **0.60 mm**, giving a nominal
  radial annular ring of `(0.60 - 0.20)/2 = 0.20 mm` before production
  tolerances. The pad geometry and solder/thermal behavior require review.
- [JLCPCB's published 2-layer capabilities](https://jlcpcb.com/capabilities/pcb-capabilities/)
  list 0.15 mm minimum drilling, 0.20 mm preferred minimum via drill, and
  a **0.18 mm absolute / 0.25 mm recommended** PTH annular-ring width for
  2-layer, 1 oz copper. [PCBWay capabilities](https://www.pcbway.com/capabilities.html)
  list 0.15 mm minimum mechanical drilling and added charges for sizes below
  0.20 mm. These are generic process ranges, **not board-specific DFM approval**.
- **Unsafe shortcut:** increasing the hole to 0.30 mm *without changing the
  0.60 mm pad* reduces the calculated radial annular ring to **0.15 mm**,
  below JLCPCB's cited absolute 0.18 mm 2-layer/1 oz figure. Enlarging pads,
  changing a via count, or removing thermal vias may also invalidate module
  footprint clearances, paste deposition, heat flow and supplier pin/pad
  provenance. None may be done as a blind DRC fix.
- At the original 2026-11-02 baseline the design identified the base
  ESP32-WROOM-32 module. On 2026-11-03 that source identity was corrected to
  the exact 16 MB orderable **ESP32-WROOM-32E-N16**. The base ESP32-WROOM-32
  is a 4 MB NRND product; the 32E-N16 datasheet v2.1 has the matching
  18 × 25.5 × 3.1 mm module outline, 38-pin map and compatible land pattern.
  The retained footprint and pad map were checked against the 32E drawing;
  no footprint geometry or RF keepout was changed. Availability and
  procurement are not verified.

### Independent D1 what-if board trials — 2026-11-02 (NOT approved)

On the **same exact PCB source** at Draft PR #119 head
ea8549c65d25467e12c16ba3ad7f825dd0005c84, system
**KiCad 10.0.8** validated the opt-in, completely routed reference
PCB at **0 native unconnected / 16 original manufacturing DRC**.
In isolated temporary copies, *only* the twelve U1/39 plated-drill
diameters, and where noted their copper pad diameters, were changed.
These were **not** modifications to the tracked vendor footprint,
default design, manufacturing outputs or PR routing contract.

| Temporary what-if, all 12 U1/39 vias | Nominal annular ring | Neighboring via-pad edge gap (0.7625 mm center pitch) | Native KiCad result | Qualification |
|---|---:|---:|---|---|
| Original 0.20 mm drill / 0.60 mm land | 0.200 mm | 0.1625 mm | 16 original errors | Source remains blocked by 0.30 mm minimum drill |
| 0.30 / 0.60 mm | **0.150 mm** | 0.1625 mm | 4 J1 errors + 1 footprint-library mismatch | **Reject**: below vendor-published 0.18 mm absolute annular ring |
| 0.30 / 0.65 mm | **0.175 mm** | 0.1125 mm | 4 J1 errors + 1 footprint-library mismatch | **Reject**: still below 0.18 mm absolute annular ring |
| 0.30 / 0.75 mm | 0.225 mm | **0.0125 mm** | 4 J1 errors + 1 footprint-library mismatch | **Unqualified**: below 0.25 mm recommended ring and very tight same-net pad spacing |
| 0.30 / 0.80 mm | 0.250 mm | **−0.0375 mm** (overlap) | 4 J1 errors + 1 footprint-library mismatch | **Unqualified**: adjacent copper pads overlap; paste, assembly and thermal behavior not approved |

The ring values are **nominal geometric calculations**, not measured
finished hole sizes. DRC does not certify process capability,
registration tolerance, solder wicking, via filling, thermal-pad paste
deposition, assembly, current/heat flow or RF performance. The
footprint-library mismatch occurs because these temporary board pad
edits do not match the unchanged original source footprint; removing
that warning by editing both files would **not** prove manufacturability.
No tested option changes the four J1 peg-to-pad clearance violations.

These results are **feasibility evidence**, not a selected
replacement footprint. An exact manufacturer land pattern and a
qualified process/assembly decision are required before updating
U1 geometry. The project's native DRC minimum drill remains
0.30 mm and no physical violations were waived. JLCPCB's
[2-layer capabilities](https://jlcpcb.com/capabilities/pcb-capabilities/)
publish a 0.18 mm absolute and 0.25 mm recommended 1 oz
PTH annular ring, not a board-specific authorization.

### Independent manufacturer source cross-check — 2026-11-02

The selected **GCT USB4105** manufacturer's [product page and
drawing](https://gct.co/connector/usb4105) identify two Ø0.65 mm
locating holes **5.78 mm center-to-center**, and a recommended
component-side land pattern using **0.60 × 1.15 mm** outer
ground-contact lands. Independent KiCad 10.0.8 extraction of
the **unchanged J1 footprint**, relative to its board origin
(80.0, 67.0) mm, shows:

| Item | Actual local footprint coordinates (mm) | Dimensions |
|---|---|---|
| Two mechanical NPTH locating pegs | (−2.89, −2.605), (+2.89, −2.605) | Ø0.65, centers 5.78 apart |
| A1/B12 shared ground contact | (−3.20, −3.68) | 0.60 × 1.15 copper |
| A12/B1 shared ground contact | (+3.20, −3.68) | 0.60 × 1.15 copper |

These dimensions agree with the listed **GCT recommended
land pattern**; the two real Ø0.65 pegs must not be shifted
just to suppress four duplicated-pad KiCad findings. The
native hole-clearance result is **0.1944 mm** versus the
unchanged 0.2500 mm board rule. Matching a drawing proves
dimensional consistency, **not** assembly, manufacturing
tolerance or supplier process acceptance. The exact
USB4105-15-A-120 shell stake and assembly fit still require
qualification.

The current official [Espressif ESP32-WROOM-32 datasheet,
Section 10.1](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html)
depicts copper vias beneath the thermal pad, but does
**not** by itself qualify the local twelve 0.20-mm drilled
/ 0.60-mm land structures or a 0.30-mm drill replacement.
The original module remains **NRND**. Any changes require
pad/paste/thermal, manufacturer land-pattern and
board-process verification, not an assumed DRC-only fix.

### Blocker D2 — USB-C J1 locating peg / GND land clearance (4 native errors)

- KiCad rule: `hole_clearance`; J1 **NPTH** locating holes at
  `(77.1100,64.3950)` and `(82.8900,64.3950)` mm. The four GND pad
  observations correspond to physically overlapping A/B contact numbers at
  `(76.8000,63.3200)` and `(83.2000,63.3200)` mm, **not four distinct pegs**.
- Actual clearance **0.1944 mm**, required **0.2500 mm**; nominal shortfall
  **0.0556 mm**. JLCPCB's generic **0.20 mm NPTH-to-track** figure does
  **not** qualify NPTH-to-*pad* proximity; indeed the measured gap is below
  even that distinct track figure. Board-house process, hole-registration
  tolerance, soldermask and exposed copper require specific review.
- [GCT USB4105 product and source drawing](https://gct.co/connector/usb4105)
  govern its 16 contact lands, two locating pegs and four plated S1 oval
  shell stakes. The existing S1 slots are 0.60 mm wide with lengths 1.40/
  1.70 mm; their plausibility under generic plated-slot capabilities does
  **not** cure the NPTH-to-GND clearance issue or certify assembly fit.
- **Unsafe shortcut:** moving the pegs, shrinking/removing GND contact lands,
  renumbering A/B contacts, treating shell stakes as net-connected copper,
  removing locating holes or relaxing clearance globally. Each would change
  actual connector fit, soldering or electrical/EMI behavior without evidence.

## Engineering-only remediation (owner direction: no external outreach)

The objective is an honest and reproducible **default** pipeline, not a
fabrication order. The historical published capability figures above provide
design constraints only; they do not authorize changing a rule or calling
the unchanged board production-ready.

| Work item | Existing evidence | Internal acceptance target |
|---|---|---|
| D1: twelve U1 thermal vias | 0.20 mm drills, 0.60 mm pads, 0.30 mm project drill minimum; isolated drill/pad trials exposed annular-ring and adjacent-pad constraints | Choose a physically defensible module land pattern and drill/pad arrangement backed by exact component drawings; independent KiCad DRC without rule suppression or new footprint mismatches |
| D2: four J1 contact/locating-peg findings | 0.1944 mm NPTH-to-GND pad clearance vs 0.25 mm board rule; actual footprint matches the selected connector drawing | Evaluate exact part/footprint compatibility and revised layout/connector options; preserve peg fit, pad pinout, shell slots and electrical constraints; independent KiCad DRC without waivers |
| Default routing | Source exports zero accepted copper and reports **seven unresolved nets** (six signal/power nets plus GND because copper_pour_gnd=false); separate opt-in review overlay has 37 genuine joins / 92 tracks / 18 vias / 0 native unconnected, but still D1/D2 | Integrate valid geometry/routing behavior through the owned deterministic pipeline; independently reproduce complete pad/net continuity in generated output with zero critical shorts/clearance defects |
| Proof/electrical evidence | Source strict Proof Pack 6 PASS / 2 FAIL and native PCB DRC 16; real RF, ESD, power and thermal qualification not established | Preserve fail-closed checks and negative regression tests; demonstrate independent native ERC/DRC and strict Proof Pack outcomes without misrepresenting hardware approval |

### Execution order

1. Characterize why the ordinary grid router reports graph-connected nets
   yet rejects actual exported traces. Use the real ESP32 input and preserve
   provenance-locked footprint/pad identities; translate the already verified
   review-only routes into algorithmic regression expectations, not an
   unvalidated static default copper overlay.
2. Investigate D1 and D2 as *source geometry and placement* constraints.
   Validate any potential replacement part and land pattern internally
   against exact public drawings and native KiCad DRC. Rejected experimental
   variants remain rejected; do not silently change the project design
   rules, pad/pin mapping, antenna keepout or shell-stake handling.
3. Re-run source-generation end to end, native schematic ERC, PCB DRC,
   complete actual pad/net connectivity, strict Proof Pack and targeted
   negative fixtures. Distinguish software verification from unperformed
   RF, ESD, thermal, USB power and assembly qualification.

**Stop rule:** if a physical geometry change cannot be independently
justified without compromising the chosen part's mechanical/electrical
requirements, keep it as an honest unresolved finding. Do not create
speculative design variants merely to reach zero warnings.

## Current engineering gates

| Gate | Required evidence | Current disposition |
|---|---|---|
| Source routing | Deterministic default copper with zero real unconnected items and no new shorts | **OPEN** — default copper zero; separate review-only PCB 0 unconnected |
| Source geometry | Exact component/footprint compatibility and independent justified KiCad DRC | **OPEN** — D1 12 + D2 4 violations |
| Strict proof | All applicable unwaived checks and regression fixtures pass | **OPEN** — source 6 PASS / 2 FAIL |
| Electrical/RF behavior | Ground return, RF keepout, USB-C CC/shell/ESD/VBUS, regulator thermal and qualified evidence | **OPEN** — not hardware-qualified |
| Fabrication release | Separate professional review and final physical evidence | **BLOCKED** — no authorization; not part of this work |

**Next:** work within #91 and #35 on genuine default copper and physical
geometry/footprint correctness; preserve the Draft PR and all fail-closed
checks while the above gates are unresolved. No external communications.
