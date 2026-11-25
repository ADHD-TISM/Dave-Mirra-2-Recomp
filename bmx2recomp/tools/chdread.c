/* chdread: reads data sectors from a CHD disc image for the launcher (bmx2launcher.py Image), which
 * cannot decode CHD itself. Built from runtime/chd_disc.c and third_party/libchdr_all.c (launcher/build_exe.sh does it):
 *   clang -O2 -w -municode -static tools/chdread.c runtime/chd_disc.c third_party/libchdr_all.c -o chdread.exe
 * Paths are taken as UTF-16 (wmain), so any characters work.
 *   chdread info FILE              prints "sectors N"
 *   chdread read FILE LSN COUNT    writes COUNT 2048-byte sectors from LSN to stdout
 *   chdread iso FILE OUT           writes every data sector to OUT (a plain .iso) */
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
#include <fcntl.h>
#include <io.h>
#include "../runtime/chd_disc.h"

static FILE *open_chd(const wchar_t *path) {
    FILE *f = _wfopen(path, L"rb");
    char err[200];
    if (!f) { fprintf(stderr, "cannot open the image\n"); exit(2); }
    if (!chd_disc_is_chd(f)) { fprintf(stderr, "not a CHD image\n"); exit(2); }
    if (chd_disc_open(f, err, sizeof err)) { fprintf(stderr, "cannot read the CHD image: %s\n", err); exit(2); }
    return f;
}

int wmain(int argc, wchar_t **argv) {
    if (argc == 3 && !wcscmp(argv[1], L"info")) {
        open_chd(argv[2]);
        printf("sectors %u\n", chd_disc_sectors());
        return 0;
    }
    if (argc == 5 && !wcscmp(argv[1], L"read")) {
        open_chd(argv[2]);
        unsigned long lsn = wcstoul(argv[3], NULL, 10), n = wcstoul(argv[4], NULL, 10);
        unsigned char s[2048];
        _setmode(_fileno(stdout), _O_BINARY);
        for (unsigned long k = 0; k < n; k++) {
            if (chd_disc_read((uint32_t)(lsn + k), s)) { fprintf(stderr, "read error at sector %lu\n", lsn + k); return 3; }
            if (fwrite(s, 1, 2048, stdout) != 2048) return 3;
        }
        return fflush(stdout) ? 3 : 0;
    }
    if (argc == 4 && !wcscmp(argv[1], L"iso")) {
        open_chd(argv[2]);
        FILE *o = _wfopen(argv[3], L"wb");
        if (!o) { fprintf(stderr, "cannot write the output\n"); return 2; }
        unsigned char s[2048];
        for (uint32_t k = 0; k < chd_disc_sectors(); k++)
            if (chd_disc_read(k, s) || fwrite(s, 1, 2048, o) != 2048) { fprintf(stderr, "error at sector %u\n", k); return 3; }
        return fclose(o) ? 3 : 0;
    }
    fprintf(stderr, "usage: chdread info FILE | read FILE LSN COUNT | iso FILE OUT\n");
    return 1;
}
