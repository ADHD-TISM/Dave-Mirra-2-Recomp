/* Pad: the IOP side of padman (sid 0x80000100/0x80000101), high-level.
 *
 * The game runs its own EE libpad ("xpad" flavour, libpad 2200). padPortOpen
 * hands the IOP a 256-byte area: two 128-byte frames that padman DMAs into
 * every vblank, the EE picking the one with the larger frame counter (+0x58).
 * Layout as read by the game's libpad (fn 1d92a8 getDmaStr, 1d9358 padRead,
 * 1d93d8 padGetState, 1d9578 padInfoAct, 1d9698 padInfoComb, 1d97b8
 * padInfoMode):
 *   +0x00 data[32]   (0 = ok, mode id, buttons active low, sticks, pressure)
 *   +0x30 act info, 4 bytes per actuator; +0x40 comb info, 4 bytes each
 *   +0x50 u16 modeTable[4]   +0x58 frame   +0x60 length
 *   +0x64 modeConfig  +0x65 modeCurId  +0x68 nrOfModes  +0x69 modeCurOffs
 *   +0x6a nrOfActuators  +0x6b numActComb  +0x6e lock
 *   +0x70 state (6 stable, 0 disconnected)  +0x71 reqState (0 done, 2 busy)
 *   +0x72 currentTask (1 = info ready)
 *
 * Port 0 slot 0 is a DualShock 2 fed from the keyboard (window focused) and
 * the first XInput controller. Other ports read as disconnected.
 *
 * PAD_SCRIPT="frame:buttons[,frame:buttons...]" presses buttons from a frame
 * on (until the next entry), for headless runs. Buttons are names joined by
 * '+': start select up down left right x square circle triangle l1 r1 l2 r2
 * l3 r3, or '-' for none. Example: PAD_SCRIPT=3700:start,3706:-,3900:x,3906:-
 */
#include "rt.h"
#include "config.h"
#include <windows.h>
#include <stdlib.h>

/* button bits of the 16-bit word (data[2] low byte, data[3] high byte), active low */
enum {
    B_SELECT = 1 << 0, B_L3 = 1 << 1, B_R3 = 1 << 2, B_START = 1 << 3,
    B_UP = 1 << 4, B_RIGHT = 1 << 5, B_DOWN = 1 << 6, B_LEFT = 1 << 7,
    B_L2 = 1 << 8, B_R2 = 1 << 9, B_L1 = 1 << 10, B_R1 = 1 << 11,
    B_TRIANGLE = 1 << 12, B_CIRCLE = 1 << 13, B_CROSS = 1 << 14, B_SQUARE = 1 << 15,
};

int g_log_pad;
static u32 area[2][4];          /* EE address per port/slot, 0 = not open */
static u32 frame_no[2][4];
static int pressure_mode, analog = 1, mode_lock;

/* ---- host input ------------------------------------------------------------ */
typedef struct { WORD buttons; BYTE lt, rt; SHORT lx, ly, rx, ry; } xi_gamepad;
typedef struct { DWORD packet; xi_gamepad g; } xi_state;
static DWORD (WINAPI *xi_get)(DWORD, xi_state *);
static int xi_tried;

static void xi_load(void) {
    xi_tried = 1;
    const char *dlls[] = { "xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll" };
    for (int i = 0; i < 3 && !xi_get; i++) {
        HMODULE m = LoadLibraryA(dlls[i]);
        if (m) xi_get = (DWORD (WINAPI *)(DWORD, xi_state *))(void *)GetProcAddress(m, "XInputGetState");
    }
}

typedef struct { u16 buttons; u8 lx, ly, rx, ry; } pad_in;

static const struct { const char *name; u16 bit; } bnames[] = {
    { "select", B_SELECT }, { "l3", B_L3 }, { "r3", B_R3 }, { "start", B_START },
    { "up", B_UP }, { "right", B_RIGHT }, { "down", B_DOWN }, { "left", B_LEFT },
    { "l2", B_L2 }, { "r2", B_R2 }, { "l1", B_L1 }, { "r1", B_R1 },
    { "triangle", B_TRIANGLE }, { "circle", B_CIRCLE }, { "x", B_CROSS }, { "cross", B_CROSS },
    { "square", B_SQUARE },
};

typedef struct { u64 frame; u16 buttons; } script_ev;
static script_ev script[256];
static int nscript = -1;

