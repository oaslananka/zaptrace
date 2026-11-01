#!/usr/bin/env bash
# Exact-source Debian 0.1.20 native viewer, workflow and touch/keyboard QA.
# Extract only; no host install, no release/signing, disposable private workdir.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
DEB=$ROOT/build/distribution/zaptrace-review-studio_0.1.20_all.deb
SHA=$(sha256sum "$DEB" | cut -d ' ' -f1)
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.20_all.sha256)
test "$(dpkg-deb -f "$DEB" Version)" = '0.1.20'
QA=$(mktemp -d /tmp/zaptrace-020-installed-qa-XXXXXX)
chmod 700 "$QA"
SPID='' CPID=''
cleanup(){
 local rc=$?
 trap - EXIT
 if [[ -n "$CPID" ]];then kill -TERM -- "-$CPID" 2>/dev/null||true; sleep .4;kill -KILL -- "-$CPID" 2>/dev/null||true;wait "$CPID" 2>/dev/null||true;fi
 if [[ -n "$SPID" ]];then kill "$SPID" 2>/dev/null||true;wait "$SPID" 2>/dev/null||true;fi
 for retry in 1 2 3 4 5 6;do rm -rf -- "$QA" 2>/dev/null||true; test ! -e "$QA" && break;sleep .2;done
 if [[ -e "$QA" ]];then echo 'QA_TEMP_CLEANUP_FAILED' >&2;exit 6;fi
 exit "$rc"
}
trap cleanup EXIT
mkdir -p "$QA/installed" "$QA/workspace" "$QA/shots"
dpkg-deb -x "$DEB" "$QA/installed"
PACKAGED="$QA/installed/usr/lib/zaptrace-review-studio/scripts"
test -f "$PACKAGED/review_studio_native_template.html"
"$QA/installed/usr/bin/zaptrace-review-studio" --version | grep -F '0.1.20'
"$QA/installed/usr/bin/zaptrace-review-studio" --doctor
cp -a build/review-studio-workspace/. "$QA/workspace/"
cp -a build/native-review "$QA/workspace/native-review-copper"
cp -a build/native-review-baseline "$QA/workspace/native-review-baseline"
# Rehydrate with the EXACT installed native UI and preserve provenance source
# JSON. Never rewrite the canonical sample or any user KiCad source.
QA_ROOT="$QA/workspace" PKG_ROOT="$PACKAGED" QA_DIR="$QA" python3 -B - <<'PY_SETUP'
from pathlib import Path
import os,re,json,hashlib
root=Path(os.environ['QA_ROOT']); source=Path(os.environ['PKG_ROOT']); private=Path(os.environ['QA_DIR'])
view=(source/'review_studio_native_template.html').read_text()
assert 'inspector-tab-issues' in view
entries=json.loads((root/'projects.json').read_text())
for i,record in enumerate(entries['projects']):
 review=(root/('native-review-copper' if i==0 else 'native-review-baseline')).resolve()
 record['review']=str(review)
 target=review/'index.html';old=target.read_text()
 match=re.search(r'(?m)^const DATA=(.*);$',old)
 back=re.search(r'<a class="project-back" id="workspaceHome".*?</a>',old)
 assert match and back
 data=json.loads(match.group(1))
 assert record['sha']==data['source_sha256']
 rebuilt=view.replace('__NATIVE_DATA__',match.group(1)).replace('__WORKSPACE_LINK__',back.group())
 assert 'inspector-tab-issues' in rebuilt and '__NATIVE_DATA__' not in rebuilt
 target.write_text(rebuilt)
 if i==0:
  opaque=hashlib.sha256(str(review).encode()).hexdigest()[:24]
  (private/'native-url-path').write_text('review-assets/'+opaque+'/index.html')
