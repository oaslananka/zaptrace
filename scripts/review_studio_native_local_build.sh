#!/usr/bin/env bash
# Local build only; native PCB input stays unchanged, no git or network operations.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
DESIGN=build/source-reference-readonly/issue91-design.yaml
PCB=build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb
PROJECT=build/new-schematic-issue91-layout
OUTPUT=build/native-review
BASELINE=build/native-review-baseline
WORKSPACE=build/review-studio-workspace
for file in "$DESIGN" "$PCB"; do
  if [[ ! -f "$file" ]]; then echo "Missing verified local input: $file" >&2; exit 2; fi
done
sha256sum -c build/source-reference-readonly/checksums.sha256
if [[ "$(sha256sum "$DESIGN" | cut -d' ' -f1)" != eb04820edf793b8833dd6cf23a9c531402f52cf5af91c57c4f1a411787928c47 ]]; then
  echo "Design source checksum differs from pinned Issue #91 review input; refusing to generate." >&2
  exit 2
fi
if [[ ! -x .venv/bin/python ]]; then
  echo "Local project venv missing; initialize it with uv before proceeding." >&2
  exit 2
fi
PYTHONPATH="$ROOT" .venv/bin/python -B -m zaptrace.cli.main pipeline --source "$DESIGN" --output "$PROJECT"
/usr/bin/python3 scripts/review_studio_native_kicad.py \
  --board "$PCB" \
  --schematic "$PROJECT/kicad/ESP32_I2C_Sensor_Board.kicad_sch" \
  --design-source "$DESIGN" \
  --workspace-home "$WORKSPACE/index.html" \
  --output "$OUTPUT"
# A separate actual, un-routed PCB source is intentionally not the 61-track
# copper variant. All native DRC values come from independent local KiCad runs.
/usr/bin/python3 scripts/review_studio_native_kicad.py \
  --board "$PROJECT/kicad/ESP32_I2C_Sensor_Board.kicad_pcb" \
  --schematic "$PROJECT/kicad/ESP32_I2C_Sensor_Board.kicad_sch" \
  --design-source "$DESIGN" \
  --workspace-home "$WORKSPACE/index.html" \
  --output "$BASELINE"
/usr/bin/python3 scripts/review_studio_workspace.py --workspace "$WORKSPACE" register-many \
  --project 'ESP32 sensor · copper review (61 native traces)' "$OUTPUT" \
  --project 'ESP32 sensor · generated unrouted baseline' "$BASELINE"
printf '\nLOCAL ONLY: %s/%s/index.html\n' "$ROOT" "$WORKSPACE"
printf 'PCB details: %s/%s/index.html\n' "$ROOT" "$OUTPUT"
