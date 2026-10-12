#!/usr/bin/env bash
# Source-only post-0.1.11 guarded native single/via/multinet Chrome proof.
# This new batch feature is NOT inside QA-qualified frozen 0.1.11 installation.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
QA=$(mktemp -d /tmp/zaptrace-via-source-chrome-XXXXXX)
chmod 700 "$QA"
SPID='' CPID=''
cleanup(){
 if [[ -n "$CPID" ]];then
  kill -TERM -- "-$CPID" 2>/dev/null||true
  sleep .3
  kill -KILL -- "-$CPID" 2>/dev/null||true
  wait "$CPID" 2>/dev/null||true
 fi
 if [[ -n "$SPID" ]];then kill "$SPID" 2>/dev/null||true;wait "$SPID" 2>/dev/null||true;fi
 for i in 1 2 3 4 5 6 7 8;do
  rm -rf -- "$QA" 2>/dev/null||true
  if [[ ! -e "$QA" ]];then return 0;fi
  sleep .3
 done
 echo "Isolated Chrome QA cleanup failed" >&2
 return 1
}
trap cleanup EXIT
SOURCE="$QA/native-source" ZIP="$QA/portable.zip" PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B - <<'PY'
from pathlib import Path
from zaptrace.core.parser import parse_file
from zaptrace.export.kicad import export_kicad
import os,zipfile
folder=Path(os.environ['SOURCE'])
export_kicad(parse_file(Path('build/source-reference-readonly/issue91-design.yaml')),folder)
if os.environ.get('ZAPTRACE_COPPER_CUSTOM_RULES')=='1':
 (folder/'ESP32_I2C_Sensor_Board.kicad_dru').write_text(
  '(version 1)\n(rule "BENIGN_COURTYARD" (constraint courtyard_clearance (min 0.1mm)))\n'
 )
with zipfile.ZipFile(os.environ['ZIP'],'w',zipfile.ZIP_DEFLATED) as archive:
 for member in sorted(folder.rglob('*')):
  if member.is_file():archive.write(member,member.relative_to(folder).as_posix())
PY
PORTS=$(python3 -B - <<'PY'
import socket
s=[socket.socket() for _ in range(2)]
for sock in s:sock.bind(('127.0.0.1',0))
print(' '.join(str(sock.getsockname()[1]) for sock in s))
for sock in s:sock.close()
PY
)
read -r PORT CHROME_PORT <<< "$PORTS"
/usr/bin/python3 -B -u scripts/review_studio_local_server.py --workspace "$QA/private-workspace" --port "$PORT" >"$QA/server.log" 2>&1 &
SPID=$!
for i in $(seq 1 90);do
 grep -q 'LOCAL REVIEW STUDIO:' "$QA/server.log" && break
 kill -0 "$SPID" 2>/dev/null || { cat "$QA/server.log" >&2; exit 2; }
 sleep .14
done
grep -q 'LOCAL REVIEW STUDIO:' "$QA/server.log"
setsid google-chrome --headless=new --no-sandbox --disable-dev-shm-usage --disable-gpu --no-first-run \
 --remote-debugging-address=127.0.0.1 --remote-debugging-port="$CHROME_PORT" \
 --remote-allow-origins='*' --user-data-dir="$QA/chrome" \
 "http://127.0.0.1:$PORT/" >"$QA/chrome.log" 2>&1 &
