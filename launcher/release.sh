#!/bin/sh
# Pack a release: DaveMirraFreestyleBMX2-<version>-Windows-x64.zip with "Dave Mirra Freestyle BMX 2.exe",
# recomplauncher.json (RecompLauncher installs from it) and THIRD_PARTY_NOTICES.txt (the licences of the code
# built into the exe) at the top. Attach the zip to the GitHub release.
# usage: sh launcher/release.sh v1.2.3 [out folder]      (out folder: launcher/dist)
# Needs what build_exe.sh needs.
set -e
V=${1:?usage: sh launcher/release.sh <version, like v1.2.3> [out folder]}
# the packed program only takes a version of this form (release_tag and version_tuple in bmx2launcher.py)
if ! printf '%s\n' "$V" | grep -Eq '^v[0-9]+(\.[0-9]+)*$'; then
    echo "the version must look like v1.2.3, not $V" >&2; exit 2
fi
# players' setup step downloads the project at this tag, so it must be this commit, here and on GitHub
# (TRY_RELEASE=1 skips these checks, for a test zip that is never published)
if [ "$TRY_RELEASE" != 1 ]; then
    REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
    G() { git -C "$REPO_DIR" "$@"; }   # the repository, wherever this is run from (its path may have spaces)
    HEAD=$(G rev-parse HEAD)
    [ -z "$(G status --porcelain --untracked-files=no)" ] || { echo "the working tree has changes: commit them first" >&2; exit 2; }
    [ "$(G rev-parse "$V^{commit}" 2>/dev/null)" = "$HEAD" ] || { echo "tag $V is not on HEAD" >&2; exit 2; }
    # on GitHub the tag must name this commit too (^{} is an annotated tag's commit; a plain tag has none)
    REFS=$(G ls-remote --tags origin)   # matched exactly: ls-remote's own patterns also match the end of longer names
    REMOTE=$(printf '%s\n' "$REFS" | awk -v r="refs/tags/$V^{}" '$2 == r { print $1 }')
    [ -n "$REMOTE" ] || REMOTE=$(printf '%s\n' "$REFS" | awk -v r="refs/tags/$V" '$2 == r { print $1 }')
    [ "$REMOTE" = "$HEAD" ] || { echo "tag $V on origin is ${REMOTE:-missing}, not HEAD: push the tag" >&2; exit 2; }
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
' "$ZIP" "$OUT/Dave Mirra Freestyle BMX 2.exe" "$HERE/../recomplauncher.json" "$OUT/THIRD_PARTY_NOTICES.txt"
echo "packed $ZIP"
