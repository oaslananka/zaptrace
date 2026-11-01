#!/usr/bin/env bash
# Native Review Studio: opens a local browser, no cloud, GitHub or source writes.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
PY=/usr/bin/python3
if [[ ! -x "$PY" ]] || ! command -v kicad-cli >/dev/null 2>&1; then
  echo 'Requires Ubuntu system Python with pcbnew and the local KiCad CLI.' >&2
  exit 2
fi
WORKSPACE="${ZAPTRACE_REVIEW_WORKSPACE:-build/review-studio-workspace}"
if [[ ! -f "$WORKSPACE/projects.json" ]]; then
  echo 'Creating the initial local native KiCad project workspace…'
  bash scripts/review_studio_native_local_build.sh
fi
mkdir -p "$WORKSPACE"
LOG=$(mktemp /tmp/zaptrace-review-server-XXXXXX)
"$PY" -u scripts/review_studio_local_server.py --workspace "$WORKSPACE" --port 0 >"$LOG" 2>&1 &
PID=$!
finish(){ kill "$PID" 2>/dev/null || :; wait "$PID" 2>/dev/null || :; rm -f -- "$LOG"; }
trap finish EXIT INT TERM
URL=''
for _ in $(seq 1 100); do
  if ! kill -0 "$PID" 2>/dev/null; then cat "$LOG" >&2; exit 2; fi
  URL=$(sed -n 's/^LOCAL REVIEW STUDIO: //p' "$LOG" | head -1)
  if [[ "$URL" == http://127.0.0.1:* ]]; then break; fi
  sleep .1
done
if [[ -z "$URL" ]]; then cat "$LOG" >&2; exit 2; fi
printf '\nZapTrace Review Studio — local KiCad engine\nOpen: %s\nLeave this launcher running while using the browser; Ctrl+C to stop.\nNo cloud, no source PCB modifications and no fab approval.\n\n' "$URL"
if [[ "${ZAPTRACE_NO_BROWSER:-0}" != 1 ]]; then
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || echo "Open manually: $URL"; fi
fi
wait "$PID"
