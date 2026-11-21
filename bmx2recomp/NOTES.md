# Dave Mirra Freestyle BMX 2 (PS2, SLUS-20159) static recomp — working notes

Everything lives in `Desktop\rea\Dave Mirra PS2\` (moved 2026-11-19):
`disc\` = extracted disc (from the .bin, MODE2/2352), `bmx2recomp\` = this project.

## Build / run
    python -I tools/recomp_ee.py ../disc/SLUS_201.59 gen --extra extra_ee.txt   # EE ELF -> gen/*.c (without --extra ~70 functions are missing)
    sh build.sh                                              # -> build/bmx2.exe (clang)
    build/bmx2.exe --turbo --log-sys 1 --frames 900 ../disc  # headless, logs to stderr
`OPT="-O1 -DEE_TRACE" sh build.sh` (after `rm -rf build/obj`) records function
entries; the last 4M are written to `disc/trace.txt` on exit.
`tools/irxdis.py <irx>` disassembles an IOP module with import stubs named.
`tools/eedis.py <elf> -f ADDR | ADDR N | --xref ADDR [--span N]` disassembles
EE code (full R5900, constant-tracked register/string/function annotation,
xref search). Names come from `tools/names.txt`; add confirmed ones there.
`tools/dis.py` needs capstone (not installed) and REA cannot analyse MIPS ELFs
on Windows, so use eedis.py. Workflow summary: skill `ps2-static-recomp`.

## State (2026-11-19, sixth session): levels run at full speed
Woodward Camp averages 68 fps in --turbo (was 6-35) and holds 59.9 fps in
real time in the window. VU1 microcode is statically recompiled to C
(gen_vu/), GS write-backs are cut down, and two host bugs were fixed (getenv
on every XGKICK, frame pacer). Game printf (DECI2 TTY) now prints. See
"Performance" and "VU1 static recompile". Still no sound.

## State (2026-11-19, fifth session): pad input works
Keyboard / XInput / scripted pad input (see "Pad" below). Start skips the
intro; the main menu, rider/bike/modifier/level screens, the loading screen
and the first level (Woodward Camp, 3D, rider on screen) all render, and
the rider rides, crashes and respawns with the run timer counting (headless,
scripted, to frame 9400). Levels run slowly (6-35 fps host). Still no sound.
The fourth-session state below is unchanged otherwise.

## State (2026-11-19, end of fourth session)
The game opens a window (on the Dell) and shows the boot movies through the
GPU GS: Acclaim logo, Z-Axis logo, the whole intro, 3600 frames with no stall
(19 s in `--turbo`). New this session: GS front end + OpenGL 3.3 back end,
VIF0/VIF1, VU0/VU1 micro mode interpreter, VIF i-bit interrupts with a
resumable DMA. No sound, no pad input yet. Where boot goes after the intro is
the next thing to find. The bullets below are from 2026-11-16 unless marked.
- EE recompiler: 4713 functions (5 from `extra_ee.txt`, found by
  `sh tools/iterate.sh <rounds> [args]`, which reruns and adds missing entries).
- Runtime: memory map, timers, DMAC (normal/chain), INTC, EE kernel HLE with
  fiber threads/semaphores/handlers/alarms, DECI2 printf, FPU, MMI (ops the
  game uses), VU0 macro mode, SIF command + RPC protocol.
- IOP: `python -I tools/recomp_iop.py ../disc/ZCDDVD.IRX zcddvd 80000 gen_iop`
  recompiles an IRX (relocated to a fixed base, image embedded);
  `runtime/iop.c` runs it on fibers against HLE kernel libs (thbase, thsemap,
  intrman, loadcore, stdio, sysclib, sifman, sifcmd incl. RPC servers and
  IOP->EE calls, cdvdman reading the .bin). ZCDDVD.IRX runs this way at
  0x80000. To add a module: list it in `modules[]` and its sids in
  `iop_is_lle_sid` (iop.c). Other servers are still RPC-level stubs in sif.c
  (loadfile, cdvd 0x8000059x, mcserv, padman, ZAUDIO 0x47, sdrdrv 0x80000701).
- Boot reaches: CD mounted, files opened/read (callbacks to EE sid 0x46 work),
  ~58k qw of GIF data sent, ZAUDIO init calls, then the Acclaim logo movie
  (ASSETS/MOVIE/ACCLAIM.PSS). (2026-11-19: the IPU now exists and the movies
  play, see below.)
- `--no-movies` (fails .PSS opens) does NOT work as a skip: the game then
  calls a null device method (ra 0x130038).
- Flags: `--log-sys 1|2`, `--log-iop`, `--log-io`, `--log-ipu`, `--turbo`, `--frames N`,
  `--log-gs 1|2|3` (targets / every batch / every vertex and GIF tag),
  `--log-vif 1|2`, `--no-window` (hidden window, GL still runs), `--scale N` (1-4, default 2),
  `--log-pad`; env `PAD_SCRIPT` (see Pad), `PROF`/`PROF_FROM`, `FT_FROM`, `LOG_GS_FROM`/`LOG_GS_LEVEL`,
  `VU_RECORD`, `VU_CHECK`, `VU_INTERP`, `GS_EXACT_SYNC`, `GS_SYNC_PER_FRAME` (see Performance / VU1 static recompile),
  `--log-frames` (see In-game stutter), `--no-audio`, `--log-spu N`, `SPU_WAV`, `ZAUDIO_HLE` (see Audio).
- Env: `GS_SHOT=<dir> GS_SHOT_EVERY=N` writes the displayed picture as PPM;
  `VU_DUMP=<dir> [VU_DUMP_AT=frame]` writes vu1_code.bin/vu1_mem.bin at the
  next XGKICK; `EE_DUMP=<file>` writes EE RAM at the frame limit;
  `IPU_DUMP` as before. `tools/vudis.py vu1_code.bin [start [count]]`
  disassembles VU micro code.

## IPU (2026-11-19, third session) — works, movies decode
`runtime/ipu.c`: commands run on a host fiber and stall where the hardware
does (input FIFO empty with ch4 idle, output FIFO full with ch3 idle). Keeps
the real 8+2 qw input FIFO so D4_MADR, IPU_BP (BP/IFC/FP) and IPU_CTRL.IFC
agree: sceMpeg saves/restores the stream as MADR - 16*(IFC+FP) + BP
(`ipu_dma_save` 0x110090 / `ipu_dma_restore` 0x110190). ch4 normal + source
chain, ch3 normal. All commands (BCLR IDEC BDEC VDEC FDEC SETIQ SETVQ CSC PACK
SETTH); VLC tables B.1-B.15 checked for prefix overlaps at start-up
("VLC tables are inconsistent" means a typo in a table).
- The coded block pattern is not a VDEC table: BDEC reads the CBP VLC itself
  for non-intra MBs and reports it in IPU_CTRL.CBP. The game only uses VDEC
  TBL 1 (MB type) and 2 (motion code). sceMpeg does motion compensation on the
  EE and colour-converts with CSC (one CSC per picture, RAW8 in).
- sceMpeg's picture output is macroblocks in **column-major** order.
- Debug: `--log-ipu` (every command but FDEC 8, plus ch4 starts),
  `IPU_DUMP=<dir> IPU_DUMP_EVERY=N` writes every Nth CSC picture as PPM;
  `ipu_stats()` prints command counts at the frame limit.
- Verified: ACCLAIM.PSS (256x128) and the Z-Axis intro (512x256) decode to
  clean pictures incl. P/B frames.

## Fixes that unblocked movie playback (2026-11-19)
- sdrdrv 0x80000701 (sif.c): `BlockTrans` (0x80e0) records the looping SPU2
  buffer; `BlockTransStatus` (0x8100) returns (half << 24) | addr advancing at
  48 kHz 16-bit stereo. With a constant 0 the movie thread never refills audio
  and the demuxer stops feeding video. No sound is produced (no SPU2 yet).
- IOP sceSifCallRpc (iop.c): the packet's rmode is not the call mode. Waiting
  calls need rmode 1 (EE answers with RPC_END), no-wait calls rmode 1 only with
  an end function. With rmode 0 the EE's sceSifExecRequest (0x1e14b0) DMAs the
  end packet to pkt_addr and sends nothing. Each IOP client now has its own
  packet buffer at 0x1f000 + 0x40*n, and sceSifCheckStatRpc checks that
  packet's rpc_id/alloc flag (bind marks it too). Before this, ZCDDVD's
  double-buffered reads (flag 1, type-4 callback, mode 0 call) hung at the end
  of a file.
- New EE entry 0x1d18f8 (indirect target in the macroblock decoder).

## GS, VIF, VU (2026-11-19, fourth session)
Files: `gs_mem.c` (swizzle), `gs.c` (front end), `gs_gl.c` (GPU back end),
`vif.c`, `vu.c`, `gs.h`. `stubs.c` is empty now.
- `gs_mem.c`: all storage layouts (CT32/24/16/16S, T8, T4, T8H/T4HL/T4HH,
  Z32/24/16/16S). Checked against the reference's address functions with a
  scratch harness: 0 mismatches over 4 base pointers x 4 widths x 256 lines.
  T8/T4 columns are the CT32 column pattern with every other row pair
  rotated by 4 (derived, not a copied table).
- `gs.c`: GIF PACKED/REGLIST/IMAGE per path (1 XGKICK, 2 VIF DIRECT, 3 DMA),
  all drawing registers, vertex queue for every primitive (sprites become 2
  triangles, points 1x1 quads, flat shading done on the CPU), host->local
  and local->local transfers, CLUT loads (CSM1/CSM2, CLD modes), SIGNAL/FINISH
  interrupts, display from DISPFB/DISPLAY/PMODE/SMODE2 (field mode halves the
  height; the game runs 640x224 fields).
- `gs_gl.c` (meets the "Renderer requirement" below): render targets are
  RGBA8 FBOs of FBW*64 x 1024 GS pixels at `--scale`, Z is DEPTH32F written
  from the shader; batches merge until the draw state changes; the shader
  does texelFetch with GS wrap modes (incl. region clamp/repeat), bilinear by
  hand, TFX/TCC, fog, alpha test (2 passes for AFAIL), and builds the GS blend
  with dual-source blending. Local memory stays the truth: uploads are mirrored
  into overlapping targets of the same layout, readers of memory a dirty target
  covers download it first, textures that are a target are sampled from it.
  Decoded textures are cached on TEX0/CLUT/TEXA + per-page write generations.
  Not done: DATE, dithering, Ad as blend factor (taken as 1.0), blend factors
  above 1.0 on the destination side, local->host transfers, Z buffer
  readback. GS_FEATURES=1 counts their use at exit: over the whole test route
  the game uses none of them (2026-11-21). COLCLAMP wrap and FBMSK bits inside
  a channel are done (see "Shadows").
- `vif.c`: every VIF command; UNPACK with cycle (skip and fill), mask,
  row/col, add modes, FLG/TOPS; BASE/OFFSET double buffering; MPG; DIRECT.
  **i-bit interrupts matter**: the game's VIF1 handler (0x107668) reads
  VIF1_MARK/VIF1_CODE, builds the movie's GIF chain (path 3) and writes the
  movie quad into the VIF stream, then resumes with FBRST.STC. So the VIF
  stalls at the i-bit, keeps the rest of the quadword, and the DMA (hw.c)
  keeps its state in MADR/QWC/TADR and continues from `dma_resume()`.
  Without the stall the movie quad had position -0.5 and Z = FLT_MAX.
- `vu.c`: VU0/VU1 micro mode interpreter (VU0 shares the COP2 registers).
  Upper result committed after the lower op; one branch delay slot; E bit ends
  after the next pair; Q/P land after their latency unless WAITQ/WAITP;
  MAC/status/clip flags without delay; XGKICK feeds path 1 at once. VU1 code
  is a jump table at 0 (`b target` + `iaddiu vi13` in the delay slot).
- Movie brightness (settled 2026-11-20, game behaviour, not ours): the movie
  quad's colour is 0x40 with alpha 0x7f, MODULATE, so the movie shows at half
  the decoded brightness. Traced with the EE write watch: the draw function
  fn_00104c68 builds vertex colours as model byte >> ctx[52] (context at
  0x25cc68, shift set by fn_001040d0: 1 unless the caller passes flag bit 4,
  which the movie player does not), and the movie source colour is 0x80,
  alpha 0xff -> 0x40 / 0x7f. All of that is the game's own code and data;
  our MODULATE (Cf * Ct >> 7) matches the GS manual, so a real PS2 shows the
  same. Nothing to fix.

## Pad (2026-11-19, fifth session) — works, menus and a level reached
`runtime/pad.c` is the IOP side of padman (sids 0x80000100/0x80000101) at
RPC level; the game's own EE libpad (xpad flavour, 2200, at 0x1d8c78..)
runs unchanged. padPortOpen (cmd 1) gives a 256-byte area: two 128-byte
frames; every vblank `pad_vsync()` writes the next one with a bigger frame
counter (+0x58) and the EE (getDmaStr 0x1d92a8) reads the newer. Offsets are
in the comment at the top of pad.c, taken from the game's padRead/
padGetState/padInfoMode/padInfoAct/padInfoComb. Port 0 is a DualShock 2
(mode 0x73, 0x79 with pressure after setButtonInfo); port 1 is disconnected.
So far the game only sends cmds 0x12, 0x10, 1 — it never set the main mode.
- Keyboard (window focused): arrows = D-pad, Enter = Start, Backspace /
  RShift = Select, K or Space = X, J = Square, L = Circle, I = Triangle,
  Q/E = L1/R1, 1/3 = L2/R2, Z/C = L3/R3, WASD = left stick, numpad 8462 =
  right stick. XInput pad 0 maps the usual way (A = X, B = Circle, X =
  Square, Y = Triangle, triggers = L2/R2).
- `PAD_SCRIPT="frame:buttons,..."` holds buttons from a frame until the next
  entry (`start`, `x`, `up+x`, `-` for none) for headless runs; `--log-pad`
  logs every change and every pad RPC.
- Route that works headless (turbo, frames are vblanks): `1000:start` skips
  the intro (main menu ~2550), then X at 2600/3000/3400/4000/4400/4800/
  5200/5600 goes ProQuest -> rider -> bike -> modifiers -> Woodward Camp ->
  loading -> instructions -> Rookie challenge panel over the 3D level
  (~5800; display drops to 512x224 in game); X at 7000/7300/7600 starts
  the run, then `7900:up` rides.
- Going this far needed 15 new `extra_ee.txt` entries (20 in all) (iterate.sh with
  PAD_SCRIPT exported).

## Performance (2026-11-19, sixth session): level 22 -> 68 fps turbo, 60 real time
Measured with `--log-gs 1` (host fps every 60 frames) on the scripted route
(NOTES "Pad"), frames 7740-8340 in Woodward Camp. Per frame there: ~1.2M VU1
instruction pairs, ~760 VU1 runs, ~280 GL batches, ~18k prims.
- Profiler: `PROF=<file> [PROF_FROM=frame]` (runtime/prof.c) samples the main
  thread's RIP at ~1 kHz; `python -I tools/prof.py build/bmx2.exe <file> [N]`
  groups by source file / function, and by DLL for samples outside the exe.
  `FT_FROM=<frame>` adds cycle shares for GL texture/state/draw/present to the
  exit stats. `LOG_GS_FROM=<frame> [LOG_GS_LEVEL=n]` turns GS logging on late.
- What it was, in order of gain:
  1. `getenv()` on every XGKICK (vu_dump) - 40% of level time. Cached. Never
     call getenv on a hot path.
  2. VU1 interpreter (~45%) -> static recompile, see below.
  3. Render-target write-backs: whole 512x224 target read back and written
     pixel by pixel ~20x a frame. Now only the page rows a reader touches
     (`clean` mask per target, `gs_write_row32`), batches wholly outside the
     scissor are dropped before texture lookup, and texture decodes reuse a
     write-back from earlier in the same frame (`sync_for_texture`; exact
     with `GS_EXACT_SYNC=1`). That last one is an approximation made for the
     TBP 0 textures (since explained: mipmapping, see "Mipmapping")
  4. Frame pacer: no `timeBeginPeriod(1)` (Sleep overslept) and a late frame
     reset the schedule. Real time was 53-57 fps, now 59.9.
- GL calls themselves were ~2% (uniforms are cached now and vertices go to a
  16 MB ring, neither changed fps measurably).
- Left over (turbo): compiled VU1 37%, vif_word 11%, ntdll 9%, io_read32 6%,
  gs_read_pixel (texture decode) 6%.

## In-game stutter (fixed 2026-11-19, ninth session)
User report: picture and music stutter in play. Measured with `--log-frames`
(each frame over 17 ms; the exit line "frames: N timed, ... over 17 ms"
counts them, work time only, without the pacer's wait). Woodward Camp,
real time: ~820 slow frames (20-22 ms, max 42) -> 72 (max 21); turbo:
490 -> 29; level average 66 -> 119 fps turbo; audio underruns only at
loads now. Causes, in order of effect:
1. The once-per-frame synchronous write-back for TBP 0 textures (see
   Performance 3) made the CPU wait for the GPU every frame. Now
   asynchronous: sync_for_texture records the rows, present() reads them
   back into a PBO (2 per target, every 2nd frame) and a capture at least 2
   frames old is copied into local memory at the next texture read. Those
   textures therefore show the frame buffer 2-4 frames late. Exact:
   `GS_EXACT_SYNC=1`; the old synchronous version: `GS_SYNC_PER_FRAME=1`.
2. WaitVSync (0x1de520) spins on INTC_STAT. hw.c io_read32 now jumps to the
   next scheduled event after 4 identical reads of a status register within
   256 cycles (timers and IPU excluded). Skips ~108 of 140 s of emulated time
   on the route; exit line "hw: N poll loops skipped ahead".
3. VU1 flag liveness (recomp_vu.py flag_liveness): of 302 MAC/status updates
   in the reachable code only 20 can be read (FMAND, FSAND mask 2), the rest
   skip set_flags. VU_CHECK no longer compares MAC/status (vi16/vi17); 0
   mismatches over 3.67M runs.
Left: ~70 frames of 18-21 ms in the level, and single long frames at loads.

## Graphics thread + vsync (2026-11-19, tenth session)
User: still stutter; asked to sync to the display and to move work off the
main thread. Measured (real time, window on the 60 Hz Dell, route to frame
9400): GPU 3D engine 8-10% busy, CPU one core full. Presentation gaps over
20 ms after frame 6600 (frames shown twice): 447 before, 26 now. EE slow
frames 125 -> 40. No audio underruns in the level either way.
- Vsync (gs_gl.c choose_vsync): at a 60/120/180/240 Hz monitor the swap
  interval is refresh/60 and the timer paces 60.00 Hz instead of 59.94 (the
  swap alone does not hold the rate: in a window the compositor followed the
  120 Hz primary). Off: `vsync = 0` in bmx2.ini or NO_VSYNC=1. Audio: the
  waveOut thread skips 1 frame in 256 while more than ~64 ms is queued
  (exit line "frames dropped for drift").
- Graphics thread (runtime/gsthread.c): VIF1, VU1, the GS front end and all
  GL run on a worker. The EE copies VIF1 DMA data and GIF path 3 data into a
  64 MB ring; a scan-only VIF1 (vif.c unit 2) on the EE follows the stream for
  i-bit stalls/interrupts and VIF1 register reads; the worker's VIF1 ignores i
  bits. VU1 starts from CTC2 vi31 are queued. PRESENT carries a copy of the GS
  privileged registers. SIGNAL/FINISH are posted and applied to CSR in
  ee_event / on CSR reads (poll-skip leaves CSR alone while the worker is
  busy). The EE waits when more than 2 frames are queued and drains the
  worker before the exit stats. Off: `gs_thread = 0` or GS_THREAD=0.
- Not covered: EE writes to VU1 memory through the 0x11008000/0x1100c000
  mapping would race with the worker (the game has no constant references to
  them); GS -> EE downloads are not implemented at all. VU_CHECK and the
  VU1 recompile run on the worker unchanged.
- Exit lines: "gst: N commands, ... waits for frames", "gs: N presents, X
  gaps over 20 ms (Y after frame 6600 ...)".

## VU1 static recompile (2026-11-19, sixth session)
The game loads one VU1 program (hash 67ff695f7ff5f9a4) at boot and keeps it
through intro, menus and Woodward Camp.
- `VU_RECORD=<dir>` writes every new VU1 code snapshot as vu1_<hash>.bin and
  the entry pcs used as vu1_<hash>.pcs (code changes are seen through MPG
  writes in vif.c; EE writes to the 0x11008000 mapping are not tracked).
- `python -I tools/recomp_vu.py gen_vu/vu1_rec.h gen_vu/vu1_*.bin` generates
  one function per snapshot from the pairs reachable from the entries (plus
  pc+16 after BAL/JALR). Each pair calls vu.c's upper()/lower()/upper_commit()
  with constant words; they are always_inline, so the decode folds away and
  the behaviour is the interpreter's by construction. vu.c includes the
  header; compiling vu.c takes ~4 minutes. build.sh rebuilds vu.o when the
  header changes.
- A jump to a pair that was not generated logs "jumped to XXXX, not
  generated" and continues in the interpreter: add the pc to the .pcs file and
  regenerate. Six computed-jump targets were added that way.
- `VU_CHECK=1` runs the interpreter on a copy first and compares registers,
  flags, Q/P state, tpc and data memory after every run: 3.6M runs, 0
  mismatches to frame 9400. `VU_INTERP=1` uses the interpreter only.
- A new snapshot (another level may load other code) runs interpreted and logs
  "not recompiled, interpreting"; record it and regenerate.

## Missing code in play (2026-11-19)
The first hand play-test died at once: the main menu's CheatSniffer callback
(0x1adf60) was never reached by the scripted runs. Menu callbacks are
registered as code-built constants (lui + addiu a1), so the recompiler does
not see them. A scan of every lui/addiu|ori constant that lands on a
function start (`addiu sp,sp,-N`) or right after a function end (`jr ra`/`j`
+ delay slot) found 47 more; all are in extra_ee.txt (70 entries now), plus
three found by poking every main-menu item with PAD_SCRIPT + iterate.sh. In
a windowed run, reaching missing code now shows a message box (main.c
missing_code) instead of the window just vanishing; the address still goes
to disc\missing_entries.txt. Expect more in screens not visited yet.
- 0x19013c and 0x14e45c (user play-tests) were switch cases, not functions:
  recomp_ee.py find_jump_table missed a table base loaded far up the
  function, tables with no bound check, and at 0x14e3e4 took an unrelated
  loop's `sltiu` (bound 2) for a 249-case table. The bound now has to test the
  register that is shifted into the table offset; without one the table is
  counted from its words (up to 256). `gen/unresolved_jr.txt` lists any jr
  still unresolved (0 now). A launcher-built game logs to game\bmx2.log and
  writes game\missing_entries.txt.

## Audio (2026-11-19, eighth session) — works, confirmed by ear by the user
- `runtime/spu2.c`: mixes in emulated time (48 kHz from ee.cycles, at every
  vblank and on every libsd call) into a ring; a waveOut thread plays it
  (8 variable-length buffers, silence only when about to run dry). No device
  in --turbo or with `--no-audio`. `SPU_WAV=<file>` writes everything mixed
  (works in turbo); `--log-spu 1|2` logs switches / every param.
- Movies: SDRDRV stays an RPC-level HLE in sif.c (sid 0x80000701); its
  BlockTrans now plays the IOP loop buffer (512-byte L/R blocks) and
  BlockTransStatus reports the real play position.
- ZAUDIO.IRX runs recompiled at 0xb0000 (gen_iop/iop_zaudio.c, sid 0x47 is
  LLE; `ZAUDIO_HLE=1` brings back the old stub). LIBSD.IRX is not run:
  `libsd_N` imports are HLE in iop.c over spu2.c. Ordinals from LIBSD.IRX's
  export table: 4 Init, 5 SetParam, 6 GetParam, 7 SetSwitch, 8 GetSwitch,
  9 SetAddr, 10 GetAddr, 11 SetCoreAttr, 17 VoiceTrans, 18 BlockTrans,
  19 VoiceTransStatus, 20 BlockTransStatus. Entry = core bit 0, voice bits
  1-5, register bits 8-15 (0 VOLL 1 VOLR 2 PITCH 3 ADSR1 4 ADSR2 5 ENVX 9/a
  MVOL; switches 13 PMON 14 NON 15 KON 16 KOFF 17 ENDX 18-1b VMIX; addr 20 SSA
  21 LSA 22 NAX). ZAUDIO never writes VMIX: spu2_reset routes all voices dry.
- ZAUDIO's tick: timrman hardware timer, 16666 us (USec2SysClock), handler
  ZAUDIO+0x4150 does iSignalSema and returns the next compare. iop.c
  run_timers() calls it from iop_run like an interrupt (own stack, 8 EE
  cycles per 36.864 MHz tick).
- Voice model: ADPCM with loop flags, 4.12 pitch, linear interpolation, ADSR
  as on the PS1/PS2 SPU, fixed volumes. Not modelled: reverb (effect sends),
  noise, pitch modulation, volume sweeps (logged as "volume reads in sweep
  mode"), SPU IRQ. Check by ear against the real game.
- Two IOP fixes this needed: the EE-side IOP heap (sif.c, sid 0x80000003)
  and iop.c's thread stacks both started at 0x100000 (now 0x180000 and
  0x100000-0x17ffff), and the RPC request queue was shared by all server
  threads, so ZAUDIO's thread ran ZCDDVD requests with ZAUDIO's gp; each
  sceSifRpcLoop now takes only requests for servers on its own queue.
- Underruns: three bursts in the first 1500 frames, at single slow frames
  (movie start / loads at frames ~140, ~388, ~1424), none in steady play.

## Memory card (2026-11-19, eleventh session) — save and load work (user: Options save and the save after a complete run both work)
`runtime/mc.c`: HLE MCSERV (sid 0x80000400) over host files; the game's own
EE libmc (SCE 2200, old v1 protocol) runs unchanged, MCMAN/MCSERV are not.
Card 1 = `memcard\mc0\` in the run folder (disc\ for build\bmx2.exe,
game\ for the launcher's build, which a rebuild never deletes); every card
directory/file is a host one. Slot 2 is empty (GetInfo -10).
- Request layouts and fn numbers are in the comment at the top of mc.c (from
  libmc at 0x1e5cd0..0x1e7338). Read writes straight into the EE buffer and
  zeroes the head/tail counts the end callback (0x1e62d0) would copy; Write
  takes the head bytes from the request and the body from EE RAM.
- Checked: Options -> Save Game -> slot 1 -> Save writes
  BASLUS-20159BMX2GAME\ (BMX2SAVE.DAT 24704 B, bmxicon.ico, icon.sys,
  BASLUS-20159BMX2GAME) and shows "SAVE COMPLETE"; after a reboot Load Game
  shows "LOAD COMPLETE". The game also opens BMX2PARK.DAT / BMX2RPLY.DAT
  (park editor, replays) at boot. `--log-mc` logs every call.
- Not done: SetFileInfo only renames; free space is a fixed 7000 clusters;
  no PS1 cards, no real .ps2 card image (a folder, not an 8 MB file).

## Coverage crawls (2026-11-20)
PAD_SCRIPT now takes 4096 events (pad.c). Scripted crawls with
tools/iterate.sh found no missing code:
- Freeride in Woodward Camp, ~1000 random trick/direction presses over 6000
  frames while riding (tricks fired: Rocket Air, X-Up, Turndown, combos).
- Park Editor, ~120 random presses over 4800 frames (place, rotate, copy).
On a fresh card only Woodward Camp is open; the other 5 levels (Trainyards,
Swamp Trails, Commercial District, Galloon Water Park, Hwy 47 Cloverleaf)
say "play more to unlock" and were not crawled.

## Menu-mode crawls (2026-11-21)
Main menu order: ProQuest, Session, Freeride, Park Editor, Options, Cool
Stuff, Multiplayer (greyed: needs a second pad; pad.c reports port 1 as
empty). Crawls of 14000 turbo frames each (boot, down N, X a few times, then
random riding or menu presses), run from separate folders: no missing code.
- ProQuest (Woodward Camp): instructions, riding, pause menu, records.
- Session: riding, pause menu.
- Options: controller setup, Save Game ("SAVE COMPLETE"), overwrite prompt.
- Cool Stuff: level records, movie list (a movie plays), Load Replay slots.
- ProQuest on the other 7 levels (cheat 7 first, ProQuest = 5x Up from
  Cool Stuff, X x4, k x Right on level select): Trainyards, Swamp Trails,
  Commercial District, Galloon Water Park, Hwy 47 Cloverleaf, Devil's Peak
  and the 8th level all load and ride; a pro challenge screen (Rick
  Moliterno) appears. No missing code.
The only odd log line in every run: "unhandled syscall 0x6b" once at boot
(pc 001de374), harmless so far.

## Mipmapping, and the TBP 0 textures explained (2026-11-20)
The TBP 0 textures were not a bug in the game or in texture upload. The
VIF1 interrupt handler (vif1_intc_handler 0x107668) allocates VRAM and
uploads a texture's mip levels lazily, from the level of detail the draw
asks for (VIF1_CODE & 0xf) down; for distant objects level 0 is never
uploaded, so TEX0's TBP (level 0) stays 0, while MIPTBP1/2 hold the real
levels. All 299 such batches in a sampled frame: MXL 2, MMIN 5 (trilinear),
LCM 0, L 0, K -4.25. The renderer had no mipmapping and always sampled level
0, i.e. frame buffer 0. Found with a debug write watch (see below) on the
texture object (TEX0 at +1304, level records of 160 bytes from +16, VRAM
address at +8 of each; allocator fn_00106ea8 state at 0x25cd20; level free
fn_00107278 on level load).
- gs.c build_state now reads TEX1 MXL/LCM/L/K and MIPTBP1/2 (regs 0x34-0x37).
- gs_gl.c: the fragment shader computes the GS LOD per pixel
  ((log2(1/|Q|) << L) + K, or K with LCM=1), clamps to MXL and samples by
  MMIN (2..5 = X_MIPMAP_Y: X within a level, Y between). Levels 1..6 are
  decoded from memory onto texture units 1..6. A batch whose vertices all have
  LOD >= 1 does not decode level 0 at all (Q is linear in screen space, so the
  largest |Q| is at a vertex).
- Result: texture decodes on the route 55k -> 4-6k, read-backs ~20/frame ->
  275 page rows per run, so texture write-back is exact again by default.
  GS_ASYNC_TEX_SYNC=1 (launcher Debug "Approximate texture write-back") keeps
  the 2-4 frame old PBO variant; GS_SYNC_PER_FRAME=1 the once-per-frame one.
  The old `exact_gs_sync` ini key does nothing now. Real time in the level:
  33 frames shown twice (26 with the approximation), no underruns.
- Debug write watch: build with `-DEE_WATCH -DEE_TRACE` (e.g. -O1 into a
  scratch obj dir, ~75 s) and run with `EE_WATCH=<hex addr>[:hex len]`; each
  EE store into the range logs frame, value and the last 3 function entries
  (main.c ee_watch_hit). Use GS_THREAD=0 with it.

## Levels and cheats (2026-11-21)
The main menu's CheatSniffer (fn_001adf60) matches key strings: each D-pad /
Square press appends a digit (1 Up, 2 Down, 3 Left, 4 Right, 5 Square) to a
32-char ring at 0x246568; the 10 codes are pointed to from 0x246540, their
effects in the jump table at 0x2509c0. Rider profiles: 17 x 968 bytes at
0x2174a8; +388 + 68*k bit 0 = level k unlocked (8 levels).
- Code 7, 13241134125 = Up Left Down Right Up Up Left Right Up Down Square,
  sets every rider's level bits (checked in an EE dump: 0,0,1,0,... ->
  all 1). Code 8 (16 presses, 1423441234134425) sets much more (looks like
  "everything"). The others were not identified.
- With code 7, Freeride crawls (tools: PAD_SCRIPT + iterate.sh, ~6000 frames
  of random tricks each) of Trainyards, Swamp Trails, Commercial District,
  Galloon Water Park and Hwy 47 Cloverleaf all loaded and rode with no
  missing code. After the cheat the cursor is on Cool Stuff (Freeride = 3x Up).

## Frames shown twice in boot / logos (fixed 2026-11-21)
388 of the first 1200 frames reached the screen more than 20 ms apart, every
4th frame during the 15 fps logo movies. Not the graphics thread (presents
started <0.1 ms after queueing, took <0.3 ms) and not vsync: the EE queued
PRESENT at the end of the frame's work, before pace() waited, so screen times
followed the work time, which jumps ~4 ms on frames that decode a movie
picture. kernel.c ee_event now calls pace() first, then gs_vsync() and
pad_vsync(): 388 -> 7 (loads), whole route 42, none in the level.
--log-frames also logs "present gap" lines; PRESENT_LOG_ALL=1 logs every
present's queue latency. PROF_GS=1 makes the profiler sample the graphics
thread. Host->local 32-bit uploads and CT32/CT24 texture decodes now go by
rows (gs_write_span32 / gs_read_span32) instead of a call per pixel.

## Volume (2026-11-21)
SPU_VOLUME=<percent> scales the mix (spu2.c); `volume = N` in bmx2.ini (launcher
Audio tab) sets it. Real-time test runs use SPU_VOLUME=50 (user request).

## Not written yet
In the GS: see "Not done" above (unused by the game). In audio: reverb,
volume sweeps, noise, pitch modulation: never set by the game (ZAUDIO or EE).

## Renderer requirement (user, 2026-11-16): use the GPU
The GS renderer is to be hardware-accelerated, not a software rasteriser:
- OpenGL 3.3 core via WGL (opengl32 is already linked; same route the PS1
  project uses for presentation). GS framebuffers/Z-buffers = FBOs, so
  internal resolution scaling (2x/4x) comes for free.
- GS primitives are batched into vertex buffers and drawn as triangles/lines;
  flush on any state change (TEX0, ALPHA, TEST, FRAME, ZBUF, SCISSOR...).
- Textures: decode from GS local memory (PSMCT32/24/16, PSMT8/4 + CLUT) into a
  GL texture cache keyed on TEX0 + CLUT hash, invalidated by writes to those
  pages (host->local transfers and render-to-texture).
- GS alpha blend ((A-B)*C+D), alpha test, DATE, fog and TEXA go in the
  fragment shader / blend state; Z test in GL depth (32-bit Z as float depth).
- Framebuffer readback (local->host) and FB-as-texture need FBO read/copy.
- VU1 microprograms and VIF/GIF unpacking stay on the CPU; only GS drawing
  and final presentation (scaling, filter, aspect) run on the GPU.

## Reference: PS2Recomp (GPL-3.0) — read only, do not copy code
Cloned at `..\ref\PS2Recomp` (commit e563698, 2026-10-23), source only, not
built. Use it to check behaviour and numbering, never paste from it (GPL-3.0
would spread to this project). Useful places:
- `ps2xIOP/src/emulator/iop_emulator.cpp` — IRX modules on a virtual IOP kernel
- `ps2xRuntime/src/lib/Kernel/Syscalls/{System,RPC}.cpp`, `Kernel/EeScheduler.cpp`
- `ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp`, `ps2_vu1_lower.cpp`, `ps2_vif1_interpreter.cpp`
- `ps2xRuntime/src/lib/gs/gs_frontend.cpp` (GS register/primitive handling;
  its backend is CPU-side, ours is to be GPU)
- `Kernel/Stubs/{MPEG,Pad,MemoryCard,CD,SIF}.cpp`

## ZCDDVD.IRX protocol (sid 0x45, EE client at 0x1fced0, state at 0x1fcec0)
Reply is a 128-byte block, word 0 = result. fn: 0 init, 1 mount check (1 = ok),
2/3 name lookup, 4 open(name[0x100]) -> {slot ptr, lsn, size}, 5 close(slot),
6/7 read {slot, ee_dest, size, flag, cb, cbarg, ...} (async, 32 KB jobs),
8 seek {slot, off, whence}, 9 tell -> {pos, size}, 10 stream read (32 KB).
File slot = {lsn, size, pos, used}, 32 slots. When the last job of a read
finishes the IOP calls back the EE RPC server sid 0x46 (EE thread entry
0x116548, callback 0x116618) with {slot, bytes, type, arg}; types 1-4.

## Launcher (built 2026-11-19, seventh session)
`..\launcher\bmx2launcher.py` (tkinter, modelled on the PS1 dmlauncher.py),
packaged by `sh ../launcher/build_exe.sh` (PyInstaller) to
`Dave Mirra PS2\Dave Mirra 2 Launcher.exe`. Root = the folder holding
`Dave Mirra 2\` / `bmx2recomp\`. CLI: `python -I launcher/bmx2launcher.py
status|download|update|build|play|update-launcher [--disc FILE] [--root DIR]`.
- Disc: finds a .cue/.bin/.iso in `Dave Mirra 2\`, checks SYSTEM.CNF boots
  SLUS_201.59, reads SLUS_201.59 + ZCDDVD.IRX itself (ISO 9660 root, raw
  2352 MODE1/2 or 2048 .iso) into `work\disc\`.
- Generate (keyed on image + recompilers + extra_ee.txt + vu_recipe.json):
  recomp_ee.py -> work\gen, recomp_iop.py -> work\gen_iop, VU1 snapshots
  rebuilt from the ELF by `vu_recipe.json` (offsets of the 6 pieces of the
  0x4000 code image in SLUS_201.59, sha256-checked, plus the .pcs entry list)
  -> recomp_vu.py -> work\gen_vu. So no game bytes need to ship. If a new VU
  snapshot is recorded, add it to vu_recipe.json (script in the 7th session:
  match 8-byte-aligned runs of the .bin against the ELF).
- Compile: per-file keyed objects in work\obj, build.sh's flags without -g,
  `-static`, vu.c started first. Output `game\bmx2.exe` + a copy of
  SLUS_201.59 + default `game\bmx2.ini` (never overwritten).
- Play: `bmx2.exe --image <bin/iso> [debug flags] <game dir>`, stdout/stderr
  to game\bmx2.log unless "console window" is ticked. "Close the launcher
  when the game starts" option, off by default.
- Tools: llvm-mingw 20261104 and embeddable Python 3.12.8 (same pins as the
  PS1 launcher) into tools\; `BMX2_CLANG=<clang.exe>` uses another clang.
- Project: REPO is empty (not published). A bmx2recomp folder without the
  `.downloaded-by-launcher` marker is a working copy and is never replaced.
- Runtime side: `runtime/config.c` reads bmx2.ini from the game folder
  (scale, window_size, fullscreen, aspect, filter, frame_limit, gamepad,
  key_* incl. sticks, exact_gs_sync / vu_mode via _putenv). No ini = old
  defaults. F11 / Alt+Enter toggle borderless fullscreen. `--image PATH`
  sets the disc image; cd_read also takes 2048-byte .iso images.

## Field jitter (fixed 2026-11-19, seventh session)
The whole picture bobbed by half a line every frame. The game runs field
mode (SMODE2 = 3, 640x224 fields) and moves XYOFFSET y by +8 (0.5 line) on
every other field (30976 / 30984), because a TV shows that field half a line
lower. We show each field progressively, so the offset became jitter.
`to_vertex()` in gs.c now drops the sub-line bits of XYOFFSET y in field
mode. Checked on the intro movie: the letterbox edge row alternated
12.5 / 9.6 brightness every frame before, steady 9.6 after. Frame pacing
(Sleep-based, swap interval 0) was not measured and may add judder on
high-refresh monitors.

## Load hitches (fixed 2026-11-21)
- The 300-590 ms frames at level loads (frames 5162-5170 of the test route)
  came only from `--log-sys 1`: thousands of sif/rpc log lines per frame
  while ZCDDVD reads the level. Without it the load has no long frame and no
  underrun. Do not judge frame times or audio with --log-sys on.
- The 3 frames of ~170-195 ms at each movie start (141, 389, 1063) were fiber
  switches: the game polls the IPU while the decoder fiber waits for input,
  and every poll switched into the fiber and back. ipu.c run() now resumes a
  stalled fiber only when in_fill/out_drain made progress: 196 -> 15 ms, IPU
  command counts identical.
- cd_read reads up to 64 sectors per fread and skips seeks on sequential reads.
- Full real-time route (9400 frames): worst frame 18.1 ms, 0 underruns, 0
  present gaps.
- Profiler: samples outside bmx2.exe also record the first return address
  into bmx2.exe on the stack, in <PROF>.callers (resolve with tools/prof.py).

## Shadows: colour wrap + bit masks (2026-11-21)
Riding levels draw stencil-style shadow volumes every frame into a 16-bit
512x224 buffer at FBP 0x1200: fill 0x78 where the scene is far, add 0x08
(front faces) and 0xf8 (back faces, -8 mod 256) with COLCLAMP 0 and Z test
GREATER, write 0 with FBMSK 0x80808080 (keeps bit 7 only), then subtract
the buffer from the frame ((Cd - Cs) * FIX, vertex colour 0x10). With
clamping and whole-channel masks the mask was always 0: no shadows.
gs_gl.c now sends a batch with COLCLAMP 0 or FBMSK bits inside a channel
through a merge path: copy the target into an RGBA32F texture (same depth
attachment), draw there, then a resolve pass writes (new mod 256, or
clamped) & ~FBMSK | old & FBMSK. 16-bit targets compare masks on bits 3-7.
The rider's shadow now shows (darkens the ground by 8). GS_NO_WRAP=1 restores
clamping; GS_SHOT_TARGET=1200 also shoots that buffer with GS_SHOT.
Real-time route: worst frame 17.8 ms, 0 underruns.

## Audio over SDRDRV (2026-11-21)
The EE calls libsd remotely (sid 0x80000701, fn 0x8000 + 0x10 * (ordinal - 4)).
Besides BlockTrans/Status it sends SetParam BVOLL/BVOLR (0x0f81/0x1081, core 1)
= 0x7fff before each movie and 0 after, and 5 VoiceTrans of 2 KB to SPU
0x4000 (the core 0 input buffer). sif.c now passes SetParam/GetParam/
Set/GetSwitch/Set/GetAddr/SetCoreAttr/VoiceTrans(+Status) to spu2.c (args
are read before the reply clears the buffer), and block PCM is scaled by
BVOL (plain 16-bit signed). Movie sound unchanged (RMS within 1).
ZAUDIO's libsd calls (--log-spu 2) are only VOL/PITCH/ADSR/SSA, KON/KOFF and
MVOL: no reverb, noise, sweeps or pitch modulation, so none is modelled.

## Memory card free space (2026-11-21)
GetInfo reports 8000 clusters less each file's 1 KB clusters and each
directory's entry clusters (2 entries of 512 bytes per cluster, with . and ..),
e.g. the game's save folder (4 files, 60 KB) leaves 7936. SetFileInfo flags 1/2
now set the host file's creation/modification time from the table entry;
attributes (4) are not kept. Checked 2026-11-21 with a scripted save
(Options -> Save Game -> slot 1) on an empty card, then a boot with that
save: the game only calls GetInfo, Open, Close, Read, Write and GetDir (fns
1 2 3 5 6 13). It never calls SetFileInfo, Delete or ChDir, so attributes and
file dates do not matter for this game; free space after the save is 7936
as computed.

## Launcher Download/Update test (2026-11-21)
Against the published v0.1.0 (ADHD-TISM/Dave-Mirra-2-Recomp), from empty
scratch folders with BMX2_CLANG set (the 190 MB compiler download not re-run):
- Download failed in launcher 2: the archive holds the project in
  bmx2recomp/, the launcher expected it at the top. Fixed in launcher 3
  (released in v0.1.1 as launcher 4). Launcher 2 copies get it through
  update-launcher only once a new tag (v0.1.1+) holding it is published:
  update-launcher downloads the newest tag, not main. v0.1.0's launcher
  cannot Download. Checked live after v0.1.1 went up: a launcher 2 copy ran
  update-launcher, became launcher 4, then downloaded v0.1.1.
- Peer review follow-ups (same day): the project folder is unpacked straight
  from <repo>-<ref>/bmx2recomp/ into bmx2recomp.tmp (safe_extract only=),
  folder renames retry 10 x 0.5 s (WinError 5 from virus scanners),
  replace_dir moves the old folder aside first (never half-deleted), temp
  folders and the zip are removed on failure, a damaged zip or a cut-off
  download is a clear error, and a bmx2recomp folder without the launcher
  marker that is incomplete is refused instead of replaced.
- Passed with the fix: download, build (script and packaged exe, the exe
  with its downloaded embedded Python), the built game boots to riding;
  update when current ("up to date"), update from an older tag (re-downloads,
  game/ kept), update-launcher from version 1 (replaces the .py).
- The packaged exe cannot update itself; it points to the releases page.
  Release v0.1.1 (pre-release, 2026-11-21) carries Dave-Mirra-2-Launcher.exe,
  launcher 4 built from 0c7532f (GitHub turns spaces in asset names into dots,
  so the asset uses dashes).

## Build time (2026-11-21)
The first launcher build took ~100 s on 16 cores, 98 s of it vu.c: the VU1
program was one function of 1388 inlined pairs, and clang's loop passes
(LoopRotate, LoopFullUnroll, LICM, GVN) grow faster than the function.
recomp_vu.py now emits chunks of 64 pairs (CHUNK), one function each; a jump
out of a chunk saves the pipeline state (vu_rs: next, ea, bp, bt, guard) and
returns to a dispatcher. vu.c 98 -> 8 s, all 47 files 99 -> 12 s, launcher
build 13 s. VU_CHECK=1 over 6000 frames: 1,055,681 runs, 0 mismatches; turbo
7000 frames 31.4-36.7 s vs 37.1-37.3 s before (not slower). EE translation
takes 3 s (the launcher message said a minute).

## Player 2 (2026-11-21)
pad.c now feeds port 1 slot 0 as well. bmx2.ini pad2 (launcher Gameplay tab):
gamepad2 (default) = the second XInput pad is player 2; gamepad1 = the first
XInput pad is player 2 and player 1 is the keyboard alone; off. Player 2
reads as plugged in only while its pad is connected (or PAD2_SCRIPT is
set, for headless runs); an empty XInput slot is polled once a second, as
XInputGetState on an empty slot is slow. Analog/pressure/lock mode is kept
per port. With player 2 plugged in the main menu's Multiplayer is no longer
grey.
Crawl (turbo, PAD_SCRIPT + PAD2_SCRIPT, 32000 frames): Multiplayer -> rider,
bike, modifier setup for both players, Select Game (Best Run 2 min), player
1 rides, New Record name entry (from A: Up, Left, Down = END, X), player 2
ready, rides and lands tricks on its own input, Time Up, View Replay/Exit.
No missing code.
All Select Game games crawled 2026-11-21 (turbo, 30000 frames each, both
players scripted; menu X presses must stop at frame 4600 or the last one
picks Best Run; the list has 14 entries and wraps): Best Run - 3 min, High
Five, B-M-X, Random Spot, Wipeout, Longest Grind, Highest Walltap, Big Air
Contest, Huge Combo Contest, Super Spin Contest, Furthest Jump, Longest
Manual, Longest Nose Wheelie and the 14th entry. Every one entered its game
and rode (attempt screens, tricks, name entry, Exit menus); no missing code,
0 VU1 mismatches. Player 2's own turn was seen in Best Run; in the others the
screenshots do not show which player is riding. Repeated identical shots are
the crash pose before a respawn, not a hang.

## Pad protocol fix + vibration (2026-11-21)
The game's libpad uses older padman command numbers than pad.c assumed
(found from fn 1d9008.., all at the 0x2fc180 request buffer):
1 open (+12 result, +20 IOP address of a 64-byte act buffer), 6 setMainMode
and 8 setActAlign (result +20), 10 setButtonInfo (result +16), 12 portMax,
13 slotMax, 14 close, 16 init, 18 version (+12). The button mask is read from
the pad frame (+0x79..), not by RPC. pad.c used 5/8/9/0x0b.. so the game's pad
setup (fn 112d98, per-pad records of 68 bytes at 0x260380, step at +17) gave
up at step 70 (no pressure buttons) before setActAlign; it now reaches step
99 (ready) with DualShock (+19), pressure mode (+18) and act align 00 01 ff...
Pressure-sensitive buttons are therefore on now (id 0x79); riding is
unchanged in the test route.
Vibration: padSetActDirect (fn 1d99a8) SIF-DMAs {counter, 1, 6, data[6]}
into half (counter & 1) of the act buffer; pad.c reads the newest half each
vblank, maps it with the game's align (actuator 0 small on/off, 1 large
0-255) and calls XInputSetState (left = large * 257, right = small ? max : 0)
on that player's pad, only on change; all motors stop at exit. bmx2.ini
rumble = 0 turns it off (launcher Gameplay tab). Not verified with a real
pad: in scripted crawls the game never asked for vibration. Its vibrate
entry fn 16bb80(player, motor, strength) is reached only from 3 places
(19d700, 19ea48 surface effects, 1af550) and none fired in Best Run riding;
fn 16bb80 checks the Vibration option bit (0x21c41c + 17 * player) and a
global block flag (gp-3568 = 0x25ba80).
Debug aid: EE_TRACE builds take EE_COUNT=addr[,addr..] (up to 8) and print
how often those functions were entered (direct calls only, not tail jumps).
When the game vibrates (2026-11-21, traced): fn 1907f8 runs the rider's
per-state handler from table 0x241e64 (index = state byte at rider+4080);
states 4 and 6 (grinding) run fn 19d700, which calls fn 16bb80(player, small
motor, 200) while rider+4312 (speed) > 0.03 and rider+352 bit 0 is clear.
fn 19ea48 (surface effect, jump table 0x24f440) calls it for surface id 12
only (large motor, strength speed * 1.7, at most 64). fn 1af550 buzzes once
when Vibration is switched on in the Controller menu. Nothing vibrates on
crashes, landings or plain riding. In the scripted ride the rider asked for
state 4 143 times (triangle presses), but enter fn 1941a8 refused each (no
rail), so 19d700 never ran. PAD_RUMBLE_TEST=<frame> calls fn 16bb80(0, 1,
255) at that frame: verified end to end (act blocks DMA'd every frame, large
motor 255 fading to 0 over 31 frames, then off).

## Widescreen (2026-11-21)
fn 100ad0(width, height) is the screen setup: it stores x = 1.0 and y =
(height / width) * 4/3 (the only reader of the 4:3 constant at 0x254880 =
gp - 0x7ff0) at 0x2073c0/c4; cameras copy them through fn 11dfd0(cam, x = f12,
y = f13) into cam+68/+72 when they are made (cam+56 is the FOV, a 16-bit
angle, 10012 = 55 deg). Writing 0x2073c0 later does nothing; patching the
4:3 constant only scales Y (Vert-).
tools/recomp_ee.py now has HOOKS: functions that start with ee_hook(addr)
(runtime/main.c). With bmx2.ini widescreen = 1 (launcher Video tab) the hook
on 11dfd0 multiplies x by 0.75 (Hor+: same height, 4/3 wider view) and the
picture is presented at 16:9 (auto window 1280x720). Checked in Woodward:
same subject size, more scene at both sides, nothing missing at the edges.
The 2D HUD and menus are stretched (not corrected). Changing recomp_ee.py
changes the launcher's regen key, so installs regenerate gen/ once.

## Anti-aliasing: area-filter present (2026-11-21)
MSAA was not added: the shadow volumes count layers with exact per-pixel
wrap (COLCLAMP 0 + FBMSK merge), which a multisample resolve would average,
and every target is also sampled as a texture and read back to GS memory.
Instead the present pass (smooth filter) now averages every source texel a
window pixel covers (pfs_src in gs_gl.c: footprint from derivatives, up to
4x4 bilinear taps), so scale 2-4 is real supersampling; enlarging is one
bilinear tap as before. Checked at scale 4 in a 640x480 window: smoother
edges (A/B with GS_PRESENT_BILINEAR=1). GS_SHOT_WINDOW=1 also saves the
presented window with GS_SHOT. Real time at scale 4 + widescreen: worst frame
17.2 ms, 0 underruns.

## Next step (recommended, 2026-11-21)
1. Playtest further; add missing code from any message box. Every level now
   loads and rides in scripted crawls (see "Levels and cheats").
