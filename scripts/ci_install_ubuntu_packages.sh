#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Osman Aslan <info@oaslananka.dev>
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
#
# Install Ubuntu packages on an ephemeral CI runner. Keep Ubuntu's archive
# signature enforcement; if hosted mirror DNS fails, try two signed mirrors.
set -euo pipefail

if (( $# == 0 )); then
  echo "Expected Ubuntu packages to install" >&2
  exit 2
fi

apt_network_options=(
  -o Acquire::Retries=1
  -o Acquire::ForceIPv4=true
  -o Acquire::http::Timeout=18
  -o Acquire::https::Timeout=18
)
if sudo timeout 100s apt-get "${apt_network_options[@]}" -o APT::Update::Error-Mode=any update &&
  sudo timeout 200s apt-get "${apt_network_options[@]}" install --no-install-recommends -y "$@"; then
  exit 0
fi

# Never change developers' configured APT mirrors or add a new trust root.
if [[ "${GITHUB_ACTIONS:-}" != "true" ]]; then
  echo "Default signed Ubuntu archive failed; no CI mirror fallback allowed" >&2
  exit 1
fi

if [[ ! -r /usr/share/keyrings/ubuntu-archive-keyring.gpg ]]; then
  echo "Ubuntu archive signing keyring is missing; refusing fallback" >&2
  exit 1
fi
. /etc/os-release
suite="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
case "$suite" in
  jammy|noble|questing|resolute) ;;
  *) echo "Unsupported Ubuntu suite: $suite" >&2; exit 1 ;;
esac

sources="$(mktemp "${RUNNER_TEMP:-/tmp}/zaptrace-signed-ubuntu-XXXXXX.list")"
trap 'rm -f "$sources"' EXIT
for mirror in https://mirrors.mit.edu/ubuntu https://mirrors.kernel.org/ubuntu; do
  : > "$sources"
  for pocket in "$suite" "$suite-updates" "$suite-security" "$suite-backports"; do
    printf 'deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] %s %s main restricted universe multiverse\n' \
      "$mirror" "$pocket" >> "$sources"
  done

  apt_mirror_options=(
    -o "Dir::Etc::sourcelist=$sources"
    -o Dir::Etc::sourceparts=-
    -o APT::Get::List-Cleanup=0
  )
  echo "Trying signed Ubuntu package index at $mirror for $suite" >&2
  if sudo timeout 100s apt-get "${apt_network_options[@]}" "${apt_mirror_options[@]}" \
      -o APT::Update::Error-Mode=any update &&
    sudo timeout 200s apt-get "${apt_network_options[@]}" "${apt_mirror_options[@]}" \
      install --no-install-recommends -y "$@"; then
    echo "Ubuntu package installation succeeded with signed mirror: $mirror"
    exit 0
  fi
done

echo "All bounded, signature-verified Ubuntu archive attempts failed" >&2
exit 1
