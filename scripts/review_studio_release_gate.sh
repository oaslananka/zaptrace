#!/usr/bin/env bash
# Non-publishing, no-root Ubuntu 24.04 / KiCad 10 release candidate gate.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
PY=.venv/bin/python
RUFF=.venv/bin/ruff
PYRIGHT=.venv/bin/pyright
for x in "$PY" "$RUFF" "$PYRIGHT" /usr/bin/python3 /usr/bin/dpkg-deb;do
  [[ -x "$x" ]] || { echo "MISSING RELEASE TOOL: $x" >&2; exit 2; }
done

echo '[1/9] Python integration and package lifecycle tests'
PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest -q -p no:cacheprovider \
  tests/test_kicad_export.py \
  tests/test_kicad_export_native_linkage.py \
  tests/test_kicad_usb4105_oval_slots.py \
  tests/test_kicad_verified_embed.py \
  tests/test_review_studio_native_copper_link.py \
  tests/test_review_studio_native_kicad.py \
  tests/test_review_studio_native_3d.py \
  tests/test_review_studio_schematic_eco.py \
  tests/test_review_studio_schematic_eco_server.py \
  tests/test_review_studio_pcb_eco.py \
  tests/test_review_studio_pcb_eco_server.py \
  tests/test_review_studio_schematic_pcb_parity.py \
  tests/test_review_studio_schematic_pcb_parity_server.py \
  tests/test_review_studio_workspace.py \
  tests/test_review_studio_local_server.py \
  tests/test_review_studio_library.py \
  tests/test_review_studio_desktop_entry.py \
  tests/test_review_studio_distribution.py \
  tests/test_review_studio_release_manifest.py \
  tests/test_review_studio_sign_release.py \
  tests/test_review_studio_release_kit.py \
  tests/test_interactive_viewer.py \
  tests/test_review_studio.py \
  tests/test_review_studio_spec.py \
  tests/test_static_viewer.py

echo '[2/9] Source lint and formatting'
SOURCES=(
  scripts/review_studio_app.py
  scripts/review_studio_build_deb.py
  scripts/review_studio_release_manifest.py
  scripts/review_studio_sign_release.py
  scripts/review_studio_release_kit.py
  scripts/review_studio_local_server.py
  scripts/review_studio_library.py
  scripts/review_studio_workspace.py
  scripts/review_studio_native_kicad.py
  scripts/review_studio_native_copper_link.py
  scripts/review_studio_schematic_eco.py
  scripts/review_studio_pcb_eco.py
  scripts/review_studio_schematic_pcb_parity.py
  scripts/review_studio_desktop_entry.py
  tests/test_review_studio_distribution.py
  tests/test_review_studio_release_manifest.py
  tests/test_review_studio_sign_release.py
  tests/test_review_studio_release_kit.py
  tests/test_review_studio_local_server.py
  tests/test_review_studio_library.py
  tests/test_review_studio_workspace.py
  tests/test_review_studio_native_kicad.py
  tests/test_review_studio_native_3d.py
  tests/test_review_studio_schematic_eco.py
  tests/test_review_studio_schematic_eco_server.py
  tests/test_review_studio_pcb_eco.py
  tests/test_review_studio_pcb_eco_server.py
  tests/test_review_studio_schematic_pcb_parity.py
  tests/test_review_studio_schematic_pcb_parity_server.py
  tests/test_kicad_export_native_linkage.py
  tests/test_kicad_usb4105_oval_slots.py
  tests/test_kicad_verified_embed.py
  tests/test_review_studio_native_copper_link.py
  tests/test_review_studio_desktop_entry.py
  zaptrace/export/kicad.py
  zaptrace/kicad/verified_vendor.py
)
"$RUFF" check "${SOURCES[@]}"
"$RUFF" format --check "${SOURCES[@]}"

echo '[3/9] Type safety'
"$PYRIGHT" scripts/review_studio_app.py scripts/review_studio_build_deb.py \
  scripts/review_studio_release_manifest.py scripts/review_studio_sign_release.py \
  scripts/review_studio_release_kit.py scripts/review_studio_local_server.py scripts/review_studio_library.py \
  scripts/review_studio_workspace.py scripts/review_studio_native_kicad.py \
  scripts/review_studio_schematic_eco.py scripts/review_studio_pcb_eco.py \
  scripts/review_studio_schematic_pcb_parity.py scripts/review_studio_desktop_entry.py zaptrace/export/kicad.py

echo '[4/9] Real native KiCad baseline/copper evidence regeneration'
bash scripts/review_studio_native_local_build.sh

echo '[5/9] JavaScript and shell syntax'
for file in scripts/review_studio_*browser_smoke.mjs;do node --check "$file";done
bash -n scripts/review_studio_local_launch.sh scripts/review_studio_native_local_build.sh

echo '[6/9] Source input SHA-256 unchanged'
sha256sum -c build/source-reference-readonly/checksums.sha256

echo '[7/9] Build reproducible native local application'
/usr/bin/python3 scripts/review_studio_build_deb.py
/usr/bin/python3 scripts/review_studio_build_deb.py --output-dir build/distribution/repro
cmp -s build/distribution/zaptrace-review-studio_0.1.9_all.deb \
       build/distribution/repro/zaptrace-review-studio_0.1.9_all.deb
(
 cd build/distribution
 sha256sum -c zaptrace-review-studio_0.1.9_all.sha256
)

echo '[8/9] Installation metadata and dependency gate'
DESKTOP=build/Review\ Studio.desktop
/usr/bin/python3 scripts/review_studio_desktop_entry.py >/dev/null
/usr/bin/desktop-file-validate "$DESKTOP"
dpkg-deb --field build/distribution/zaptrace-review-studio_0.1.9_all.deb
echo '[9/9] Ubuntu APT dependency simulation for this exact package'
apt-get -s install ./build/distribution/zaptrace-review-studio_0.1.9_all.deb >/dev/null
printf '\nRELEASE GATE: PASS (Ubuntu 24.04 amd64 / KiCad 10 target; local unsigned distribution only)\n'
