#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Osman Aslan <info@oaslananka.dev>
# SPDX-License-Identifier: MIT

set -euo pipefail

if (( $# == 0 )); then
  echo "usage: ci_install_kicad.sh <apt-package> [<apt-package> ...]" >&2
  exit 2
fi

for attempt in 1 2 3; do
  echo "Adding KiCad 10 PPA (attempt ${attempt}/3)"
  if sudo timeout 90s add-apt-repository --yes --no-update ppa:kicad/kicad-10.0-releases; then
    break
  fi
  if (( attempt == 3 )); then
    echo "Unable to add KiCad 10 PPA after 3 bounded attempts" >&2
    exit 1
  fi
  sleep $((attempt * 5))
done

ubuntu_mirror_file="/etc/apt/apt-mirrors.txt"
if [[ -f "$ubuntu_mirror_file" ]] && grep -q "azure.archive.ubuntu.com/ubuntu" "$ubuntu_mirror_file"; then
  echo "Replacing runner-local Azure Ubuntu mirror with archive.ubuntu.com"
  sudo sed -i -E 's#https?://azure\.archive\.ubuntu\.com/ubuntu#https://archive.ubuntu.com/ubuntu#g' "$ubuntu_mirror_file"
fi

apt_network_options=(
  -o Acquire::Retries=3
  -o Acquire::http::Timeout=30
  -o Acquire::https::Timeout=30
)

sudo timeout 300s apt-get "${apt_network_options[@]}" update
sudo timeout 600s apt-get "${apt_network_options[@]}" install --no-install-recommends -y "$@"
