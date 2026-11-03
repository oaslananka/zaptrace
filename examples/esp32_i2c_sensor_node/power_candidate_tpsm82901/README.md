# TPSM82901SISR review-only power-stage candidate

**Status: isolated four-layer review candidate — routed and native DRC/ERC clean, but not electrically bench-tested, thermally/EMI-qualified or approved for fabrication. It is not part of the active ESP32 source design.**

This isolated KiCad project evaluates a lower-loss 5 V → 3.3 V buck replacement for the current AMS1117 placeholder. It is intentionally separate from examples/esp32_i2c_sensor_node/design.yaml. It contains a first-pass compact power-stage placement, copper zones, short signal paths and stitching vias; it remains an engineering candidate, not a released board design.

## Exact device and pin contract

- Production orderable MPN: TPSM82901SISR (TI product addendum dated 2026-02-06 lists it Active / Production; uSiP SIS, 11 pins).
- Package: SIS0011A, 3.0 × 2.8 × 1.6 mm max, integrated 1 µH inductor.
- Pins: 1/2 VIN; 3 EN; 4 MODE/S-CONF; 5 SS/TR; 6 PG; 7 FB/VSET; 8 SW/NC; 9/10 VOUT; 11 exposed GND.
- Pin 8 is intentionally floating (no net, no copper). Pin 11 must be soldered to the common ground plane.
- The 11-pad local footprint is explicitly marked DRAFT and is not promoted into ZapTrace's verified vendor-footprint registry. It now follows TI SIS0011A example dimensions: ten 0.55 mm-long perimeter lands; four corner lands 0.575 mm wide and six middle lands 0.25 mm wide; inner-pin pitch 0.5 mm; outer pin 1-to-5 / 10-to-6 span 2.325 mm; center exposed land 0.9 × 2.15 mm. The footprint uses TI's solder-mask-defined example (nominal 0.05 mm mask encroachment) and two split stencil windows approximating 80% paste coverage. The stencil split is an approximation from the datasheet image and requires assembly review. The drawing marks three optional 0.2 mm via locations under the exposed land; they are deliberately not drilled in this draft because TI requires vias beneath paste to be filled, plugged or tented, and the assembly process is not yet defined.

## Electrical configuration (TI TPSM82901EVM BSR188-001 reference)

| Ref | Value / connection | Function |
|---|---|---|
| U3 | TPSM82901SISR | 3.3 V buck |
| C1 | 10 µF, 25 V, X7R, TDK C3216X7R1E106K160AE | VIN bypass candidate |
| C2 | 22 µF, 10 V, X7S, TDK C2012X7S1A226M125AC | VOUT capacitance candidate |
| R1 | 113 kΩ, 1% | VOUT-to-FB upper divider |
| R2 | 24.9 kΩ, 1% | FB-to-GND lower divider |
| R3 | 7.15 kΩ, 1% to GND | 2.5 MHz, Auto PFM/PWM with AEE, external FB, output discharge disabled |
| C3 | 22 pF, C0G | Optional feed-forward capacitor |
| C4 | 3.3 nF | SS/TR capacitor (EVM value) |
| R4 | 1 MΩ | PG open-drain pull-up to VOUT |

Nominal feedback calculation: 0.6 × (1 + 113 kΩ / 24.9 kΩ) = 3.3229 V. This is the nominal resistor-ratio target using the 0.6 V feedback reference; it is not a measurement. The TI EVM uses the same nominal 3.3 V output. The selected capacitor MPNs are candidate parts only: confirm effective capacitance at applied DC bias, tolerance, temperature and aging before approving the circuit.

## Layout status

