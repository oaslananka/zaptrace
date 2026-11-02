#!/usr/bin/env bash
# Source-only post-0.1.11 acceptance. NEVER a substitute for 0.1.12 package/Ubuntu QA.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
test -f scripts/review_studio_native_copper_batch.py
test -x /usr/bin/python3
test -x .venv/bin/python
test -x .venv/bin/ruff
test -x .venv/bin/pyright
echo '[1/5] Isolated source-only native KiCad batch, server, prior single-route and ECO regressions'
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
 tests/test_review_studio_native_copper_batch.py \
 tests/test_review_studio_native_copper_batch_server.py \
 tests/test_review_studio_native_copper_link.py \
 tests/test_review_studio_native_copper_server.py \
 tests/test_review_studio_pcb_eco.py \
 tests/test_review_studio_pcb_eco_server.py \
 tests/test_review_studio_schematic_eco.py \
 tests/test_review_studio_schematic_eco_server.py \
 tests/test_review_studio_local_server.py \
 tests/test_review_studio_workspace.py \
 tests/test_review_studio_clean_ubuntu_0111_report.py
echo '[2/5] Python source quality (Ruff + Pyright)'
.venv/bin/ruff check scripts/review_studio_build_deb.py scripts/review_studio_native_copper_batch.py \
 scripts/review_studio_native_copper_bundle.py scripts/review_studio_native_copper_link.py \
 scripts/review_studio_local_server.py scripts/review_studio_pcb_eco.py \
 tests/test_review_studio_native_copper_batch.py tests/test_review_studio_native_copper_batch_server.py
.venv/bin/ruff format --check scripts/review_studio_build_deb.py scripts/review_studio_native_copper_batch.py \
 scripts/review_studio_native_copper_bundle.py scripts/review_studio_native_copper_link.py \
 scripts/review_studio_local_server.py scripts/review_studio_pcb_eco.py \
 tests/test_review_studio_native_copper_batch.py tests/test_review_studio_native_copper_batch_server.py
.venv/bin/pyright scripts/review_studio_build_deb.py scripts/review_studio_native_copper_batch.py \
 scripts/review_studio_native_copper_bundle.py scripts/review_studio_native_copper_link.py \
 scripts/review_studio_local_server.py scripts/review_studio_pcb_eco.py \
 tests/test_review_studio_native_copper_batch.py tests/test_review_studio_native_copper_batch_server.py
echo '[3/5] Browser and shell syntax; exact output source safety'
node --check scripts/review_studio_native_copper_browser_smoke.mjs
bash -n scripts/review_studio_native_copper_source_chrome_qa.sh
git diff --check
sha256sum -c build/source-reference-readonly/checksums.sha256
echo '[4/5] Frozen 0.1.11 package/kit unchanged; source-only 0.1.12 cannot mislabel package'
(
 cd build/distribution
 sha256sum -c zaptrace-review-studio_0.1.11_all.sha256
 sha256sum -c zaptrace-review-studio_0.1.11_ubuntu24.04-local-RC.zip.sha256
)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
 tests/test_review_studio_native_copper_batch.py -k post_0111_batch_source_cannot
echo '[5/5] Real authenticated Chrome and KiCad 10 single/via/batch regression'
ZAPTRACE_COPPER_CUSTOM_RULES=1 bash scripts/review_studio_native_copper_source_chrome_qa.sh
echo 'SOURCE ONLY 0.1.12: ALL FIVE GATES PASS; NOT A SIGNED OR PUBLISHABLE DEBIAN RELEASE'
