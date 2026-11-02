#!/usr/bin/env bash
# Real Debian installed server in disposable Ubuntu 24.04 container,
# real host Chrome via Docker --network=host. No host package install.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
NAME=${ZAPTRACE_UBUNTU_QA_CONTAINER:-zaptrace-0112-qa-20261012}
DEB=${1:-build/distribution/zaptrace-review-studio_0.1.12_all.deb}
DEB=$(realpath -- "$DEB")
test "${DEB##*/}" = zaptrace-review-studio_0.1.12_all.deb
(cd "$(dirname "$DEB")" && sha256sum -c "$(basename "$DEB" .deb).sha256")
SHA=$(sha256sum "$DEB" | cut -d ' ' -f1)
docker inspect --format '{{.HostConfig.NetworkMode}}' "$NAME" | grep -Fx 'host' >/dev/null
docker exec "$NAME" test -f /usr/lib/zaptrace-review-studio/scripts/review_studio_native_copper_link.py
docker exec "$NAME" test -f /usr/lib/zaptrace-review-studio/scripts/review_studio_local_server.py
docker exec "$NAME" test -f /usr/lib/zaptrace-review-studio/scripts/review_studio_native_copper_batch.py
test -f build/qa-012-release-20261012/PORTABLE_ESP32_CUSTOM_REFERENCE.zip
QA=$(mktemp -d /tmp/zaptrace-0112-ubuntu-installed-browser-XXXXXX)
chmod 700 "$QA"
SPID='' CPID='' URL='' TOKEN=''
cleanup(){
 if [[ -n "$TOKEN" && -n "$URL" ]];then
   curl -fsS -X POST -H "Origin: $URL" -H "X-Review-Token: $TOKEN" "$URL/api/shutdown" -d '{}' >/dev/null 2>&1||true
 fi
 if [[ -n "$CPID" ]];then
   kill -TERM -- "-$CPID" 2>/dev/null||true
   sleep .4
   kill -KILL -- "-$CPID" 2>/dev/null||true
   wait "$CPID" 2>/dev/null||true
 fi
 if [[ -n "$SPID" ]];then
   for n in 1 2 3 4 5 6 7 8 9 10;do kill -0 "$SPID" 2>/dev/null||break;sleep .2;done
   if kill -0 "$SPID" 2>/dev/null;then kill "$SPID" 2>/dev/null||true;fi
   wait "$SPID" 2>/dev/null||true
 fi
 for n in 1 2 3 4 5 6 7 8;do
   rm -rf -- "$QA" 2>/dev/null||true
   if [[ ! -e "$QA" ]];then return 0;fi
   sleep .3
 done
 echo "Chrome test temporary assets could not be removed: $QA" >&2
 return 1
}
trap cleanup EXIT
PORTS=$(python3 -B - <<'PY'
import socket
s=[socket.socket() for i in range(2)]
for sock in s:sock.bind(('127.0.0.1',0))
print(' '.join(str(sock.getsockname()[1]) for sock in s))
for sock in s:sock.close()
PY
)
read -r PORT CHROME_PORT <<< "$PORTS"
URL="http://127.0.0.1:$PORT"
docker exec "$NAME" /usr/bin/python3 -B -u /usr/lib/zaptrace-review-studio/scripts/review_studio_local_server.py \
 --workspace /tmp/zaptrace-0112-ubuntu-actually-installed-browser --port "$PORT" > "$QA/server.log" 2>&1 &
SPID=$!
for n in $(seq 1 110);do
 if grep -q "LOCAL REVIEW STUDIO:" "$QA/server.log";then break;fi
 kill -0 "$SPID" 2>/dev/null || { cat "$QA/server.log" >&2; exit 2; }
 sleep .14
done
grep -q "LOCAL REVIEW STUDIO:" "$QA/server.log"
TOKEN=$(python3 -B - "$URL" <<'PY'
import re,sys,urllib.request
base=sys.argv[1]
with urllib.request.urlopen(base+"/",timeout=10) as resp:
 body=resp.read().decode()
found=re.search(r'window\.__REVIEW_LOCAL__=\{token:"([^"]+)"',body)
assert found,"Installed Ubuntu app did not offer guarded localhost session"
print(found.group(1))
PY
)
setsid google-chrome --headless=new --no-sandbox --disable-dev-shm-usage --disable-gpu --no-first-run \
 --remote-debugging-address=127.0.0.1 --remote-debugging-port="$CHROME_PORT" \
 --remote-allow-origins='*' --user-data-dir="$QA/chrome" "$URL/" >"$QA/chrome.log" 2>&1 &
CPID=$!
export ZAPTRACE_CHROME_PORT="$CHROME_PORT"
export ZAPTRACE_COPPER_ZIP="$PWD/build/qa-012-release-20261012/PORTABLE_ESP32_CUSTOM_REFERENCE.zip"
export ZAPTRACE_COPPER_DOWNLOAD_DIR="$QA/downloads-via"
export ZAPTRACE_COPPER_VIA_PAIR=1
export ZAPTRACE_COPPER_CUSTOM_RULES=1
node scripts/review_studio_native_copper_browser_smoke.mjs
test -s "$QA/downloads-via/native-copper-project.zip"
test -s "$QA/downloads-via/EVIDENCE.json"
unset ZAPTRACE_COPPER_VIA_PAIR
export ZAPTRACE_COPPER_DOWNLOAD_DIR="$QA/downloads-legacy"
node scripts/review_studio_native_copper_browser_smoke.mjs
export ZAPTRACE_COPPER_BATCH=1
export ZAPTRACE_COPPER_VIA_PAIR=1
export ZAPTRACE_COPPER_DOWNLOAD_DIR="$QA/downloads-batch"
node scripts/review_studio_native_copper_browser_smoke.mjs
python3 -B - "$QA/downloads-batch/EVIDENCE.json" <<'PY_VERIFY_012_BROWSER_BATCH'
import json,sys
e=json.load(open(sys.argv[1]))
assert e['distinct_nets']==['GND','VCC_3V3'] and e['cumulative_drc']['after_unconnected']==35
assert e['cumulative_drc']['after_violations']==16 and e['fabApproved'] is False
print('UBUNTU_24_04_APT_0112_MULTINET_BATCH_CHROME=PASS')
PY_VERIFY_012_BROWSER_BATCH
unset ZAPTRACE_COPPER_BATCH
unset ZAPTRACE_COPPER_VIA_PAIR
export ZAPTRACE_PCB_ECO_SOURCE="$PWD/tests/fixtures/review_studio_native_eco_placement.kicad_pcb"
export ZAPTRACE_PCB_ECO_SHOTS="$QA"
export ZAPTRACE_PCB_ECO_ROTATE=90
node scripts/review_studio_pcb_eco_workspace_browser_smoke.mjs
export ZAPTRACE_ECO_SOURCE="$PWD/tests/fixtures/review_studio_native_eco_sensor.kicad_sch"
export ZAPTRACE_ECO_SHOTS="$QA"
node scripts/review_studio_schematic_eco_workspace_browser_smoke.mjs
(cd "$(dirname "$DEB")" && sha256sum -c "$(basename "$DEB" .deb).sha256")
echo "PACKAGE_SHA256=$SHA"
echo 'UBUNTU_24_04_REAL_APT_INSTALLED_SERVER_PLUS_HOST_CHROME_NATIVE_COPPER_PCB_ROTATE_SCHEMATIC_ECO=PASS'
echo 'UBUNTU_24_04_APT_0112_CUSTOM_DRC_AND_TWO_VIA_CHROME=PASS'