The candidate board is set to four copper layers: F.Cu, In1.Cu, In2.Cu and B.Cu. A broad GND zone is present on all four layers; VIN and VOUT have local top-layer copper regions and In1.Cu spreading islands. CIN is next to VIN, COUT next to VOUT, the FB divider/CFF are close to FB, the MODE resistor faces MODE/S-CONF and the SS capacitor faces SS/TR. The first-pass layout contains 15 copper track segments and 11 through-vias (0.60 mm copper / 0.30 mm finished drill). One additional GND stitching via at (20.0, 15.8) connects the exposed-pad-side GND copper to the inner/bottom planes; it remains outside the exposed pad and stencil apertures (not via-in-pad). The boundary VIN/3V3 feeds, local signal routes, PG return and power/GND zone fills are connected. All designators remain visible on KiCad F.Fab for review; they are not placed on F.Silkscreen, keeping the switching-power area and solder-mask clear. Native KiCad reports zero unconnected items. This is a first-pass topology/layout candidate; copper distribution and the 4-layer GND reference still require detailed EMI, transient, current-density and thermal review. The KiCad board records 1.6 mm overall thickness and four copper layers, but does not specify a copper weight/finished copper thickness. TI recommends 1 oz copper for its thermal guidance; this candidate does not yet prove that condition or inherit the TI EVM/JEDEC thermal resistance.

TI states that SW/NC must remain floating; any copper beneath it must be small, electrically floating, isolated from inner layers and have no vias. Pad 8 has no net, and an all-copper-layer rule area blocks tracks, vias and zone fills beneath/around the package pad. The DRC report shows no items in that keepout.

## Power budget and integration review — 2026-11-03

### Capacitor sufficiency

TI specifies at least **3 µF effective input capacitance** and, at the selected
2.5 MHz mode, at least **10 µF effective output capacitance** directly at the
device. Its application guidance recommends 10 µF nominal at VIN for most
applications and 22 µF nominal at VOUT. The selected 10 µF / 22 µF parts match
those nominal starting values, but nominal marking is not the same as
effective capacitance. TDK publishes DC-bias characteristic curves for both
selected MPNs; the exact effective values at 5 V VIN and 3.323 V VOUT,
including tolerance and temperature, have not yet been extracted or measured.
Do not mark either minimum as proven until those curves or bench measurements
are checked against TI's effective-capacitance limits.

The EVM adds a 47 µF tantalum bulk input capacitor in addition to its 10 µF
MLCC. TI's datasheet does not make that extra 47 µF mandatory for most
applications. Do not add it automatically; decide from the actual USB source,
cable impedance and input-transient measurements.

### 5 V source-current envelope

For a buck converter, the first-order input estimate is
I_IN = V_OUT × I_OUT / (V_IN × efficiency). At 5 V input and 3.3 V output:

| 3.3 V output load | Assumed efficiency | Estimated 5 V input |
|---:|---:|---:|
| 379 mA | 80% | 313 mA |
| 379 mA | 85% | 294 mA |
| 379 mA | 90% | 278 mA |
| 500 mA | 80% | 413 mA |
| 500 mA | 85% | 388 mA |
| 500 mA | 90% | 367 mA |
| 1,000 mA | 85% | 776 mA |

These efficiencies are illustrative assumptions, **not measured TPSM82901
efficiency at 5 V / 3.3 V**. Espressif's 500 mA recommendation is a minimum
source-capability recommendation, not a measured constant ESP32 current.
Sensors and other 3.3 V loads add to the module's demand. The TPSM82901's 1 A
rating therefore does not mean the USB-powered board may draw 1 A from a
default-current USB-C source.

The Type-C sink in the active source schematic has 5.1 kΩ CC pull-downs, but
no current-advertisement sensing/limit logic is represented. Treat default
source capability as the design envelope unless a compliant source-current
detection/management design is added separately. Do not assume a 1.5 A or
3 A source just because the connector is USB-C.

### Board-level ESP32 integration findings

The active source design was inspected but not changed:
- USB-C VBUS entry currently has a 100 nF capacitor (C3) and the PESD5V0S1BA
  protection element (D1), but no 10 µF nominal bulk capacitor at the main
  power entrance. The buck candidate's 10 µF C1 is local to the converter;
  it is not at the USB-C entry after integration because the source design
  places U3 about 34 mm from J1.
- The source design's 10 µF 3.3 V capacitor C2 is approximately 26.9 mm from
  the ESP32 module U1; its 100 nF C1 is approximately 26 mm away. Espressif
  recommends local 10 µF support on VDD3P3 and an additional 10 µF at the main
  power entrance when those locations are not close. On this board, they are
  not close.
