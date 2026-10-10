#!/usr/bin/env bash
# Review-only native KiCad board DRC. Never releases an unverified PCB.
set -euo pipefail
if (( $# != 2 )); then
    echo "Usage: $0 source.kicad_pcb review.kicad_pcb" >&2
    exit 2
fi
readonly CLI=/usr/bin/kicad-cli
readonly PYTHON=/usr/bin/python3
readonly TIMEOUT=/usr/bin/timeout
readonly ENV_BIN=/usr/bin/env
[[ -x "$CLI" && -x "$PYTHON" && -x "$TIMEOUT" && -x "$ENV_BIN" ]] || {
    echo "Requires installed system KiCad, Python and GNU timeout" >&2; exit 2;
}
source_pcb="$(realpath -e -- "$1")"
output_pcb="$(realpath -m -- "$2")"
[[ "$source_pcb" == *.kicad_pcb && "$output_pcb" == *.kicad_pcb ]] || exit 2
[[ "$source_pcb" != "$output_pcb" ]] || exit 2
[[ "$(dirname "$source_pcb")" == "$(dirname "$output_pcb")" ]] || exit 2
readonly source_pcb output_pcb
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly VERSION="$("$CLI" version)"
[[ "$VERSION" == 10.* ]] || { echo "KiCad 10 required: $VERSION" >&2; exit 2; }
readonly REVIEW_BASE="${output_pcb%.kicad_pcb}"
readonly CANDIDATE="${REVIEW_BASE}.candidate.kicad_pcb"
readonly MANIFEST="${REVIEW_BASE}.candidate-evidence.json"
readonly BASE_DRC="${REVIEW_BASE}.baseline-drc.rpt"
readonly REVIEW_DRC="${REVIEW_BASE}.review-drc.rpt"
cleanup() {
    rm -f -- "$CANDIDATE" "$MANIFEST" "${CANDIDATE%.kicad_pcb}.kicad_pro" "${CANDIDATE%.kicad_pcb}.kicad_prl"
}
trap cleanup EXIT
# A failed invocation must not leave behind a stale approved PCB or report.
rm -f -- "$output_pcb" "${REVIEW_BASE}.review-evidence.json" "$BASE_DRC" "$REVIEW_DRC" "$CANDIDATE" "$MANIFEST"
readonly HOME_DIR="$(getent passwd "$(id -u)" | cut -d: -f6)"
[[ -n "$HOME_DIR" && -d "$HOME_DIR" ]] || { echo "Missing system home directory" >&2; exit 2; }
run_native_drc() {
    local source_file="$1"
    local report="$2"
    local rc=0
    "$TIMEOUT" 120 "$ENV_BIN" -i HOME="$HOME_DIR" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
        "$CLI" pcb drc --exit-code-violations --output "$report" "$source_file" || rc=$?
    if (( rc != 0 && rc != 5 )); then
        echo "Native KiCad DRC execution failed ($rc)" >&2
        exit 1
    fi
    [[ -s "$report" ]] || { echo "Native KiCad DRC produced no report" >&2; exit 1; }
}
run_native_drc "$source_pcb" "$BASE_DRC"
"$PYTHON" -B "$SCRIPT_DIR/issue91_native_copper_review.py" prepare "$source_pcb" "$output_pcb"
run_native_drc "$CANDIDATE" "$REVIEW_DRC"
"$PYTHON" -B "$SCRIPT_DIR/issue91_native_copper_review.py" finalize "$source_pcb" "$output_pcb" --kicad-version "$VERSION"
