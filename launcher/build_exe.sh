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
# the licences of the code built into the program (libchdr and its codecs in chdread.exe, and Python), for
# THIRD_PARTY_NOTICES.txt: packed into the program and put next to it (release.sh adds it to the zip)
${PYTHON:-python} -I - "$R/third_party/libchdr" "$WORK/THIRD_PARTY_NOTICES.txt" <<'EOF'
import os, re, sys
top, out = sys.argv[1], sys.argv[2]
def read(*p):
    with open(os.path.join(top, *p), encoding="utf-8") as f:
        return f.read()
miniz = re.search(r"/\*{10,}(.*?)\*{10,}/", read("deps", "miniz-3.1.2", "miniz.c"), re.S).group(1)
miniz = "\n".join(l.strip(" *") for l in miniz.splitlines()).strip()
flac = read("include", "dr_libs", "dr_flac.h")
flac = flac[flac.index("This software is available as a choice"):]
flac = flac[:flac.index("*/")].strip()
parts = [("libchdr (CHD reading, in chdread.exe)", read("LICENSE.txt").strip()),
         ("Zstandard 1.5.7 (in libchdr)", read("deps", "zstd-1.5.7", "LICENSE").strip()),
         ("miniz 3.1.2 (in libchdr)", miniz),
         ("LZMA SDK 26.02 (in libchdr)", read("deps", "lzma-26.02", "LICENSE").strip()),
         ("dr_flac (in libchdr)", flac)]
py = os.path.join(sys.base_prefix, "LICENSE.txt")
if os.path.isfile(py):
    with open(py, encoding="utf-8", errors="replace") as f:
        parts.append(("Python %d.%d (the program runs on it)" % sys.version_info[:2], f.read().strip()))
with open(out, "w", encoding="utf-8", newline="\r\n") as f:
    f.write("Dave Mirra Freestyle BMX 2.exe contains the following third-party code.\n")
    for name, text in parts:
        f.write("\n" + "=" * 78 + "\n" + name + "\n" + "=" * 78 + "\n\n" + text + "\n")
EOF
cp "$WORK/THIRD_PARTY_NOTICES.txt" "$OUT/THIRD_PARTY_NOTICES.txt"
${PYTHON:-python} -m PyInstaller --onefile --windowed --noconfirm --clean --name "Dave Mirra Freestyle BMX 2" \
  --add-data "$WORK/release_tag.txt:." --add-binary "$WORK/chdread.exe:." --add-data "$WORK/THIRD_PARTY_NOTICES.txt:." \
  --distpath "$OUT" --workpath "$WORK" --specpath "$WORK" bmx2launcher.py
echo "built $OUT/Dave Mirra Freestyle BMX 2.exe"
