#!/bin/sh
# Build bmx2.exe: generated EE code (gen/) + runtime. Objects cached in build/.
set -e
cd "$(dirname "$0")"
CC=${CC:-clang}
OPT=${OPT:--O2}
mkdir -p build/obj
CFLAGS="$OPT -g -fno-strict-aliasing -fwrapv -Wall -Wno-unused-but-set-variable -Iruntime -Igen -Igen_vu -Wno-unused-function"
compile() {
  src=$1; obj=build/obj/$(echo "$src" | tr '/' '_' | sed 's/\.c$/.o/')
  if [ ! -f "$obj" ] || [ "$src" -nt "$obj" ] || [ runtime/ee.h -nt "$obj" ]; then
    $CC $CFLAGS -c "$src" -o "$obj" || exit 1
  fi
}
export -f compile 2>/dev/null || true
export CC CFLAGS
ls gen/*.c gen_iop/*.c runtime/*.c | xargs -P 16 -I{} sh -c '
  src={}; obj=build/obj/$(echo "$src" | tr "/" "_" | sed "s/\.c$/.o/")
  if [ ! -f "$obj" ] || [ "$src" -nt "$obj" ] || [ runtime/ee.h -nt "$obj" ] || [ runtime/rt.h -nt "$obj" ] || [ runtime/iop.h -nt "$obj" ] || { case "$src" in runtime/*) [ runtime/config.h -nt "$obj" ] || [ runtime/gs.h -nt "$obj" ];; *) false;; esac; } || { [ "$src" = runtime/vu.c ] && [ -f gen_vu/vu1_rec.h ] && [ gen_vu/vu1_rec.h -nt "$obj" ]; }; then
    $CC $CFLAGS -c "$src" -o "$obj" || exit 255
  fi'
# icon (from the disc's memory card icon) and name: runtime/bmx2.rc
if [ -f ../disc/ASSETS/ICON.DAT ] && { [ ! -f gen/bmx2.ico ] || [ tools/make_icon.py -nt gen/bmx2.ico ]; }; then
  python -I tools/make_icon.py ../disc/ASSETS/ICON.DAT gen/bmx2.ico
fi
if [ -f gen/bmx2.ico ] && ! command -v "${WINDRES:-windres}" >/dev/null; then
  echo "no windres: building without the icon"; rm -f build/obj/bmx2_res.o
elif [ -f gen/bmx2.ico ]; then
  res=build/obj/bmx2_res.o
  if [ ! -f $res ] || [ runtime/bmx2.rc -nt $res ] || [ gen/bmx2.ico -nt $res ]; then ${WINDRES:-windres} -I gen -i runtime/bmx2.rc -O coff -o $res; fi
fi
$CC -g build/obj/*.o -o build/bmx2.exe -Wl,--stack,67108864 -lwinmm -lgdi32 -luser32 -lopengl32
echo "built build/bmx2.exe"
