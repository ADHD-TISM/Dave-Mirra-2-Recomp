/* Recomp Achievements (third_party/rl_achievements): RecompLauncher's achievement system.
 *
 * An events list (achievements.json in the repository root, hosted by RecompLauncher) maps each
 * event name below to an achievement. The runtime fires the events from checks on the game's own
 * memory, once per vblank (ach_vsync, from kernel.c ee_event): a 16 KB compare and a few hundred
 * byte reads, no getenv. Started outside RecompLauncher (no RL_SESSION) the library sends nothing;
 * the checks still run and log "ach: <event>" so scripted runs show them. Evidence for every
 * address: NOTES.md "Achievements".
 *
 * Progress in the rider profiles only counts when it changes while the game runs: at boot, after a
 * save is read (mc.c calls ach_save_read) and after a cheat code, the profiles are taken as the new
 * baseline, so neither a loaded save nor a cheat unlocks anything. */
#include "rt.h"
#include "../third_party/rl_achievements/include/rl_achievements.h"
#include <string.h>

#define PROFILES      0x2174a8u  /* 17 rider profiles of 968 bytes */
#define NPROF         17
#define PROF_SIZE     968
#define RESPECT       156        /* + 4 * level: u32 respect in the level, shown "N OUT OF 5,000" */
#define NLEVELS       8
#define WOODWARD      2          /* Woodward Camp: open from the start */
#define LEVEL_REC     328        /* + 68 * level: the level's ProQuest record in a profile */
#define LEVEL_SIZE    68
#define R_FLAGS       60         /* bit 0 unlocked, bit 1 competition open, bit 4 every objective done */
#define R_TIER        61         /* objective tier: 0 Rookie, 1 Amateur, 2 Pro, 3 Hardcore, 4 Expert */
#define R_TIER_DONE   62         /* objectives done in the current tier */
#define R_MEDAL       63         /* 0 none, 1 bronze, 2 silver, 3 gold */
#define R_GAPS        64         /* u32: one bit per gap found */
#define HUD_SCORE     0x25bc28u  /* float: the score the HUD shows; 2^32 = no score shown */
#define CHEAT_RING    0x246568u  /* CheatSniffer's 32 typed digits; a matched code is zeroed */
#define BOOT_FRAMES   600        /* boot: the game clears and sets up the profiles */
#define RESYNC_FRAMES 300        /* after a save read: the game copies it into the profiles */
#define BIG_RUN       25000.0f

/* objectives per tier (the game's table at 0x256710, gp-24992) */
static const u8 tier_goals[5] = { 1, 4, 4, 4, 1 };

static u8 base[NPROF * PROF_SIZE];   /* the profiles as last seen */
static int resync = BOOT_FRAMES;     /* > 0: take the profiles as they are, fire nothing */
static int ring_nonzero = -1;
static int score_was_zero = 1, score_was_small = 1;
static u32 fired;                    /* events already sent this session (bit per event) */

enum { EV_FIRST_TRICK, EV_ROOKIE, EV_AMATEUR, EV_PRO, EV_HARDCORE, EV_NEW_LEVEL, EV_GAP,
       EV_MEDAL, EV_GOLD, EV_RESPECT, EV_BIG_RUN, EV_MASTER, EV_COUNT };
static const char *const ev_name[EV_COUNT] = {
    "first_trick", "rookie_objective", "amateur_objectives", "pro_objectives", "hardcore_objectives",
    "level_unlocked", "first_gap", "medal", "gold_medal", "max_respect", "big_run", "proquest_master" };

static void fire(int ev) {
    if (fired & (1u << ev)) return;
    fired |= 1u << ev;
    LOG("ach: %s (frame %llu)\n", ev_name[ev], (unsigned long long)g_frame);
    rl_ach_event(ev_name[ev]);
}

static u32 read_ram(u32 address, u8 *buf, u32 n, void *ud) {
    (void)ud;   /* main RAM only (0 to 32 MB): the game's own addresses, no mirrors */
    if (address >= sizeof ee_ram || n > sizeof ee_ram - address) return 0;
    memcpy(buf, ee_ram + address, n);
    return n;
}

