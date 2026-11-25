/* Recomp Achievements (third_party/rl_achievements): RecompLauncher's achievement system.
 *
 * An events list (achievements.json in the repository root, hosted by RecompLauncher) maps each
 * event name below to an achievement. The runtime fires the events from checks on the game's own
 * memory, once per vblank (ach_vsync, from kernel.c ee_event): a few dozen byte reads, no getenv.
 * Started outside RecompLauncher (no RL_SESSION) the library sends nothing; the checks still run
 * and log "ach: <event>" so scripted runs show them. Evidence for every address: NOTES.md
 * "Achievements".
 *
 * Progress in the rider profiles only counts when it changes while the game runs: after a save is
 * read (mc.c calls ach_save_read) or a cheat code is entered, the profiles are taken as the new
 * baseline, so neither a loaded save nor a cheat unlocks anything. */
#include "rt.h"
#include "../third_party/rl_achievements/include/rl_achievements.h"
#include <string.h>

#define PROFILES     0x2174a8u   /* 17 rider profiles of 968 bytes */
#define NPROF        17
#define PROF_SIZE    968
#define NLEVELS      8
#define LEVEL_REC    328         /* + 68 * level: the level's ProQuest record in a profile */
#define LEVEL_SIZE   68
#define HUD_SCORE    0x25bc28u   /* float: the score the HUD shows; 2^32 = no score shown */
#define CHEAT_RING   0x246568u   /* CheatSniffer's 32 typed digits; a matched code is zeroed */
#define RESYNC_FRAMES 300        /* after a save read: the game copies it into the profiles */

static u8 base[NPROF * PROF_SIZE];   /* the profiles as last seen */
static int resync = 1;               /* > 0: take the profiles as they are, fire nothing */
static int ring_nonzero = -1;
static int score_was_zero = 1;
static u32 fired;                    /* events already sent this session (bit per event) */

enum { EV_FIRST_TRICK, EV_ROOKIE, EV_COUNT };
static const char *const ev_name[EV_COUNT] = { "first_trick", "rookie_objective" };

static void fire(int ev) {
    if (fired & (1u << ev)) return;
    fired |= 1u << ev;
    LOG("ach: %s (frame %llu)\n", ev_name[ev], (unsigned long long)g_frame);
    rl_ach_event(ev_name[ev]);
}

static u32 read_ram(u32 address, u8 *buf, u32 n, void *ud) {
    (void)ud;
    address &= 0x1fffffff;
    if (address >= sizeof ee_ram || n > sizeof ee_ram - address) return 0;
    memcpy(buf, ee_ram + address, n);
    return n;
}

void ach_init(void) {
    int on = rl_ach_init("ps2", read_ram, NULL);   /* reads RL_SESSION once */
    if (on) LOG("ach: connected to RecompLauncher\n");
}

/* mc.c: the game read its save file (BMX2SAVE.DAT) */
void ach_save_read(void) {
    resync = RESYNC_FRAMES;
    rl_ach_save_loaded();
}

/* A cheat code matched: CheatSniffer (fn_001adf60) zeroes the matched digits in its ring, and
 * typed digits are never 0, so fewer non-zero bytes than last frame = a code fired. */
static void check_cheats(void) {
    int n = 0;
    for (u32 i = 0; i < 32; i++) n += ee_ram[CHEAT_RING + i] != 0;
    if (ring_nonzero >= 0 && n < ring_nonzero) {
        LOG("ach: cheat code entered: unlocks from now are Casual\n");
        rl_ach_casual("cheats");
        if (resync < 2) resync = 2;
    }
    ring_nonzero = n;
}

static void check_profiles(void) {
    const u8 *now = ee_ram + PROFILES;
    if (resync > 0) { memcpy(base, now, sizeof base); resync--; return; }
    if (!memcmp(base, now, sizeof base)) return;
    for (int p = 0; p < NPROF; p++)
        for (int lv = 0; lv < NLEVELS; lv++) {
            u32 r = p * PROF_SIZE + LEVEL_REC + lv * LEVEL_SIZE;
            /* tier 0 (Rookie) has one objective, record + 0; bit 0x40 = completed */
            if ((now[r] & 0x40) && !(base[r] & 0x40)) fire(EV_ROOKIE);
        }
    memcpy(base, now, sizeof base);
}

static void check_score(void) {
    float s; memcpy(&s, ee_ram + HUD_SCORE, 4);
    if (s > 0 && s < 4294967296.0f) { if (score_was_zero) fire(EV_FIRST_TRICK); score_was_zero = 0; }
    else score_was_zero = 1;
}

void ach_vsync(void) {
    check_cheats();
    check_profiles();
    check_score();
    rl_ach_frame();
}
