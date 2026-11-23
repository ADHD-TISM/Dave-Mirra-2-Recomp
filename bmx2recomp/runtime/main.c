/* Entry point: load the ELF image into EE RAM and run the recompiled code. */
#include "rt.h"
#include "config.h"
#include <stdlib.h>
#include <math.h>
#include <windows.h>

ee_state ee;
int g_log_sys, g_log_io, g_turbo;
static u64 max_frames;

static const char *elf_name = "SLUS_201.59";

static int show_window = 1;

/* The game reached EE code the recompiler did not generate. In a windowed run
 * say so on screen instead of just vanishing. */
static void missing_code(u32 addr, const char *what) {
    FILE *m = fopen("missing_entries.txt", "a");
    if (m) { fprintf(m, "%08x\n", addr); fclose(m); }
    if (show_window) {
        char msg[512];
        snprintf(msg, sizeof msg, "The game %s %08x, which was not recompiled.\n\n"
                 "The address was added to disc\\missing_entries.txt. Add it to extra_ee.txt, "
                 "run tools/recomp_ee.py and build.sh, and the game will get past this point.", what, addr);
        MessageBoxA(NULL, msg, "bmx2recomp: missing code", MB_OK | MB_ICONERROR);
    }
    exit(3);
}

ee_fn ee_lookup(u32 addr) {
    unsigned lo = 0, hi = ee_table_count;
    while (lo < hi) {
        unsigned m = (lo + hi) / 2;
        if (ee_table[m].addr == addr) return ee_table[m].fn;
        if (ee_table[m].addr < addr) lo = m + 1; else hi = m;
    }
    return 0;
}

void ee_call(u32 addr) {
    ee_fn f = ee_lookup(addr & 0x1fffffff);
    if (!f) {
        LOG("ee: call to unknown address %08x (ra %08x)\n", addr, GW(31));
        missing_code(addr, "called");
    }
    f();
}

void call_guest(u32 addr) { ee_call(addr); }

void ee_bad(u32 pc, u32 w) { LOG("ee: bad instruction %08x at %08x\n", w, pc); exit(4); }
void ee_fallthrough(u32 pc) {
    LOG("ee: fell off function into %08x\n", pc);
    missing_code(pc, "ran into");
}
void ee_break(u32 pc, u32 code) { LOG("ee: break %u at %08x\n", code, pc); }

static void load_elf(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { LOG("cannot open %s\n", path); exit(1); }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    u8 *d = malloc(n); if (fread(d, 1, n, f) != (size_t)n) exit(1); fclose(f);
    u32 phoff; u16 phnum; memcpy(&phoff, d + 0x1c, 4); memcpy(&phnum, d + 0x2c, 2);
    for (int k = 0; k < phnum; k++) {
        u32 ph[8]; memcpy(ph, d + phoff + 32 * k, 32);
        if (ph[0] != 1) continue;
        memcpy(ee_ram + (ph[2] & 0x1ffffff), d + ph[1], ph[4]);
        memset(ee_ram + (ph[2] & 0x1ffffff) + ph[4], 0, ph[5] - ph[4]);
    }
    free(d);
}

#ifdef EE_WATCH
u32 ee_watch_lo = 0xffffffffu, ee_watch_hi;
static int watch_init;
void ee_watch_hit(u32 a, int n, u64 v) {
    static int hits;
    if (hits++ > 400) return;
#ifdef EE_TRACE
    extern u32 ee_trace_buf[1 << 22]; extern u32 ee_trace_pos;
    LOG("watch: frame %llu write%d %08x = %llx  (fn", (unsigned long long)g_frame, n * 8, a, (unsigned long long)v);
    for (int k = 1; k <= 10; k++) LOG(" %08x", ee_trace_buf[(ee_trace_pos - k) & 0x3fffff]);   /* most recent first */
    LOG(") a0 %08x a1 %08x a2 %08x s4 %08x ra %08x\n", GW(4), GW(5), GW(6), GW(20), GW(31));
#else
    LOG("watch: frame %llu write%d %08x = %llx  ra %08x\n", (unsigned long long)g_frame, n * 8, a, (unsigned long long)v, GW(31));
#endif
}
static void watch_setup(void) {
    const char *e = getenv("EE_WATCH");
    if (watch_init++ || !e) return;
    char *c; u32 lo = (u32)strtoul(e, &c, 16), len = *c == ':' ? (u32)strtoul(c + 1, 0, 16) : 8;
    ee_watch_lo = lo & 0x1ffffff; ee_watch_hi = ee_watch_lo + len;
    LOG("watch: EE stores to %08x..%08x\n", ee_watch_lo, ee_watch_hi);
}
#else
static void watch_setup(void) {}
#endif

