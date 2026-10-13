# AI-native #33 — STM32F103 and USB4105 physical pin check (LOCAL)

This is MSI local-only source verification, not manufacturing, procurement,
board-routing or electronic engineering sign-off.

## Primary documentary basis

- ST DS5319 Rev 20 Fig 8: https://www.st.com/resource/en/datasheet/stm32f103c8.pdf
  LQFP48 physical pins 42 PB6, 43 PB7, 44 BOOT0; 10 PA0, 11 PA1;
  23/35/47 VSS and 24/36/48 VDD.
- ST RM0008 Rev 21 Table 55: default I2C1_SCL=PB6 and I2C1_SDA=PB7;
  remapped I2C1_SCL=PB8 and SDA=PB9 needs AFIO configuration.
  Previous compiler used PA0/PA1 as arbitrary GPIO pins, NOT I2C1.
- GCT USB4105 Rev B: https://gct.co/files/drawings/usb4105.pdf
  Independent specs: https://gct.co/files/specs/usb4105-spec.pdf
  Contact identities: VBUS A4/A9/B4/B9, GND A1/A12/B1/B12;
  CC1 A5, CC2 B5, S1 shell shield. KiCad USB4105 geometry is
  digest-pinned in repository verified_vendor module. High-risk
  orientation, shield copper, manufacturer land pattern and solder
  assembly remain unreviewed.

## Narrow contract

The source candidate uses ST documented 48-pin LQFP map, exact MPN and
datasheet identity; only exact prior PA0/PA1 bus topology is rewritten
as PB7(SDA) and PB6(SCL). Incorrect upstream net topology is refused.
Independent explicit GCT pin/contact table is compared against both
library and actual SHA-vetted vendored KiCad footprint. A mutated
library map cannot self-certify. 16 contacts, four repeated S1 shield
lands and two anonymous NPTH holes are bounded and verified.

The inspection-only KiCad footprint generator permits precisely those
two actual unplated alignment holes; unnamed electrical copper pads
still fail. Source SHA/candidate ID are saved and verified and never
replaced with separate KiCad adapter output.

## Independent measured local result

- New exact source candidate and native KiCad outputs:
  build/qa-038-physical-pin-source/candidate/
  build/qa-038-physical-pin-source/oracle/
- Native KiCad 10.0.7 export: 12 components, 8 nets, all 52/52
  source-backed logical pin, pad ID and net nodes match in KiCad XML.
  This improves prior fixture's 34/48 scoped matches.
- Physical repeated-pad proof still blocked: the four USB S1 pads
  share a KiCad netlist pin label but no native PCB copper connectivity
  test confirms each shell pad independently. Do not mark globally passed.
- Genuine ERC: zero errors / zero warnings; four KiCad ignored checks,
  so ERC overall remains BLOCKED and no check was waived.
- SPICE not checked: MSI lacks ngspice; routed PCB DRC, simulation,
  two-EDA interchange, manufacturing and human sign-off all pending.
- ST and GCT manufacturer source data do not imply lifecycle,
  orderable-part qualification, correct fabrication land pattern, or
  full board fitness.

## Next

Verify each GCT repeated physical S1 pad with actual native PCB copper
net connectivity and independently review four ignored KiCad checks.
Continue #33 only until its accepted gates can be fairly demonstrated.
No new dependencies, GitHub writes or live user GUI.