- The isolated buck candidate's C2 is a local converter output capacitor;
  it does not replace the ESP32 module's local bypass capacitor.

These are integration requirements to review before adopting the buck.
They are **not** changes to the active source schematic or placement in this
PR. Preserve the current source design until an independently reviewed
adoption plan is ready.

### Thermal envelope — scenario only

At a 3.3 V / 500 mA output load (1.65 W), estimated converter loss is about
0.413 W at 80% efficiency, 0.291 W at 85%, and 0.183 W at 90%. Applying TI's
published reference RθJA values (58.2 °C/W for its JEDEC PCB and 48.7 °C/W
for its EVM) would yield indicative junction rises of roughly 24.0/20.1 °C,
16.9/14.2 °C, and 10.7/8.9 °C respectively. These are mathematical scenarios,
not a prediction for this candidate: the exact PCB copper weight/stackup,
enclosure, ambient, airflow and real efficiency are not established. The
board file has four copper layers and 1.6 mm overall thickness, but no 1 oz
copper specification. No thermal simulation or temperature measurement has
been performed.

## Current checks

- Native KiCad 10.0.8 schematic ERC: **0 errors / 0 warnings**. U3 pin classes reflect VIN/EN/MODE/SS/FB inputs, PG open-collector, VOUT output pair (one passive in the schematic symbol to represent the internally-paralleled output pin pair without a false output-to-output ERC finding) and GND passive. The PCB still carries both VOUT physical pads on VCC_3V3.
- Native KiCad 10.0.8 PCB DRC: **0 violations / 0 unconnected items**, with local candidate footprint libraries loaded. A further GND stitching via was added near EP pad 11 (outside the land/paste area); it remains on GND and passes the unchanged clearance rules. This checks the generated copper geometry and net continuity, not power conversion, loop stability, EMI, current/thermal margin or a real assembly.
- The TI drawing shows three optional 0.2 mm via positions under the exposed pad. They remain omitted because the existing project min finished drill is 0.30 mm and TI requires vias under paste to be filled, plugged or tented. No drill/clearance rule was weakened. One additional 0.30 mm finished-drill GND stitch is placed just outside EP pad 11 and its paste windows; it is not via-in-pad.
- No active source-board component replacement, default-pipeline change, PR merge, release, vendor contact or fabrication action.

## Official references

- [TI TPSM82901 datasheet](https://www.ti.com/lit/ds/symlink/tpsm82901.pdf)
- [TI TPSM82901EVM BSR188-001 user guide](https://www.ti.com/lit/ug/snvu796/snvu796.pdf)
- [TI TPSM82901 product page and CAD resources](https://www.ti.com/product/TPSM82901)
- [Ultra Librarian TPSM82901SISR CAD preview](https://app.ultralibrarian.com/details/e0386623-7ae6-11ed-b159-0a34d6323d74/Texas-Instruments/TPSM82901SISR)
- [TDK C1 DC-bias characterization, C3216X7R1E106K160AE](https://product.tdk.com/en/system/files/dam/doc/product/capacitor/ceramic/mlcc/charasheet/c3216x7r1e106k160ae_200122.pdf)
- [TDK C1 product data](https://product.tdk.com/en/search/capacitor/ceramic/mlcc/info?part_no=C3216X7R1E106K160AE)
- [TDK C2 product data and DC-bias characteristic, C2012X7S1A226M125AC](https://product.tdk.com/en/search/capacitor/ceramic/mlcc/info?part_no=C2012X7S1A226M125AC)
- [Espressif ESP32 schematic checklist — power supply recommendations](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32/schematic-checklist.html)
- [Espressif ESP32 hardware design guidelines — power traces and RF-related VDD3P3 placement](https://documentation.espressif.com/esp-hardware-design-guidelines/en/latest/esp32/index.html)
- [USB Type-C Specification, Release 2.0 — VBUS current detection and usage](https://www.usb.org/sites/default/files/USB%20Type-C%20Spec%20R2.0%20-%20August%202019.pdf)

**Decision:** retain as a review-only candidate. Do not replace U3 in the source board until the land pattern, layout, input-current budget, transient behavior, RF noise, capacitor DC-bias, thermal performance and native routed-board verification are complete.
