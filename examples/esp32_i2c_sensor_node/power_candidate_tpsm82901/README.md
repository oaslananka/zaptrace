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

The candidate board is set to four copper layers: F.Cu, In1.Cu, In2.Cu and B.Cu. A broad GND zone is present on all four layers; VIN and VOUT have local top-layer copper regions and In1.Cu spreading islands. CIN is next to VIN, COUT next to VOUT, the FB divider/CFF are close to FB, the MODE resistor faces MODE/S-CONF and the SS capacitor faces SS/TR. The first-pass layout contains 15 copper track segments and 10 through-vias (0.60 mm copper / 0.30 mm finished drill). The boundary VIN/3V3 feeds, local signal routes, PG return and power/GND zone fills are connected. All designators remain visible on KiCad F.Fab for review; they are not placed on F.Silkscreen, keeping the switching-power area and solder-mask clear. Native KiCad reports zero unconnected items. This is a first-pass topology/layout candidate; copper distribution and the 4-layer GND reference still require detailed EMI, transient, current-density and thermal review.

TI states that SW/NC must remain floating; any copper beneath it must be small, electrically floating, isolated from inner layers and have no vias. Pad 8 has no net, and an all-copper-layer rule area blocks tracks, vias and zone fills beneath/around the package pad. The DRC report shows no items in that keepout.

## Current checks

- Native KiCad 10.0.8 schematic ERC: **0 errors / 0 warnings**. U3 pin classes reflect VIN/EN/MODE/SS/FB inputs, PG open-collector, VOUT output pair (one passive in the schematic symbol to represent the internally-paralleled output pin pair without a false output-to-output ERC finding) and GND passive. The PCB still carries both VOUT physical pads on VCC_3V3.
- Native KiCad 10.0.8 PCB DRC: **0 violations / 0 unconnected items**, with local candidate footprint libraries loaded. This checks the generated copper geometry and net continuity, not power conversion, loop stability, EMI, current/thermal margin or a real assembly.
- The TI drawing shows three optional 0.2 mm via positions under the exposed pad. They remain omitted because the existing project min finished drill is 0.30 mm and TI requires vias under paste to be filled, plugged or tented. No drill/clearance rule was weakened.
- No active source-board component replacement, default-pipeline change, PR merge, release, vendor contact or fabrication action.

## Official references

- [TI TPSM82901 datasheet](https://www.ti.com/lit/ds/symlink/tpsm82901.pdf)
- [TI TPSM82901EVM BSR188-001 user guide](https://www.ti.com/lit/ug/snvu796/snvu796.pdf)
- [TI TPSM82901 product page and CAD resources](https://www.ti.com/product/TPSM82901)
- [Ultra Librarian TPSM82901SISR CAD preview](https://app.ultralibrarian.com/details/e0386623-7ae6-11ed-b159-0a34d6323d74/Texas-Instruments/TPSM82901SISR)

**Decision:** retain as a review-only candidate. Do not replace U3 in the source board until the land pattern, layout, input-current budget, transient behavior, RF noise, capacitor DC-bias, thermal performance and native routed-board verification are complete.
