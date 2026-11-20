#!/usr/bin/env bash
# Build Loft Lite and add it to a draft release made by the Release workflow. Its signing key stays
# on this computer (never on GitHub), and every update must be signed with that same key, so keep
# a copy of ~/.local/share/android-build/loft.keystore somewhere safe.
# Its checksum goes into SHA256SUMS.txt, which the app checks updates against.
#   bash packaging/attach-apk.sh v0.1.2
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${1:?give the release tag, like v0.1.2}"
V="${TAG#v}"
grep -q "VERSION_NAME:-$V}" android-lite/build.sh || { echo "android-lite/build.sh isn't at version $V"; exit 1; }
bash android-lite/build.sh
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp android-lite/build/loft-lite.apk "$work/loft-lite-$V.apk"
gh release download "$TAG" -p SHA256SUMS.txt -D "$work"
grep -v " loft-lite-" "$work/SHA256SUMS.txt" > "$work/sums" || true
(cd "$work" && sha256sum "loft-lite-$V.apk" >> sums && sort -k2 sums > SHA256SUMS.txt)
gh release upload "$TAG" "$work/loft-lite-$V.apk" "$work/SHA256SUMS.txt" --clobber
echo "Attached loft-lite-$V.apk to $TAG. Publish the draft when it's ready."