static void script_load(void) {
    nscript = 0;
    const char *s = getenv("PAD_SCRIPT");
    while (s && *s && nscript < 256) {
        char *e; u64 f = strtoull(s, &e, 10);
        if (*e != ':') break;
        s = e + 1;
        u16 b = 0;
        while (*s && *s != ',') {
            const char *t = s; while (*s && *s != '+' && *s != ',') s++;
            size_t n = (size_t)(s - t);
            for (unsigned k = 0; k < sizeof bnames / sizeof bnames[0]; k++)
                if (strlen(bnames[k].name) == n && !_strnicmp(t, bnames[k].name, n)) b |= bnames[k].bit;
            if (*s == '+') s++;
        }
        script[nscript].frame = f; script[nscript].buttons = b; nscript++;
        if (*s == ',') s++;
    }
    if (nscript) LOG("pad: %d scripted inputs\n", nscript);
}

static u8 stick(int neg, int pos) { return neg && !pos ? 0x00 : pos && !neg ? 0xff : 0x80; }
static u8 axis(SHORT v, int flip) {
    int a = flip ? -(int)v : v;            /* -32768..32767 -> 0..255, 128 centre */
    a = (a + 32768) >> 8; if (a > 255) a = 255; if (a < 0) a = 0;
    return (u8)a;
}

static void read_host(pad_in *p) {
    p->buttons = 0; p->lx = p->ly = p->rx = p->ry = 0x80;
    if (nscript < 0) script_load();
    for (int i = 0; i < nscript; i++) if (script[i].frame <= g_frame) p->buttons = script[i].buttons;

    extern int gsgl_has_focus(void);
    if (gsgl_has_focus()) {
#define K(vk) (GetAsyncKeyState(vk) & 0x8000)
        static const u16 bit[16] = { B_UP, B_DOWN, B_LEFT, B_RIGHT, B_START, B_SELECT, B_CROSS, B_CIRCLE,
                                     B_SQUARE, B_TRIANGLE, B_L1, B_R1, B_L2, B_R2, B_L3, B_R3 };
#define KB(b) ((g_cfg.keys[b][0] && K(g_cfg.keys[b][0])) || (g_cfg.keys[b][1] && K(g_cfg.keys[b][1])))
        for (int k = 0; k < 16; k++) if (KB(k)) p->buttons |= bit[k];
        int l = KB(CFG_LS_LEFT), r = KB(CFG_LS_RIGHT), u = KB(CFG_LS_UP), d = KB(CFG_LS_DOWN);
        if (l || r) p->lx = stick(l, r);
        if (u || d) p->ly = stick(u, d);
        l = KB(CFG_RS_LEFT); r = KB(CFG_RS_RIGHT); u = KB(CFG_RS_UP); d = KB(CFG_RS_DOWN);
        if (l || r) p->rx = stick(l, r);
        if (u || d) p->ry = stick(u, d);
#undef KB
#undef K
    }

    if (!xi_tried) xi_load();
    xi_state x;
    if (g_cfg.gamepad && xi_get && xi_get(0, &x) == 0) {
        WORD w = x.g.buttons;
        static const struct { WORD xb; u16 bit; } map[] = {
            { 0x0001, B_UP }, { 0x0002, B_DOWN }, { 0x0004, B_LEFT }, { 0x0008, B_RIGHT },
            { 0x0010, B_START }, { 0x0020, B_SELECT }, { 0x0040, B_L3 }, { 0x0080, B_R3 },
            { 0x0100, B_L1 }, { 0x0200, B_R1 },
            { 0x1000, B_CROSS }, { 0x2000, B_CIRCLE }, { 0x4000, B_SQUARE }, { 0x8000, B_TRIANGLE },
        };
        for (unsigned k = 0; k < sizeof map / sizeof map[0]; k++) if (w & map[k].xb) p->buttons |= map[k].bit;
        if (x.g.lt > 30) p->buttons |= B_L2;
        if (x.g.rt > 30) p->buttons |= B_R2;
        /* dead zone so a resting stick does not override the keyboard */
        if (abs(x.g.lx) > 7849) p->lx = axis(x.g.lx, 0);
        if (abs(x.g.ly) > 7849) p->ly = axis(x.g.ly, 1);
        if (abs(x.g.rx) > 8689) p->rx = axis(x.g.rx, 0);
        if (abs(x.g.ry) > 8689) p->ry = axis(x.g.ry, 1);
    }
}

/* ---- the DMA'd frame ------------------------------------------------------- */
static void put8(u32 a, u8 v) { mw8(a, v); }

