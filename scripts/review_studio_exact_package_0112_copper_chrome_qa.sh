#!/usr/bin/env bash
# Exact .deb bytes: rootless dpkg extract + native KiCad/Chrome authenticated copy-on-write.
# No package installs, no host system package changes, no Git or network changes.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
DEB=${1:-build/distribution/zaptrace-review-studio_0.1.12_all.deb}
DEB=$(realpath -- "$DEB")
test "${DEB##*/}" = zaptrace-review-studio_0.1.12_all.deb
test -f "$DEB"
(cd "$(dirname -- "$DEB")" && sha256sum -c "$(basename -- "$DEB" .deb).sha256")
for tool in /usr/bin/dpkg-deb /usr/bin/python3 google-chrome node kicad-cli;do
 command -v "$tool" >/dev/null || { echo "Required exact-package QA tool missing: $tool" >&2;exit 2; }
done
QA=$(mktemp -d /tmp/zaptrace-0112-installed-chrome-XXXXXX)
SPID='' CPID=''
cleanup(){
 if [[ -n "$CPID" ]];then
   kill -TERM -- "-$CPID" 2>/dev/null||true
   sleep .35
   kill -KILL -- "-$CPID" 2>/dev/null||true
   wait "$CPID" 2>/dev/null||true
 fi
 if [[ -n "$SPID" ]];then kill "$SPID" 2>/dev/null||true;wait "$SPID" 2>/dev/null||true;fi
 for retry in 1 2 3 4 5 6 7 8;do
   if rm -rf -- "$QA" 2>/dev/null && [[ ! -e "$QA" ]];then return 0;fi
   sleep .35
 done
 echo "Disposable Chrome QA directory could not be removed: $QA" >&2
 return 1
}
trap cleanup EXIT
chmod 700 "$QA"
dpkg-deb -x "$DEB" "$QA/installed"
PACKAGED="$QA/installed/usr/lib/zaptrace-review-studio/scripts"
for name in review_studio_local_server.py review_studio_native_copper_link.py \
 review_studio_native_copper_bundle.py review_studio_native_copper_batch.py review_studio_workspace_template.html;do
 test -s "$PACKAGED/$name"
done
"$QA/installed/usr/bin/zaptrace-review-studio" --version | grep -F '0.1.12'
"$QA/installed/usr/bin/zaptrace-review-studio" --doctor
export ZAPTRACE_COPPER_ZIP="$QA/native-portable-project.zip"
SOURCE="$QA/native-source" ZIP="$ZAPTRACE_COPPER_ZIP" \
 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B - <<'PY'
from pathlib import Path
from zaptrace.core.parser import parse_file
from zaptrace.export.kicad import export_kicad
import os,zipfile
folder=Path(os.environ["SOURCE"])
export_kicad(parse_file(Path("build/source-reference-readonly/issue91-design.yaml")),folder)
(folder/"ESP32_I2C_Sensor_Board.kicad_dru").write_text(
 '(version 1)\n(rule "BENIGN_COURTYARD" (constraint courtyard_clearance (min 0.1mm)))\n'
)
with zipfile.ZipFile(os.environ["ZIP"],"w",zipfile.ZIP_DEFLATED) as bundle:
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            bundle.write(path,path.relative_to(folder).as_posix())
PY
PORTS=$(python3 -B - <<'PY'
import socket
s=[socket.socket() for i in range(2)]
for x in s:x.bind(('127.0.0.1',0))
print(' '.join(str(x.getsockname()[1]) for x in s))
for x in s:x.close()
PY
)
read -r PORT CHROME_PORT <<< "$PORTS"
/usr/bin/python3 -B -u "$PACKAGED/review_studio_local_server.py" \
 --workspace "$QA/workspace" --port "$PORT" > "$QA/installed-server.log" 2>&1 &
SPID=$!
for i in $(seq 1 90);do
 grep -q 'LOCAL REVIEW STUDIO:' "$QA/installed-server.log" && break
 kill -0 "$SPID" 2>/dev/null || { cat "$QA/installed-server.log" >&2;exit 2; }
 sleep .13
done
grep -q 'LOCAL REVIEW STUDIO:' "$QA/installed-server.log" || { echo 'Packaged server failed to start' >&2;exit 2;}
setsid google-chrome --headless=new --no-sandbox --disable-dev-shm-usage --disable-gpu --no-first-run \
 --remote-debugging-address=127.0.0.1 --remote-debugging-port="$CHROME_PORT" \
 --remote-allow-origins='*' --user-data-dir="$QA/chrome" \
 "http://127.0.0.1:$PORT/" >"$QA/chrome.log" 2>&1 &
