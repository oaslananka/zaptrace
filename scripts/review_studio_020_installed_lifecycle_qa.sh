#!/usr/bin/env bash
# 0.1.20 actual package, actual Chrome file selection, private backup/delete/restore.
# Owned QA sandbox only; never use or mutate the user's real Review Studio library.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
DEB=$ROOT/build/distribution/zaptrace-review-studio_0.1.20_all.deb
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.20_all.sha256)
QA=$(mktemp -d /tmp/zaptrace-020-lifecycle-qa-XXXXXX)
chmod 700 "$QA"
SPID='' CPID=''
cleanup(){
 local rc=$?
 trap - EXIT
 if [[ -n "$CPID" ]];then kill -TERM -- "-$CPID" 2>/dev/null||true;sleep .5;kill -KILL -- "-$CPID" 2>/dev/null||true;wait "$CPID" 2>/dev/null||true;fi
 if [[ -n "$SPID" ]];then kill "$SPID" 2>/dev/null||true;wait "$SPID" 2>/dev/null||true;fi
 for i in 1 2 3 4 5;do rm -rf -- "$QA" 2>/dev/null||true;test ! -e "$QA" && break;sleep .2;done
 [[ ! -e "$QA" ]]||exit 6
 exit "$rc"
}
trap cleanup EXIT
mkdir -p "$QA/installed" "$QA/workspace" "$QA/shots" "$QA/downloads"
dpkg-deb -x "$DEB" "$QA/installed"
PACKAGED="$QA/installed/usr/lib/zaptrace-review-studio/scripts"
test "$(dpkg-deb -f "$DEB" Version)" = 0.1.20
PORT=$(python3 -B - <<'PY'
import socket
for i in range(80):
 a=socket.socket();b=socket.socket()
 try:
  a.bind(('127.0.0.1',0));p=a.getsockname()[1]
  b.bind(('127.0.0.1',p+1));print(p);break
 except OSError:pass
 finally:a.close();b.close()
else:raise RuntimeError('No port pair')
PY
)
/usr/bin/python3 -B -u "$PACKAGED/review_studio_local_server.py" --workspace "$QA/workspace" --port "$PORT" >"$QA/server.log" 2>&1 &
SPID=$!
for i in $(seq 1 70);do grep -q 'LOCAL REVIEW STUDIO:' "$QA/server.log" && break;kill -0 "$SPID" 2>/dev/null||{ cat "$QA/server.log";exit 2;};sleep .14;done
setsid google-chrome --headless=new --no-sandbox --disable-dev-shm-usage --disable-gpu --no-first-run --remote-debugging-port="$((PORT+1))" --remote-allow-origins='*' --user-data-dir="$QA/chrome" --window-size=1440,900 "http://127.0.0.1:$PORT/" > "$QA/chrome.log" 2>&1 &
CPID=$!
for i in $(seq 1 80);do curl -fsS "http://127.0.0.1:$((PORT+1))/json/list" >/dev/null 2>&1 && break;sleep .15;done
export ZAPTRACE_TEST_PCB="$ROOT/build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"
export ZAPTRACE_CHROME_PORT="$PORT"
mkdir -p build/review-studio-live-test
before=$(sha256sum "$ZAPTRACE_TEST_PCB"|cut -d ' ' -f1)
echo '[1/4] Real packaged Chrome file chooser -> native KiCad PCB importer'
node scripts/review_studio_local_import_browser_smoke.mjs
export ZAPTRACE_CHROME_PORT="$((PORT+1))" ZAPTRACE_RELEASE_SHOTS="$QA/shots" ZAPTRACE_BACKUP_DIR="$QA/downloads"
echo '[2/4] SHA-linked private ZIP backup -> guarded DELETE -> empty project library'
node scripts/review_studio_data_lifecycle_browser_smoke.mjs
ZIP=$(find "$QA/downloads" -maxdepth 1 -type f -name 'zaptrace-review-*.zip' -print -quit)
test -n "$ZIP" && test -s "$ZIP"
echo '[3/4] Source-verified ZIP restore -> native recheck ERC/DRC -> mobile layout'
export ZAPTRACE_RESTORE_ZIP="$ZIP"
node scripts/review_studio_restore_browser_smoke.mjs
echo '[4/4] Source, archived ZIP and exact Debian SHA preserved'
after=$(sha256sum "$ZAPTRACE_TEST_PCB"|cut -d ' ' -f1)
test "$before" = "$after"
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.20_all.sha256)
echo "PACKAGE_SHA256=$(/usr/bin/sha256sum "$DEB"|cut -d ' ' -f1)"
echo 'EXACT_020_REAL_CHROME_IMPORT_BACKUP_DELETE_RESTORE_AND_SOURCE_IMMUTABLE=PASS'