static void write_frame(int port, int slot, const pad_in *in) {
    u32 base = area[port][slot];
    if (!base) return;
    u32 n = ++frame_no[port][slot];
    u32 f = base + 128 * (n & 1);
    for (u32 k = 0; k < 128; k += 4) mw32(f + k, 0);
    mw32(f + 0x58, n);
    put8(f + 0x72, 1);                 /* currentTask: info ready */
    put8(f + 0x71, 0);                 /* reqState: complete */
    if (port != 0 || slot != 0) {      /* nothing plugged in */
        put8(f + 0x70, 0);
        return;
    }
    u8 id = !analog ? 0x41 : pressure_mode ? 0x79 : 0x73;
    put8(f + 0x70, 6);                 /* stable */
    put8(f + 0x64, 2);                 /* modeConfig: mode info read */
    put8(f + 0x65, id);
    put8(f + 0x66, 3);                 /* model: DualShock 2 */
    put8(f + 0x67, 1);
    mw16(f + 0x50, 4); mw16(f + 0x52, 7);     /* modeTable: digital, dualshock */
    put8(f + 0x68, 2);
    put8(f + 0x69, analog ? 1 : 0);
    put8(f + 0x6a, 2);                 /* two motors */
    put8(f + 0x30, 0); put8(f + 0x31, 1); put8(f + 0x32, 0); put8(f + 0x33, 1);       /* small: on/off */
    put8(f + 0x34, 0); put8(f + 0x35, 1); put8(f + 0x36, 1); put8(f + 0x37, 0x14);    /* large: 8-bit level */
    put8(f + 0x6b, 1);
    put8(f + 0x40, 0); put8(f + 0x41, 1); put8(f + 0x42, 0); put8(f + 0x43, 0);
    put8(f + 0x6e, (u8)mode_lock);

    u16 b = (u16)~in->buttons;
    u8 d[32]; memset(d, 0, sizeof d);
    d[0] = 0; d[1] = id; d[2] = (u8)b; d[3] = (u8)(b >> 8);
    u32 len = 4;
    if (id != 0x41) {
        d[4] = in->rx; d[5] = in->ry; d[6] = in->lx; d[7] = in->ly;
        len = 8;
    }
    if (id == 0x79) {
        static const u16 order[12] = { B_RIGHT, B_LEFT, B_UP, B_DOWN, B_TRIANGLE, B_CIRCLE,
                                       B_CROSS, B_SQUARE, B_L1, B_R1, B_L2, B_R2 };
        for (int k = 0; k < 12; k++) d[8 + k] = (in->buttons & order[k]) ? 0xff : 0;
        len = 20;
    }
    for (int k = 0; k < 32; k++) put8(f + k, d[k]);
    mw32(f + 0x60, len);
}

void pad_vsync(void) {
    pad_in in;
    read_host(&in);
    static u16 last;
    if (g_log_pad && in.buttons != last) LOG("pad: frame %llu buttons %04x\n", (unsigned long long)g_frame, in.buttons);
    last = in.buttons;
    for (int p = 0; p < 2; p++) for (int s = 0; s < 4; s++) write_frame(p, s, &in);
}

/* padman RPC: buf is the 128-byte request/reply in IOP RAM. Reply value at +12. */
void pad_rpc(u8 *buf) {
    u32 w[8]; memcpy(w, buf, 32);
    u32 cmd = w[0], port = w[1] & 1, slot = w[2] & 3, ret = 1;
    switch (cmd) {
    case 0x01: area[port][slot] = w[4]; frame_no[port][slot] = 0; break;   /* open(port, slot, -, area) */
    case 0x05:                                                           /* setMainMode(port, slot, mode, lock) */
        if (port == 0 && slot == 0) { analog = w[3] != 0; mode_lock = w[4] == 3; if (!analog) pressure_mode = 0; }
        break;
    case 0x08: ret = pressure_mode ? 0x3ffff : 0; break;                 /* getButtonMask */
    case 0x09: pressure_mode = (w[3] & 0x3ffff) != 0; break;             /* setButtonInfo */
    case 0x0b: ret = 2; break;                                           /* getPortMax */
    case 0x0c: ret = 1; break;                                           /* getSlotMax */
    case 0x0d: area[port][slot] = 0; break;                              /* close */
    case 0x10: ret = 1; break;                                           /* init */
    case 0x12: memset(buf, 0, 128); ret = 0x400; break;                  /* module version */
    default: break;                                                      /* act dir/align, vref, end */
    }
    if (g_log_pad || cmd != 0x06) LOG("pad: cmd %#x port %u slot %u args %08x %08x -> %#x\n", cmd, port, slot, w[3], w[4], ret);
    memcpy(buf + 12, &ret, 4);
}