CPID=$!
export ZAPTRACE_CHROME_PORT="$CHROME_PORT"
export ZAPTRACE_COPPER_ZIP="$QA/portable.zip"
export ZAPTRACE_COPPER_DOWNLOAD_DIR="$QA/downloads-via"
export ZAPTRACE_COPPER_VIA_PAIR=1
node scripts/review_studio_native_copper_browser_smoke.mjs
python3 -B - "$QA/downloads-via/native-copper-project.zip" <<'PY'
import json,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as result:
 assert result.testzip() is None
 evidence=json.loads(result.read('EVIDENCE.json'))
 assert evidence['link']['via_indices']==[1,2]
 assert evidence['link']['via_count']==2
 assert evidence['link']['segment_layers']==['F.Cu','B.Cu','F.Cu']
 assert evidence['native_drc']['before_unconnected']==37
 assert evidence['native_drc']['after_unconnected']==36
 assert evidence['native_drc']['before_violations']==evidence['native_drc']['after_violations']==16
 assert evidence['fabApproved'] is False
 assert result.read('before.svg')!=result.read('after.svg')
 if __import__('os').environ.get('ZAPTRACE_COPPER_CUSTOM_RULES')=='1':
  context=evidence['rule_context']
  assert context['custom_rule_loader_probe_passed'] is True
  assert context['default_drc_crosscheck_passed'] is True
  assert context['effective_rules_independently_verified'] is False
  assert evidence['source_asset_sha256']['ESP32_I2C_Sensor_Board.kicad_dru']==context['custom_rules_sha256']
  assert 'baseline-default-drc.json' in result.namelist()
  assert 'candidate-default-drc.json' in result.namelist()
  assert len(json.loads(result.read('candidate-default-drc.json'))['unconnected_items'])==36
 from pathlib import Path
 board=Path(sys.argv[1]).parent/'native-verified-via.kicad_pcb'
 board.write_bytes(result.read('ESP32_I2C_Sensor_Board.kicad_pcb'))
 import subprocess
 native=subprocess.run(['/usr/bin/python3','-B','-c',"""
import json,pcbnew as p,sys
b=p.LoadBoard(sys.argv[1])
via=[t for t in b.GetTracks() if isinstance(t,p.PCB_VIA)]
back=[t for t in b.GetTracks() if not isinstance(t,p.PCB_VIA) and t.GetLayer()==p.B_Cu]
assert len(via)==2 and len(back)==1
assert all(v.GetLayerSet().Contains(p.F_Cu) and v.GetLayerSet().Contains(p.B_Cu) for v in via)
assert all(v.GetDrillValue()==p.FromMM(0.3) and v.GetWidth()==p.FromMM(0.6) for v in via)
assert all(v.GetNetname()=='GND' for v in via+back)
print('INDEPENDENT_SAVED_KICAD_PCBNEW_TWO_VIAS_AND_BOTTOM_COPPER=PASS')
""",str(board)],capture_output=True,text=True,timeout=35,check=True)
 print(native.stdout.strip())
 board.unlink()
 print('CHROME_DOWNLOADED_REAL_KICAD_NATIVE_TWO_THROUGH_VIA_COPY=PASS')
PY
export ZAPTRACE_COPPER_BATCH=1
export ZAPTRACE_COPPER_DOWNLOAD_DIR="$QA/downloads-batch"
node scripts/review_studio_native_copper_browser_smoke.mjs
python3 -B - "$QA/downloads-batch/native-copper-project.zip" <<'PY_CHECK_BATCH'
import json,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as result:
 assert result.testzip() is None
 evidence=json.loads(result.read('EVIDENCE.json'))
 assert evidence['step_count']==2
 assert evidence['distinct_nets']==['GND','VCC_3V3']
 assert evidence['cumulative_drc']['before_unconnected']==37
 assert evidence['cumulative_drc']['after_unconnected']==35
 assert evidence['cumulative_drc']['before_violations']==evidence['cumulative_drc']['after_violations']==16
 assert evidence['fabApproved'] is False
 assert len([p for p in result.namelist() if p.startswith('step-') and p.endswith('-evidence.json')])==2
 print('CHROME_DOWNLOADED_NATIVE_TRANSACTIONAL_TWO_NETS_DRC_37_TO_35=PASS')
PY_CHECK_BATCH
unset ZAPTRACE_COPPER_BATCH
unset ZAPTRACE_COPPER_VIA_PAIR
export ZAPTRACE_COPPER_DOWNLOAD_DIR="$QA/downloads-old"
node scripts/review_studio_native_copper_browser_smoke.mjs
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.11_all.sha256)
echo 'POST_0111_SOURCE_ONLY_CHROME_TWO_VIA_TWO_NET_BATCH_AND_LEGACY_FCU_ALL_PASSED'
