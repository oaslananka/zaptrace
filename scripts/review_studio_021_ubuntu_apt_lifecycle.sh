#!/usr/bin/env bash
# Real disposable Ubuntu 24.04 APT upgrade 0.1.20 -> 0.1.21 -> removal.
# Fail closed, no host package modification and no real user workspace touched.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
NAME=${ZAPTRACE_UBUNTU_QA_CONTAINER:-zt-021-qa-20261013}
[[ "$NAME" == zt-021-qa-* ]] || { echo 'Refusing non-QA container' >&2;exit 2; }
docker inspect --format '{{.HostConfig.NetworkMode}}' "$NAME" |grep -Fx host >/dev/null
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.20_all.sha256 && sha256sum -c zaptrace-review-studio_0.1.21_all.sha256)
docker exec -e DEBIAN_FRONTEND=noninteractive "$NAME" /bin/sh -ec '
 set -e
 DATA=/root/.local/share/zaptrace-review-studio/qa-owned-fixture.bin
 mkdir -p "$(dirname "$DATA")"
 printf "ISOLATED_QA_ONLY_NO_PERSONAL_SOURCE\\n" > "$DATA"
 chmod 600 "$DATA"
 BASE=$(sha256sum "$DATA" | cut -d " " -f1)
 apt-get -qy --allow-downgrades install /tmp/review020.deb
 test "$(dpkg-query -W -f="\${Version}" zaptrace-review-studio)" = 0.1.20
 test "$(kicad-cli version)" = 10.0.7
 echo "APT_020_BASELINE_KICAD_10_0_7=PASS"
 apt-get -qy install /tmp/review021.deb
 test "$(dpkg-query -W -f="\${Version}" zaptrace-review-studio)" = 0.1.21
 test "$(sha256sum "$DATA"|cut -d " " -f1)" = "$BASE"
 test "$(zaptrace-review-studio --version)" = "ZapTrace Review Studio 0.1.21"
 test -f /usr/lib/zaptrace-review-studio/scripts/review_studio_native_kicad.py
 zaptrace-review-studio --doctor
 echo "UBUNTU_24_04_APT_020_TO_021_UPGRADE_AND_DOCTOR=PASS"
 apt-get -qy remove zaptrace-review-studio
 test "$(sha256sum "$DATA"|cut -d " " -f1)" = "$BASE"
 test ! -f /usr/bin/zaptrace-review-studio
 echo "UBUNTU_24_04_APT_021_REMOVAL_PRESERVES_PRIVATE_DATA=PASS"
'
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.21_all.sha256)
echo "PACKAGE_SHA256=$(sha256sum build/distribution/zaptrace-review-studio_0.1.21_all.deb|cut -d ' ' -f1)"
echo 'EXACT_021_REAL_UBUNTU_24_04_UPGRADE_REMOVE=PASS'