#ifdef EE_TRACE
u32 ee_trace_buf[1 << 22]; u32 ee_trace_pos;
u32 ee_count_addr[8], ee_count_hits[8]; int ee_count_n;
static void count_init(void) __attribute__((constructor));
static void count_init(void) {
    const char *e = getenv("EE_COUNT");
    while (e && *e && ee_count_n < 8) { char *x; ee_count_addr[ee_count_n++] = (u32)strtoul(e, &x, 16); e = *x == ',' ? x + 1 : x; if (x == e && *e) break; }
}
static void trace_dump(void) {
    for (int i = 0; i < ee_count_n; i++) LOG("count: fn %08x entered %u times\n", ee_count_addr[i], ee_count_hits[i]);
    if (getenv("EE_COUNT")) return;     /* counting only: skip the 4M-line trace file */
    FILE *f = fopen("trace.txt", "w");
    if (!f) return;
    u32 n = ee_trace_pos < (1u << 22) ? ee_trace_pos : (1u << 22);
    for (u32 k = ee_trace_pos - n; k != ee_trace_pos; k++) fprintf(f, "%08x\n", ee_trace_buf[k & 0x3fffff]);
    fclose(f);
    LOG("trace: %u entries written to trace.txt\n", n);
}
#else
static void trace_dump(void) {}
#endif

/* entry hooks: tools/recomp_ee.py emits ee_hook(addr) at the start of the
 * functions in its HOOKS set, so the runtime can adjust arguments */
static float camf(u32 a) { float v; memcpy(&v, ee_ptr(a), 4); return v; }
static void camf_set(u32 a, float v) { memcpy(ee_ptr(a), &v, 4); }

/* the game's tan of a 16-bit angle (fn 127940: its sin / cos tables) */
static float game_tan(int half) {
    GD(4) = (u64)(s64)half; ee_call(0x00127940);
    return ee.fpr[0].f;
}

/* The widescreen setting each camera was made with (fn 11dfd0, a0 = cam): the
   in-game menu changes g_cfg.widescreen, but a camera keeps the aspect it got.
   The frustum hook uses its camera's value, and the picture shape follows the
   camera the game built a frustum for last (g_ws_active), so they always match
   the projection. Before any camera: the setting. */
static struct { u32 cam; int ws; u64 used; } cam_ws[32];   /* used: last frustum or set (least used goes first) */
static u64 cam_clock;
/* the camera's value, or -1 for a camera made before the table knew it */
static int cam_ws_of(u32 cam) {
    for (int i = 0; i < 32; i++) if (cam_ws[i].used && cam_ws[i].cam == cam) { cam_ws[i].used = ++cam_clock; return cam_ws[i].ws; }
    return -1;
}
static void cam_ws_set(u32 cam, int ws) {
    int k = 0;
    for (int i = 0; i < 32; i++) {
        if (cam_ws[i].used && cam_ws[i].cam == cam) { k = i; break; }
        if (cam_ws[i].used < cam_ws[k].used) k = i;
    }
    cam_ws[k].cam = cam; cam_ws[k].ws = ws; cam_ws[k].used = ++cam_clock;
}
volatile int g_ws_active = -1;
int ws_active(void) { return g_ws_active < 0 ? g_cfg.widescreen : g_ws_active; }

int ee_hook(u32 a) {
    switch (a) {
    case 0x0011dfd0:   /* camera aspect setter (cam+68 = f12 x, cam+72 = f13 y), from fn 100ad0 values */
        cam_ws_set(GW(4) & 0x1ffffff, g_cfg.widescreen);
        if (g_cfg.widescreen) ee.fpr[12].f *= 0.75f;   /* Hor+: same height, 4/3 wider view */
        break;
    case 0x00101068: { /* view frustum builder (a0 = cam), called by fn 1017e0 each frame */
        /* It builds the cull planes and corners from the FOV angle cam+56 (16-bit, 65536 = 360
         * deg) and the screen size cam+24/+28: tan x = tan(fov/2), tan y = tan x * h / w. It
         * does not see the widescreen aspect above, so objects at the sides of the 16:9 view
         * were culled and popped in and out. Widescreen: run it with a FOV whose tan is 4/3
         * wider and h scaled to keep tan y, then put back fov, h and the focal length cam+1096
         * (read by the projection fn 101570 and copied to the draw state). */
        static int inner;
        if (inner) return 0;
        u32 cam = GW(4) & 0x1ffffff;
        int ws = cam_ws_of(cam);
        if (ws >= 0) g_ws_active = ws;           /* the picture shape follows a known camera only */
        else ws = g_cfg.widescreen;
        if (!ws) return 0;
        if (!ee_ptr(cam) || !ee_ptr(cam + 1100)) return 0;
        u16 fov; memcpy(&fov, ee_ptr(cam + 56), 2);
        float h = camf(cam + 28), w = camf(cam + 24);
        /* game_tan runs game code: it changes a0, v0, temporaries and the cycle count.
         * Every path below puts the entry state back before the builder runs. */
        ee_state entry = ee;
        int half = (s16)fov >> 1;                     /* as the game: (fov << 16) >> 17 */
        float t = game_tan(half);
        double wide = atan(t * (4.0 / 3.0)) * (65536.0 / (2 * 3.14159265358979));
        int half_w = (int)(wide + 0.5);
        if (!(t > 0) || half_w <= half || half_w >= 16384) { ee = entry; return 0; }   /* odd FOV: leave it alone */
        float tw = game_tan(half_w);
        u16 fov_w = (u16)(half_w * 2);
        memcpy(ee_ptr(cam + 56), &fov_w, 2);
        camf_set(cam + 28, h * (t / tw));
        ee = entry;                                   /* the builder sees its own a0 and registers */
        inner = 1; ee_call(0x00101068); inner = 0;
        memcpy(ee_ptr(cam + 56), &fov, 2);
        camf_set(cam + 28, h);
        camf_set(cam + 1096, (w * 0.5f) / t);         /* the game's own focal length for fov */
        return 1;
    }
    }
    return 0;
}

