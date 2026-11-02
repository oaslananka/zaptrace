#!/usr/bin/env bash
# Exact SHA-qualified 0.1.19 native KiCad UI: 3D, multi-sheet, gallery and preferences.
# Source data immutable, isolated browser origin, disposable assets. No host install.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
DEB=$ROOT/build/distribution/zaptrace-review-studio_0.1.19_all.deb
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.19_all.sha256)
QA=$(mktemp -d /tmp/zaptrace-019-viewer-modes-XXXXXX)
chmod 700 "$QA"
SPID='' CPID=''
cleanup(){
 local rc=$?
 trap - EXIT
 if [[ -n "$CPID" ]];then kill -TERM -- "-$CPID" 2>/dev/null||true; sleep .35;kill -KILL -- "-$CPID" 2>/dev/null||true;wait "$CPID" 2>/dev/null||true;fi
 if [[ -n "$SPID" ]];then kill "$SPID" 2>/dev/null||true;wait "$SPID" 2>/dev/null||true;fi
 for retry in 1 2 3 4 5 6;do rm -rf -- "$QA" 2>/dev/null||true;test ! -e "$QA" && break;sleep .2;done
 [[ ! -e "$QA" ]]||exit 6
 exit "$rc"
}
trap cleanup EXIT
mkdir -p "$QA/installed" "$QA/reviews" "$QA/shots"
dpkg-deb -x "$DEB" "$QA/installed"
UI="$QA/installed/usr/lib/zaptrace-review-studio/scripts/review_studio_native_template.html"
QA_DIR="$QA" PKG_TEMPLATE="$UI" PKG_SCRIPTS="$QA/installed/usr/lib/zaptrace-review-studio/scripts" /usr/bin/python3 -B - <<'PY'
from pathlib import Path
import re,json,os,shutil,hashlib,sys,base64
sys.path.insert(0,os.environ["PKG_SCRIPTS"])
from review_studio_native_kicad import _read_kicad, safe_inline_json, schematic_svg_drawn_elements
qa=Path(os.environ['QA_DIR']);ui=Path(os.environ['PKG_TEMPLATE']).read_text()
for short,source in (
    ('three-d','build/native-review'),
    ('multi','build/native-multi-sheet-test'),
    ('native','build/native-review'),
):
    incoming=Path(source)
    output=qa/'reviews'/short
    shutil.copytree(incoming,output)
    old=(output/'index.html').read_text()
    match=re.search(r'(?m)^const DATA=(.*);$',old)
    back=re.search(r'<a class="project-back" id="workspaceHome".*?</a>',old)
    assert match
    data=json.loads(match.group(1))
    assert len(data['source_sha256'])==64
    native_board=Path('build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb')
    assert hashlib.sha256(native_board.read_bytes()).hexdigest()==data['source_sha256']
    diagnostic=_read_kicad(native_board)['model_assets']
    assert diagnostic['model_geometry_approved'] is False
    data['board']['model_assets']=diagnostic
    if data.get('schematic'):
        for page in data['schematic'].get('pages', []):
            raw=base64.b64decode(page['src'].split(',', 1)[1], validate=True)
            source_count=schematic_svg_drawn_elements(raw)
            if 'drawn_element_count' in page and page['drawn_element_count']!=source_count:
                raise RuntimeError('Cached source page inventory does not match KiCad SVG')
            page['drawn_element_count']=source_count
    rendered=ui.replace('__NATIVE_DATA__',safe_inline_json(data)).replace('__WORKSPACE_LINK__',back.group(0) if back else '')
    assert '__NATIVE_DATA__' not in rendered and 'inspector-tab-issues' in rendered
    (output/'index.html').write_text(rendered)
    print(short,'SHA',data['source_sha256'],'MODEL',data.get('render3d',{}).get('state'))
