/* Sampling profiler. PROF=<file> [PROF_FROM=frame]: a side thread suspends
 * the main thread about every millisecond from that frame on and counts its
 * instruction pointer (EE/IOP fibers all run on the main thread). At exit the
 * counts go to <file> as "offset count" lines, offset = RIP - image base.
 * Resolve with: python -I tools/prof.py build/bmx2.exe <file> */
#include "rt.h"
#include <windows.h>
#include <stdlib.h>

#define NB (1 << 20)
static u64 keys[NB];
static u32 counts[NB];
static HANDLE main_thread;
static volatile int running;
static u64 from_frame, base;
static u64 total;
static const char *out;

static void add(u64 rip) {
    u64 h = (rip * 0x9e3779b97f4a7c15ull) >> 44;
    for (;;) {
        h &= NB - 1;
        if (keys[h] == rip) { counts[h]++; return; }
        if (!keys[h]) { keys[h] = rip; counts[h] = 1; return; }
        h++;
    }
}

static DWORD WINAPI sampler(void *p) {
    (void)p;
    timeBeginPeriod(1);
    while (running) {
        Sleep(1);
        if (g_frame < from_frame) continue;
        if (SuspendThread(main_thread) == (DWORD)-1) continue;
        CONTEXT c; c.ContextFlags = CONTEXT_CONTROL;
        if (GetThreadContext(main_thread, &c)) { add(c.Rip); total++; }
        ResumeThread(main_thread);
    }
    return 0;
}

static void prof_dump(void) {
    running = 0;
    Sleep(5);
    FILE *f = fopen(out, "w");
    if (!f) return;
    for (u32 i = 0; i < NB; i++) {
        if (!keys[i]) continue;
        HMODULE m = 0; char name[MAX_PATH] = "?";
        if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)keys[i], &m) && m) {
            if ((u64)m == base) { fprintf(f, "%llx %u\n", (unsigned long long)(keys[i] - base), counts[i]); continue; }
            GetModuleFileNameA(m, name, sizeof name);
        }
        const char *b = strrchr(name, '\\'); b = b ? b + 1 : name;
        fprintf(f, "%llx %u %s+%llx\n", (unsigned long long)(keys[i] - base), counts[i], b, (unsigned long long)(keys[i] - (u64)m));
    }
    fclose(f);
    LOG("prof: %llu samples written to %s\n", (unsigned long long)total, out);
}

void prof_init(void) {
    out = getenv("PROF");
    if (!out) return;
    if (getenv("PROF_FROM")) from_frame = strtoull(getenv("PROF_FROM"), 0, 10);
    base = (u64)GetModuleHandleA(NULL);
    DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(), &main_thread, 0, FALSE, DUPLICATE_SAME_ACCESS);
    running = 1;
    atexit(prof_dump);
    CreateThread(NULL, 0, sampler, NULL, 0, NULL);
}
