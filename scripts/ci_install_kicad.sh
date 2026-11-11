#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Osman Aslan <info@oaslananka.dev>
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0

set -euo pipefail

if (( $# == 0 )); then
  echo "usage: ci_install_kicad.sh <apt-package> [<apt-package> ...]" >&2
  exit 2
fi

# The simulation-only and utility jobs need Ubuntu packages, not KiCad.
# Avoid making their mandatory evidence dependent on Launchpad PPA availability.
needs_kicad_ppa=false
for package in "$@"; do
  case "$package" in
    kicad|kicad-*) needs_kicad_ppa=true; break ;;
  esac
done

# A successful PPA bootstrap also depends on Launchpad's signing-key API.
# If that API is unavailable, configure the *same* PPA using a locally pinned
# public signing key. APT still checks the Release signature on every install.
configure_kicad_ppa_with_pinned_key() {
  local key_file="security/kicad-10-ppa-signing-key.asc"
  local expected_fingerprint="FDA854F61C4D0D9572BB95E5245D5502FAD7A805"
  local actual_fingerprint codename source_file
  if [[ ! -f "$key_file" ]]; then
    echo "KiCad PPA signing key fixture missing: $key_file" >&2
    return 1
  fi
  actual_fingerprint="$(gpg --batch --show-keys --with-colons "$key_file" 2>/dev/null |
    awk -F: '$1 == "fpr" { print $10; exit }')"
  if [[ "$actual_fingerprint" != "$expected_fingerprint" ]]; then
    echo "KiCad PPA signing key fingerprint mismatch: refusing unsigned/untrusted fallback" >&2
    return 1
  fi

  # GHA's supported Ubuntu runner series; fail closed on an unknown distro.
  . /etc/os-release
  codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
  case "$codename" in
    jammy|noble|questing|resolute) ;;
    *)
      echo "No pinned KiCad 10 PPA fallback for Ubuntu suite: $codename" >&2
      return 1
      ;;
  esac

  echo "Configuring KiCad 10 PPA using pre-verified fingerprint $expected_fingerprint"
  sudo install -D -m 0644 "$key_file" /usr/share/keyrings/zaptrace-kicad-10-ppa.asc
  # Overwrite the exact partial source path add-apt-repository may have left
  # behind, avoiding duplicate repository definitions with conflicting keys.
  source_file="/etc/apt/sources.list.d/kicad-ubuntu-kicad-10_0-releases-${codename}.sources"
  printf 'Types: deb\nURIs: https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu/\nSuites: %s\nComponents: main\nSigned-By: /usr/share/keyrings/zaptrace-kicad-10-ppa.asc\n' "$codename" |
    sudo tee "$source_file" >/dev/null
}

if [[ "$needs_kicad_ppa" == true ]]; then
  for attempt in 1 2 3; do
    echo "Adding KiCad 10 PPA (attempt ${attempt}/3)"
    if sudo timeout 90s add-apt-repository --yes --no-update ppa:kicad/kicad-10.0-releases; then
      break
    fi
    if (( attempt == 3 )); then
      echo "Launchpad PPA API unavailable after 3 bounded attempts; verifying pinned signed fallback" >&2
      configure_kicad_ppa_with_pinned_key || exit 1
      break
    fi
    sleep $((attempt * 5))
  done
else
  echo "No KiCad package requested: use the Ubuntu archive without adding a KiCad PPA"
fi

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
