# AI-native pilot — physical footprint root-cause repair (MSI local)

This is a SOURCE-BOUND **unrouted** KiCad placement experiment. It is not
production approval, physical-device signoff, a release or a GitHub update.

## Verified problem

The initial 12-component / 8-net source-bound KiCad 10.0.7 board had
42 unconnected items and 445 other DRC findings, including 9 shorting,
277 clearance and 131 solder-mask bridge violations. **Every short, all
277 clearance findings and all 131 mask bridges occurred on U2 STM32.**
The older generic footprint resolver had placed 48 LQFP leads along
incompatible temporary pad geometry, causing overlapping copper and mask.

## Bounded correction in a derived placement only

The original candidate, nets and SHA remain unchanged. Local
`scripts/ai_native_pilot_placement_geometry.py` requires exact ST
`STM32F103C8T6` / LQFP-48 and Sensirion SHT31 identities and
uses only the previously checked-in KiCad official pad geometries:

- LQFP-48_7x7mm_P0.5mm, original digest:
  `ec36273cf5fa99acf022c2f5af17310d123fa4b5ccfe98a2f562fedabe7f3f46`
- Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm:
  `2380f3b4d6982902f05e8940603f19f7cfbc1bdfd6ae0f78ebd281c1a3f30a8f`

Original part ID, pin numbering, 48/9 physical pad inventories and
physical SHA are verified; any mismatches refuse the derived design.
ST's STM32F103C8 datasheet DS5319 Rev 20 specifies LQFP48 7x7 mm:
https://www.st.com/resource/en/datasheet/stm32f103c8.pdf

GCT USB4105 is placed at the **provisional** 100×80 mm PCB bottom
edge. The vendored footprint's `Dwgs.User` board-edge line lies at
relative Y=3.675 mm, so local J1 center is (50,76.325 mm). This is
geometric alignment to a KiCad drawing marker only, not validated
mating/connector envelope, shield mounting, fabrication or enclosure
approval. Manufacturer drawing:
https://gct.co/files/drawings/usb4105.pdf

## Actual independent KiCad result

Artifacts in `build/qa-041-vendor-footprints/placement-v1/`.
Against `build/qa-040-native-placement/source-bound-final/`:

- **9 → 0** shorts.
- **277 → 0** copper clearance violations.
- **131 → 0** solder-mask bridge violations.
- **445 → 16** other DRC findings total.
- **42 → 43** unrouted connections (new placement, still 0 tracks/zones).

Remaining native DRC findings: **12 lib_footprint_mismatch**, caused
by the difference between local synthetic footprint instance metadata
and project-local library templates; **4 hole_clearance** at two GCT
USB4105 anonymous mechanical alignment holes adjacent to electrical
contact pads. Do not waive either set or alter genuine vendor drill
geometry without reviewed authority. Five DRC checks are still
ignored by baseline project defaults and require coverage review.

All 12 schematic↔PCB UUID paths, every physical pad net and four
separate J1.S1 GND UUIDs must remain verified. Source candidate SHA is
still `34b97dd4fba4034b4605998e27d5a3cb7a20c210f16f233be406c6f613c863df`.
This is only geometry/source compatibility evidence; SPICE remains
NOT CHECKED, production approval FALSE and routing remains incomplete.

## Next

Resolve the library/PCB instance mismatch with a single authoritative
footprint, verify the four GCT drill clearances against original
manufacturing drawings without any rule waivers, then run native KiCad
DRC and validate J1 shell copper before proceeding with #35 routing.
