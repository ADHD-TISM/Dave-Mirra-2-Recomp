/* CHD disc images (MAME's compressed format, chdman createcd / createdvd), read with libchdr
 * (third_party/libchdr, BSD). Gives the game's 2048-byte data sectors by LSN, like a .iso.
 * Used by iop.c (the game's disc) and tools/chdread.c (the launcher's helper). */
#ifndef CHD_DISC_H
#define CHD_DISC_H
#include <stdio.h>
#include <stdint.h>

/* True when the file starts with the CHD magic ("MComprHD"). Leaves the position at 0. */
int chd_disc_is_chd(FILE *f);

/* Opens a CHD on an open file (the file must stay open). 0 on success, else -1 with a reason in err. */
int chd_disc_open(FILE *f, char *err, size_t errlen);

/* Number of data sectors, after a successful open. */
uint32_t chd_disc_sectors(void);

/* Reads one 2048-byte data sector; past the end gives zeros. 0 on success, -1 on a read error. */
int chd_disc_read(uint32_t lsn, uint8_t *out);

void chd_disc_close(void);

/* Parses one CD track metadata text (v2 = CHT2, else CHTR) for track 1: frames = data sectors, lead = stored
 * pregap frames before LSN 0, off = data offset in a sector (-1 = by its mode byte). 1, or -1 with err.
 * Used by chd_disc_open; separate so tools/test_chd_disc.c can feed it hostile text. */
int chd_disc_parse_track1(const char *meta, int v2, char *err, size_t errlen,
                          uint32_t *frames, uint32_t *lead, int *off);
#endif
