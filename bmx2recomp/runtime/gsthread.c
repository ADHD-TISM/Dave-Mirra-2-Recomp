/* Graphics worker thread (like PCSX2's MTVU, wider): VIF1, VU1, the GS front
 * end and all OpenGL work run on a second thread; the EE thread only queues.
 *
 * The EE side copies what it hands over (VIF1 DMA data, GIF path 3 data) into
 * a ring, so the game may reuse its buffers at once, as after a finished DMA.
 * VIF1 interrupts (the i bit, whose handler patches the rest of the DMA data)
 * stay on the EE side: a scan-only copy of VIF1 (vif.c unit 2) follows the
 * same stream, stops at the i bit exactly as before and answers the EE's
 * VIF1 register reads. The worker's VIF1 ignores i bits. GS SIGNAL/FINISH
 * bits are posted by the worker and applied to CSR by the EE (gst_apply_csr).
 * At each vblank the EE queues a PRESENT with a copy of the display registers.
 * The EE waits when the worker is more than 2 frames behind, and for a full
 * drain (gst_sync) before stats and exit.
 *
 * Off with `gs_thread = 0` in bmx2.ini or GS_THREAD=0: everything runs on the
 * EE thread as before. */
#include "rt.h"
#include <windows.h>
#include <stdlib.h>

int g_gs_mt;

enum { C_VIF1 = 1, C_GIF, C_VU1, C_VIF1_RESET, C_VIF1_REG, C_PRESENT, C_WRAP };
typedef struct { u32 type, len, a, b; } cmd_t;        /* len = payload bytes after the header */

#define QSIZE (64u << 20)
static u8 *q;
static volatile u64 q_head, q_tail;                   /* bytes written by the EE / consumed by the worker (monotonic) */
static volatile u64 presents_queued, presents_done;
static volatile LONG worker_sleeping, ee_waiting;
static volatile u32 csr_pending;
static HANDLE ev_work, ev_space;
static u64 n_cmds, n_bytes, n_waits_full, n_waits_frames, n_syncs;

/* worker side, in vif.c / gs.c / gs_gl.c / vu.c */
u32 vif1_worker_feed(const u8 *p, u32 nqw);
void vif1_worker_reset(void);
void vif1_worker_reg(u32 off, u32 val);
void gif_transfer(const u8 *p, u32 nqw, int path);
void vu1_start(u32 pc);
void gs_present_from(const u64 *priv);
void gsgl_bind_context(void);
void gsgl_unbind_context(void);
void gsgl_flush(void);

