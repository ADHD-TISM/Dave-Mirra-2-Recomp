#!/bin/sh
# Build the one-file launcher exe and put it next to the "Dave Mirra 2" folder:
#   Dave Mirra PS2/Dave Mirra 2 Launcher.exe
# Needs Python 3 with Tk and PyInstaller (python -m pip install pyinstaller).
set -e
cd "$(dirname "$0")"
${PYTHON:-python} -m PyInstaller --onefile --windowed --noconfirm --clean --name "Dave Mirra 2 Launcher" \
  --distpath dist --workpath ../work/launcher_pyi --specpath ../work/launcher_pyi bmx2launcher.py
cp "dist/Dave Mirra 2 Launcher.exe" ..
echo "built $(cd .. && pwd)/Dave Mirra 2 Launcher.exe"
