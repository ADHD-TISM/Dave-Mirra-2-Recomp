#!/bin/sh
# Pack a release: DaveMirraFreestyleBMX2-<version>-Windows-x64.zip with "Dave Mirra Freestyle BMX 2.exe" and
# recomplauncher.json at the top (RecompLauncher installs from it). Attach the zip to the GitHub release.
# usage: sh launcher/release.sh v1.2.3 [out folder]      (out folder: launcher/dist)
# Needs what build_exe.sh needs.
set -e
V=${1:?usage: sh launcher/release.sh <version, like v1.2.3> [out folder]}
case "$V" in   # the packed program only takes a version of this form (release_tag in bmx2launcher.py)
    v[0-9]*) ;;
    *) echo "the version must look like v1.2.3, not $V" >&2; exit 2 ;;
esac
OUT=${2:-$(dirname -- "$0")/dist}
mkdir -p "$OUT"
OUT=$(CDPATH= cd -- "$OUT" && pwd)
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RELEASE_TAG="$V" DIST="$OUT" sh "$HERE/build_exe.sh"
ZIP="$OUT/DaveMirraFreestyleBMX2-$V-Windows-x64.zip"
${PYTHON:-python} -c '
import os, sys, zipfile
out, files = sys.argv[1], sys.argv[2:]
with zipfile.ZipFile(out + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(f, os.path.basename(f))
os.replace(out + ".tmp", out)
' "$ZIP" "$OUT/Dave Mirra Freestyle BMX 2.exe" "$HERE/../recomplauncher.json"
echo "packed $ZIP"