static inline u64 ld(volatile u64 *p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
static inline void st(volatile u64 *p, u64 v) { __atomic_store_n(p, v, __ATOMIC_RELEASE); }

/* ---- EE side ------------------------------------------------------------------ */
static void wake_worker(void) {
    if (__atomic_load_n(&worker_sleeping, __ATOMIC_ACQUIRE)) SetEvent(ev_work);
}
/* the EE waits for the worker (room, frames, drain): 1 ms timeout, so a missed wake costs 1 ms at most */
static void ee_wait(void) {
    wake_worker();
    __atomic_store_n(&ee_waiting, 1, __ATOMIC_RELEASE);
    WaitForSingleObject(ev_space, 1);
    __atomic_store_n(&ee_waiting, 0, __ATOMIC_RELEASE);
}

static void put(u32 type, u32 a, u32 b, const void *data, u32 len) {
    u32 need = (u32)sizeof(cmd_t) + ((len + 15) & ~15u);
    for (;;) {
        u64 head = q_head, tail = ld(&q_tail);
        u32 pos = (u32)(head % QSIZE), room_end = QSIZE - pos;
        if (room_end < need) {                        /* not enough before the end: wrap marker */
            if (QSIZE - (head - tail) < room_end + need) { n_waits_full++; ee_wait(); continue; }
            cmd_t w = { C_WRAP, room_end - (u32)sizeof(cmd_t), 0, 0 };
            memcpy(q + pos, &w, sizeof w);
            st(&q_head, head + room_end);
            continue;
        }
        if (QSIZE - (head - tail) < need) { n_waits_full++; ee_wait(); continue; }
        cmd_t c = { type, len, a, b };
        memcpy(q + pos, &c, sizeof c);
        if (len) memcpy(q + pos + sizeof c, data, len);
        st(&q_head, head + need);
        n_cmds++; n_bytes += need;
        wake_worker();
        return;
    }
}

void gst_vif1(const u8 *p, u32 nqw) { if (nqw) put(C_VIF1, nqw, 0, p, nqw * 16); }
void gst_gif(const u8 *p, u32 nqw, int path) { if (nqw) put(C_GIF, nqw, (u32)path, p, nqw * 16); }
void gst_vu1_start(u32 pc) { put(C_VU1, pc, 0, 0, 0); }
void gst_vif1_reset(void) { put(C_VIF1_RESET, 0, 0, 0, 0); }
void gst_vif1_reg(u32 off, u32 val) { put(C_VIF1_REG, off, val, 0, 0); }

int gst_busy(void) { return g_gs_mt && ld(&q_tail) != q_head; }

void gst_present(const u64 *priv) {
    /* at most 2 frames in flight: the picture may lag, the game may not run away */
    while (ld(&presents_done) + 2 < presents_queued) { n_waits_frames++; ee_wait(); }
    presents_queued++;
    LARGE_INTEGER t; QueryPerformanceCounter(&t);   /* when the EE queued it (latency log) */
    put(C_PRESENT, (u32)t.QuadPart, (u32)(t.QuadPart >> 32), priv, 0x20 * 8);
}

void gst_sync(void) {
    if (!g_gs_mt) return;
    n_syncs++;
    while (ld(&q_tail) != q_head) ee_wait();
}

/* SIGNAL (1) / FINISH (2) bits the worker raised: CSR and the GS interrupt, on the EE */
void gst_post_csr(u32 bits) { __atomic_fetch_or(&csr_pending, bits, __ATOMIC_ACQ_REL); }
void gst_apply_csr(void) {
    if (!g_gs_mt || !__atomic_load_n(&csr_pending, __ATOMIC_ACQUIRE)) return;
    u32 b = __atomic_exchange_n(&csr_pending, 0, __ATOMIC_ACQ_REL);
    gs_csr |= b;
    if (((b & 1) && !(gs_imr & 0x100)) || ((b & 2) && !(gs_imr & 0x200))) intc_raise(0);
}

/* ---- worker -------------------------------------------------------------------- */
static DWORD WINAPI worker(void *arg) {
    (void)arg;
    gsgl_bind_context();
    { void prof_here(void); prof_here(); }
    for (;;) {
        u64 tail = q_tail, head = ld(&q_head);
        if (tail == head) {
            /* spin a little, then sleep until the EE queues something */
            int spun = 0;
            while (ld(&q_head) == tail && spun < 2000) { YieldProcessor(); spun++; }
            if (ld(&q_head) == tail) {
                __atomic_store_n(&worker_sleeping, 1, __ATOMIC_RELEASE);
                if (ld(&q_head) == tail) { gsgl_flush(); WaitForSingleObject(ev_work, 5); }
                __atomic_store_n(&worker_sleeping, 0, __ATOMIC_RELEASE);
            }
            continue;
        }
        u32 pos = (u32)(tail % QSIZE);
        cmd_t c; memcpy(&c, q + pos, sizeof c);
        const u8 *data = q + pos + sizeof c;
        u32 size = (u32)sizeof(cmd_t) + ((c.len + 15) & ~15u);
        switch (c.type) {
        case C_WRAP: size = QSIZE - pos; break;
        case C_VIF1: vif1_worker_feed(data, c.len / 16); break;
        case C_GIF: gif_transfer(data, c.len / 16, (int)c.b); break;
        case C_VU1: vu1_start(c.a); break;
        case C_VIF1_RESET: vif1_worker_reset(); break;
        case C_VIF1_REG: vif1_worker_reg(c.a, c.b); break;
        case C_PRESENT: {
            LARGE_INTEGER t0; QueryPerformanceCounter(&t0);
            gs_present_from((const u64 *)data); __atomic_fetch_add(&presents_done, 1, __ATOMIC_ACQ_REL);
            extern int g_log_frames;
            if (g_log_frames) {
                LARGE_INTEGER t1, fq; QueryPerformanceCounter(&t1); QueryPerformanceFrequency(&fq);
                s64 q = (s64)(((u64)c.b << 32) | c.a);
                double wait = (double)(t0.QuadPart - q) * 1000.0 / fq.QuadPart, took = (double)(t1.QuadPart - t0.QuadPart) * 1000.0 / fq.QuadPart;
                if (wait + took > (getenv("PRESENT_LOG_ALL") ? -1 : 3)) LOG("gst: present at frame %llu: %.1f ms after it was queued, %.1f ms to present\n", (unsigned long long)g_frame, wait, took);
            }
            break; }
        default: LOG("gst: bad command %u at %llu\n", c.type, (unsigned long long)tail); exit(6);
        }
        st(&q_tail, tail + size);
        if (__atomic_load_n(&ee_waiting, __ATOMIC_ACQUIRE)) SetEvent(ev_space);
    }
    return 0;
}

void gst_init(void) {
    const char *e = getenv("GS_THREAD");
    if (e && *e == '0') { LOG("gst: graphics thread off (GS_THREAD=0)\n"); return; }
    extern int g_gs_thread_cfg;
    if (!g_gs_thread_cfg) { LOG("gst: graphics thread off (gs_thread = 0)\n"); return; }
    q = VirtualAlloc(NULL, QSIZE, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!q) { LOG("gst: no memory for the queue, graphics thread off\n"); return; }
    ev_work = CreateEventA(NULL, FALSE, FALSE, NULL);
    ev_space = CreateEventA(NULL, FALSE, FALSE, NULL);
    { void vu_init(void); vu_init(); }
    gsgl_unbind_context();
    g_gs_mt = 1;
    HANDLE t = CreateThread(NULL, 64 << 20, worker, NULL, 0, NULL);
    SetThreadPriority(t, THREAD_PRIORITY_ABOVE_NORMAL);
    LOG("gst: graphics thread on (VIF1, VU1, GS, OpenGL)\n");
}

void gst_stats(void) {
    if (!g_gs_mt) return;
    LOG("gst: %llu commands, %.1f MB queued, %llu waits for room, %llu waits for frames, %llu full syncs\n",
        (unsigned long long)n_cmds, n_bytes / 1048576.0, (unsigned long long)n_waits_full,
        (unsigned long long)n_waits_frames, (unsigned long long)n_syncs);
}
