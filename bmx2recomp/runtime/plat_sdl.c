/* Linux: keyboard, mouse buttons, gamepads and the message box through SDL2
 * (zlib licence), behind the Win32 names of plat.h. The window, GL context and
 * event pump are gs_gl.c's; it hands controller events to plat_sdl_event.
 * Nothing here on Windows. */
#ifndef _WIN32
#include "plat.h"
#include <SDL.h>

/* ---- keyboard ------------------------------------------------------------------- */
/* virtual-key code -> SDL scancode (0 = none). Letters and digits go by the
 * keyboard layout, as Windows' virtual keys do. */
static int vk_scancode(int vk) {
    if ((vk >= 'A' && vk <= 'Z') || (vk >= '0' && vk <= '9'))
        return (int)SDL_GetScancodeFromKey((SDL_Keycode)(vk >= 'A' ? vk - 'A' + 'a' : vk));
    if (vk >= VK_NUMPAD0 && vk <= VK_NUMPAD0 + 9) return vk == VK_NUMPAD0 ? SDL_SCANCODE_KP_0 : SDL_SCANCODE_KP_1 + (vk - VK_NUMPAD0 - 1);
    if (vk >= VK_F1 && vk <= VK_F1 + 11) return SDL_SCANCODE_F1 + (vk - VK_F1);
    switch (vk) {
    case VK_BACK: return SDL_SCANCODE_BACKSPACE;
    case VK_TAB: return SDL_SCANCODE_TAB;
    case VK_RETURN: return SDL_SCANCODE_RETURN;
    case VK_ESCAPE: return SDL_SCANCODE_ESCAPE;
    case VK_SPACE: return SDL_SCANCODE_SPACE;
    case VK_LEFT: return SDL_SCANCODE_LEFT;
    case VK_UP: return SDL_SCANCODE_UP;
    case VK_RIGHT: return SDL_SCANCODE_RIGHT;
    case VK_DOWN: return SDL_SCANCODE_DOWN;
    case VK_LSHIFT: return SDL_SCANCODE_LSHIFT;
    case VK_RSHIFT: return SDL_SCANCODE_RSHIFT;
    case VK_LCONTROL: return SDL_SCANCODE_LCTRL;
    case VK_RCONTROL: return SDL_SCANCODE_RCTRL;
    case VK_LMENU: return SDL_SCANCODE_LALT;
    case VK_RMENU: return SDL_SCANCODE_RALT;
    case VK_OEM_1: return SDL_SCANCODE_SEMICOLON;
    case VK_OEM_COMMA: return SDL_SCANCODE_COMMA;
    case VK_OEM_PERIOD: return SDL_SCANCODE_PERIOD;
    case VK_OEM_2: return SDL_SCANCODE_SLASH;
    }
    return 0;
}

SHORT GetAsyncKeyState(int vk) {
    int down = 0;
    if (vk >= VK_LBUTTON && vk <= VK_XBUTTON2 && vk != 3) {
        static const Uint32 mb[] = { 0, SDL_BUTTON_LMASK, SDL_BUTTON_RMASK, 0, SDL_BUTTON_MMASK, SDL_BUTTON_X1MASK, SDL_BUTTON_X2MASK };
        down = (SDL_GetMouseState(NULL, NULL) & mb[vk]) != 0;
    } else {
        const Uint8 *k = SDL_GetKeyboardState(NULL);
        if (vk == VK_SHIFT) down = k[SDL_SCANCODE_LSHIFT] || k[SDL_SCANCODE_RSHIFT];
        else if (vk == VK_CONTROL) down = k[SDL_SCANCODE_LCTRL] || k[SDL_SCANCODE_RCTRL];
        else if (vk == VK_MENU) down = k[SDL_SCANCODE_LALT] || k[SDL_SCANCODE_RALT];
        else { int sc = vk_scancode(vk); down = sc && k[sc]; }
    }
    return down ? (SHORT)0x8000 : 0;
}

int plat_vk_from_scancode(int sc) {
    static unsigned char map[SDL_NUM_SCANCODES]; static int made;
    if (!made) {   /* the keyboard layout is read once, at the first key */
        made = 1;
        for (int vk = 255; vk > 0; vk--) { int s = vk_scancode(vk); if (s > 0 && s < SDL_NUM_SCANCODES) map[s] = (unsigned char)vk; }
    }
    return sc > 0 && sc < SDL_NUM_SCANCODES ? map[sc] : 0;
}

/* ---- message box ---------------------------------------------------------------- */
int MessageBoxA(void *wnd, const char *text, const char *caption, unsigned type) {
    (void)wnd;
    fprintf(stderr, "%s: %s\n", caption, text);
    SDL_ShowSimpleMessageBox(type & MB_ICONERROR ? SDL_MESSAGEBOX_ERROR : SDL_MESSAGEBOX_INFORMATION, caption, text, NULL);
    return 1;
}

