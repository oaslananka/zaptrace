# AI-native pilot: portable KiCad inspection library and strict native oracle

> **Historical engineering experiment (October 2026).** This page records an earlier local-only investigation, not the current publication, validation or manufacturing status. The original no-GitHub-change statements describe the experiment at that time; its source was later included in the recovery integration PR. No fabrication approval is implied.

**Scope:** User-approved #33 local workstation-only vertical slice. The project-local
footprint library below is NOT a general EDA exporter change or a
fabrication/engineering approval. No GitHub writes, packages, user GUI
operations or new dependencies.

## Root cause / correction

The KiCad schematic originally referenced unqualified footprint names such
as 0402, USB-C-16P-SMD and AP2112K-3.3TRG1-SOT25. These lacked the mandatory
KiCad library nickname and project-local footprint tables. Genuine KiCad 10.0.7
reported 12 footprint_link_issues.

The pilot-only inspection adapter uses the existing physical pad geometry
from the original SHA-bound candidate and fills geometry on the isolated
oracle copy through the existing footprint resolver. It then writes a
project-local ZapTracePilot.pretty library, KiCad fp-lib-table with a portable
project-relative URI, and ref-specific named footprint definitions. Every
generated footprint is re-imported and compared to its source across pad ID,
shape, dimensions, position, layer, drill, plating, solder paste, rotation
and roundrect corner ratio. An unsupported/missing original pad definition,
malicious pad ID, or altered geometry is refused, not fabricated. One sensor
pad with no solder paste is explicitly preserved.

Source candidate artifacts and the original component footprint identifiers
are NOT modified. These generated library assets are only a physical
inspection adapter: their graphical outline and manufacturer land-pattern
qualification have NOT been independently certified.

Real KiCad 10.0.7 ERC on the exact same candidate: 12 -> 0 warnings;
0 errors both before and after. **Four previously ignored KiCad checks
remain**: footprint_filter, simulation_model_issue, single_global_label,
four_way_junction. Nothing was waived or suppressed; native full ERC
acceptance remains BLOCKED until check coverage is independently proved.

## Independent schematic -> physical pad/net check

Export actual KiCad native XML netlist, and compare each connected
(ref, physical pad, named net) against the canonical source logical net,
component package_pin_map and actual footprint pad IDs.

Real pilot: 12 components, 8 nets, 48 native connected pin nodes,
34 matching. Reasons include 14 extra/unmatched KiCad nodes, 9 MCU pins
without physical mapping and 5 USB connector logical pins mapping to pads
absent from the selected geometry. Counts overlap: they are diagnostics,
not percentages of total electrical completeness. The pin/net gate is
BLOCKED. KiCad ERC 0 warnings does not certify real MCU or USB wiring.

SPICE is NOT CHECKED because local workstation lacks ngspice; no new dependency installed.

## Evidence and reproduction

Source candidate: build/qa-036-passive-footprints/qualified-candidate/
Native report: build/qa-037-native-portable/oracle-mask-preserved/oracle-evidence.json
Actual native KiCad XML, ERC JSON, .pretty footprints and tables:
build/qa-037-native-portable/oracle-mask-preserved/kicad/

From local workstation repository root, use a new (non-existing) target directory:

    .venv/bin/python -m scripts.ai_native_candidate_oracles \
      --candidate-dir build/qa-036-passive-footprints/qualified-candidate \
      --output-dir build/qa-037-native-portable/fresh-oracle

Still open: manufacturer-qualified MCU physical pin map; exact USB-C
footprint/pad correspondence; independent KiCad ignored-check review; SPICE
models/simulator; routed PCB, multi-EDA fidelity and accountable proof pack.
No real human engineer or fabrication sign-off.
