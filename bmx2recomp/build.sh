#!/bin/sh
# Build bmx2.exe (Windows, llvm-mingw clang) or bmx2 (Linux x86-64: gcc or clang
# + SDL2 + libGL): generated EE code (gen/) + runtime. Objects cached in build/.
set -e
cd "$(dirname "$0")"
case "$(uname -s)" in Linux) LINUX=1 ;; *) LINUX= ;; esac
if [ -n "$LINUX" ]; then
  if [ -z "$CC" ]; then if command -v clang >/dev/null; then CC=clang; else CC=gcc; fi; fi
  SDL_CFLAGS=$(sdl2-config --cflags 2>/dev/null || pkg-config --cflags sdl2) || { echo "SDL2 development files are missing (Debian/Ubuntu: apt install libsdl2-dev)"; exit 1; }
  SDL_CFLAGS="$SDL_CFLAGS -Wno-misleading-indentation"   # gcc's style warning on one-line ifs the code uses throughout
  SDL_LIBS=$(sdl2-config --libs 2>/dev/null || pkg-config --libs sdl2)
else
  CC=${CC:-clang}
  SDL_CFLAGS=
fi
OPT=${OPT:--O2}
# objects per system: a Windows checkout used from WSL must not link Windows objects into a Linux build
if [ -n "$LINUX" ]; then OBJ=build/obj-linux; else OBJ=build/obj; fi
export OBJ
mkdir -p $OBJ
CFLAGS="$OPT -g -fno-strict-aliasing -fwrapv -Wall -Wno-unused-but-set-variable -Iruntime -Igen -Igen_vu -Wno-unused-function $SDL_CFLAGS"
compile() {
  src=$1; obj=$OBJ/$(echo "$src" | tr '/' '_' | sed 's/\.c$/.o/')
  if [ ! -f "$obj" ] || [ "$src" -nt "$obj" ] || [ runtime/ee.h -nt "$obj" ]; then
    $CC $CFLAGS -c "$src" -o "$obj" || exit 1
  fi
}
[ -z "$BASH_VERSION" ] || export -f compile 2>/dev/null || true   # bash only (dash, Linux sh, stops at export -f)
export CC CFLAGS
ls gen/*.c gen_iop/*.c runtime/*.c | xargs -P 16 -I{} sh -c '
  src={}; obj=$OBJ/$(echo "$src" | tr "/" "_" | sed "s/\.c$/.o/")
  if [ ! -f "$obj" ] || [ "$src" -nt "$obj" ] || [ runtime/ee.h -nt "$obj" ] || [ runtime/rt.h -nt "$obj" ] || [ runtime/iop.h -nt "$obj" ] || { case "$src" in runtime/*) [ runtime/config.h -nt "$obj" ] || [ runtime/plat.h -nt "$obj" ] || { [ "$src" = runtime/font_posix.c ] && [ third_party/stb_truetype.h -nt "$obj" ]; } || [ runtime/gs.h -nt "$obj" ] || [ runtime/chd_disc.h -nt "$obj" ] || { [ "$src" = runtime/chd_disc.c ] && [ -n "$(find third_party/libchdr/include -newer "$obj" -name "*.h" | head -1)" ]; } || { [ "$src" = runtime/achievements.c ] && [ -n "$(find third_party/rl_achievements/include -newer "$obj" -name "*.h" | head -1)" ]; };; *) false;; esac; } || { [ "$src" = runtime/vu.c ] && [ -f gen_vu/vu1_rec.h ] && [ gen_vu/vu1_rec.h -nt "$obj" ]; }; then
    $CC $CFLAGS -c "$src" -o "$obj" || exit 255
  fi'
# libchdr (CHD images, runtime/chd_disc.c): third-party code, built once without warnings
if [ ! -f $OBJ/libchdr_all.o ] || [ -n "$(find third_party/libchdr third_party/libchdr_all.c -newer $OBJ/libchdr_all.o -name '*.[ch]' | head -1)" ]; then
  $CC $OPT -w -c third_party/libchdr_all.c -o $OBJ/libchdr_all.o
fi
# Recomp Achievements (runtime/achievements.c): third-party code, built once without warnings (both systems)
RLA=third_party/rl_achievements
if [ ! -f $OBJ/rl_achievements_all.o ] || [ -n "$(find $RLA third_party/rl_achievements_all.c -newer $OBJ/rl_achievements_all.o -name '*.[ch]' | head -1)" ]; then
  $CC $OPT -w -DRC_DISABLE_LUA -I$RLA/include -I$RLA/third_party/rcheevos/include -I$RLA/third_party/rcheevos/src -I$RLA/third_party/cjson \
    -c third_party/rl_achievements_all.c -o $OBJ/rl_achievements_all.o
fi
if [ -n "$LINUX" ]; then
  # no exe resources on Linux (the launcher's .desktop entry carries the icon)
  rm -f $OBJ/bmx2_res.o
  $CC -g $OBJ/*.o -o build/bmx2 $SDL_LIBS -lGL -lEGL -lm -lpthread
  echo "built build/bmx2"
  exit 0
fi
# icon (from the disc's memory card icon) and name: runtime/bmx2.rc
if [ -f ../disc/ASSETS/ICON.DAT ] && { [ ! -f gen/bmx2.ico ] || [ tools/make_icon.py -nt gen/bmx2.ico ]; }; then
  python -I tools/make_icon.py ../disc/ASSETS/ICON.DAT gen/bmx2.ico
fi
# plus the manifest (UTF-8 paths: runtime/bmx2.manifest), with or without the icon; remade every build (fast)
if ! command -v "${WINDRES:-windres}" >/dev/null; then
  echo "no windres: building without the icon and the manifest"; rm -f $OBJ/bmx2_res.o
else
  icon=; [ -f gen/bmx2.ico ] && icon=-DBMX2_ICON
  ${WINDRES:-windres} -I gen -I runtime $icon -i runtime/bmx2.rc -O coff -o $OBJ/bmx2_res.o
fi
$CC -g $OBJ/*.o -o build/bmx2.exe -Wl,--stack,67108864 -lwinmm -lgdi32 -luser32 -lopengl32
echo "built build/bmx2.exe"
