/* Linux: the Win32 subset of plat.h on POSIX (time, threads, events, fibers,
 * memory, paths). Nothing here on Windows. */
#ifndef _WIN32
#define _GNU_SOURCE
#include "plat.h"
#include <errno.h>
#include <stdlib.h>
#include <time.h>
#include <sys/mman.h>

/* ---- time ------------------------------------------------------------------ */
static long long now_ns(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (long long)t.tv_sec * 1000000000ll + t.tv_nsec;
}
BOOL QueryPerformanceCounter(LARGE_INTEGER *t) { t->QuadPart = now_ns(); return TRUE; }
BOOL QueryPerformanceFrequency(LARGE_INTEGER *f) { f->QuadPart = 1000000000ll; return TRUE; }
DWORD GetTickCount(void) { return (DWORD)(now_ns() / 1000000); }
void Sleep(DWORD ms) {
    struct timespec t = { (time_t)(ms / 1000), (long)(ms % 1000) * 1000000l };
    while (nanosleep(&t, &t) && errno == EINTR) {}
}

/* ---- threads ----------------------------------------------------------------- */
typedef struct { pthread_t t; LPTHREAD_START_ROUTINE fn; void *arg; } thread_h;
static void *thread_main(void *p) { thread_h *h = p; h->fn(h->arg); return NULL; }
HANDLE CreateThread(void *attr, size_t stack, LPTHREAD_START_ROUTINE fn, void *arg, DWORD flags, DWORD *id) {
    (void)attr; (void)flags; (void)id;
    thread_h *h = calloc(1, sizeof *h);
    if (!h) return NULL;
    h->fn = fn; h->arg = arg;
    pthread_attr_t a; pthread_attr_init(&a);
    if (stack) pthread_attr_setstacksize(&a, stack);
    int r = pthread_create(&h->t, &a, thread_main, h);
    pthread_attr_destroy(&a);
    if (r) { free(h); return NULL; }
    return h;
}
HANDLE GetCurrentThread(void) {
    static __thread thread_h self; self.t = pthread_self(); return &self;
}
BOOL QueryThreadCycleTime(HANDLE t, ULONG64 *ns) {
    clockid_t c; struct timespec ts;
    if (!t || pthread_getcpuclockid(((thread_h *)t)->t, &c) || clock_gettime(c, &ts)) { *ns = 0; return FALSE; }
    *ns = (ULONG64)ts.tv_sec * 1000000000ull + (ULONG64)ts.tv_nsec;
    return TRUE;
}

/* ---- auto-reset events ------------------------------------------------------- */
typedef struct { pthread_mutex_t m; pthread_cond_t c; int set; } event_h;
HANDLE CreateEventA(void *attr, BOOL manual, BOOL initial, const char *name) {
    (void)attr; (void)manual; (void)name;
    event_h *e = calloc(1, sizeof *e);
    if (!e) return NULL;
    pthread_mutex_init(&e->m, NULL);
    pthread_condattr_t ca; pthread_condattr_init(&ca);
    pthread_condattr_setclock(&ca, CLOCK_MONOTONIC);
    pthread_cond_init(&e->c, &ca);
    pthread_condattr_destroy(&ca);
    e->set = initial != 0;
    return e;
}
BOOL SetEvent(HANDLE h) {
    event_h *e = h;
    pthread_mutex_lock(&e->m); e->set = 1; pthread_cond_signal(&e->c); pthread_mutex_unlock(&e->m);
    return TRUE;
}
DWORD WaitForSingleObject(HANDLE h, DWORD ms) {
    event_h *e = h;
    struct timespec until;
    if (ms != INFINITE) {
        clock_gettime(CLOCK_MONOTONIC, &until);
        until.tv_sec += ms / 1000; until.tv_nsec += (long)(ms % 1000) * 1000000l;
        if (until.tv_nsec >= 1000000000l) { until.tv_sec++; until.tv_nsec -= 1000000000l; }
    }
    pthread_mutex_lock(&e->m);
    while (!e->set) {
        int r = ms == INFINITE ? pthread_cond_wait(&e->c, &e->m) : pthread_cond_timedwait(&e->c, &e->m, &until);
        if (r == ETIMEDOUT) break;
    }
    int got = e->set; e->set = 0;
    pthread_mutex_unlock(&e->m);
    return got ? WAIT_OBJECT_0 : WAIT_TIMEOUT;
}

/* ---- fibers ------------------------------------------------------------------ */
typedef struct fiber {
    void *sp;                     /* saved stack pointer while not running */
    void *stack; size_t size;     /* mapping (NULL for a converted thread) */
    LPFIBER_START_ROUTINE fn; void *arg;
} fiber;
static __thread fiber *cur_fiber;

/* plat_fiber_switch(&old->sp, new_sp): push the callee-saved registers and the
 * FP control words on the old stack, save its sp, load the new one and pop. A
 * new fiber's stack holds the same frame with fiber_entry as return address. */
