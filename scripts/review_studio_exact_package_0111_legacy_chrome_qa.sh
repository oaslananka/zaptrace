#!/usr/bin/env bash
# Exact Debian package regression: real KiCad 10 PCB placement/rotation,
# standalone schematic value ECO, source-only schematic/PCB parity in Chrome.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
DEB=${1:-build/distribution/zaptrace-review-studio_0.1.11_all.deb}
DEB=$(realpath -- "$DEB")
test "${DEB##*/}" = zaptrace-review-studio_0.1.11_all.deb
(cd "$(dirname -- "$DEB")" && sha256sum -c "$(basename -- "$DEB" .deb).sha256")
QA=$(mktemp -d /tmp/zaptrace-0111-installed-legacy-chrome-XXXXXX)
chmod 700 "$QA"
SPID='' CPID=''
cleanup(){
 if [[ -n "$CPID" ]]; then
   kill -TERM -- "-$CPID" 2>/dev/null||true
   sleep .35
   kill -KILL -- "-$CPID" 2>/dev/null||true
   wait "$CPID" 2>/dev/null||true
 fi
 if [[ -n "$SPID" ]]; then kill "$SPID" 2>/dev/null||true; wait "$SPID" 2>/dev/null||true; fi
 for i in 1 2 3 4 5 6 7 8;do
   if rm -rf -- "$QA" 2>/dev/null && [[ ! -e "$QA" ]];then return 0;fi
   sleep .35
 done
 echo "Incomplete disposable Chrome QA cleanup: $QA" >&2
 return 1
}
trap cleanup EXIT
dpkg-deb -x "$DEB" "$QA/installed"
PACKAGED="$QA/installed/usr/lib/zaptrace-review-studio/scripts"
test -s "$PACKAGED/review_studio_local_server.py"
mkdir -p "$QA/screen"
PORTS=$(python3 -B - <<'PY'
import socket
s=[socket.socket() for i in range(2)]
for x in s:x.bind(('127.0.0.1',0))
print(' '.join(str(x.getsockname()[1]) for x in s))
for x in s:x.close()
PY
)
read -r PORT CHROME_PORT <<< "$PORTS"
/usr/bin/python3 -B -u "$PACKAGED/review_studio_local_server.py" --workspace "$QA/workspace" --port "$PORT" >"$QA/server.log" 2>&1 &
SPID=$!
for i in $(seq 1 90);do
 grep -q 'LOCAL REVIEW STUDIO:' "$QA/server.log" && break
 kill -0 "$SPID" 2>/dev/null || { cat "$QA/server.log" >&2;exit 2;}
 sleep .12
done
grep -q 'LOCAL REVIEW STUDIO:' "$QA/server.log"
setsid google-chrome --headless=new --no-sandbox --disable-dev-shm-usage --disable-gpu --no-first-run \
 --remote-debugging-address=127.0.0.1 --remote-debugging-port="$CHROME_PORT" \
 --remote-allow-origins='*' --user-data-dir="$QA/chrome" \
 "http://127.0.0.1:$PORT/" >"$QA/chrome.log" 2>&1 &
CPID=$!
export ZAPTRACE_CHROME_PORT="$CHROME_PORT"
export ZAPTRACE_PCB_ECO_SOURCE="$PWD/tests/fixtures/review_studio_native_eco_placement.kicad_pcb"
export ZAPTRACE_PCB_ECO_SHOTS="$QA/screen"
export ZAPTRACE_PCB_ECO_ROTATE=90
node scripts/review_studio_pcb_eco_workspace_browser_smoke.mjs
export ZAPTRACE_PCB_ECO_ROTATE=0
node scripts/review_studio_pcb_eco_workspace_browser_smoke.mjs
export ZAPTRACE_ECO_SOURCE="$PWD/tests/fixtures/review_studio_native_eco_sensor.kicad_sch"
export ZAPTRACE_ECO_SHOTS="$QA/screen"
node scripts/review_studio_schematic_eco_workspace_browser_smoke.mjs
export ZAPTRACE_PARITY_SCHEMATIC="$PWD/build/source-reference-readonly/ESP32_I2C_Sensor_Board.kicad_sch"
export ZAPTRACE_PARITY_PCB="$PWD/build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"
export ZAPTRACE_PARITY_DOWNLOAD_DIR="$QA/private-parity-download"
node scripts/review_studio_parity_audit_browser_smoke.mjs
(cd "$(dirname -- "$DEB")" && sha256sum -c "$(basename -- "$DEB" .deb).sha256")
echo "PACKAGE_SHA256=$(sha256sum "$DEB" | cut -d ' ' -f1)"
echo 'Exact package 0.1.11 Chrome quarter-turn and private parity audit: PASS'
echo 'Exact package 0.1.11 schematic ECO/PCB move/rotation with native KiCad and no original overwrite: PASS'
