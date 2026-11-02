# TPSM82901SISR review-only power-stage candidate

**Status: internal review candidate only — not part of the active ESP32 source design, not routed, not thermally qualified and not for fabrication.**

This isolated KiCad project evaluates a lower-loss 5 V → 3.3 V buck replacement for the current AMS1117 placeholder. It is intentionally separate from examples/esp32_i2c_sensor_node/design.yaml. The component placement shown is a non-overlapping review placeholder, not a switching-power layout.

## Exact device and pin contract

- Production orderable MPN: TPSM82901SISR (TI product addendum dated 2026-02-06 lists it Active / Production; uSiP SIS, 11 pins).
- Package: SIS0011A, 3.0 × 2.8 × 1.6 mm max, integrated 1 µH inductor.
- Pins: 1/2 VIN; 3 EN; 4 MODE/S-CONF; 5 SS/TR; 6 PG; 7 FB/VSET; 8 SW/NC; 9/10 VOUT; 11 exposed GND.
- Pin 8 is intentionally floating (no net, no copper). Pin 11 must be soldered to the common ground plane.
- The 11-pad local footprint is explicitly marked DRAFT and is not promoted into ZapTrace's verified vendor-footprint registry. Its 10 perimeter lands use the TI example's 0.55 mm × 0.25 mm pad dimensions and 0.5 mm pitch; pad 11 uses the 0.9 mm × 2.1 mm exposed thermal-land outline. Copper/paste/mask tolerances, solder-mask-defined construction and thermal-via locations still require direct review against the TI SIS0011A land-pattern drawing and selected assembly process.

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

The candidate board is set to four copper layers, as TI's thermal guidance recommends at least four layers with 1 oz copper. However, thermal GND/VIN/VOUT vias, the continuous GND planes, current loops, FB routing, switching-node keepout, and thermal copper have **not** been laid out. The generated board deliberately contains no tracks or vias (22 airwires remain). KiCad DRC therefore checks package/library consistency and geometric rule violations, not functional routing or thermal performance.

TI states that SW/NC must remain floating; if copper is used beneath it, that copper must be small, electrically floating, isolated from inner layers, and have no vias. This candidate leaves pad 8 without a net and no copper connection.

## Current checks

- Native KiCad 10.0.8 schematic ERC: zero errors; the connectivity-only generated symbol still has 20 warnings (9 symbol/footprint link mismatches and 11 off-grid endpoints). The embedded symbol currently models pins as passive for net export, not as a reviewed electrical symbol. These are review-export warnings, not an electrical pass.
- Native KiCad 10.0.8 PCB DRC: zero violations with local candidate footprint libraries loaded.
- Unconnected: 22, expected because the candidate is not routed.
- No source-board component replacement, no power-net routing, no default-pipeline change, no merge/release/fabrication action.

## Official references

- [TI TPSM82901 datasheet](https://www.ti.com/lit/ds/symlink/tpsm82901.pdf)
- [TI TPSM82901EVM BSR188-001 user guide](https://www.ti.com/lit/ug/snvu796/snvu796.pdf)
- [TI TPSM82901 product page and CAD resources](https://www.ti.com/product/TPSM82901)
- [Ultra Librarian TPSM82901SISR CAD preview](https://app.ultralibrarian.com/details/e0386623-7ae6-11ed-b159-0a34d6323d74/Texas-Instruments/TPSM82901SISR)

**Decision:** retain as a review-only candidate. Do not replace U3 in the source board until the land pattern, layout, input-current budget, transient behavior, RF noise, capacitor DC-bias, thermal performance and native routed-board verification are complete.
