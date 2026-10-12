#!/usr/bin/env bash
# Real native KiCad source, exact unsigned candidate Debian, isolated headless Chrome.
# Never installs on host or signs off fabrication.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
DEB=${ZAPTRACE_027_DEB:-build/distribution/zaptrace-review-studio_0.1.27_all.deb}
DEB=$(realpath -- "$DEB")
[[ "${DEB##*/}" = zaptrace-review-studio_0.1.27_all.deb ]]
[[ "$(dpkg-deb -f "$DEB" Version)" = 0.1.27 ]]
(cd "$(dirname "$DEB")";sha256sum -c zaptrace-review-studio_0.1.27_all.sha256)
SOURCE_3D=${ZAPTRACE_027_NATIVE_3D:-build/native-review/index.html}
SOURCE_MULTI=${ZAPTRACE_027_NATIVE_MULTI:-build/native-multi-sheet-test/index.html}
[[ -s "$SOURCE_3D" && -s "$SOURCE_MULTI" ]]
SHOTS=${ZAPTRACE_027_SCREEN_DIR:-build/qa-027-visual}
mkdir -p "$SHOTS"
SHOTS=$(realpath -- "$SHOTS")
QA=$(mktemp -d /tmp/zaptrace-027-exact-chrome-XXXXXXXX)
chmod 700 "$QA"
SPID='' CPID=''
cleanup(){
 local code=$?
 trap - EXIT
 if [[ -n "$CPID" ]];then kill -TERM -- "-$CPID" 2>/dev/null||true;fi
 if [[ -n "$SPID" ]];then kill "$SPID" 2>/dev/null||true;fi
 sleep .3
 if [[ -n "$CPID" ]];then kill -KILL -- "-$CPID" 2>/dev/null||true;wait "$CPID" 2>/dev/null||true;fi
 if [[ -n "$SPID" ]];then wait "$SPID" 2>/dev/null||true;fi
 rm -rf -- "$QA"
 exit "$code"
}
trap cleanup EXIT
dpkg-deb -x "$DEB" "$QA/installed"
python3 -B - "$SOURCE_3D" "$SOURCE_MULTI" "$QA" <<'PY'
from pathlib import Path
import hashlib,json,re,sys
three,multi,dest=(Path(x) for x in sys.argv[1:])
tpl=(dest/'installed/usr/lib/zaptrace-review-studio/scripts/review_studio_native_template.html').read_text()
assert 'function bindCanvasRoving()' in tpl and 'ercErrors' in tpl
canonical=Path('build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb')
assert canonical.is_file()
original_sha=hashlib.sha256(canonical.read_bytes()).hexdigest()
for origin,target in ((three,'index.html'),(multi,'multi.html')):
 m=re.search(r'(?m)^const DATA=(.*);$',origin.read_text())
 assert m,origin
 payload=json.loads(m.group(1))
 assert payload['source_sha256']==original_sha
 h=tpl.replace('__NATIVE_DATA__',m.group(1)).replace('__WORKSPACE_LINK__','')
 assert '__NATIVE_DATA__' not in h
 (dest/target).write_text(h)
print('EXACT_027_PKG_SHA_AND_CANONICAL_KICAD_INPUT_VERIFIED=PASS')
PY
read -r PORT CDP <<< "$(python3 -B - <<'PY'
import socket
s=[socket.socket() for _ in range(2)]
for x in s:x.bind(('127.0.0.1',0))
print(' '.join(str(x.getsockname()[1]) for x in s))
for x in s:x.close()
PY
)"
python3 -B -m http.server "$PORT" --bind 127.0.0.1 --directory "$QA" >"$QA/http.log" 2>&1 & SPID=$!
setsid google-chrome --headless=new --no-sandbox --disable-dev-shm-usage --disable-gpu --no-first-run \
 --remote-debugging-address=127.0.0.1 --remote-debugging-port="$CDP" \
 --remote-allow-origins='*' --user-data-dir="$QA/profile" --window-size=1440,900 \
 "http://127.0.0.1:$PORT/index.html" >"$QA/chrome.log" 2>&1 & CPID=$!
CDP_PORT="$CDP" HTTP_PORT="$PORT" ZAPTRACE_027_SCREEN_DIR="$SHOTS" \
 timeout 120s node scripts/review_studio_027_visual_browser_smoke.mjs
(cd "$(dirname "$DEB")";sha256sum -c zaptrace-review-studio_0.1.27_all.sha256)
echo 'EXACT_027_DEBIAN_REAL_CHROME_KICAD_3D_AND_ERC_ALL_VIEWPORTS=PASS'