void ach_init(void) {
    if (rl_ach_init("ps2", read_ram, NULL)) LOG("ach: connected to RecompLauncher\n");   /* reads RL_SESSION once */
}

/* mc.c: the game read its save file (BMX2SAVE.DAT) */
void ach_save_read(void) {
    if (resync < RESYNC_FRAMES) resync = RESYNC_FRAMES;
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

static u32 rd32(const u8 *p) { u32 v; memcpy(&v, p, 4); return v; }

/* every objective of tier t in this level record is done: each of its objective bytes (record +
 * 12 * tier + 3 * i) has bit 0x40. The game derives R_TIER_DONE from these bits and moves R_TIER on
 * in one pass (tier_recount fn_00181f58); a vblank in the middle of that pass could show the new tier with the
 * old count, so the counters are not used here. */
static int tier_done(const u8 *r, int t) {
    for (int i = 0; i < tier_goals[t]; i++) if (!(r[12 * t + 3 * i] & 0x40)) return 0;
    return 1;
}

static void check_profiles(void) {
    const u8 *now = ee_ram + PROFILES;
    if (resync > 0) { memcpy(base, now, sizeof base); resync--; return; }
    if (!memcmp(base, now, sizeof base)) return;
    for (int p = 0; p < NPROF; p++) {
        const u8 *np = now + p * PROF_SIZE, *bp = base + p * PROF_SIZE;
        int all_now = 1, all_before = 1;
        for (int lv = 0; lv < NLEVELS; lv++) {
            const u8 *n = np + LEVEL_REC + lv * LEVEL_SIZE, *b = bp + LEVEL_REC + lv * LEVEL_SIZE;
            all_now &= (n[R_FLAGS] >> 4) & 1; all_before &= (b[R_FLAGS] >> 4) & 1;
            if (!memcmp(n, b, LEVEL_SIZE) && rd32(np + RESPECT + 4 * lv) == rd32(bp + RESPECT + 4 * lv)) continue;
            /* bit 0x40 of an objective byte = completed (goal_progress fn_0017f8d0) */
            if (tier_done(n, 0) && !tier_done(b, 0)) fire(EV_ROOKIE);
            if (tier_done(n, 1) && !tier_done(b, 1)) fire(EV_AMATEUR);
            if (tier_done(n, 2) && !tier_done(b, 2)) fire(EV_PRO);
            if (tier_done(n, 3) && !tier_done(b, 3)) fire(EV_HARDCORE);
            if (lv != WOODWARD && (n[R_FLAGS] & 1) && !(b[R_FLAGS] & 1)) fire(EV_NEW_LEVEL);
            if (rd32(n + R_GAPS) & ~rd32(b + R_GAPS)) fire(EV_GAP);
            if (n[R_MEDAL] > b[R_MEDAL] && n[R_MEDAL] >= 1 && n[R_MEDAL] <= 3) fire(EV_MEDAL);
            if (n[R_MEDAL] == 3 && b[R_MEDAL] != 3) fire(EV_GOLD);
            if (rd32(np + RESPECT + 4 * lv) >= 5000 && rd32(bp + RESPECT + 4 * lv) < 5000) fire(EV_RESPECT);
        }
        if (all_now && !all_before) fire(EV_MASTER);
    }
    memcpy(base, now, sizeof base);
}

static void check_score(void) {
    float s; memcpy(&s, ee_ram + HUD_SCORE, 4);
    int shown = s > 0 && s < 4294967296.0f;
    if (shown && score_was_zero) fire(EV_FIRST_TRICK);
    if (shown && s >= BIG_RUN && score_was_small) fire(EV_BIG_RUN);
    score_was_zero = !shown;
    score_was_small = !(shown && s >= BIG_RUN);
}

void ach_vsync(void) {
    check_cheats();
    check_profiles();
    check_score();
    rl_ach_frame();
}
