#!/usr/bin/env bash
# Actual APT 0.1.12 -> 0.1.13 upgrade/remove in an owned disposable Ubuntu
# 24.04 QA container; private user data must persist. NEVER run against host.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
NAME=${ZAPTRACE_UBUNTU_QA_CONTAINER:-zt-013-qa-20261012}
[[ "$NAME" == zt-013-qa-* ]] || { echo 'Refuse non-QA container name' >&2;exit 2; }
docker inspect --format '{{.HostConfig.NetworkMode}}' "$NAME" | grep -Fx host >/dev/null
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.12_all.sha256 && sha256sum -c zaptrace-review-studio_0.1.13_all.sha256)
docker cp build/distribution/zaptrace-review-studio_0.1.12_all.deb "$NAME:/tmp/old012.deb"
docker exec -e DEBIAN_FRONTEND=noninteractive "$NAME" /bin/sh -ec '
 set -e
 DATA=/root/.local/share/zaptrace-review-studio/private-preserved-ui-record.bin
 mkdir -p "$(dirname "$DATA")"
 printf "LOCAL_QA_ONLY_RANDOM_CONTENT_NOT_A_REAL_USER\n" > "$DATA"
 chmod 600 "$DATA"
 OLD=$(sha256sum "$DATA" | cut -d " " -f1)
 apt-get -qy --allow-downgrades install /tmp/old012.deb
 test "$(dpkg-query -W -f="\${Version}" zaptrace-review-studio)" = 0.1.12
 test "$(sha256sum "$DATA" | cut -d " " -f1)" = "$OLD"
 printf "REAL_012_BASELINE_APT_INSTALLED_WITH_USER_DATA=PASS\n"
 apt-get -qy install /tmp/review013.deb
 test "$(dpkg-query -W -f="\${Version}" zaptrace-review-studio)" = 0.1.13
 test "$(sha256sum "$DATA" | cut -d " " -f1)" = "$OLD"
 test "$(zaptrace-review-studio --version)" = "ZapTrace Review Studio 0.1.13"
 printf "REAL_012_TO_013_APT_UPGRADE_PRESERVES_PRIVATE_USER_DATA=PASS\n"
 apt-get -qy remove zaptrace-review-studio
 test "$(sha256sum "$DATA" | cut -d " " -f1)" = "$OLD"
 test ! -f /usr/bin/zaptrace-review-studio
 printf "REAL_013_APT_REMOVE_RETAINS_USER_DATA_AND_REMOVES_BINARIES=PASS\n"
'
(cd build/distribution && sha256sum -c zaptrace-review-studio_0.1.12_all.sha256 && sha256sum -c zaptrace-review-studio_0.1.13_all.sha256)
echo "PACKAGE_SHA256=$(sha256sum build/distribution/zaptrace-review-studio_0.1.13_all.deb | cut -d ' ' -f1)"
echo 'SIGNED_KICAD_10_SOURCES_UNMODIFIED=PASS'
echo 'UBUNTU_24_04_REAL_012_TO_013_UPGRADE_REMOVE_PRIVATE_PRESERVED=PASS'
