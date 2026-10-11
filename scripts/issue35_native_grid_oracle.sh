#!/usr/bin/env bash
# Independent, real KiCad 10 DRC: two unrouted PTH nets -> routed zero violations.
set -euo pipefail
if (( $# > 2 )); then
  echo "Usage: $0 [output-dir] [--smd]" >&2
  exit 2
fi
readonly CLI=/usr/bin/kicad-cli
readonly PYTHON=/usr/bin/python3
readonly TIMEOUT=/usr/bin/timeout
readonly ENV_BIN=/usr/bin/env
for bin in "$CLI" "$PYTHON" "$TIMEOUT" "$ENV_BIN"; do
  test -x "$bin" || { echo "Required system tool absent: $bin" >&2; exit 2; }
done
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
ROOT="$(dirname "$SCRIPT_DIR")"
readonly ROOT
DEST="$(realpath -m -- "${1:-$ROOT/build/issue35-native-grid}")"
readonly DEST
KICAD_VERSION="$("$CLI" version)"
readonly KICAD_VERSION
[[ "$KICAD_VERSION" == 10.* ]] || { echo "KiCad 10 required: $KICAD_VERSION" >&2; exit 2; }
mkdir -p -- "$DEST"
# Use a clean temporary output directory rather than trusting cached reports.
TEMP="$(mktemp -d "$DEST/.native-XXXXXXXX")"
readonly TEMP
cleanup() { rm -rf -- "$TEMP"; }
trap cleanup EXIT
HOME_DIR="$(getent passwd "$(id -u)" | cut -d: -f6)"
readonly HOME_DIR
test -d "$HOME_DIR" || { echo "System account HOME missing" >&2; exit 2; }
run_python() {
  "$ENV_BIN" -i HOME="$HOME_DIR" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONPATH="$ROOT" \
    "$PYTHON" -B "$SCRIPT_DIR/issue35_native_grid_fixture.py" "$1" "$TEMP"
}
readonly UV_PYTHON="$ROOT/.venv/bin/python"
test -x "$UV_PYTHON" || { echo "Use uv sync --locked --all-extras --all-groups first" >&2; exit 2; }
if [[ "${2:-}" == "--smd" ]]; then
  readonly PLAN_SCRIPT="$SCRIPT_DIR/issue35_smd_native_plan.py"
  readonly EXPECTED_BEFORE=1
elif [[ -z "${2:-}" ]]; then
  readonly PLAN_SCRIPT="$SCRIPT_DIR/issue35_grid_native_plan.py"
  readonly EXPECTED_BEFORE=2
else
  echo "Unknown fixture mode: $2" >&2
  exit 2
fi
"$UV_PYTHON" -B "$PLAN_SCRIPT" "$TEMP"
run_python prepare
for board in baseline routed; do
  rc=0
  "$TIMEOUT" 75 "$ENV_BIN" -i HOME="$HOME_DIR" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    "$CLI" pcb drc --exit-code-violations --output "$TEMP/$board.rpt" "$TEMP/$board.kicad_pcb" || rc=$?
  if [[ "$board" == baseline && "$rc" != 5 ]]; then
    echo "Baseline must contain unconnected pads (KiCad exit 5), found exit $rc" >&2
    exit 1
  fi
  if [[ "$board" == routed && "$rc" != 0 ]]; then
    echo "Routed board failed native KiCad DRC with exit $rc" >&2
    exit 1
  fi
done
if [[ "${2:-}" == "--smd" ]]; then
  unsafe_rc=0
  "$TIMEOUT" 75 "$ENV_BIN" -i HOME="$HOME_DIR" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    "$CLI" pcb drc --exit-code-violations --output "$TEMP/unsafe.rpt" "$TEMP/unsafe.kicad_pcb" || unsafe_rc=$?
  if [[ "$unsafe_rc" != 5 ]]; then
    echo "Deliberately shorted SMD negative control must fail native KiCad DRC (exit 5): $unsafe_rc" >&2
    exit 1
  fi
fi
run_python verify
# Commit evidence only after both independent native DRC passes.
for item in baseline.kicad_pcb routed.kicad_pcb baseline.rpt routed.rpt manifest.json route-plan.json; do
  cp -- "$TEMP/$item" "$DEST/$item"
done
if [[ "${2:-}" == "--smd" ]]; then
  cp -- "$TEMP/unsafe.kicad_pcb" "$TEMP/unsafe.rpt" "$DEST/"
fi
echo "Independent KiCad $KICAD_VERSION: $EXPECTED_BEFORE -> 0 unconnected, 0 new DRC violations"
