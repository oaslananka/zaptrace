# AI-native architecture pilot: local footprints and native oracle

**MSI only, no GitHub mutations.** Follow-up to the initial candidate compiler
for a 12-component/8-net USB-C, STM32, 3.3V 100mA, I2C sensor board.

## Component qualification

- R1/R2/R3/R4/R5 and C1/C2/C3 are assigned physical repository 0402
  geometry only when connected pad labels are exactly 1 and 2.
  This is a two-pad package family, not an authorized purchase/voltage rating.
- Generic U1 LDO is never given an arbitrary SOT-23-3 pin map.
  The pilot uses a local starter-library AP2112K-3.3TRG1 five-pin candidate:
  1 VIN, 2 GND, 3 EN, 4 NC, 5 VOUT. Exact vendor footprint pad inventory is
  verified before rewiring. VIN + EN -> VBUS, GND -> ground, VOUT -> 3.3 V rail.
  EN tied to VBUS is explicitly an always-on engineering assumption.
  Selection is restricted to a USB-C 5V and 3.3V rail with stated <=0.5A.
  The library still marks this record HEURISTIC and unreviewed; the official
  KiCad land pattern and Diodes suggested dimensions differ. Independent
  pinout/footprint/stability/sourcing review remains essential.
- Missing library source, altered pin map, unsupported output/current or pad
  count stays blocked; no invented device properties or approval.

## Independent observations

- Internal ZapTrace ERC: 29 checks; zero errors, zero warnings, down from
  eight ERC020 missing-footprint warnings, with known coverage gaps.
- Actual KiCad 10.0.7 native ERC JSON: 0 errors, 12 warnings (footprint
  library link problems), 4 ignored checks. Status BLOCKED. The regular
  CLI exit code can be zero despite violations; the oracle demands a fully
  clean JSON and uses --exit-code-violations.
- MSI has no ngspice: simulation NOT CHECKED. Physical routing, KiCad PCB
  DRC, transient models, KiCad/EasyEDA roundtrip and production review remain
  unverified, not represented as passes.
- Exact local source hash and candidate identity are protected by the
  existing SHA manifest. Oracle input SHA checking and existing-output refusal
  protect local evidence from stale/tampered accidental reuse.

Local paths: build/qa-036-passive-footprints/qualified-candidate/ and
build/qa-036-passive-footprints/oracle/oracle-evidence.json (complete
KiCad JSON report under the oracle/kicad folder).

Run another fresh local candidate and its independent oracle:

    .venv/bin/python -m scripts.ai_native_candidate_pilot \
      --intent 'USB-C powered STM32 MCU board, 3.3V rail at 100 mA, I2C temperature sensor' \
      --output-dir build/qa-036-passive-footprints/new-candidate

    .venv/bin/python -m scripts.ai_native_candidate_oracles \
      --candidate-dir build/qa-036-passive-footprints/new-candidate \
      --output-dir build/qa-036-passive-footprints/new-oracle

No live KiCad GUI, physical user project, GitHub or accepted Debian package is
touched. Local build evidence is not an authenticated signature.