/* ---- gamepads as XInput slots 0-3 ---------------------------------------------- */
static SDL_GameController *slot[4];
static SDL_JoystickID slot_id[4];

void plat_sdl_event(const SDL_Event *e) {
    if (e->type == SDL_CONTROLLERDEVICEADDED) {
        int k = 0; while (k < 4 && slot[k]) k++;
        if (k == 4) return;
        SDL_GameController *c = SDL_GameControllerOpen(e->cdevice.which);
        if (!c) return;
        SDL_JoystickID id = SDL_JoystickInstanceID(SDL_GameControllerGetJoystick(c));
        for (int i = 0; i < 4; i++) if (slot[i] && slot_id[i] == id) { SDL_GameControllerClose(c); return; }   /* already open */
        slot[k] = c; slot_id[k] = id;
        fprintf(stderr, "pad: %s is gamepad %d\n", SDL_GameControllerName(c) ? SDL_GameControllerName(c) : "a controller", k + 1);
    } else if (e->type == SDL_CONTROLLERDEVICEREMOVED) {
        for (int k = 0; k < 4; k++)
            if (slot[k] && slot_id[k] == e->cdevice.which) { SDL_GameControllerClose(slot[k]); slot[k] = NULL; }
    }
}

DWORD plat_xinput_get(DWORD idx, plat_xi_state *s) {
    if (idx > 3 || !slot[idx] || !SDL_GameControllerGetAttached(slot[idx])) return 1167;   /* ERROR_DEVICE_NOT_CONNECTED */
    SDL_GameController *c = slot[idx];
    static const struct { SDL_GameControllerButton b; WORD xb; } map[] = {
        { SDL_CONTROLLER_BUTTON_DPAD_UP, 0x0001 }, { SDL_CONTROLLER_BUTTON_DPAD_DOWN, 0x0002 },
        { SDL_CONTROLLER_BUTTON_DPAD_LEFT, 0x0004 }, { SDL_CONTROLLER_BUTTON_DPAD_RIGHT, 0x0008 },
        { SDL_CONTROLLER_BUTTON_START, 0x0010 }, { SDL_CONTROLLER_BUTTON_BACK, 0x0020 },
        { SDL_CONTROLLER_BUTTON_LEFTSTICK, 0x0040 }, { SDL_CONTROLLER_BUTTON_RIGHTSTICK, 0x0080 },
        { SDL_CONTROLLER_BUTTON_LEFTSHOULDER, 0x0100 }, { SDL_CONTROLLER_BUTTON_RIGHTSHOULDER, 0x0200 },
        { SDL_CONTROLLER_BUTTON_A, 0x1000 }, { SDL_CONTROLLER_BUTTON_B, 0x2000 },
        { SDL_CONTROLLER_BUTTON_X, 0x4000 }, { SDL_CONTROLLER_BUTTON_Y, 0x8000 },
    };
    memset(s, 0, sizeof *s);
    for (unsigned k = 0; k < sizeof map / sizeof map[0]; k++)
        if (SDL_GameControllerGetButton(c, map[k].b)) s->g.buttons |= map[k].xb;
    /* triggers 0..32767 -> 0..255; sticks as XInput: y up is positive */
    s->g.lt = (BYTE)(SDL_GameControllerGetAxis(c, SDL_CONTROLLER_AXIS_TRIGGERLEFT) >> 7);
    s->g.rt = (BYTE)(SDL_GameControllerGetAxis(c, SDL_CONTROLLER_AXIS_TRIGGERRIGHT) >> 7);
    s->g.lx = SDL_GameControllerGetAxis(c, SDL_CONTROLLER_AXIS_LEFTX);
    s->g.ly = (SHORT)(-1 - SDL_GameControllerGetAxis(c, SDL_CONTROLLER_AXIS_LEFTY));
    s->g.rx = SDL_GameControllerGetAxis(c, SDL_CONTROLLER_AXIS_RIGHTX);
    s->g.ry = (SHORT)(-1 - SDL_GameControllerGetAxis(c, SDL_CONTROLLER_AXIS_RIGHTY));
    return 0;
}

DWORD plat_xinput_set(DWORD idx, plat_xi_vibration *v) {
    if (idx > 3 || !slot[idx]) return 1167;
    /* XInput motors run until the next value; SDL caps a rumble at SDL_MAX_RUMBLE_DURATION_MS (65 s) */
    SDL_GameControllerRumble(slot[idx], v->left, v->right, v->left || v->right ? 0xffffffffu : 0);
    return 0;
}
#endif
