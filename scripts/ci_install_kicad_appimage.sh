#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Osman Aslan <info@oaslananka.dev>
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
#
# KiCad 10 CI toolchain, independent of the Launchpad PPA package endpoint.
# Every downloadable byte is SHA-256 pinned and the AppImage is upstream-signed.

set -euo pipefail

version="10.0.8"
artifact="kicad-${version}-x86_64-lite.AppImage"
archive="${artifact}.tar"
signature="${artifact}.minisig"
expected_archive_sha="abb59cee9f9782736c1b9a92e3ab08b31320ee01d72a6f9442a07fdef71b87d0"
expected_appimage_sha="4dfc6a52f89aa072d206e466a2a1de4c5ef5975d7ef49da24e4d4db0bb40ba3b"
upstream_minisign_pubkey="RWSyix0AVvjWQGZChX64ywBpE5XqV1Eg+ZXYHR3Y27md9EoZ0AtVr9i9"
mirror_primary="https://mirrors.mit.edu/kicad/appimage/stable"
mirror_secondary="https://mirror.nju.edu.cn/kicad/appimage/stable"

if (( $# == 0 )); then
  echo "KiCad AppImage setup needs an explicit kicad package request" >&2
  exit 2
fi

native_packages=(minisign curl ca-certificates)
requested_kicad=false
for package in "$@"; do
  case "$package" in
    kicad) requested_kicad=true ;;
    ngspice|desktop-file-utils) native_packages+=("$package") ;;
    *) echo "Unsupported KiCad CI package request: $package" >&2; exit 2 ;;
  esac
done
if [[ "$requested_kicad" != true ]]; then
  echo "Missing requested KiCad package; refusing to install an unrelated toolchain" >&2
  exit 2
fi

# Keep exactly the same Ubuntu package requirements, but handle degraded
# hosted Azure/Ubuntu mirrors without weakening APT's signed index policy.
bash scripts/ci_install_ubuntu_packages.sh "${native_packages[@]}"

work_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/zaptrace-kicad-1008-XXXXXXXX")"
trap 'rm -rf "$work_dir"' EXIT
cd "$work_dir"

download() {
  local filename="$1"
  local mirror
  for mirror in "$mirror_primary" "$mirror_secondary"; do
    if curl --fail --location --silent --show-error \
      --connect-timeout 12 --max-time 210 --retry 2 \
      --output "$filename" "$mirror/$filename"; then
      return 0
    fi
    echo "KiCad download unavailable from this official mirror; trying the second one" >&2
  done
  return 1
}

download "$archive"
download "$signature"
printf '%s  %s\n' "$expected_archive_sha" "$archive" | sha256sum --check --status

# The tarball is fixed to one known regular filename and its SHA-256 was
# checked before extraction. The signature authenticates the inner AppImage.
if [[ "$(tar tf "$archive")" != "$artifact" ]]; then
  echo "KiCad archive contents differ from the pinned single-file contract" >&2
  exit 1
fi
tar xf "$archive"
printf '%s  %s\n' "$expected_appimage_sha" "$artifact" | sha256sum --check --status
minisign -Vm "$artifact" -x "$signature" -P "$upstream_minisign_pubkey"
chmod 0755 "$artifact"

# Extract once: GitHub-hosted Linux VMs do not need FUSE mount permissions and
# repeated kicad-cli invocations do not re-extract the 300 MiB AppImage.
mkdir extracted
(
  cd extracted
  "../$artifact" --appimage-extract > /dev/null
)
test -x extracted/AppDir/AppRun
install_root="/opt/zaptrace-ci/kicad-${version}"
if [[ -e "$install_root" ]]; then
  echo "Refusing to overwrite an existing KiCad CI toolchain: $install_root" >&2
  exit 1
fi
sudo install -d -m 0755 /opt/zaptrace-ci
sudo mv extracted/AppDir "$install_root"
sudo chown -R root:root "$install_root"

# Keep exactly the existing kicad-cli command used by the oracle and test
# lanes; this redirects *execution*, never skips any native validation.
cat <<'WRAPPER' | sudo tee /usr/local/bin/kicad-cli >/dev/null
#!/bin/sh
# The version probe is a contract for both native CLI and Python pcbnew
# availability. This is the same fixed, verified AppImage; no extra provider.
if [ "$#" -eq 1 ] && [ "$1" = "version" ]; then
  /opt/zaptrace-ci/kicad-10.0.8/AppRun python3.11 -c 'import pcbnew; assert pcbnew.Version() == "10.0.8"' || exit 1
fi
exec /opt/zaptrace-ci/kicad-10.0.8/AppRun kicad-cli "$@"
WRAPPER
sudo chmod 0755 /usr/local/bin/kicad-cli

# Native PCB ECO/parity scripts use the matching upstream Python 3.11 + pcbnew
# bindings bundled with KiCad 10.0.8.  Do not silently fall back to Ubuntu's
# incompatible system Python on the external-tool lane.
cat <<'WRAPPER' | sudo tee /usr/local/bin/kicad-python >/dev/null
#!/bin/sh
exec /opt/zaptrace-ci/kicad-10.0.8/AppRun python3.11 "$@"
WRAPPER
sudo chmod 0755 /usr/local/bin/kicad-python
pcbnew_version="$(/usr/local/bin/kicad-python -c 'import pcbnew; print(pcbnew.Version())')"
if [[ "$pcbnew_version" != "$version" ]]; then
  echo "KiCad pcbnew bindings mismatch: expected $version, got $pcbnew_version" >&2
  exit 1
fi
if [[ -n "${GITHUB_ENV:-}" ]]; then
  printf 'ZAPTRACE_KICAD_PYTHON=appimage\n' >> "$GITHUB_ENV"
fi

installed_version="$(kicad-cli version)"
if [[ "$installed_version" != "$version" ]]; then
  echo "KiCad version mismatch: expected $version, got $installed_version" >&2
  exit 1
fi
echo "Verified signed KiCad $installed_version AppImage and installed native CLI wrapper"
