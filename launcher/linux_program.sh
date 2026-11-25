#!/bin/sh
# The Linux release's program, "Dave Mirra Freestyle BMX 2" (launcher/release.sh linux packs it under that name):
# RecompLauncher's start and setup step, as the .exe is on Windows. It runs bmx2launcher.py, packed next to it,
# with the system's Python 3, and pins the project version in release_tag.txt next to it.
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
    echo "Missing: Python 3. Install it (Debian/Ubuntu: sudo apt install python3), then run the setup again."
    exit 1
fi
if [ -f "$HERE/release_tag.txt" ]; then
    BMX2_RELEASE_TAG=$(head -n 1 "$HERE/release_tag.txt")
    export BMX2_RELEASE_TAG
fi
exec python3 -I "$HERE/bmx2launcher.py" "$@"
