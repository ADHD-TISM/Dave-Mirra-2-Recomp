#!/bin/sh
# Pack a release: DaveMirraFreestyleBMX2-<version>-Windows-x64.zip with "Dave Mirra Freestyle BMX 2.exe" and
# recomplauncher.json at the top (RecompLauncher installs from it). Attach the zip to the GitHub release.
# usage: sh launcher/release.sh v1.2.3 [out folder]      (out folder: launcher/dist)
# Needs what build_exe.sh needs.
set -e
V=${1:?usage: sh launcher/release.sh <version, like v1.2.3> [out folder]}
# the packed program only takes a version of this form (release_tag and version_tuple in bmx2launcher.py)
if ! printf '%s\n' "$V" | grep -Eq '^v[0-9]+(\.[0-9]+)*$'; then
    echo "the version must look like v1.2.3, not $V" >&2; exit 2
fi
# players' setup step downloads the project at this tag, so it must be this commit and on GitHub
# (TRY_RELEASE=1 skips these checks, for a test zip that is never published)
if [ -z "$TRY_RELEASE" ]; then
    [ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "the working tree has changes: commit them first" >&2; exit 2; }
    [ "$(git rev-parse "$V^{commit}" 2>/dev/null)" = "$(git rev-parse HEAD)" ] || { echo "tag $V is not on HEAD" >&2; exit 2; }
    git ls-remote --exit-code --tags origin "refs/tags/$V" > /dev/null || { echo "tag $V is not pushed to origin" >&2; exit 2; }
fi
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