(root/'projects.json').write_text(json.dumps(entries,indent=2)+'\n')
print('EXACT_020_INSTALLED_NATIVE_UI_AND_SOURCE_SHA_VALIDATION=PASS')
PY_SETUP
PORTS=$(python3 -B - <<'PY'
import socket
s=[socket.socket() for _ in range(2)]
for x in s:x.bind(('127.0.0.1',0))
print(' '.join(str(x.getsockname()[1]) for x in s))
for x in s:x.close()
PY
)
read -r PORT CHROME_PORT <<< "$PORTS"
URL="http://127.0.0.1:$PORT/"
/usr/bin/python3 -B -u "$PACKAGED/review_studio_local_server.py" --workspace "$QA/workspace" --port "$PORT" > "$QA/server.log" 2>&1 &
SPID=$!
for i in $(seq 1 90);do grep -q 'LOCAL REVIEW STUDIO:' "$QA/server.log" && break; kill -0 "$SPID" 2>/dev/null || { cat "$QA/server.log";exit 3;};sleep .15;done
grep -q 'LOCAL REVIEW STUDIO:' "$QA/server.log"
setsid google-chrome --headless=new --no-sandbox --disable-dev-shm-usage --disable-gpu --no-first-run --remote-debugging-port="$CHROME_PORT" --remote-allow-origins='*' --user-data-dir="$QA/chrome" --window-size=1440,900 "$URL" > "$QA/chrome.log" 2>&1 &
CPID=$!
for i in $(seq 1 80);do curl -fsS "http://127.0.0.1:$CHROME_PORT/json/list" >/dev/null 2>&1 && break; sleep .17;done
export ZAPTRACE_CHROME_PORT="$CHROME_PORT" ZAPTRACE_AUDIT_URL="$URL" ZAPTRACE_EXPECT_TWO=1
export ZAPTRACE_EXPECT_VERSION=0.1.20 ZAPTRACE_UX_SCREENSHOTS="$QA/shots"
echo '[1/8] Installed package workspace accessibility, all input errors and viewport sizes'
node scripts/review_studio_accessibility_browser_smoke.mjs
echo '[2/8] Installed version source-linked comparison and source-rule inequality'
ZAPTRACE_SKIP_COMPARISON_SHOTS=1 ZAPTRACE_WORKSPACE_SCREENSHOTS="$QA/shots" node scripts/review_studio_comparison_browser_smoke.mjs
echo '[3/8] Browser exact native KiCad PCB/schematic/3D (same bundled native template)'
export ZAPTRACE_AUDIT_URL="${URL}$(cat "$QA/native-url-path")"
ZAPTRACE_URL="$ZAPTRACE_AUDIT_URL" node --input-type=module <<'JS'
const pages=await(await fetch('http://127.0.0.1:'+process.env.ZAPTRACE_CHROME_PORT+'/json/list')).json();
const page=pages.find(x=>x.type==='page'&&x.url===process.env.ZAPTRACE_AUDIT_URL.replace(/review-assets.*/,''));
if(!page)throw Error('Package Chrome main page unavailable');
const ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise((ok,no)=>{ws.addEventListener('open',ok,{once:true});ws.addEventListener('error',no,{once:true})});ws.send(JSON.stringify({id:1,method:'Page.navigate',params:{url:process.env.ZAPTRACE_URL}}));ws.close();
JS
ZAPTRACE_EXPECT_LAYOUT=improved ZAPTRACE_SCREENSHOT_DIR="$QA/shots" node scripts/review_studio_native_browser_smoke.mjs
export ZAPTRACE_AUDIT_URL="$URL"
node --input-type=module <<'JS'
const pages=await(await fetch('http://127.0.0.1:'+process.env.ZAPTRACE_CHROME_PORT+'/json/list')).json();
const page=pages.find(x=>x.type==='page'&&x.url?.includes('/review-assets/')&&x.url?.endsWith('/index.html'));
if(!page)throw Error('Installed native review page missing');
const ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise((ok,no)=>{ws.addEventListener('open',ok,{once:true});ws.addEventListener('error',no,{once:true})});ws.send(JSON.stringify({id:1,method:'Page.navigate',params:{url:process.env.ZAPTRACE_AUDIT_URL}}));ws.close();
JS
echo '[4/8] Genuine local KiCad PCB move and rotate ECO'
export ZAPTRACE_PCB_ECO_SOURCE="$ROOT/tests/fixtures/review_studio_native_eco_placement.kicad_pcb" ZAPTRACE_PCB_ECO_SHOTS="$QA/shots" ZAPTRACE_PCB_ECO_ROTATE=90
node scripts/review_studio_pcb_eco_workspace_browser_smoke.mjs
echo '[5/8] Genuine local KiCad schematic ECO'
export ZAPTRACE_ECO_SOURCE="$ROOT/tests/fixtures/review_studio_native_eco_sensor.kicad_sch" ZAPTRACE_ECO_SHOTS="$QA/shots"
node scripts/review_studio_schematic_eco_workspace_browser_smoke.mjs
echo '[6/8] Real schematic–PCB read-only parity and provenance'
export ZAPTRACE_PARITY_SCHEMATIC="$ROOT/build/source-reference-readonly/ESP32_I2C_Sensor_Board.kicad_sch"
export ZAPTRACE_PARITY_PCB="$ROOT/build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"
export ZAPTRACE_PARITY_DOWNLOAD_DIR="$QA/private-parity-download"
node scripts/review_studio_parity_audit_browser_smoke.mjs
echo '[7/8] Authenticated KiCad native guarded copper real Chrome via + multinet'
export ZAPTRACE_COPPER_ZIP="$ROOT/build/qa-012-release-20261012/PORTABLE_ESP32_CUSTOM_REFERENCE.zip"
export ZAPTRACE_COPPER_DOWNLOAD_DIR="$QA/downloads-via" ZAPTRACE_COPPER_VIA_PAIR=1 ZAPTRACE_COPPER_CUSTOM_RULES=1
node scripts/review_studio_native_copper_browser_smoke.mjs
test -s "$QA/downloads-via/EVIDENCE.json"
unset ZAPTRACE_COPPER_VIA_PAIR
export ZAPTRACE_COPPER_DOWNLOAD_DIR="$QA/downloads-legacy"
node scripts/review_studio_native_copper_browser_smoke.mjs
export ZAPTRACE_COPPER_BATCH=1 ZAPTRACE_COPPER_VIA_PAIR=1 ZAPTRACE_COPPER_DOWNLOAD_DIR="$QA/downloads-multinet"
node scripts/review_studio_native_copper_browser_smoke.mjs
QA_EVIDENCE="$QA/downloads-multinet/EVIDENCE.json" python3 -B - <<'PY'
import os,json
from pathlib import Path
x=json.loads(Path(os.environ['QA_EVIDENCE']).read_text())
assert x['distinct_nets']==['GND','VCC_3V3']
assert x['cumulative_drc']['before_unconnected']==37 and x['cumulative_drc']['after_unconnected']==35
assert x['cumulative_drc']['before_violations']==x['cumulative_drc']['after_violations']==16
assert x['fabApproved'] is False
print('EXACT_020_PACKAGE_TWO_NET_NATIVE_KICAD_DRC_37_TO_35_AND_16_TO_16=PASS')
PY
echo '[8/8] Immutable source/package and no signoff'
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.20_all.sha256 && sha256sum -c zaptrace-review-studio_0.1.12_all.sha256)
echo "PACKAGE_SHA256=$SHA"
echo 'EXACT_020_INSTALLED_ROOTLESS_DEB_ALL_EIGHT_CHROME_KICAD_GATES=PASS'
