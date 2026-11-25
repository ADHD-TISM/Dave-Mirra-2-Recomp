#!/bin/sh
# Build the one-file program: launcher/dist/Dave Mirra Freestyle BMX 2.exe. It has no window: RecompLauncher runs
# it (recomplauncher.json), and it builds the game from the player's disc and starts it.
# Needs Python 3 and PyInstaller 6 or later (python -m pip install pyinstaller).
# DIST=<folder> builds into another folder.
# RELEASE_TAG=<version> (launcher/release.sh sets it) packs that project version in: the setup step ("prepare")
# then installs exactly it, not the newest one.
set -e
OUT=${DIST:-$(dirname "$0")/dist}
mkdir -p "$OUT"
OUT=$(CDPATH= cd -- "$OUT" && pwd)
CDPATH= cd -- "$(dirname -- "$0")"
WORK=../work/launcher_pyi
mkdir -p "$WORK"
WORK=$(CDPATH= cd -- "$WORK" && pwd)
printf '%s\n' "$RELEASE_TAG" > "$WORK/release_tag.txt"   # empty without RELEASE_TAG: then the newest is taken
# chdread.exe reads CHD images for the program (Python cannot decode them); also left next to bmx2launcher.py
# for runs from source. Needs clang for Windows (llvm-mingw); CC=<compiler> picks another.
R=../bmx2recomp
${CC:-clang} -O2 -w -municode -static "$R/tools/chdread.c" "$R/runtime/chd_disc.c" "$R/third_party/libchdr_all.c" \
  -o "$WORK/chdread.exe"
cp "$WORK/chdread.exe" chdread.exe
${PYTHON:-python} -m PyInstaller --onefile --windowed --noconfirm --clean --name "Dave Mirra Freestyle BMX 2" \
  --add-data "$WORK/release_tag.txt:." --add-binary "$WORK/chdread.exe:." \
  --distpath "$OUT" --workpath "$WORK" --specpath "$WORK" bmx2launcher.py
echo "built $OUT/Dave Mirra Freestyle BMX 2.exe"
