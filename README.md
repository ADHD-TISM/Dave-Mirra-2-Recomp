# Dave Mirra Freestyle BMX 2 — PC recompilation

<a href="https://recomplauncher.com"><picture><source media="(prefers-color-scheme: dark)" srcset="https://recomplauncher.com/assets/press/launcher/badge-light.svg"><img alt="Get it on RecompLauncher" src="https://recomplauncher.com/assets/press/launcher/badge-dark.svg" height="48"></picture></a>

> Mainly Complete.

A native Windows and Linux build of **Dave Mirra Freestyle BMX 2** (PlayStation 2, USA,
SLUS-20159). The game's own program is translated to C and compiled for the PC.
It is not an emulator: the game code runs natively, and a small runtime stands
in for the PS2 hardware. Graphics run on your GPU through OpenGL.

**No game data is included.** You need your own copy of the game. The game is
built on your PC from your own disc image, in
[RecompLauncher](https://recomplauncher.com).

## What works

- The intro movies, menus, saving and loading on a memory card.
- All 8 levels, at 60 fps.
- Music, sound effects and movie sound.
- Keyboard and Xbox-style gamepads.
- Higher internal resolution (2x to 4x), windowed or borderless fullscreen.

Known gaps: some rarely used graphics features are missing, and some sound
effects (reverb) may sound drier than on a PS2.

## Requirements

- Windows 10 or 11, 64-bit, or Linux on x86-64 (see Linux below).
- A GPU with OpenGL 3.3.
- About 1 GB of free disk space.
- Your own disc image of **Dave Mirra Freestyle BMX 2, USA (SLUS-20159),
  version 1.00**: a `.bin` + `.cue`, an `.iso`, or a `.chd` (made with
  chdman `createcd` or `createdvd`). Other regions do not work.

On Windows you do not need to install a compiler or Python. The setup step
downloads its own build tools (about 200 MB) into the game's folder and writes
nothing outside it.

**Linux:** the game is built with your system's tools. Install a C compiler,
Python 3, and the SDL2, OpenGL and EGL development files first:

```
sudo apt install gcc python3 libsdl2-dev libgl-dev libegl-dev        # Debian, Ubuntu, Mint
sudo dnf install gcc python3 SDL2-devel mesa-libGL-devel mesa-libEGL-devel   # Fedora
sudo pacman -S gcc python sdl2 mesa                                  # Arch
```

The Linux release (`DaveMirraFreestyleBMX2-<version>-Linux-x86_64.tar.gz`)
holds the program `Dave Mirra Freestyle BMX 2`; it takes the same commands as
the Windows exe below. The setup step only downloads the project's source.

## Install and play

1. Install [RecompLauncher](https://recomplauncher.com).
2. Find Dave Mirra Freestyle BMX 2 in its catalog and install it. It is not
   listed yet. Until it is, unpack a release zip (below) and add that folder in
   RecompLauncher with **Settings > Bring Your Games > Pick a Folder**, or use
   the command line below.
3. On the setup screen, pick your disc image (`.cue` with its `.bin`, `.iso`
   or `.chd`), and tick **Download the build tools and the project's source**.
4. The setup step translates the game's code from your disc and builds it. The
   first build takes about a minute.
5. Press **Play**.

RecompLauncher brings each new release and builds the game again. Updates keep
your settings and memory card saves.

**Without RecompLauncher:** download `DaveMirraFreestyleBMX2-<version>-Windows-x64.zip`
from the [Releases](https://github.com/ADHD-TISM/Dave-Mirra-2-Recomp/releases)
page and unpack it. Then, in that folder, build once and play:

```
"Dave Mirra Freestyle BMX 2.exe" --disc=<your .cue, .iso or .chd> prepare --accept-downloads
"Dave Mirra Freestyle BMX 2.exe" --disc=<your .cue, .iso or .chd> run
```

On Linux, unpack the `.tar.gz` and use `"./Dave Mirra Freestyle BMX 2"` the
same way. The built game is `game/bmx2`.

After `prepare`, a double click on `Dave Mirra Freestyle BMX 2.exe` starts
the game. It has no window of its own. Without `--disc=`, it uses the first
image of the game in a `Dave Mirra 2` folder next to it.

To update, unpack the new release zip over the folder and run the `prepare`
line again. For another disc image, run `prepare` with the new `--disc=`.

## Controls

The keyboard defaults are below. Change them in `bmx2.ini` (see Settings).

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
X = Square, Y = Triangle). A second gamepad is player 2, for Multiplayer.
With only one gamepad, set **Player 2** to **First gamepad**: the gamepad is
then player 2 and the keyboard player 1. **F11** or **Alt+Enter** toggles
fullscreen. In RecompLauncher's Big Picture mode the game starts fullscreen.

## Settings

The game's page in RecompLauncher has the settings: internal resolution,
window mode, widescreen (16:9), picture shape, picture filter, V-Sync, intro
movies, volume, gamepad, vibration and player 2. Internal resolution 2-4 also
smooths edges. The game vibrates the pad only while grinding and on a few
surfaces, as on the PS2.

They are kept in `game\bmx2.ini`, which also has the window size and the key
bindings, with a comment on each line. Delete it to get the defaults back.
In RecompLauncher, `game\` is inside the game's `recompdata` folder.

## Saves

The memory card is the folder `game\memcard\mc0`. RecompLauncher backs it up
after every session. Without it, back the folder up yourself.

## Troubleshooting

- **"is not a disc image" or "does not match":** check that the image is the USA
  version 1.00 (SLUS-20159) and is not compressed.
- **A message box says the game called code that was not recompiled:** please
  open an issue with a screenshot of the message and what you were doing.
- **The setup step stopped with code 10:** tick **Download the build tools and
  the project's source** on the setup screen (or add `--accept-downloads`).
- **Stutter:** make sure V-Sync is on in Settings, and try a lower resolution.
  Most laptops with two graphics chips from different makers (NVIDIA or AMD
  plus Intel, or NVIDIA plus AMD) run the game on the dedicated chip, and
  with vsync on the game paces frames with its own timer instead;
  `game\bmx2.log` then says "driven by another graphics chip". The picture
  may tear. If you mind the tearing more than stutter, turn on **V-Sync on
  two-chip laptops** (under Show Advanced Options, or `vsync_two_chip = 1`
  in `bmx2.ini`). The log line `gs: OpenGL ... (<chip>)` names the
  chip in use. If it names the integrated chip, open Windows Settings >
  System > Display > Graphics, add `game\bmx2.exe` (Browse) and set it to
  High performance.

## Building from source (developers)

The setup step does all of this for you. To work on the code directly:

- `bmx2recomp/tools/recomp_ee.py`, `recomp_iop.py` and `recomp_vu.py` translate
  the game's main CPU, sound/disc CPU and VU1 programs to C.
- `bmx2recomp/runtime/` is the hardware runtime: GS on OpenGL, VIF/VU, IPU
  movies, SPU2 sound, pad, memory card, kernel.
- `bmx2recomp/build.sh` builds `bmx2.exe` with clang (on Linux: `build/bmx2`
  with gcc or clang, SDL2 and libGL/libEGL). Its icon comes from the
  game's memory card icon on your disc (`tools/make_icon.py`, built into the
  exe with `runtime/bmx2.rc`), so no game art is in this repository.
- `bmx2recomp/NOTES.md` holds the research notes and the current state.
- `launcher/bmx2launcher.py` is the program players get
  (`python launcher/bmx2launcher.py --help`): the setup step (`prepare`) and
  the game starter (`run`) that `recomplauncher.json` names.
  `sh launcher/release.sh v1.2.3` packs a release zip with
  `recomplauncher.json` beside the exe.

Never commit game data: no disc images, extracted files or generated code.
The `.gitignore` only lets source files in.

## License

The code in this repository is under the [MIT License](LICENSE), except
`bmx2recomp/third_party/libchdr` (CHD reading: BSD 3-clause, with its own
licence files or licence headers for LZMA, miniz, Zstandard and dr_flac),
`bmx2recomp/third_party/stb_truetype.h` (the Linux menu's text: public domain
or MIT, at your choice) and `bmx2recomp/third_party/rl_achievements` (Recomp
Achievements: the Recomp Achievements License 1.0 in its LICENSE file, free
for games, launchers need its author's written permission; it includes
rcheevos and cJSON, MIT).
None of these licences grant rights to Dave Mirra Freestyle BMX 2 or its data,
which belong to their owners.
This project is not affiliated with or endorsed by them.
