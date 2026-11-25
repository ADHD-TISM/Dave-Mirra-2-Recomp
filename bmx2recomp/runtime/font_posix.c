/* Linux: text for the in-game menu (menu.c draws it with GDI on Windows).
 * stb_truetype (third_party, public domain / MIT) rasterises a TrueType font
 * of the system: DejaVu Sans, Liberation Sans or Noto Sans from the usual
 * folders, else whatever `fc-match sans` names. No font: rectangles only. */
#ifndef _WIN32
#include "rt.h"
#include <stdlib.h>
#define STB_TRUETYPE_IMPLEMENTATION
#define STBTT_STATIC
#include "../third_party/stb_truetype.h"

typedef struct { stbtt_fontinfo info; unsigned char *data; int ok; } font_t;
static font_t f_reg, f_bold;

static unsigned char *read_all(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    unsigned char *d = n > 0 && n < (64 << 20) ? malloc((size_t)n) : NULL;
    if (d && fread(d, 1, (size_t)n, f) != (size_t)n) { free(d); d = NULL; }
    fclose(f);
    return d;
}
static int load(font_t *ft, const char *path) {
    unsigned char *d = read_all(path);
    if (!d) return 0;
    if (!stbtt_InitFont(&ft->info, d, stbtt_GetFontOffsetForIndex(d, 0))) { free(d); return 0; }
    ft->data = d; ft->ok = 1;
    return 1;
}
static int load_first(font_t *ft, const char *const *paths) {
    for (int i = 0; paths[i]; i++) if (load(ft, paths[i])) return 1;
    return 0;
}
static int load_fc(font_t *ft, const char *pattern) {
    char cmd[128], path[1024]; snprintf(cmd, sizeof cmd, "fc-match -f '%%{file}' '%s' 2>/dev/null", pattern);
    FILE *p = popen(cmd, "r");
    if (!p) return 0;
    size_t n = fread(path, 1, sizeof path - 1, p); path[n] = 0;
    pclose(p);
    return n && load(ft, path);
}

int font_init(void) {
    static int done;
    if (done++) return f_reg.ok;
    static const char *const reg[] = {
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "/usr/share/fonts/noto/NotoSans-Regular.ttf", NULL };
    static const char *const bold[] = {
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", "/usr/share/fonts/noto/NotoSans-Bold.ttf", NULL };
    if (!load_first(&f_reg, reg)) load_fc(&f_reg, "sans");
    if (!load_first(&f_bold, bold)) load_fc(&f_bold, "sans:bold");
    if (!f_reg.ok) LOG("menu: no TrueType font found (install DejaVu Sans); the menu shows without text\n");
    return f_reg.ok;
}

/* pix: w x h, RGBA in memory order */
static inline void put(u32 *pix, int w, int h, int x, int y, u32 rgb, int a) {
    if (x < 0 || y < 0 || x >= w || y >= h || a <= 0) return;
    u32 *p = &pix[y * w + x], d = *p, o = 0;
    for (int s = 0; s < 24; s += 8) {
        int c = (int)((rgb >> s) & 255), b = (int)((d >> s) & 255);
        o |= (u32)((c * a + b * (255 - a) + 127) / 255) << s;
    }
    *p = o | (d & 0xff000000u);
}
void font_fill(u32 *pix, int w, int h, int x0, int y0, int x1, int y1, u32 rgb) {
    for (int y = y0 < 0 ? 0 : y0; y < y1 && y < h; y++)
        for (int x = x0 < 0 ? 0 : x0; x < x1 && x < w; x++) pix[y * w + x] = rgb | 0xff000000u;
}
/* text of em size px in the box, vertically centred; align 0 left, 1 right, 2 centre (DrawText's DT_ flags) */
void font_text(u32 *pix, int w, int h, const char *s, int px, int bold, int x0, int y0, int x1, int y1, int align, u32 rgb) {
    font_t *ft = bold && f_bold.ok ? &f_bold : &f_reg;
    if (!ft->ok) return;
    float sc = stbtt_ScaleForMappingEmToPixels(&ft->info, (float)px);
    int asc, desc, gap; stbtt_GetFontVMetrics(&ft->info, &asc, &desc, &gap);
    float tw = 0;
    for (const char *c = s; *c; c++) {
        int adv, lsb; stbtt_GetCodepointHMetrics(&ft->info, (unsigned char)*c, &adv, &lsb);
        tw += adv * sc;
        if (c[1]) tw += sc * stbtt_GetCodepointKernAdvance(&ft->info, (unsigned char)*c, (unsigned char)c[1]);
    }
    float x = align == 1 ? x1 - tw : align == 2 ? x0 + ((x1 - x0) - tw) / 2 : (float)x0;
    int base = y0 + ((y1 - y0) - (int)((asc - desc) * sc + 0.5f)) / 2 + (int)(asc * sc + 0.5f);
    for (const char *c = s; *c; c++) {
        int cp = (unsigned char)*c, adv, lsb, gw, gh, xo, yo;
        stbtt_GetCodepointHMetrics(&ft->info, cp, &adv, &lsb);
        float fx = x - (float)(int)x;
        unsigned char *bm = stbtt_GetCodepointBitmapSubpixel(&ft->info, sc, sc, fx, 0, cp, &gw, &gh, &xo, &yo);
        if (bm) {
            for (int j = 0; j < gh; j++)
                for (int i = 0; i < gw; i++) put(pix, w, h, (int)x + xo + i, base + yo + j, rgb, bm[j * gw + i]);
            stbtt_FreeBitmap(bm, NULL);
        }
        x += adv * sc;
        if (c[1]) x += sc * stbtt_GetCodepointKernAdvance(&ft->info, cp, (unsigned char)c[1]);
    }
}
#endif