print('EXACT_019_PACKAGE_VIEWER_TEMPLATES_SOURCE_LINKED=PASS')
PY
PORTS=$(python3 -B - <<'PY'
import socket
s=[socket.socket() for _ in range(2)]
for sock in s:sock.bind(('127.0.0.1',0))
print(' '.join(str(sock.getsockname()[1]) for sock in s))
for sock in s:sock.close()
PY
)
read -r PORT CP <<< "$PORTS"
python3 -B -m http.server "$PORT" --bind 127.0.0.1 --directory "$QA/reviews" >"$QA/http.log" 2>&1 &
SPID=$!
for i in $(seq 1 80);do curl -fsS "http://127.0.0.1:$PORT/three-d/index.html" >/dev/null 2>&1 && break;sleep .14;done
setsid google-chrome --headless=new --no-sandbox --disable-dev-shm-usage --disable-gpu --no-first-run --remote-debugging-port="$CP" --remote-allow-origins='*' --user-data-dir="$QA/chrome" --window-size=1440,900 "http://127.0.0.1:$PORT/three-d/index.html" >"$QA/chrome.log" 2>&1 &
CPID=$!
for i in $(seq 1 80);do curl -fsS "http://127.0.0.1:$CP/json/list" >/dev/null 2>&1 && break;sleep .14;done
export ZAPTRACE_CHROME_PORT="$CP" ZAPTRACE_3D_SHOTS="$QA/shots" ZAPTRACE_GALLERY_SHOTS="$QA/shots" ZAPTRACE_MULTISHEET_SCREEN_DIR="$QA/shots"
next_page(){
 ZAPTRACE_PAGE_URL="$1" node --input-type=module <<'JS'
const pages=await(await fetch('http://127.0.0.1:'+process.env.ZAPTRACE_CHROME_PORT+'/json/list')).json();
const page=pages.find(x=>x.type==='page'&&x.url?.startsWith('http://127.0.0.1:'));
if(!page)throw Error('Owned Chrome page missing');
const ws=new WebSocket(page.webSocketDebuggerUrl);
await new Promise((ok,no)=>{ws.addEventListener('open',ok,{once:true});ws.addEventListener('error',no,{once:true})});
ws.send(JSON.stringify({id:1,method:'Page.bringToFront'}));
ws.send(JSON.stringify({id:2,method:'Page.navigate',params:{url:process.env.ZAPTRACE_PAGE_URL}}));
ws.close();
console.log('NATIVE_UI_CHANGED',process.env.ZAPTRACE_PAGE_URL)
JS
}
echo '[1/4] Actual KiCad 3D 8 orbit views, top and iso and mobile'
timeout 110s node scripts/review_studio_native_3d_browser_smoke.mjs
ZAPTRACE_019_SCREENSHOT="$QA/shots/native-3d-model-diagnostics-390.png" timeout 80s node scripts/review_studio_019_model_browser_smoke.mjs
cp -- "$QA/shots/native-3d-model-diagnostics-390.png" build/qa-019-release-20261012/
cp -- "$QA/shots/native-3d-model-diagnostics-320.png" build/qa-019-release-20261012/
cp -- "$QA/shots/native-kicad-3d-isometric-desktop.png" build/qa-019-release-20261012/
echo "MOBILE_3D_PROOF_SHA256=$(sha256sum "$QA/shots/native-3d-model-diagnostics-390.png" | cut -d ' ' -f1)"
echo "MOBILE_3D_320_PROOF_SHA256=$(sha256sum "$QA/shots/native-3d-model-diagnostics-320.png" | cut -d ' ' -f1)"
next_page "http://127.0.0.1:$PORT/multi/index.html"
echo '[2/4] Actual root/child Eeschema pages + source-only cross-probe'
timeout 110s node scripts/review_studio_multisheet_browser_smoke.mjs
next_page "http://127.0.0.1:$PORT/multi/index.html"
echo '[3/4] Native schematic gallery, source SVG thumbnails + keyboard navigation'
ZAPTRACE_GALLERY_KIND=multi timeout 110s node scripts/review_studio_schematic_gallery_browser_smoke.mjs
timeout 100s node scripts/review_studio_019_multisheet_responsive_browser_smoke.mjs
cp -- "$QA/shots/native-multisheet-child-320.png" build/qa-019-release-20261012/
cp -- "$QA/shots/native-multisheet-child-390.png" build/qa-019-release-20261012/
for width in 320 390;do echo "MOBILE_SCHEMATIC_${width}_SHA256=$(sha256sum "$QA/shots/native-multisheet-child-${width}.png" | cut -d ' ' -f1)";done
next_page "http://127.0.0.1:$PORT/native/index.html"
echo '[4/4] Persisted source-scoped native inspector/layout, fail-closed hostile localStorage'
timeout 110s node scripts/review_studio_native_preferences_browser_smoke.mjs
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.19_all.sha256)
echo "PACKAGE_SHA256=$(sha256sum "$DEB"|cut -d ' ' -f1)"
echo 'EXACT_019_INSTALLED_3D_MULTISHEET_GALLERY_PREFERENCES_ALL_FOUR_GATES=PASS'
