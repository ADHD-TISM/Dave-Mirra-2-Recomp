/* CHD disc images: see chd_disc.h. One hunk is kept decoded; reads are sequential in practice. */
#include "chd_disc.h"
#include <string.h>
#include <stdlib.h>
#include "../third_party/libchdr/include/libchdr/chd.h"

static chd_file *chd;
static uint8_t *hunk;               /* the decoded hunk cur_hunk, hunkbytes long */
static uint32_t cur_hunk = UINT32_MAX, unit, per_hunk, nsect, hunkbytes;
static int data_off = -1;           /* where the 2048 data bytes sit in a unit; -1 = by the sector's mode byte */

int chd_disc_is_chd(FILE *f) {
    char m[8] = { 0 };
    int ok = fseek(f, 0, SEEK_SET) == 0 && fread(m, 1, 8, f) == 8 && !memcmp(m, "MComprHD", 8);
    fseek(f, 0, SEEK_SET);
    return ok;
}

/* track 1's layout, from the CD metadata: the data offset in a 2352-byte sector, and its frame count */
static int cd_track1(char *err, size_t errlen, uint32_t *frames) {
    char meta[256] = { 0 }, type[32] = { 0 }, sub[32];
    uint32_t len = 0, tag = 0;
    uint8_t flags = 0;
    int track = 0, n = 0;
    if (chd_get_metadata(chd, CDROM_TRACK_METADATA2_TAG, 0, meta, sizeof meta - 1, &len, &tag, &flags) != CHDERR_NONE &&
        chd_get_metadata(chd, CDROM_TRACK_METADATA_TAG, 0, meta, sizeof meta - 1, &len, &tag, &flags) != CHDERR_NONE)
        return 0;                    /* not a CD: a DVD image of 2048-byte sectors */
    if (sscanf(meta, "TRACK:%d TYPE:%31s SUBTYPE:%31s FRAMES:%d", &track, type, sub, &n) < 4 || track != 1 || n <= 0) {
        snprintf(err, errlen, "unreadable CD track information: %.80s", meta);
        return -1;
    }
    *frames = (uint32_t)n;
    if (!strcmp(type, "MODE1") || !strcmp(type, "MODE2_FORM1")) data_off = 0;      /* stored as 2048 bytes */
    else if (!strcmp(type, "MODE2")) data_off = 8;                                  /* 2336: subheader first */
    else if (!strcmp(type, "MODE1_RAW") || !strcmp(type, "MODE2_RAW")) data_off = -1;   /* full 2352 sectors */
    else { snprintf(err, errlen, "the first track is %s, not a data track", type); return -1; }
    return 1;
}

int chd_disc_open(FILE *f, char *err, size_t errlen) {
    chd_disc_close();
    chd_error e = chd_open_file(f, CHD_OPEN_READ, NULL, &chd);
    if (e != CHDERR_NONE) {
        snprintf(err, errlen, "%s", e == CHDERR_REQUIRES_PARENT ? "it needs a parent CHD (a diff image): use the full image"
                                                               : chd_error_string(e));
        chd = NULL;
        return -1;
    }
    const chd_header *h = chd_get_header(chd);
    hunkbytes = h->hunkbytes;
    unit = h->unitbytes;
    uint32_t frames = 0;
    int cd = cd_track1(err, errlen, &frames);
    if (cd < 0) { chd_disc_close(); return -1; }
    if (!cd) {
        data_off = 0;
        if (unit != 2048) { snprintf(err, errlen, "unexpected sector size %u", unit); chd_disc_close(); return -1; }
        frames = (uint32_t)(h->logicalbytes / 2048);
    } else if (unit < 2352) {
        snprintf(err, errlen, "unexpected CD frame size %u", unit);
        chd_disc_close();
        return -1;
    }
    if (!unit || !hunkbytes || hunkbytes % unit) { snprintf(err, errlen, "bad hunk size"); chd_disc_close(); return -1; }
    per_hunk = hunkbytes / unit;
    nsect = frames;
    hunk = malloc(hunkbytes);
    if (!hunk) { snprintf(err, errlen, "out of memory"); chd_disc_close(); return -1; }
    cur_hunk = UINT32_MAX;
    return 0;
}

uint32_t chd_disc_sectors(void) { return nsect; }

int chd_disc_read(uint32_t lsn, uint8_t *out) {
    if (!chd || lsn >= nsect) { memset(out, 0, 2048); return chd ? 0 : -1; }
    uint32_t hn = lsn / per_hunk;
    if (hn != cur_hunk) {
        if (chd_read(chd, hn, hunk) != CHDERR_NONE) { cur_hunk = UINT32_MAX; memset(out, 0, 2048); return -1; }
        cur_hunk = hn;
    }
    const uint8_t *s = hunk + (size_t)(lsn % per_hunk) * unit;
    int off = data_off >= 0 ? data_off : s[15] == 2 ? 24 : 16;    /* raw: MODE2 form 1 data at 24, MODE1 at 16 */
    memcpy(out, s + off, 2048);
    return 0;
}

void chd_disc_close(void) {
    if (chd) chd_close(chd);
    chd = NULL;
    free(hunk);
    hunk = NULL;
    cur_hunk = UINT32_MAX;
    nsect = 0;
}