static void on_exit_report(void) { trace_dump(); fflush(stdout); fflush(stderr); }

void check_frame_limit(void) {
    if (max_frames && g_frame >= max_frames) {
        extern void kernel_dump(void);
        LOG("frame limit reached\n"); kernel_dump(); ipu_stats();
        if (getenv("EE_DUMP")) { FILE *f = fopen(getenv("EE_DUMP"), "wb"); if (f) { fwrite(ee_ram, 1, 32 << 20, f); fclose(f); } }
        gst_sync(); gst_stats();
        { void gsgl_stats(void), vif_stats(void), vu_stats(void); gsgl_stats(); vif_stats(); vu_stats(); spu2_stats(); }
        { extern u64 n_poll_skips, n_poll_skipped_cycles;
          LOG("hw: %llu poll loops skipped ahead, %.1f s of emulated time\n", (unsigned long long)n_poll_skips, n_poll_skipped_cycles / 294912000.0); }
        exit(0);
    }
}

int main(int argc, char **argv) {
    const char *disc = ".";
    int gs_scale = 2, scale_given = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--log-sys") && i + 1 < argc) g_log_sys = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--log-io")) g_log_io = 1;
        else if (!strcmp(argv[i], "--log-ipu")) { extern int g_log_ipu; g_log_ipu = 1; }
        else if (!strcmp(argv[i], "--no-movies")) { extern int g_no_movies; g_no_movies = 1; }
        else if (!strcmp(argv[i], "--log-iop")) { extern int g_log_iop; g_log_iop = 1; }
        else if (!strcmp(argv[i], "--turbo")) { g_turbo = 1; extern int g_turbo_cli; g_turbo_cli = 1; }
        else if (!strcmp(argv[i], "--no-audio")) g_no_audio = 1;
        else if (!strcmp(argv[i], "--log-mc")) { extern int g_log_mc; g_log_mc = 1; }
        else if (!strcmp(argv[i], "--log-frames")) { extern int g_log_frames; g_log_frames = 1; }
        else if (!strcmp(argv[i], "--log-spu") && i + 1 < argc) g_log_spu = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--log-pad")) { extern int g_log_pad; g_log_pad = 1; }
        else if (!strcmp(argv[i], "--no-window")) show_window = 0;
        else if (!strcmp(argv[i], "--scale") && i + 1 < argc) { gs_scale = atoi(argv[++i]); scale_given = 1; }
        else if (!strcmp(argv[i], "--image") && i + 1 < argc) {
            /* made absolute now: the disc folder below becomes the current directory */
            static char full[MAX_PATH]; extern const char *g_disc_image;
            g_disc_image = GetFullPathNameA(argv[++i], MAX_PATH, full, NULL) ? full : argv[i];
        }
        else if (!strcmp(argv[i], "--log-vif") && i + 1 < argc) { extern int g_log_vif; g_log_vif = atoi(argv[++i]); }
        else if (!strcmp(argv[i], "--log-gs") && i + 1 < argc) { extern int g_log_gs; g_log_gs = atoi(argv[++i]); }
        else if (!strcmp(argv[i], "--frames") && i + 1 < argc) max_frames = strtoull(argv[++i], 0, 10);
        else disc = argv[i];
    }
    setvbuf(stderr, NULL, _IONBF, 0);
    atexit(on_exit_report);
    { void prof_init(void); prof_init(); }
    watch_setup();
    if (!SetCurrentDirectoryA(disc)) { LOG("cannot enter disc folder %s\n", disc); return 1; }
    config_load("bmx2.ini");
    if (g_cfg.scale && !scale_given) gs_scale = g_cfg.scale;
    if (!g_cfg.frame_limit) g_turbo = 1;
    hw_init();
    { void ipu_init(void); ipu_init(); }
    { void gs_init(int, int); gs_init(show_window, gs_scale); }
    gst_init();
    spu2_init();
    load_elf(elf_name);
    sif_init();
    kernel_init();
    ee.fcr31 = 0x01000001;
    GD(29) = 0x01f00000;
    LOG("boot: entry %08x, %u functions\n", ee_entry, ee_table_count);
    ee_call(ee_entry);
    LOG("boot: entry returned\n");
    return 0;
}
