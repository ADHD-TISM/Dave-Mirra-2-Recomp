/* Host platform. Windows: <windows.h>, nothing else. Linux (x86-64): the small
 * subset of Win32 names the runtime uses, implemented in plat_posix.c on
 * POSIX threads, clock_gettime, mmap and a hand-written fiber switch, plus
 * SDL2 for the window, input, gamepads and sound (gs_gl.c, pad.c, spu2.c).
 * Keeping the Win32 names lets the Windows build stay exactly as it was; only
 * the window, sound, pad and memory card code have their own Linux branches.
 * See NOTES.md "Linux". */
#pragma once
#ifdef _WIN32
#include <windows.h>
#define PATH_SEP "\\"
#else
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <strings.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
#include <immintrin.h>

#define PATH_SEP "/"
#define WINAPI
#define CALLBACK
#define TRUE 1
#define FALSE 0
#define MAX_PATH 4096
typedef uint32_t DWORD; typedef int32_t LONG; typedef int BOOL; typedef uint16_t WORD; typedef uint8_t BYTE;
typedef int16_t SHORT; typedef uint64_t ULONG64; typedef uintptr_t WPARAM; typedef intptr_t LPARAM;
typedef void *HANDLE; typedef long long LONGLONG;
typedef union { struct { uint32_t LowPart; int32_t HighPart; } u; long long QuadPart; } LARGE_INTEGER;

/* time: QueryPerformanceCounter counts nanoseconds (CLOCK_MONOTONIC) */
BOOL QueryPerformanceCounter(LARGE_INTEGER *t);
BOOL QueryPerformanceFrequency(LARGE_INTEGER *f);
DWORD GetTickCount(void);
void Sleep(DWORD ms);
static inline DWORD timeBeginPeriod(DWORD ms) { (void)ms; return 0; }   /* nanosleep is already exact */
#define YieldProcessor() _mm_pause()

/* threads and auto-reset events */
typedef DWORD (*LPTHREAD_START_ROUTINE)(void *);
HANDLE CreateThread(void *attr, size_t stack, LPTHREAD_START_ROUTINE fn, void *arg, DWORD flags, DWORD *id);
HANDLE GetCurrentThread(void);   /* a handle that stays valid for this thread */
BOOL QueryThreadCycleTime(HANDLE t, ULONG64 *ns);   /* thread CPU time in ns (Windows: cycles); debug stats only */
#define THREAD_PRIORITY_ABOVE_NORMAL 1
static inline BOOL SetThreadPriority(HANDLE t, int p) { (void)t; (void)p; return TRUE; }   /* not without privileges */
HANDLE CreateEventA(void *attr, BOOL manual, BOOL initial, const char *name);   /* auto-reset only */
BOOL SetEvent(HANDLE e);
DWORD WaitForSingleObject(HANDLE e, DWORD ms);   /* events only */
#define WAIT_OBJECT_0 0
#define WAIT_TIMEOUT 258
#define INFINITE 0xffffffffu

/* reader/writer lock */
#include <pthread.h>
typedef pthread_rwlock_t SRWLOCK;
#define SRWLOCK_INIT PTHREAD_RWLOCK_INITIALIZER
#define AcquireSRWLockExclusive(l) pthread_rwlock_wrlock(l)
#define ReleaseSRWLockExclusive(l) pthread_rwlock_unlock(l)
#define AcquireSRWLockShared(l) pthread_rwlock_rdlock(l)
#define ReleaseSRWLockShared(l) pthread_rwlock_unlock(l)
#define InterlockedIncrement(p) __atomic_add_fetch((p), 1, __ATOMIC_SEQ_CST)

/* fibers: one stack each, switched by plat_fiber_switch (x86-64 SysV, saves the
 * callee-saved registers, MXCSR and the x87 control word). Only the thread that
 * converted itself with ConvertThreadToFiberEx switches between them. */
#define FIBER_FLAG_FLOAT_SWITCH 1
typedef void (*LPFIBER_START_ROUTINE)(void *);
void *ConvertThreadToFiberEx(void *arg, DWORD flags);
void *CreateFiberEx(size_t commit, size_t reserve, DWORD flags, LPFIBER_START_ROUTINE fn, void *arg);
void SwitchToFiber(void *fiber);
void *GetCurrentFiber(void);
void DeleteFiber(void *fiber);   /* never the running one */

/* memory */
#define MEM_COMMIT 0x1000
#define MEM_RESERVE 0x2000
#define PAGE_READWRITE 4
void *VirtualAlloc(void *addr, size_t size, DWORD type, DWORD protect);   /* zeroed, NULL on failure */

/* C runtime names */
#define _stricmp strcasecmp
#define _strnicmp strncasecmp
#define _fseeki64 fseeko
#define _ftelli64 ftello
int _putenv(const char *s);   /* copies s (POSIX putenv keeps the pointer) */
#define _mkdir(p) mkdir((p), 0777)
#define _rmdir rmdir
#define _stat64 stat
#define _S_IFDIR S_IFDIR

/* files and folders */
DWORD GetFullPathNameA(const char *name, DWORD n, char *out, char **file);
BOOL SetCurrentDirectoryA(const char *dir);

/* message box: SDL's (plat_sdl.c); to stderr when there is no display */
#define MB_OK 0
#define MB_ICONERROR 0x10
int MessageBoxA(void *wnd, const char *text, const char *caption, unsigned type);

/* keyboard: Windows virtual-key codes stay the key codes (bmx2.ini names,
 * menu.c); plat_sdl.c maps them to SDL scancodes and mouse buttons */
SHORT GetAsyncKeyState(int vk);
int plat_vk_from_scancode(int sc);   /* SDL scancode -> virtual-key code, 0 if none */
#define VK_LBUTTON 0x01
#define VK_RBUTTON 0x02
#define VK_MBUTTON 0x04
#define VK_XBUTTON1 0x05
#define VK_XBUTTON2 0x06
#define VK_BACK 0x08
#define VK_TAB 0x09
#define VK_RETURN 0x0D
#define VK_SHIFT 0x10
#define VK_CONTROL 0x11
#define VK_MENU 0x12
#define VK_ESCAPE 0x1B
#define VK_SPACE 0x20
#define VK_LEFT 0x25
#define VK_UP 0x26
#define VK_RIGHT 0x27
#define VK_DOWN 0x28
#define VK_NUMPAD0 0x60
#define VK_NUMPAD2 0x62
#define VK_NUMPAD4 0x64
#define VK_NUMPAD6 0x66
#define VK_NUMPAD8 0x68
#define VK_F1 0x70
#define VK_F11 0x7A
#define VK_LSHIFT 0xA0
#define VK_RSHIFT 0xA1
#define VK_LCONTROL 0xA2
#define VK_RCONTROL 0xA3
#define VK_LMENU 0xA4
#define VK_RMENU 0xA5
#define VK_OEM_1 0xBA
#define VK_OEM_COMMA 0xBC
#define VK_OEM_PERIOD 0xBE
#define VK_OEM_2 0xBF

/* gamepads: SDL game controllers read in XInput's layout (pad.c keeps its
 * XInput code); index = the order the controllers were connected in */
typedef struct { WORD buttons; BYTE lt, rt; SHORT lx, ly, rx, ry; } plat_xi_gamepad;
typedef struct { DWORD packet; plat_xi_gamepad g; } plat_xi_state;
typedef struct { WORD left, right; } plat_xi_vibration;
DWORD plat_xinput_get(DWORD idx, plat_xi_state *s);         /* 0 = a pad is there */
DWORD plat_xinput_set(DWORD idx, plat_xi_vibration *v);
#endif
