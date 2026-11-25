/* Tests runtime/chd_disc.c's CD track parser with good and hostile metadata text. Exit 0 = all passed.
 *   clang -fsanitize=address -g tools/test_chd_disc.c runtime/chd_disc.c third_party/libchdr_all.c -o test_chd_disc.exe
 * (AddressSanitizer turns a buffer overflow into a failure.) */
#include <stdio.h>
#include <string.h>
#include "../runtime/chd_disc.h"

static int failed;
static void check(int ok, const char *what) { printf("%s %s\n", ok ? "ok  " : "FAIL", what); if (!ok) failed++; }

int main(void) {
    char err[200], meta[256], big[201];
    uint32_t frames = 0, lead = 0;
    int off = 0;
    check(chd_disc_parse_track1("TRACK:1 TYPE:MODE2_RAW SUBTYPE:NONE FRAMES:306432 PREGAP:0 PGTYPE:MODE1 PGSUB:RW POSTGAP:0",
                                1, err, sizeof err, &frames, &lead, &off) == 1 && frames == 306432 && !lead && off == -1,
          "chdman createcd of the .bin");
    check(chd_disc_parse_track1("TRACK:1 TYPE:MODE2_RAW SUBTYPE:NONE FRAMES:306432 PREGAP:150 PGTYPE:VMODE2_RAW PGSUB:RW POSTGAP:0",
                                1, err, sizeof err, &frames, &lead, &off) == 1 && frames == 306282 && lead == 150,
          "stored pregap moves LSN 0");
    check(chd_disc_parse_track1("TRACK:1 TYPE:MODE2_RAW SUBTYPE:NONE FRAMES:500 PREGAP:150 PGTYPE:MODE2_RAW PGSUB:RW POSTGAP:0",
                                1, err, sizeof err, &frames, &lead, &off) == 1 && frames == 500 && !lead,
          "pregap not stored (no V): LSN 0 is frame 0");
    check(chd_disc_parse_track1("TRACK:1 TYPE:MODE2_FORM_MIX SUBTYPE:NONE FRAMES:10", 0, err, sizeof err, &frames, &lead,
                                &off) == 1 && off == 8, "MODE2_FORM_MIX, v1 text");
    check(chd_disc_parse_track1("TRACK:1 TYPE:AUDIO SUBTYPE:NONE FRAMES:10", 0, err, sizeof err, &frames, &lead, &off) < 0
          && strstr(err, "not a data track"), "audio first track refused");
    check(chd_disc_parse_track1("TRACK:1 TYPE:MODE1 SUBTYPE:NONE FRAMES:10 PREGAP:10 PGTYPE:VMODE1 PGSUB:RW POSTGAP:0",
                                1, err, sizeof err, &frames, &lead, &off) < 0, "pregap as long as the track refused");
    memset(big, 'A', 200);
    big[200] = 0;
    snprintf(meta, sizeof meta, "TRACK:1 TYPE:%s SUBTYPE:NONE FRAMES:10 PREGAP:0 PGTYPE:MODE1 PGSUB:RW POSTGAP:0", big);
    check(chd_disc_parse_track1(meta, 1, err, sizeof err, &frames, &lead, &off) < 0, "200-character TYPE refused, no overflow");
    snprintf(meta, sizeof meta, "TRACK:1 TYPE:MODE1 SUBTYPE:NONE FRAMES:10 PREGAP:0 PGTYPE:%s PGSUB:%s POSTGAP:0", big, big);
    chd_disc_parse_track1(meta, 1, err, sizeof err, &frames, &lead, &off);
    check(1, "200-character PGTYPE/PGSUB, no overflow");
    snprintf(meta, sizeof meta, "TRACK:1 TYPE:MODE1 SUBTYPE:%s FRAMES:10", big);
    check(chd_disc_parse_track1(meta, 0, err, sizeof err, &frames, &lead, &off) < 0, "200-character SUBTYPE (v1) refused");
    printf("%s\n", failed ? "FAILED" : "all passed");
    return failed != 0;
}
