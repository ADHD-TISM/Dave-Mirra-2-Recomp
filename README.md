# Dave Mirra Freestyle BMX 2 — PC recompilation

> **Early work in progress.** Expect bugs, crashes and missing effects.

A native Windows build of **Dave Mirra Freestyle BMX 2** (PlayStation 2, USA,
SLUS-20159). The game's own program is translated to C and compiled for the PC.
It is not an emulator: the game code runs natively, and a small runtime stands
in for the PS2 hardware. Graphics run on your GPU through OpenGL.

**No game data is included.** You need your own copy of the game. The launcher
reads the code from your disc image and builds the game on your PC.

## What works

- The intro movies, menus, saving and loading on a memory card.
- All 8 levels, at 60 fps.
- Music, sound effects and movie sound.
- Keyboard and Xbox-style gamepads.
- Higher internal resolution (2x to 4x), windowed or borderless fullscreen.

Known gaps: some rarely used graphics features are missing, and some sound
effects (reverb) may sound drier than on a PS2.

## Requirements

- Windows 10 or 11, 64-bit.
- A GPU with OpenGL 3.3.
- About 1 GB of free disk space.
- Your own disc image of **Dave Mirra Freestyle BMX 2, USA (SLUS-20159),
  version 1.00**: a `.bin` + `.cue` or an `.iso`. Other regions do not work.

You do not need to install a compiler or Python. The launcher downloads its own
build tools into its folder and writes nothing outside it.

## Install and play

1. Download `Dave-Mirra-2-Launcher.exe` from the
   [Releases](https://github.com/ADHD-TISM/Dave-Mirra-2-Recomp/releases) page.
   Put it in an empty folder.
2. Start the launcher once. It creates a folder called `Dave Mirra 2` next to it.
3. Copy your disc image (`.bin` + `.cue`, or `.iso`) into `Dave Mirra 2`.
4. Open the **Update** tab and click **Download**. This fetches the build tools
   (about 200 MB) and the project.
5. Open the **Build** tab and click **Build the game**. The first build takes
   about a minute.
6. Open the **Play** tab and click **Play**.

To update later, open **Update** and click **Update the project**, then build
again. A new launcher comes as a new download from the Releases page.
Updates keep your settings and memory card saves.

## Controls

The keyboard defaults are below. Change them in the launcher's **Settings** tab.

| PS2 | Keyboard |
|---|---|
| D-pad | Arrow keys |
| Left stick | W A S D |
| Cross | K or Space |
| Circle | L |
| Square | J |
| Triangle | I |
| L1 / R1 | Q / E |
| L2 / R2 | 1 / 3 |
| Start | Enter |
| Select | Backspace or Right Shift |

An Xbox-style gamepad works as the PS2 pad (A = Cross, B = Circle,
X = Square, Y = Triangle). **F11** or **Alt+Enter** toggles fullscreen.

## Settings

The **Settings** tab edits `game\bmx2.ini`. You can change the internal
resolution, window size, fullscreen, picture shape (4:3 or stretched), picture
filter, volume, vsync and the key bindings. Delete `bmx2.ini` to get the
defaults back.

## Saves

The memory card is the folder `game\memcard\mc0`. Back it up to keep your saves.

## Troubleshooting

- **"is not a disc image" or "does not match":** check that the image is the USA
  version 1.00 (SLUS-20159) and is not compressed.
- **A message box says the game called code that was not recompiled:** please
  open an issue with a screenshot of the message and what you were doing.
- **Stutter:** make sure vsync is on in Settings, and try a lower resolution.

## Building from source (developers)

The launcher does all of this for you. To work on the code directly:

- `bmx2recomp/tools/recomp_ee.py`, `recomp_iop.py` and `recomp_vu.py` translate
  the game's main CPU, sound/disc CPU and VU1 programs to C.
- `bmx2recomp/runtime/` is the hardware runtime: GS on OpenGL, VIF/VU, IPU
  movies, SPU2 sound, pad, memory card, kernel.
- `bmx2recomp/build.sh` builds `bmx2.exe` with clang.
- `bmx2recomp/NOTES.md` holds the research notes and the current state.
- The launcher's own source is `launcher/bmx2launcher.py`
  (`python launcher/bmx2launcher.py --help`).

Never commit game data: no disc images, extracted files or generated code.
The `.gitignore` only lets source files in.

## License

The code in this repository is under the [MIT License](LICENSE). It grants no
rights to Dave Mirra Freestyle BMX 2 or its data, which belong to their owners.
This project is not affiliated with or endorsed by them.