void plat_fiber_switch(void **save_sp, void *new_sp);
void plat_fiber_start(void);
__asm__(
    ".text\n"
    ".globl plat_fiber_switch\n"
    ".type plat_fiber_switch, @function\n"
    "plat_fiber_switch:\n"
    "  pushq %rbp\n  pushq %rbx\n  pushq %r12\n  pushq %r13\n  pushq %r14\n  pushq %r15\n"
    "  subq $8, %rsp\n  stmxcsr (%rsp)\n  fnstcw 4(%rsp)\n"
    "  movq %rsp, (%rdi)\n"
    "  movq %rsi, %rsp\n"
    "  ldmxcsr (%rsp)\n  fldcw 4(%rsp)\n  addq $8, %rsp\n"
    "  popq %r15\n  popq %r14\n  popq %r13\n  popq %r12\n  popq %rbx\n  popq %rbp\n"
    "  ret\n"
    ".size plat_fiber_switch, .-plat_fiber_switch\n"
    ".globl plat_fiber_start\n"
    ".type plat_fiber_start, @function\n"
    "plat_fiber_start:\n"          /* first switch into a fiber returns here: r12 = entry, r13 = fiber */
    "  movq %r13, %rdi\n"
    "  callq *%r12\n"
    "  ud2\n"
    ".size plat_fiber_start, .-plat_fiber_start\n");

static void fiber_entry(fiber *f) {
    f->fn(f->arg);
    fprintf(stderr, "plat: a fiber function returned\n");   /* Windows ends the thread; nothing here may */
    abort();
}

void *ConvertThreadToFiberEx(void *arg, DWORD flags) {
    (void)arg; (void)flags;
    if (cur_fiber) return cur_fiber;
    cur_fiber = calloc(1, sizeof *cur_fiber);
    return cur_fiber;
}
void *GetCurrentFiber(void) { return cur_fiber; }

void *CreateFiberEx(size_t commit, size_t reserve, DWORD flags, LPFIBER_START_ROUTINE fn, void *arg) {
    (void)flags;
    size_t page = (size_t)sysconf(_SC_PAGESIZE), size = reserve > commit ? reserve : commit;
    if (size < 64 << 10) size = 64 << 10;
    size = (size + page - 1) & ~(page - 1);
    fiber *f = calloc(1, sizeof *f);
    if (!f) return NULL;
    /* reserved address space, pages come on first touch; the lowest page stays a guard */
    f->stack = mmap(NULL, size + page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE | MAP_STACK, -1, 0);
    if (f->stack == MAP_FAILED) { free(f); return NULL; }
    mprotect(f->stack, page, PROT_NONE);
    f->size = size + page; f->fn = fn; f->arg = arg;
    uintptr_t top = ((uintptr_t)f->stack + f->size) & ~(uintptr_t)15;
    uint64_t *s = (uint64_t *)top;
    *--s = (uint64_t)(uintptr_t)plat_fiber_start;   /* after its ret rsp = top: the call in it is 16-byte aligned */
    *--s = 0;                                   /* rbp */
    *--s = 0;                                   /* rbx */
    *--s = (uint64_t)(uintptr_t)fiber_entry;    /* r12 */
    *--s = (uint64_t)(uintptr_t)f;              /* r13 */
    *--s = 0;                                   /* r14 */
    *--s = 0;                                   /* r15 */
    uint32_t csr = _mm_getcsr(); uint16_t cw; __asm__ volatile("fnstcw %0" : "=m"(cw));
    *--s = (uint64_t)csr | (uint64_t)cw << 32;  /* the creator's FP modes */
    f->sp = s;
    return f;
}

void SwitchToFiber(void *p) {
    fiber *f = p, *o = cur_fiber;
    if (f == o) return;
    cur_fiber = f;
    plat_fiber_switch(&o->sp, f->sp);
}

void DeleteFiber(void *p) {
    fiber *f = p;
    if (!f || f == cur_fiber) return;
    if (f->stack) munmap(f->stack, f->size);
    free(f);
}

/* ---- memory, environment, paths ---------------------------------------------- */
void *VirtualAlloc(void *addr, size_t size, DWORD type, DWORD protect) {
    (void)addr; (void)type; (void)protect;
    void *p = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    return p == MAP_FAILED ? NULL : p;
}

int _putenv(const char *s) {
    char *c = strdup(s);
    return c ? putenv(c) : -1;
}

DWORD GetFullPathNameA(const char *name, DWORD n, char *out, char **file) {
    char buf[MAX_PATH * 2];
    if (file) *file = NULL;
    if (name[0] == '/') snprintf(buf, sizeof buf, "%s", name);
    else {
        char cwd[MAX_PATH];
        if (!getcwd(cwd, sizeof cwd)) return 0;
        snprintf(buf, sizeof buf, "%s/%s", cwd, name);
    }
    size_t l = strlen(buf);
    if (l + 1 > n) return (DWORD)(l + 1);   /* as Windows: the size needed */
    memcpy(out, buf, l + 1);
    return (DWORD)l;
}

BOOL SetCurrentDirectoryA(const char *dir) { return chdir(dir) == 0; }
#endif
