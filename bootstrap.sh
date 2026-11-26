#!/usr/bin/env bash
# Public GitHub bootstrap: no gh auth, git or Python needed to download sources.
set -euo pipefail
if [[ "$(uname -s)" != Linux ]]; then
  echo 'Linux only. On Windows use install.ps1 with PowerShell.' >&2
  exit 1
fi
if [[ $EUID -ne 0 ]]; then
  echo 'Run with: curl -fsSL https://raw.githubusercontent.com/doctorBax/wave/main/bootstrap.sh | sudo bash' >&2
  exit 1
fi
command -v tar >/dev/null || { echo 'tar is required' >&2; exit 1; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
URL='https://github.com/doctorBax/wave/archive/refs/heads/main.tar.gz'
if command -v curl >/dev/null; then
  curl -fLsS --retry 2 "$URL" -o "$TMP/source.tar.gz" || {
    echo 'Cannot download archive. Repository must be public (or authenticated).' >&2; exit 1;
  }
elif command -v wget >/dev/null; then
  wget -q "$URL" -O "$TMP/source.tar.gz" || {
    echo 'Cannot download archive. Repository must be public (or authenticated).' >&2; exit 1;
  }
else
  echo 'Need curl or wget' >&2; exit 1
fi
mkdir -p "$TMP/source"
tar -xzf "$TMP/source.tar.gz" -C "$TMP/source" --strip-components=1
bash "$TMP/source/install.sh"