CPID=$!
export ZAPTRACE_CHROME_PORT="$CHROME_PORT"
export ZAPTRACE_COPPER_DOWNLOAD_DIR="$QA/downloads-via"
export ZAPTRACE_COPPER_VIA_PAIR=1
export ZAPTRACE_COPPER_CUSTOM_RULES=1
node scripts/review_studio_native_copper_browser_smoke.mjs
python3 -B - "$QA/downloads-via/native-copper-project.zip" "$QA/downloads-via/EVIDENCE.json" <<'PY'
import json,sys,zipfile
from pathlib import Path
bundle=Path(sys.argv[1]); evidence=json.loads(Path(sys.argv[2]).read_text())
assert evidence["fabApproved"] is False
assert evidence["native_drc"]["before_unconnected"]==37
assert evidence["native_drc"]["after_unconnected"]==36
assert evidence["native_drc"]["before_violations"]==evidence["native_drc"]["after_violations"]==16
with zipfile.ZipFile(bundle) as archive:
    assert archive.testzip() is None
    for name in ("EVIDENCE.json","baseline-drc.json","candidate-drc.json","PREVIEW.html","before.svg","after.svg"):
        assert name in archive.namelist()
    assert archive.read("before.svg") != archive.read("after.svg")
    assert json.loads(archive.read("EVIDENCE.json"))==evidence
    assert evidence["link"]["via_indices"]==[1,2]
    assert evidence["link"]["segment_layers"]==["F.Cu","B.Cu","F.Cu"]
    assert evidence["rule_context"]["custom_rule_loader_probe_passed"] is True
    assert evidence["rule_context"]["default_drc_crosscheck_passed"] is True
    assert evidence["rule_context"]["effective_rules_independently_verified"] is False
    for name in ("ESP32_I2C_Sensor_Board.kicad_dru","baseline-default-drc.json","candidate-default-drc.json"):
        assert name in archive.namelist()
    assert len(json.loads(archive.read("candidate-drc.json"))["unconnected_items"])==36
print("EXACT_PACKAGE_NATIVE_COPPER_ZIP_AND_DRC: PASS")
PY
(cd "$(dirname -- "$DEB")" && sha256sum -c "$(basename -- "$DEB" .deb).sha256")
echo "PACKAGE_SHA256=$(sha256sum "$DEB" | cut -d ' ' -f1)"
echo 'Exact package 0.1.12 Chrome guarded copper ZIP, SVG, discard: PASS'
echo 'Installed 0.1.12 native custom KiCad rules loader + independent default DRC verified: PASS'
unset ZAPTRACE_COPPER_VIA_PAIR
export ZAPTRACE_COPPER_DOWNLOAD_DIR="$QA/downloads-legacy"
node scripts/review_studio_native_copper_browser_smoke.mjs
echo 'EXACT_PACKAGE_0112_CUSTOM_TWO_VIA_AND_LEGACY_FCU_CHROME: PASS'
export ZAPTRACE_COPPER_BATCH=1
export ZAPTRACE_COPPER_VIA_PAIR=1
export ZAPTRACE_COPPER_DOWNLOAD_DIR="$QA/downloads-batch"
node scripts/review_studio_native_copper_browser_smoke.mjs
python3 -B - "$QA/downloads-batch/native-copper-project.zip" "$QA/downloads-batch/EVIDENCE.json" <<'PY_CHECK_012_BATCH'
import json,sys,zipfile
from pathlib import Path
evidence=json.loads(Path(sys.argv[2]).read_text())
assert evidence['step_count']==2
assert evidence['distinct_nets']==['GND','VCC_3V3']
assert evidence['cumulative_drc']['before_unconnected']==37
assert evidence['cumulative_drc']['after_unconnected']==35
assert evidence['cumulative_drc']['before_violations']==evidence['cumulative_drc']['after_violations']==16
assert evidence['fabApproved'] is False
with zipfile.ZipFile(sys.argv[1]) as archive:
 assert archive.testzip() is None
 assert json.loads(archive.read('EVIDENCE.json'))==evidence
 assert len([name for name in archive.namelist() if name.startswith('step-') and name.endswith('-evidence.json')])==2
 assert len(json.loads(archive.read('candidate-drc.json'))['unconnected_items'])==35
 assert archive.read('before.svg')!=archive.read('after.svg')
print('EXACT_PACKAGE_0112_NATIVE_TWO_NET_PROJECT_AND_SHA_EVIDENCE=PASS')
PY_CHECK_012_BATCH
unset ZAPTRACE_COPPER_BATCH
echo 'EXACT_PACKAGE_0112_CUSTOM_THROUGH_VIAS_MULTINET_AND_LEGACY_CHROME: PASS'
echo 'NATIVE_KICAD_COPPER_INSTALLED_SOURCE_IMMUTABLE: PASS'
