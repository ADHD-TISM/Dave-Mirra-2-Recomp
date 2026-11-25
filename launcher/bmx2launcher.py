#!/usr/bin/env python3
"""Dave Mirra Freestyle BMX 2 (PS2) recompilation, on Windows and Linux (x86-64):
builds the game from your own disc and starts it. RecompLauncher
(recomplauncher.json) runs it; it has no window of its own.

You need your own copy of the game (SLUS-20159, USA, version 1.00) as a
.bin/.cue, an .iso or a .chd. On Windows the build tools (a C compiler and Python for the code
generators) are downloaded into tools/, only with --accept-downloads; on Linux the
system's compiler, Python 3, SDL2 and OpenGL/EGL development files are used (nothing
but the project is downloaded). Nothing is written outside the root folder.

    Dave Mirra Freestyle BMX 2.exe --root DIR --disc=FILE prepare --accept-downloads
                                               download the tools, build the game (RecompLauncher's setup step)
    Dave Mirra Freestyle BMX 2.exe --root DIR --disc=FILE run
                                               start the game and wait until it ends; its exit code is the game's
                                               (7: the disc is missing or another game; 1: another problem)
                                               (words after run go to the game, e.g. run --frames 600)
    ... status                                 what is ready
    ... download|update|build|play|update-launcher

--root DIR keeps everything in DIR (RecompLauncher passes its data folder);
without it, RECOMPLAUNCHER_DATA when RecompLauncher set it, else the folder
this program is in. Folders under the root: tools/
(compiler and Python, downloaded), bmx2recomp/ (the project: recompilers and
runtime), work/ (files read from the disc, generated code, objects) and game/
(the built game, bmx2.ini, the memory card and the log). Updates never touch
game/, so settings and saves are kept. Started with no command, the game is
started when it is built.
"""
import errno
import hashlib
import http.client
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor

# The project's online home (GitHub "owner/name"). Empty while it is not published:
# the launcher then uses the bmx2recomp folder next to it and Update says so.
REPO = "ADHD-TISM/Dave-Mirra-2-Recomp"
LAUNCHER_VERSION = "9"

GAME_NAME = "Dave Mirra Freestyle BMX 2"
GAME_SERIAL = "SLUS-20159"
GAME_EXE = "SLUS_201.59"
IOP_MODULES = [("ZCDDVD.IRX", "zcddvd", "80000"),   # (file on the disc, name, load address) for recomp_iop.py
               ("ZAUDIO.IRX", "zaudio", "b0000")]   # audio driver (2026-11-19); runtime/iop.c links iop_mod_zaudio

# Build tools: llvm-mingw (clang + a MinGW-w64 UCRT sysroot), pinned and checked. Same as the PS1 launcher.
LLVM_NAME = "llvm-mingw-20261104-ucrt-x86_64"
LLVM_URL = "https://github.com/mstorsjo/llvm-mingw/releases/download/20261104/%s.zip" % LLVM_NAME
LLVM_SHA256 = "552191b5754c49a5a20723276a6fc56541ea1922c4c50b7b669022333fc1b40f"
LLVM_SKIP = ("aarch64-w64-mingw32/", "armv7-w64-mingw32/", "i686-w64-mingw32/", "arm64ec-w64-mingw32/")
# Python for the code generators, used only when the launcher itself is a packaged exe.
PY_URL = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip"
PY_SHA256 = "8d3f33be9eb810f23c102f08475af2854e50484b8e4e06275e937be61ce3d2fb"

FROZEN = bool(getattr(sys, "frozen", False))
WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if WIN else 0        # Popen creationflags (Windows only)
EXE_FILE = "bmx2.exe" if WIN else "bmx2"
# Linux builds with the system's compiler, Python 3, SDL2 and OpenGL/EGL headers: nothing is downloaded but the
# project. This is what to install when they are missing (the last line of a failed setup step).
LINUX_PACKAGES = ("Debian/Ubuntu: sudo apt install gcc python3 libsdl2-dev libgl-dev libegl-dev; "
                  "Fedora: sudo dnf install gcc python3 SDL2-devel mesa-libGL-devel mesa-libEGL-devel; "
                  "Arch: sudo pacman -S gcc python sdl2 mesa")
INI_FILE = "bmx2.ini"
UA = {"User-Agent": "bmx2recomp-launcher"}
MARKER = ".downloaded-by-launcher"     # in a project folder the launcher installed (and so may replace)


class Fail(Exception):
    """A step failed; the message says what to do about it."""


class DiscFail(Fail):
    """The chosen disc image is missing or not this game: exit code BAD_DISC, which RecompLauncher explains."""


class ChdFail(Fail):
    """chdread.exe is missing or failed: says nothing about which game the image is, so it is not cached."""


# ---------------------------------------------------------------- paths/config

def default_root():
    """The folder the launcher lives in, or the one above it when it sits in launcher/ or launcher/dist/."""
    here = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
    d = here
    for _ in range(3):
        if os.path.isdir(os.path.join(d, "Dave Mirra 2")) or os.path.isdir(os.path.join(d, "bmx2recomp")):
            return d
        d = os.path.dirname(d)
    return here


class Paths:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.tools = os.path.join(self.root, "tools")
        self.project = os.path.join(self.root, "bmx2recomp")
        self.work = os.path.join(self.root, "work")
        self.dl = os.path.join(self.work, "dl")
        self.discfiles = os.path.join(self.work, "disc")
        self.gen = os.path.join(self.work, "gen")
        self.gen_iop = os.path.join(self.work, "gen_iop")
        self.gen_vu = os.path.join(self.work, "gen_vu")
        self.obj = os.path.join(self.work, "obj")
        self.llvm = os.path.join(self.tools, "llvm-mingw")
        self.pydir = os.path.join(self.tools, "python")
        self.discdir = os.path.join(self.root, "Dave Mirra 2")     # where people put their game
        self.game = os.path.join(self.root, "game")
        self.exe = os.path.join(self.game, EXE_FILE)
        self.ini = os.path.join(self.game, INI_FILE)
        self.cfg = os.path.join(self.root, "launcher.json")

    @property
    def clang(self):
        """The C compiler. Windows: BMX2_CLANG (a developer's own llvm-mingw clang) or the downloaded one.
        Linux: BMX2_CC, else the system's cc, gcc or clang ("" when there is none)."""
        if not WIN:
            cc = os.environ.get("BMX2_CC")
            return cc if cc else next((shutil.which(c) for c in ("cc", "gcc", "clang") if shutil.which(c)), "")
        return os.environ.get("BMX2_CLANG") or os.path.join(self.llvm, "bin", "x86_64-w64-mingw32-clang.exe")

    @property
    def tool_python(self):
        if not WIN:      # the system's Python 3 (a packaged launcher carries no Python of its own there)
            return (shutil.which("python3") or "") if FROZEN else sys.executable
        return os.path.join(self.pydir, "python.exe") if FROZEN else sys.executable


class Config:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()   # compile_game's threads and the main thread both save
        try:
            with open(path, encoding="utf-8") as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        with self.lock:
            self.d[k] = v
            self.save()

    def save(self):
        with self.lock:
            tmp = self.path + ".tmp"
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, indent=1, sort_keys=True)
            os.replace(tmp, self.path)


# ---------------------------------------------------------------- helpers

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, dest, log, sha256=None, label=None):
    """Download url to dest (through a .part file), checking the SHA-256 if given."""
    label = label or os.path.basename(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    last = None
    for attempt in range(3):
        try:
            h = hashlib.sha256()
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got, shown = 0, -1
                while True:
                    b = r.read(1 << 18)
                    if not b:
                        break
                    f.write(b)
                    h.update(b)
                    got += len(b)
                    if total and got * 10 // total != shown:
                        shown = got * 10 // total
                        log("  %s: %d%% of %.1f MB" % (label, shown * 10, total / 1e6))
            if sha256 and h.hexdigest() != sha256:
                raise Fail("%s failed its checksum (corrupt or tampered download)" % label)
            os.replace(part, dest)
            return
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException) as e:
            last = e   # HTTPException: e.g. IncompleteRead when a chunked archive is cut off
            log("  %s: %s%s" % (label, e, ", retrying" if attempt < 2 else ""))
            time.sleep(2)
    raise Fail("could not download %s: %s. Check your internet connection." % (label, last))


def safe_extract(zpath, dest, strip=0, skip=(), only=None):
    """Unpack a zip into dest, dropping `strip` leading path parts and refusing
    any member that would land outside dest. only: keep just the members whose
    path (after dropping strip - 1 parts) starts with this folder, e.g. "bmx2recomp/"."""
    base = os.path.realpath(dest)
    os.makedirs(base, exist_ok=True)
    if only is not None:
        if strip < 1 or not only.endswith("/"):      # a real check, not an assert: kept under python -O
            raise ValueError("only= needs strip >= 1 and a folder name ending in /")
    try:
        with zipfile.ZipFile(zpath) as z:
            _extract_members(z, base, strip, skip, only)
    except (zipfile.BadZipFile, zlib.error, EOFError):
        raise Fail("the download is damaged; try again")
    except OSError as e:
        # a central directory whose offsets do not match the data makes zipfile seek
        # before the start (EINVAL); other OSErrors (disk full, access) keep their message
        if e.errno == errno.EINVAL and e.filename is None:
            raise Fail("the download is damaged; try again")
        raise


def _extract_members(z, base, strip, skip, only):
    """safe_extract's loop over the archive members."""
    for info in z.infolist():
        all_parts = [p for p in info.filename.split("/") if p]
        if only is not None and not ("/".join(all_parts[strip - 1:]) + "/").startswith(only):
            continue
        parts = all_parts[strip:]
        if not parts:
            continue
        rel = "/".join(parts)
        if any((rel + "/").startswith(s) for s in skip):
            continue
        target = os.path.realpath(os.path.join(base, *parts))
        if target != base and not target.startswith(base + os.sep):
            raise Fail("unsafe path in archive: %s" % info.filename)
        if info.is_dir() or info.filename.endswith("/"):
            os.makedirs(target, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with z.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out, 1 << 20)


def rename_dir(src, dst):
    """os.replace for a folder, retried: on Windows a virus scanner holding a
    just-written file open makes the rename fail for a moment (WinError 5)."""
    for attempt in range(10):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.5)


def replace_dir(tmp, final):
    """Swap tmp in for final. final is first moved aside whole, so a failure
    never leaves it half deleted (with its launcher marker gone)."""
    old = final + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(old):
        raise Fail("%s is left from an earlier update and cannot be deleted (a file in it is open?). "
                   "Close other programs or delete it, then try again." % old)
    moved = False
    if os.path.isdir(final):
        rename_dir(final, old)
        moved = True
    try:
        rename_dir(tmp, final)
    except OSError:
        if moved and not os.path.exists(final):
            rename_dir(old, final)     # put the old one back
        raise
    shutil.rmtree(old, ignore_errors=True)


def run(cmd, log, cwd=None, env=None, tag=""):
    """Run a command, streaming its output to log. Returns the output text."""
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=NO_WINDOW, text=True, errors="replace")
    out = []
    for line in p.stdout:
        out.append(line)
        if tag:
            log(tag + line.rstrip())
    p.wait()
    text = "".join(out)
    if p.returncode != 0:
        raise Fail("%s failed (exit %d)\n%s" % (os.path.basename(cmd[0]), p.returncode, text[-2000:]))
    return text


def key_of(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def file_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def source_bytes(path):
    """A source file's bytes, plus the libchdr files it includes: all of the tree for third_party/libchdr_all.c,
    the headers for runtime/chd_disc.c (so a new libchdr also rebuilds the code that reads its header struct)."""
    data = file_bytes(path)
    name, here = os.path.basename(path), os.path.dirname(path)
    top = (os.path.join(here, "libchdr") if name == "libchdr_all.c" else
           os.path.join(here, "..", "third_party", "libchdr", "include") if name == "chd_disc.c" else None)
    if top and os.path.isdir(top):
        for dirpath, dirs, files in os.walk(top):
            dirs.sort()
            for n in sorted(files):
                p = os.path.join(dirpath, n)
                data += os.path.relpath(p, top).replace(os.sep, "/").encode() + b"\0" + file_bytes(p)
    return data


# ---------------------------------------------------------------- download/update

def version_tuple(tag):
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", tag or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def latest_tag(log, strict=False):
    """Newest vX.Y.Z tag of the project, or None (no tags, not published, or GitHub not reachable)."""
    if not REPO:
        return None
    try:
        req = urllib.request.Request("https://api.github.com/repos/%s/tags?per_page=100" % REPO, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            tags = [t["name"] for t in json.load(r)]
    except (urllib.error.URLError, OSError, ValueError, TimeoutError, http.client.HTTPException) as e:
        if strict:
            raise Fail("could not look up the newest version (%s). Try again in a few minutes." % e)
        log("could not look up the newest version: %s" % e)
        return None
    tags = [t for t in tags if version_tuple(t)]
    return max(tags, key=version_tuple) if tags else None


TOOL_MARK = "bmx2-tools-version.txt"     # in tools/llvm-mingw and tools/python: which pinned version is there
# the only versions pinned before the marks existed (v0.2.1 and older): an unmarked install of them is kept
UNMARKED = {"llvm": "llvm-mingw-20261104-ucrt-x86_64", "python": "python-3.12.8-embed-amd64"}
PY_NAME = PY_URL.rsplit("/", 1)[1][:-len(".zip")]     # python-3.12.8-embed-amd64


def _tool_current(folder, tool_file, kind, want):
    """True when tool_file is there and folder's mark names want. An unmarked folder from before the marks
    counts as the version those launchers pinned, and gets its mark."""
    if not os.path.isfile(tool_file):
        return False
    mark = os.path.join(folder, TOOL_MARK)
    try:
        with open(mark, encoding="utf-8") as f:
            return f.read().strip() == want
    except OSError:
        pass
    if UNMARKED[kind] != want:
        return False
    try:
        with open(mark, "w", encoding="utf-8") as f:
            f.write(want + "\n")
    except OSError:
        pass
    return True


def _mark_tool(folder, name):
    with open(os.path.join(folder, TOOL_MARK), "w", encoding="utf-8") as f:
        f.write(name + "\n")


_sdl2_flags = {}


def sdl2_flags(kind):
    """Linux: SDL2's compile ("cflags") or link ("libs") options from sdl2-config or pkg-config, or None."""
    if kind not in _sdl2_flags:
        _sdl2_flags[kind] = _sdl2_query(kind)
    return _sdl2_flags[kind]


def _sdl2_query(kind):
    for cmd in (["sdl2-config", "--" + kind], ["pkg-config", "--" + kind, "sdl2"]):
        if shutil.which(cmd[0]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True)
            except OSError:
                continue
            if r.returncode == 0:
                return r.stdout.split()
    return None


_linux_missing = {}


def linux_missing(P):
    """Linux: what the build still needs from the system, in words for the player ([] when nothing). Checked once
    per compiler: a compiler, Python 3, and SDL2, OpenGL and EGL headers (tried with the compiler's preprocessor)."""
    cc = P.clang
    if cc in _linux_missing:
        return _linux_missing[cc]
    miss = []
    if not cc:
        miss.append("a C compiler (gcc or clang)")
    if not P.tool_python:
        miss.append("Python 3")
    cflags = sdl2_flags("cflags")
    if cflags is None:
        miss.append("SDL2's development files")
    elif cc:
        src = "#include <SDL.h>\n#include <GL/gl.h>\n#include <EGL/egl.h>\n"
        try:
            r = subprocess.run([cc, "-x", "c", "-E", "-o", os.devnull, "-"] + cflags, input=src, capture_output=True,
                               text=True)
            bad = r.returncode != 0
        except OSError:
            bad = True
        if not bad:     # the headers can be there without the libraries to link (libGL.so, libEGL.so)
            exe = os.path.join(tempfile.gettempdir(), "bmx2-linktest-%d" % os.getpid())
            try:
                r = subprocess.run([cc, "-x", "c", "-", "-o", exe] + cflags + (sdl2_flags("libs") or ["-lSDL2"])
                                   + ["-lGL", "-lEGL"], input=src + "int main(void) { return 0; }\n",
                                   capture_output=True, text=True)
                bad = r.returncode != 0
            except OSError:
                bad = True
            finally:
                try:
                    os.remove(exe)
                except OSError:
                    pass
        if bad:
            miss.append("the OpenGL and EGL development files")
    _linux_missing[cc] = miss
    return miss


def compiler_current(P):
    if not WIN:
        return not linux_missing(P)
    if os.environ.get("BMX2_CLANG"):        # a developer's own compiler: theirs to keep current
        return os.path.isfile(P.clang)
    return _tool_current(P.llvm, P.clang, "llvm", LLVM_NAME)


def python_current(P):
    return not WIN or not FROZEN or _tool_current(P.pydir, P.tool_python, "python", PY_NAME)


def toolchain_ok(P):
    """The pinned compiler (and, packaged, the pinned Python) is installed: a release that pins a newer one
    makes this false, so the setup step downloads it again."""
    return compiler_current(P) and python_current(P)


def install_toolchain(P, log):
    if not WIN:     # nothing to download: the system's packages
        miss = linux_missing(P)
        if miss:
            raise Fail("Missing: %s. Install them, then run the setup again. %s" % (", ".join(miss), LINUX_PACKAGES))
        log("build tools: %s and %s" % (P.clang, P.tool_python))
        return
    if not compiler_current(P):
        z = os.path.join(P.dl, LLVM_NAME + ".zip")
        if not (os.path.isfile(z) and sha256_file(z) == LLVM_SHA256):
            log("downloading the C compiler (about 190 MB)")
            fetch(LLVM_URL, z, log, LLVM_SHA256, "compiler")
        log("unpacking the compiler")
        tmp = P.llvm + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        safe_extract(z, tmp, strip=1, skip=LLVM_SKIP)
        _mark_tool(tmp, LLVM_NAME)
        replace_dir(tmp, P.llvm)
        os.remove(z)
    else:
        log("build tools: compiler is installed")
    if not python_current(P):
        z = os.path.join(P.dl, "python-embed.zip")
        log("downloading Python for the code generators (about 11 MB)")
        fetch(PY_URL, z, log, PY_SHA256, "python")
        tmp = P.pydir + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        safe_extract(z, tmp)
        _mark_tool(tmp, PY_NAME)
        replace_dir(tmp, P.pydir)
        os.remove(z)
    if not toolchain_ok(P):
        raise Fail("the build tools did not unpack correctly; delete the tools folder and try again")


PROJECT_FILES = [os.path.join("tools", n) for n in ("recomp_ee.py", "recomp_iop.py", "recomp_vu.py")] + \
                ["extra_ee.txt", "vu_recipe.json", os.path.join("runtime", "main.c")]


def project_ok(P):
    return all(os.path.isfile(os.path.join(P.project, n)) for n in PROJECT_FILES)


def is_working_copy(P):
    """A project folder the launcher did not download (a developer's own): never replaced."""
    return project_ok(P) and not os.path.isfile(os.path.join(P.project, MARKER))


def fetch_project_zip(P, tag, log):
    ref = "refs/tags/" + tag if tag else "refs/heads/main"
    url = "https://github.com/%s/archive/%s.zip" % (REPO, ref)
    z = os.path.join(P.dl, "project-%s.zip" % (tag or "main"))
    log("downloading the project (%s)" % (tag or "main"))
    fetch(url, z, log, None, "project")
    return z


def release_tag():
    """The project version a packaged release was made with (launcher/release.sh packs it in), or None. The Linux
    release runs this file from source: its program (launcher/linux_program.sh) passes BMX2_RELEASE_TAG."""
    if not FROZEN:      # run from source: the project is whatever is installed or downloaded
        tag = os.environ.get("BMX2_RELEASE_TAG", "").strip()
        return tag if tag and version_tuple(tag) and tag.startswith("v") else None
    try:
        with open(os.path.join(getattr(sys, "_MEIPASS", ""), "release_tag.txt"), encoding="ascii") as f:
            tag = f.read().strip()
        return tag if version_tuple(tag) and tag.startswith("v") else None
    except (OSError, ValueError):
        return None


def install_project(P, C, log, force=False, want=None):
    """Download the newest project version (or the version want) unless that one is already installed."""
    if is_working_copy(P):
        log("project: using your own copy in %s (the launcher never replaces it)" % P.project)
        return "local"
    if os.path.isdir(P.project) and not os.path.isfile(os.path.join(P.project, MARKER)) and os.listdir(P.project):
        raise Fail("%s exists but is incomplete and was not made by the launcher, so it is not replaced. "
                   "Move it away, then try again." % P.project)
    if not REPO:
        if project_ok(P):
            log("project is installed; there is no online copy to update from yet")
            return C.get("tag", "local")
        raise Fail("The project is not published online yet, so it cannot be downloaded. "
                   "Put the bmx2recomp folder next to the launcher.")
    tag = want or latest_tag(log, strict=not (project_ok(P) and C.get("tag")))
    have = C.get("tag")
    if project_ok(P) and not force and have and (tag is None or tag == have):
        log("project is up to date (%s)" % have)
        return have
    z = fetch_project_zip(P, tag, log)
    tmp = P.project + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        # the repository archive is <repo>-<ref>/bmx2recomp/... next to launcher/: unpack just that folder
        safe_extract(z, tmp, strip=2, only="bmx2recomp/")
        if not all(os.path.isfile(os.path.join(tmp, n)) for n in PROJECT_FILES):
            raise Fail("the downloaded project looks wrong (files missing)")
        open(os.path.join(tmp, MARKER), "w").close()
        replace_dir(tmp, P.project)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            os.remove(z)
        except OSError:
            pass
    C.set("tag", tag or "main")
    log("project installed: %s" % (tag or "main"))
    return tag or "main"


def update_launcher(P, C, log):
    """Replace this file with the launcher from the project's newest version."""
    if not REPO:
        raise Fail("The project is not published online yet, so there is no newer launcher to get.")
    if FROZEN:
        raise Fail("This is the packaged launcher: download the new launcher from the project's releases page.")
    tag = latest_tag(log, strict=True)
    z = fetch_project_zip(P, tag, log)
    try:
        try:
            with zipfile.ZipFile(z) as zf:
                names = [n for n in zf.namelist() if n.endswith("/launcher/bmx2launcher.py")]
                if not names:
                    raise Fail("this version of the project has no launcher")
                new = zf.read(names[0])
        except (zipfile.BadZipFile, zlib.error, EOFError):
            raise Fail("the download is damaged; try again")
    finally:
        os.remove(z)
    me = os.path.abspath(__file__)
    m = re.search(rb'^LAUNCHER_VERSION = "(\d+)"', new, re.M)
    if not m:
        raise Fail("the downloaded launcher looks wrong; not replacing this one")
    if new == file_bytes(me) or int(m.group(1)) <= int(LAUNCHER_VERSION):
        log("the launcher is already the newest (version %s)" % LAUNCHER_VERSION)
        return False
    tmp = me + ".new"
    with open(tmp, "wb") as f:
        f.write(new)
    os.replace(tmp, me)
    log("launcher updated; restart it to use the new version")
    return True


# ---------------------------------------------------------------- disc image

def resolve_image(path):
    """The data file behind a .cue (or the .bin/.iso itself)."""
    if not path or not os.path.isfile(path):
        raise DiscFail("game image not found: %s" % (path or "(none chosen)"))
    if path.lower().endswith(".cue"):
        with open(path, encoding="utf-8", errors="replace") as f:
            m = re.search(r'^\s*FILE\s+"(.+?)"', f.read(), re.M | re.I)
        if not m:
            raise DiscFail("%s has no FILE line" % os.path.basename(path))
        b = os.path.join(os.path.dirname(os.path.abspath(path)), m.group(1))
        if not os.path.isfile(b):
            raise DiscFail("%s names %s, which is not next to it" % (os.path.basename(path), m.group(1)))
        return b
    return path


def image_present(path):
    """True when the image (and for a .cue, the .bin it names) is there."""
    try:
        return os.path.isfile(resolve_image(path))
    except (Fail, OSError):
        return False


CHD_MAGIC = b"MComprHD"
CHD_CHUNK = 256          # sectors per chdread call


_chd_session = []      # Linux: the Paths of open_session, where chd_tool builds chdread


def chd_tool():
    """chdread.exe (bmx2recomp/tools/chdread.c): packed into the program by build_exe.sh, or next to this file.
    Linux: work/chdread, built from the project with the system compiler the first time a .chd is read."""
    if not WIN:
        if not _chd_session:
            raise ChdFail("CHD images need the project installed (run the setup step)")
        P = _chd_session[0]
        out = os.path.join(P.work, "chdread")
        srcs = [os.path.join(P.project, *p) for p in (("tools", "chdread.c"), ("runtime", "chd_disc.c"),
                                                     ("third_party", "libchdr_all.c"))]
        if not all(os.path.isfile(s) for s in srcs):
            raise ChdFail("this project version cannot read .chd images")
        if not os.path.isfile(out) or any(os.path.getmtime(s) > os.path.getmtime(out) for s in srcs):
            if not P.clang:
                raise ChdFail("reading a .chd needs a C compiler. " + LINUX_PACKAGES)
            os.makedirs(P.work, exist_ok=True)
            r = subprocess.run([P.clang, "-O2", "-w"] + srcs + ["-o", out + ".tmp", "-lm", "-lpthread"],
                               capture_output=True, text=True)
            if r.returncode:
                raise ChdFail("could not build chdread: %s" % (r.stderr.strip()[-500:] or r.returncode))
            os.replace(out + ".tmp", out)
        return out
    here = getattr(sys, "_MEIPASS", None) if FROZEN else os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here or "", "chdread.exe")
    if not os.path.isfile(p):
        raise ChdFail("CHD images need chdread.exe next to the launcher (launcher/build_exe.sh builds it)")
    return p


def is_chd(path):
    try:
        with open(path, "rb") as f:
            return f.read(8) == CHD_MAGIC
    except OSError:
        return False


class Image:
    """Reads files by path (subfolders included) from a raw 2352-byte-sector .bin, a 2048-byte-sector .iso,
    or a .chd (through chdread.exe, since Python cannot decode CHD hunks)."""
    def __init__(self, path):
        self.path = resolve_image(path)
        self.chd = is_chd(self.path)
        self.f = None
        if self.chd:
            out = self._chdread("info", self.path).decode("ascii", "replace")
            m = re.match(r"sectors (\d+)", out)
            if not m:
                raise ChdFail("%s: unexpected answer from chdread: %s" % (os.path.basename(self.path), out.strip()))
            self.nsect, self.cache = int(m.group(1)), {}
            return
        n = os.path.getsize(self.path)
        if n % 2352 == 0:
            self.ss = 2352
        elif n % 2048 == 0:
            self.ss = 2048
        else:
            raise DiscFail("%s is not a disc image (its size fits neither .bin nor .iso sectors)" % os.path.basename(self.path))
        self.f = open(self.path, "rb")

    def _chdread(self, *args):
        r = subprocess.run([chd_tool()] + list(args), capture_output=True, creationflags=NO_WINDOW)
        if r.returncode:
            raise ChdFail("%s: %s" % (os.path.basename(self.path),
                                      r.stderr.decode("utf-8", "replace").strip() or "chdread failed (%d)" % r.returncode))
        return r.stdout

    def close(self):
        if self.f:
            self.f.close()

    def sector(self, lba):
        if self.chd:
            if lba >= self.nsect:
                return b"\0" * 2048
            base = lba - lba % CHD_CHUNK
            if base not in self.cache:
                n = min(CHD_CHUNK, self.nsect - base)
                data = self._chdread("read", self.path, str(base), str(n))
                if len(data) != n * 2048:
                    raise ChdFail("%s: short read from chdread" % os.path.basename(self.path))
                self.cache = {base: data}      # one chunk: reads go forward through each file
            d = self.cache[base]
            o = (lba - base) * 2048
            return d[o:o + 2048]
        self.f.seek(lba * self.ss)
        raw = self.f.read(self.ss)
        if len(raw) < self.ss:
            return b"\0" * 2048
        if self.ss == 2048:
            return raw
        return raw[24:24 + 2048] if raw[15] == 2 else raw[16:16 + 2048]

    def _dir(self, lba, size, dirs=False):
        """{NAME: (lba, size)} for the files (or, with dirs, the subfolders) of one directory."""
        if not 0 < size <= 1 << 20:
            raise Fail("%s: bad directory on the disc" % os.path.basename(self.path))
        data = b"".join(self.sector(lba + i) for i in range((size + 2047) // 2048))[:size]
        out, p = {}, 0
        while p + 34 <= len(data):
            n = data[p]
            if n == 0:
                p = (p // 2048 + 1) * 2048
                continue
            k = data[p + 32]
            name = data[p + 33:p + 33 + k].decode("ascii", "replace").split(";")[0]
            if bool(data[p + 25] & 2) == dirs and name not in ("\0", "\1"):
                out[name.upper()] = (struct.unpack_from("<I", data, p + 2)[0], struct.unpack_from("<I", data, p + 10)[0])
            p += n
        return out

    def root(self, dirs=False):
        """{NAME: (lba, size)} for the files in the root directory, or with dirs=True its subfolders."""
        pvd = self.sector(16)
        if pvd[1:6] != b"CD001":
            raise Fail("%s is not a game disc image (no ISO 9660 file system)" % os.path.basename(self.path))
        return self._dir(struct.unpack_from("<I", pvd, 158)[0], struct.unpack_from("<I", pvd, 166)[0], dirs)

    def read(self, name):
        """A file by its path, e.g. SLUS_201.59 or ASSETS/ICON.DAT."""
        parts = name.upper().split("/")
        ent = None
        if len(parts) == 1:
            ent = self.root().get(parts[0])
        else:
            d = self.root(dirs=True).get(parts[0])
            for sub in parts[1:-1]:
                d = d and self._dir(d[0], d[1], dirs=True).get(sub)
            ent = d and self._dir(d[0], d[1]).get(parts[-1])
        if not ent:
            raise Fail("%s is not on this disc: is it %s (%s)?" % (name, GAME_NAME, GAME_SERIAL))
        lba, size = ent
        return b"".join(self.sector(lba + i) for i in range((size + 2047) // 2048))[:size]


def image_fingerprint(path):
    b = resolve_image(path)
    st = os.stat(b)
    return "%s|%d|%d" % (os.path.abspath(b), st.st_size, st.st_mtime_ns)


def identify(C, path):
    """The boot file the disc's SYSTEM.CNF names (e.g. SLUS_201.59), or "" if none. Cached per image."""
    fp = image_fingerprint(path)
    cached = C.get("ident", {}).get(fp)
    if cached is None:
        im = Image(path)
        try:
            cnf = im.read("SYSTEM.CNF").decode("ascii", "replace")
            m = re.search(r"BOOT2\s*=\s*cdrom0:\\?([^;\s]+)", cnf, re.I)
            cached = m.group(1).upper() if m else ""
        except ChdFail:
            raise           # a helper problem, not "this is another disc": try again next time
        except Fail:
            cached = ""
        finally:
            im.close()
        with C.lock:
            C.d.setdefault("ident", {})[fp] = cached
            C.save()
    return cached


def check_disc(C, path):
    """Raise Fail unless path is this game."""
    have = identify(C, path)
    if have != GAME_EXE:
        raise DiscFail("this image is %s, not %s (%s)" % (("a disc that boots " + have) if have else "not a PS2 game disc",
                                                     GAME_NAME, GAME_SERIAL))


def find_disc(P, C):
    """The first image of this game in the "Dave Mirra 2" folder (or one folder inside it), or None."""
    try:
        os.makedirs(P.discdir, exist_ok=True)
        cands = {".cue": [], ".bin": [], ".iso": [], ".chd": []}
        for dirpath, dirs, files in os.walk(P.discdir):
            if os.path.relpath(dirpath, P.discdir).count(os.sep) >= 1:
                dirs[:] = []
            for n in sorted(files):
                ext = os.path.splitext(n)[1].lower()
                if ext in cands:
                    cands[ext].append(os.path.join(dirpath, n))
        for path in cands[".cue"] + cands[".bin"] + cands[".iso"] + cands[".chd"]:
            try:
                check_disc(C, path)
                return path
            except (Fail, OSError):
                continue
    except OSError:
        pass
    return None


def adopt_disc(P, C):
    """Use the image in the game folder when none that works is chosen. True if the choice changed."""
    cur = C.get("disc")
    try:
        if cur:
            check_disc(C, cur)
            return False
    except (Fail, OSError):
        pass
    found = find_disc(P, C)
    if found and os.path.abspath(found) != cur:
        C.set("disc", os.path.abspath(found))
        return True
    return False


# ---------------------------------------------------------------- generate

ICON_FILE = "ASSETS/ICON.DAT"     # the game's memory card icon: its texture becomes bmx2.exe's icon


def icon_tool(P):
    """tools/make_icon.py, or None in a project from before the icon (v0.1.8 and older)."""
    p = os.path.join(P.project, "tools", "make_icon.py")
    return p if os.path.isfile(p) else None


def gen_inputs(P):
    pr = P.project
    return [os.path.join(pr, "tools", n) for n in ("recomp_ee.py", "recomp_iop.py", "recomp_vu.py")] + \
           [os.path.join(pr, "extra_ee.txt"), os.path.join(pr, "vu_recipe.json")] + \
           ([icon_tool(P)] if icon_tool(P) else [])


def regen_key(P, disc):
    return key_of("gen1", image_fingerprint(disc), *[file_bytes(p) for p in gen_inputs(P)])


def generated_ok(P, C, disc):
    try:
        return (bool(disc) and project_ok(P) and C.get("regen_key") == regen_key(P, disc)
                and os.path.isfile(os.path.join(P.gen, "table.c"))
                and os.path.isfile(os.path.join(P.gen_vu, "vu1_rec.h"))
                and (not icon_tool(P) or os.path.isfile(os.path.join(P.gen, "bmx2.ico")))
                and all(os.path.isfile(os.path.join(P.gen_iop, "iop_%s.c" % n)) for _f, n, _a in IOP_MODULES))
    except (Fail, OSError):
        return False


def build_vu_snapshots(P, elf_dir, log):
    """Rebuild the VU1 code snapshots from the game's own files (vu_recipe.json says where each piece is)."""
    with open(os.path.join(P.project, "vu_recipe.json"), encoding="utf-8") as f:
        recipe = json.load(f)
    outs = []
    for snap in recipe["snapshots"]:
        src = file_bytes(os.path.join(elf_dir, snap["from_file"]))
        code = bytearray(snap["size"])
        for pc in snap["pieces"]:
            piece = src[pc["file"]:pc["file"] + pc["len"]]
            if len(piece) != pc["len"]:
                raise Fail("%s is shorter than expected: is the disc %s?" % (snap["from_file"], GAME_SERIAL))
            code[pc["vu"]:pc["vu"] + pc["len"]] = piece
        if hashlib.sha256(code).hexdigest() != snap["sha256"]:
            raise Fail("the VU1 program read from %s does not match: is the disc %s, version 1.00?"
                       % (snap["from_file"], GAME_SERIAL))
        base = os.path.join(P.gen_vu, "vu1_%s" % snap["hash"])
        with open(base + ".bin", "wb") as f:
            f.write(code)
        with open(base + ".pcs", "w") as f:
            f.write("\n".join(snap["pcs"]) + "\n")
        outs.append(base + ".bin")
    log("  %d VU1 program(s) rebuilt from the disc" % len(outs))
    return outs


def generate(P, C, disc, log):
    if generated_ok(P, C, disc):
        log("generated code is up to date")
        return
    if not project_ok(P):
        raise Fail("the project is missing (download)")
    check_disc(C, disc)
    key = regen_key(P, disc)
    py = P.tool_python
    tools = os.path.join(P.project, "tools")
    C.set("regen_key", None)
    for d in (P.discfiles, P.gen, P.gen_iop, P.gen_vu):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    log("reading the game files from the disc image")
    im = Image(disc)
    try:
        for name in [GAME_EXE] + [f for f, _n, _a in IOP_MODULES]:
            with open(os.path.join(P.discfiles, name), "wb") as f:
                f.write(im.read(name))
        if icon_tool(P):
            with open(os.path.join(P.discfiles, "ICON.DAT"), "wb") as f:
                f.write(im.read(ICON_FILE))
    finally:
        im.close()
    if icon_tool(P):
        log("making the game's icon")
        run([py, "-I", icon_tool(P), os.path.join(P.discfiles, "ICON.DAT"), os.path.join(P.gen, "bmx2.ico")],
            log, cwd=P.project)
    elf = os.path.join(P.discfiles, GAME_EXE)
    log("translating the game code (EE, a few seconds)")
    run([py, "-I", os.path.join(tools, "recomp_ee.py"), elf, P.gen, "--extra", os.path.join(P.project, "extra_ee.txt")],
        log, cwd=P.project)
    for fname, name, addr in IOP_MODULES:
        log("translating %s (IOP)" % fname)
        run([py, "-I", os.path.join(tools, "recomp_iop.py"), os.path.join(P.discfiles, fname), name, addr, P.gen_iop],
            log, cwd=P.project)
    log("translating the VU1 microcode")
    snaps = build_vu_snapshots(P, P.discfiles, log)
    run([py, "-I", os.path.join(tools, "recomp_vu.py"), os.path.join(P.gen_vu, "vu1_rec.h")] + snaps, log, cwd=P.project)
    C.set("regen_key", key)
    log("code translated")


# ---------------------------------------------------------------- compile

def _sources(P):
    rt = os.path.join(P.project, "runtime")
    src = [os.path.join(rt, n) for n in sorted(os.listdir(rt)) if n.endswith(".c")]
    src += [os.path.join(P.gen, n) for n in sorted(os.listdir(P.gen)) if n.endswith(".c")]
    src += [os.path.join(P.gen_iop, n) for n in sorted(os.listdir(P.gen_iop)) if n.endswith(".c")]
    chdr = os.path.join(P.project, "third_party", "libchdr_all.c")     # CHD images (v0.2.1 on)
    if os.path.isfile(chdr):
        src.append(chdr)
    hdr = []
    for d in (rt, P.gen, P.gen_vu):
        hdr += [os.path.join(d, n) for n in sorted(os.listdir(d)) if n.endswith(".h")]
    return src, hdr


def _flags(P, src):
    # the options build.sh uses, without debug info
    f = ["-O2", "-fno-strict-aliasing", "-fwrapv", "-I", os.path.join(P.project, "runtime"), "-I", P.gen, "-I", P.gen_vu]
    if os.path.dirname(src) == os.path.join(P.project, "runtime"):
        f += ["-Wall", "-Wno-unused-but-set-variable", "-Wno-unused-function"]
        if not WIN:
            f += ["-Wno-misleading-indentation"] + (sdl2_flags("cflags") or [])   # as build.sh
    else:
        f += ["-w"]
    return f


LINK = ["-static", "-Wl,--stack,67108864", "-lwinmm", "-lgdi32", "-luser32", "-lopengl32"]


def link_args():
    """The link options: Windows' LINK, or on Linux SDL2, OpenGL and EGL (as build.sh)."""
    return LINK if WIN else (sdl2_flags("libs") or ["-lSDL2"]) + ["-lGL", "-lEGL", "-lm", "-lpthread"]


def compiler_name(P):
    """What build_key records as the compiler: the pinned llvm-mingw, or on Linux the system compiler's version."""
    if WIN:
        return LLVM_NAME
    try:
        r = subprocess.run([P.clang, "--version"], capture_output=True, text=True)
        return (r.stdout.splitlines() or [""])[0]
    except OSError:
        return P.clang
RES_ARGS = ["-O", "coff"]     # windres: the icon as a COFF object the linker takes like any other


def _resources(P):
    """runtime/bmx2.rc and the files it names: the manifest (v0.2.1 on) and the icon when it was made.
    v0.1.9 to v0.2.0 have no manifest and need the icon; v0.1.8 and older have no bmx2.rc."""
    rt = os.path.join(P.project, "runtime")
    rc, man, ico = os.path.join(rt, "bmx2.rc"), os.path.join(rt, "bmx2.manifest"), os.path.join(P.gen, "bmx2.ico")
    if not WIN or not os.path.isfile(rc):      # Linux executables carry no resources
        return []
    if os.path.isfile(man):
        return [rc, man] + ([ico] if os.path.isfile(ico) else [])
    return [rc, ico] if os.path.isfile(ico) else []


def _res_args(P, res):
    """windres arguments for _resources' list (-D BMX2_ICON only where the rc tests it and the icon exists)."""
    args = ["-I", P.gen, "-I", os.path.dirname(res[0])]
    if os.path.join(P.gen, "bmx2.ico") in res and len(res) == 3:
        args.append("-DBMX2_ICON")
    return args + ["-i", res[0]] + RES_ARGS


def build_key(P):
    src, hdr = _sources(P)
    h = hashlib.sha256(b"build1")
    flags = [a for d in (os.path.join(P.project, "runtime"), P.gen) for a in _flags(P, os.path.join(d, "x.c"))
             if not os.path.isabs(a)]
    h.update(repr((link_args(), compiler_name(P), flags, RES_ARGS)).encode())   # the compile, icon and link recipe, the compiler
    for p in hdr + src + _resources(P):
        h.update(os.path.basename(p).encode())
        h.update(source_bytes(p))
    return h.hexdigest()


def built_ok(P, C):
    try:
        return (os.path.isfile(P.exe) and os.path.isfile(os.path.join(P.game, GAME_EXE))
                and os.path.isdir(P.gen) and C.get("build_key") == build_key(P))
    except OSError:
        return False


def compile_game(P, C, log, progress=None):
    if not toolchain_ok(P):
        raise Fail("the build tools are not downloaded yet (download)")
    if built_ok(P, C):
        log("game is up to date")
        return
    src, hdr = _sources(P)
    hh = hashlib.sha256(b"".join(file_bytes(p) for p in hdr)).hexdigest()
    os.makedirs(P.obj, exist_ok=True)
    keyfile = os.path.join(P.obj, "keys.json")
    try:
        with open(keyfile) as f:
            keys = json.load(f)
    except (OSError, ValueError):
        keys = {}
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(P.clang) + os.pathsep + env.get("PATH", "")
    todo, objs, newkeys = [], [], {}
    # an object is kept only from the same compiler: on Linux its path (/usr/bin/cc) stays across upgrades and
    # switches, so the version line counts there (Windows keeps the path: the pinned llvm-mingw is in it)
    cc_id = P.clang if WIN else compiler_name(P)
    for p in src:
        tag = os.path.basename(os.path.dirname(p)) + "_" + os.path.basename(p)     # runtime_main.c, gen_code_000.c
        o = os.path.join(P.obj, tag[:-2] + ".o")
        objs.append(o)
        k = key_of(hh, " ".join(_flags(P, p)), cc_id, source_bytes(p))
        newkeys[tag] = k
        if not (os.path.isfile(o) and keys.get(tag) == k):
            todo.append((tag, p, o))
    # vu.c (with the recompiled VU1 programs) and libchdr_all.c are the largest files: start them first
    todo.sort(key=lambda t: t[1].endswith((os.sep + "vu.c", os.sep + "libchdr_all.c")), reverse=True)
    log("compiling %d of %d files%s" % (len(todo), len(src), " (the first build takes about a minute)" if len(todo) > 20 else ""))
    done = [0]
    errors = []
    ok_done = {}
    lock = threading.Lock()

    def one(t):
        tag, p, o = t
        if errors:
            return
        tmp = o + ".tmp"
        try:
            run([P.clang, "-c", p, "-o", tmp] + _flags(P, p), lambda s: None, cwd=P.root, env=env)
            os.replace(tmp, o)
            ok_done[tag] = True
        except Fail as e:
            errors.append(str(e))
        with lock:
            done[0] += 1
            if progress:
                progress(done[0], len(todo))
            if done[0] % 10 == 0 or done[0] == len(todo):
                log("  %d / %d" % (done[0], len(todo)))

    if todo:
        for tag, _p, _o in todo:
            keys.pop(tag, None)
        with ThreadPoolExecutor(max_workers=max(1, os.cpu_count() or 2)) as ex:
            list(ex.map(one, todo))
        if errors:     # keep the keys of what did compile, so the next build does not redo it
            pending = set(t[0] for t in todo)
            with open(keyfile, "w") as f:
                json.dump({k: v for k, v in newkeys.items() if k not in pending or ok_done.get(k)}, f)
            raise Fail("compile error:\n" + errors[0])
    with open(keyfile, "w") as f:
        json.dump(newkeys, f)
    res = _resources(P)
    windres = os.path.join(os.path.dirname(P.clang), "x86_64-w64-mingw32-windres.exe")
    if res and not os.path.isfile(windres):
        log("no windres next to the compiler: building without the icon and the manifest")
    elif res:
        log("adding the icon and the manifest" if len(res) == 3 else "adding the manifest" if res[1].endswith(".manifest")
            else "adding the icon")
        ro = os.path.join(P.obj, "bmx2_res.o")     # a COFF object: lld would read a .res name as a raw .res file
        run([windres] + _res_args(P, res) + ["-o", ro], log, cwd=P.root, env=env)
        objs.append(ro)
    log("linking")
    os.makedirs(P.game, exist_ok=True)
    tmp = P.exe + ".new"
    run([P.clang] + objs + ["-o", tmp] + link_args(), log, cwd=P.root, env=env)
    if not os.path.isfile(P.ini):
        with open(P.ini, "w", encoding="utf-8", newline="\n") as f:
            f.write(default_ini_text())
    try:
        os.replace(tmp, P.exe)
    except OSError:
        os.remove(tmp)
        raise Fail("%s is in use: close the game and build again" % EXE_FILE)
    # the game's ELF (the runtime loads it at start) goes in last: it is the file RecompLauncher takes as "built"
    # (recomplauncher.json prepare.done), the same name on Windows and Linux (bmx2.exe / bmx2)
    elf = os.path.join(P.game, GAME_EXE)
    shutil.copyfile(os.path.join(P.discfiles, GAME_EXE), elf + ".new")
    os.replace(elf + ".new", elf)
    C.set("build_chd", any(os.path.basename(p) == "libchdr_all.c" for p in src))   # before build_key: built_ok trusts it
    C.set("build_key", build_key(P))
    log("game built: %s" % P.exe)


def build_all(P, C, disc, log, progress=None):
    if not disc:
        raise DiscFail("put your game in the \"Dave Mirra 2\" folder or choose it with --disc=FILE")
    if not toolchain_ok(P) or not project_ok(P):
        raise Fail("download the build tools first (download)")
    generate(P, C, disc, log)
    compile_game(P, C, log, progress)


# ---------------------------------------------------------------- settings (bmx2.ini)

KEYNAMES = ("up down left right enter backspace tab space lshift rshift lctrl rctrl lalt ralt "
            "comma period slash semicolon num0 num1 num2 num3 num4 num5 num6 num7 num8 num9 f1-f12 return escape shift ctrl alt "
            "none").split() + ["mouse left", "mouse right", "mouse middle", "mouse 4", "mouse 5"]   # f1-f12: F1 to F12
B01 = ["0", "1"]

# (key, tab, label, kind, choices, default, comment)
SETTINGS = [
    ("frame_limit", "Gameplay", "Run at console speed (60 fps)", "bool", B01, "1",
     "1 = the console's speed, 0 = as fast as the PC can go (for testing)"),
    ("gamepad", "Gameplay", "Use an Xbox-style gamepad", "bool", B01, "1",
     "1 = use XInput gamepads (A = cross, B = circle, X = square, Y = triangle) for player 1 and the Player 2 pad setting; 0 = keyboard only"),
    ("rumble", "Gameplay", "Gamepad vibration", "bool", B01, "1",
     "1 = the gamepad vibrates when the game asks for it (also needs Vibration: On in the game's Options > Controller)"),
    ("pad2", "Gameplay", "Player 2 pad", "choice", ["gamepad2", "gamepad1", "off"], "gamepad2",
     "Player 2 (Multiplayer): gamepad2 = second gamepad, gamepad1 = first gamepad (player 1 uses the keyboard), off. Needs gamepads on"),
    ("skip_intro", "Gameplay", "Skip intro movies", "bool", B01, "0",
     "1 = skip the start-up movies (Acclaim and Z-Axis logos still show 2 s each); movies in Cool Stuff still play"),
    ("scale", "Video", "Internal resolution", "choice", ["1", "2", "3", "4"], "2",
     "Internal 3D resolution: 1 = original PS2, 2-4 = sharper, with smoother edges (supersampled with the smooth filter; more GPU work)"),
    ("window_size", "Video", "Window size", "combo", ["auto", "640x480", "960x720", "1280x960", "1600x1200",
                                                      "1280x720", "1920x1080"], "auto",
     "Window size in pixels (WxH). auto = 1280x960 (1280x720 with widescreen), made smaller if the screen is"),
    ("vsync", "Video", "Vertical sync", "bool", B01, "1",
     "1 = show frames in step with a 60 or 120 Hz screen (smoother); 0 = timer only"),
    ("vsync_two_chip", "Video", "Vertical sync on two-chip laptops", "bool", B01, "0",
     "When another graphics chip drives the screen (most laptops with two chips): 0 = timer only (smooth, may tear), 1 = vertical sync (no tearing, may stutter). Needs Vertical sync on"),
    ("fullscreen", "Video", "Start in fullscreen", "bool", B01, "0",
     "1 = start in borderless fullscreen (F11 or Alt+Enter toggles while playing)"),
    ("widescreen", "Video", "Widescreen (16:9)", "bool", B01, "0",
     "1 = a wider 3D view shown at 16:9 (the menus and on-screen text are stretched)"),
    ("aspect", "Video", "Aspect ratio", "choice", ["4:3", "stretch"], "4:3",
     "4:3 = console shape with black bars, stretch = fill the window"),
    ("filter", "Video", "Picture filter", "choice", ["smooth", "nearest"], "smooth",
     "How the picture is enlarged to the window: smooth = blended, nearest = sharp pixels"),
    ("volume", "Audio", "Volume (%)", "choice", ["100", "75", "50", "25", "0"], "100",
     "Game sound volume in percent (music, effects and movie sound)"),
    ("gs_thread", "Debug", "Graphics on its own thread", "bool", B01, "1",
     "1 = VIF1, VU1 and drawing run on a second CPU thread (smoother); 0 = all on one thread"),
    ("async_tex_sync", "Debug", "Approximate texture write-back", "bool", B01, "0",
     "1 = textures read from GPU drawing use a copy 2-4 frames old (faster, inexact); 0 = exact"),
    ("vu_mode", "Debug", "VU1 code", "choice", ["recompiled", "interpreter", "check"], "recompiled",
     "recompiled = fast; interpreter = run VU1 microcode in the interpreter; check = run both and compare (slow)"),
]
KEYS = [("up", "up"), ("down", "down"), ("left", "left"), ("right", "right"), ("start", "enter"),
        ("select", "backspace, rshift"), ("cross", "K, space"), ("circle", "L"), ("square", "J"), ("triangle", "I"),
        ("l1", "Q"), ("r1", "E"), ("l2", "1"), ("r2", "3"), ("l3", "Z"), ("r3", "C"),
        ("lstick_up", "W"), ("lstick_down", "S"), ("lstick_left", "A"), ("lstick_right", "D"),
        ("rstick_up", "num8"), ("rstick_down", "num2"), ("rstick_left", "num4"), ("rstick_right", "num6")]
for _n, _d in KEYS:
    SETTINGS.append(("key_" + _n, "Input", "Key: " + _n.replace("_", " ").upper(), "key", None, _d, None))


def default_ini_text():
    out = ["# Dave Mirra Freestyle BMX 2 recomp settings (bmx2.ini). Delete this file to get the defaults back.",
           "# RecompLauncher's settings for the game edit it; updates never replace it.", ""]
    for key, _tab, _lab, kind, _ch, dflt, comment in SETTINGS:
        if comment:
            out.append("# " + comment)
        if key == "key_up":
            out.append("# Keyboard: a letter or digit, or " + " ".join('"%s"' % k if " " in k else k for k in KEYNAMES)
                       + "; two keys separated by a comma; no quotes (key_cross = mouse left)")
        out.append("%s = %s" % (key, dflt))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- play

def play(P, C, log, wait=False, extra=()):
    """Start the built game; with wait, stay until it ends and return its exit code. extra: arguments for bmx2.exe."""
    if not os.path.isfile(P.exe):
        raise Fail("the game is not built yet (run prepare, or build)")
    disc = C.get("disc")
    if not disc:
        raise DiscFail("no game image chosen (--disc=FILE)")
    image = resolve_image(disc)
    if is_chd(image) and not C.get("build_chd"):     # a build from v0.2.0 or older reads a .chd as raw sectors
        raise Fail("this build of the game cannot read .chd images: run the setup step again (prepare)")
    args = [P.exe, "--image", os.path.abspath(image)] + list(extra) + [P.game]
    for n in (2, 1):        # keep the logs of the last 3 runs: bmx2.log, bmx2.1.log, bmx2.2.log
        older = os.path.join(P.game, "bmx2.%d.log" % n)
        newer = os.path.join(P.game, "bmx2.log" if n == 1 else "bmx2.%d.log" % (n - 1))
        try:
            if os.path.isfile(newer):
                os.replace(newer, older)
        except OSError:
            pass
    logf = open(os.path.join(P.game, "bmx2.log"), "w")    # what the game prints, for when something goes wrong
    try:
        how = {"creationflags": NO_WINDOW} if WIN else {"preexec_fn": _end_with_parent()} if wait else {}
        proc = subprocess.Popen(args, cwd=P.game, stdout=logf, stderr=subprocess.STDOUT, **how)
    finally:
        logf.close()
    log("started the game (its messages go to %s)" % os.path.join(P.game, "bmx2.log"))
    if not wait:
        return 0
    job = end_with_us(proc) if WIN else None   # kept open while waiting: when this program is ended, Windows ends the game too
    try:
        return proc.wait()
    finally:
        if job:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(job)


def _end_with_parent():
    """Linux: a function for Popen's preexec_fn. In the game's process before it starts, it asks the kernel for
    SIGTERM when this program ends (RecompLauncher stops the program it started, which is this one), as Windows'
    job does there. Made here, before the fork; if this program already ended in between, the game does not start."""
    import ctypes
    import signal
    parent = os.getpid()
    try:
        prctl = ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):
        return None

    def child():
        prctl(1, int(signal.SIGTERM), 0, 0, 0)   # PR_SET_PDEATHSIG
        if os.getppid() != parent:
            os._exit(1)
    return child


def end_with_us(proc):
    """Put proc in a job that Windows closes, ending proc, when this program ends (RecompLauncher stops the program
    it started, which is this one). Returns the job handle, or None when that is not possible."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes",
                                                       "OtherBytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = Extended()
        info.Basic.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        h = k32.OpenProcess(0x0101, False, proc.pid)   # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        ok = (h and k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))   # extended limits
              and k32.AssignProcessToJobObject(job, h))
        if h:
            k32.CloseHandle(h)
        if not ok:
            k32.CloseHandle(job)
            return None
        return job
    except (OSError, AttributeError, ImportError):
        return None


# ---------------------------------------------------------------- status

def status(P, C):
    """(key, label, ok, command_that_fixes_it) for each requirement."""
    disc = C.get("disc")
    disc_ok = False
    try:
        if disc:
            check_disc(C, disc)
            disc_ok = True
    except (Fail, OSError):
        pass
    return [
        ("tools", "Build tools", toolchain_ok(P), "download"),
        ("project", "Project files", project_ok(P), "download"),
        ("disc", "Your game (%s)" % GAME_SERIAL, disc_ok, "--disc=FILE"),
        ("gen", "Game code generated", generated_ok(P, C, disc) if disc_ok else False, "build"),
        ("built", "Game built", built_ok(P, C) if disc_ok else os.path.isfile(P.exe), "build"),
    ]


def ready_to_play(P, C):
    st = {k: ok for k, _l, ok, _t in status(P, C)}
    return os.path.isfile(P.exe) and st["disc"]


# ---------------------------------------------------------------- command line

def open_session(root, disc=None):
    # RecompLauncher gives its data folder as RECOMPLAUNCHER_DATA too, also when the player skipped Easy Setup and
    # this program starts with no arguments: the build is there, not next to the program
    P = Paths(root or os.environ.get("RECOMPLAUNCHER_DATA") or default_root())
    _chd_session[:] = [P]       # Linux: chd_tool builds chdread under this root
    C = Config(P.cfg)
    if disc:
        # Linux reads a .chd with chdread built from the project: before the first install there is none, so
        # prepare checks the image after it has installed the project
        if WIN or project_ok(P) or not (image_present(disc) and is_chd(resolve_image(disc))):
            check_disc(C, disc)
        C.set("disc", os.path.abspath(disc))
    else:
        adopt_disc(P, C)
    return P, C


NEEDS_DOWNLOADS = 10    # prepare's exit code; the game's own codes (3, 4, 5, 6) mean something else
BAD_DISC = 7            # the disc image is missing or another game: for run, recomplauncher.json exit_codes
                        # explains it; a failed prepare shows its last error line on the setup screen


def prepare(P, C, accept, log):
    """RecompLauncher's setup step (recomplauncher.json): no window, nothing asked. Downloads the build tools and the
    project only with accept (the player ticked it on the setup screen), then builds the game from the chosen disc.
    Prints lines "progress <0 to 1> <text>". Returns 0 when the game is built (or already was), NEEDS_DOWNLOADS (10)
    when the downloads are needed but not allowed; a failure raises Fail."""
    def say(f, text):
        print("progress %.3f %s" % (min(max(f, 0.0), 1.0), text), flush=True)
    disc = C.get("disc")
    if not disc:
        raise DiscFail("prepare: no disc image given (--disc=FILE)")
    if not WIN and not toolchain_ok(P):
        install_toolchain(P, log)    # nothing to download on Linux: says which system packages are missing
    if not (toolchain_ok(P) and project_ok(P)) and not accept:
        print("the build tools and the project are not downloaded yet, and --accept-downloads was not given",
              flush=True)
        return NEEDS_DOWNLOADS
    if not toolchain_ok(P):
        say(0.01, "Downloading the C compiler")

        def download_log(s):   # fetch logs "  compiler: 40% of 190.0 MB": show it on the setup screen too
            m = re.match(r"\s*(compiler|python): (\d+)% of", s)
            if m:
                lo, span = (0.01, 0.15) if m.group(1) == "compiler" else (0.16, 0.03)   # one after the other
                say(lo + span * int(m.group(2)) / 100, "Downloading the %s (%s%%)"
                    % ("C compiler" if m.group(1) == "compiler" else "Python", m.group(2)))
            log(s)
        install_toolchain(P, download_log)
    if not project_ok(P):     # the first install: this release's version, or the newest for a build without one
        say(0.2, "Downloading the project")
        install_project(P, C, log, want=release_tag())
    elif not accept and release_tag() and release_tag() != C.get("tag") and not is_working_copy(P):
        print("this release needs project version %s (installed: %s), and --accept-downloads was not given"
              % (release_tag(), C.get("tag", "none")), flush=True)
        return NEEDS_DOWNLOADS
    elif accept:   # a packaged release builds its own project version, also when the player goes back to an older one
        want = release_tag()
        if want:
            say(0.2, "Getting project version %s" % want)
            install_project(P, C, log, want=want)
        elif os.environ.get("RECOMPLAUNCHER") == "1":
            log("no release version packed in; RecompLauncher brings the releases, so the project stays as it is")
        else:
            say(0.2, "Checking for a newer project version")
            install_project(P, C, log)
    if generated_ok(P, C, disc) and built_ok(P, C):
        say(1, "Already built")
        return 0
    say(0.25, "Translating the game's code from your disc")
    generate(P, C, disc, log)
    say(0.4, "Building the game")

    def build_log(s):
        if s == "linking":
            say(0.97, "Linking")
        log(s)
    compile_game(P, C, build_log,
                 lambda d, n: say(0.4 + 0.55 * d / max(n, 1), "Building the game (%d of %d files)" % (d, n)))
    say(1, "Ready to play")
    return 0


def parse_args(argv):
    """(root, disc, accept_downloads, the command and its words) from the command line."""
    root, disc, cmd, accept = None, None, [], False
    it = iter(argv)
    for a in it:
        if a == "--root":
            root = next(it, None)
        elif a == "--disc":
            disc = next(it, None)
        elif a.startswith("--disc="):
            disc = a[len("--disc="):]
        elif a == "--accept-downloads":
            accept = True
        else:
            cmd.append(a)
    return root, disc, accept, cmd


def cli(argv):
    root, disc, accept, cmd = parse_args(argv)
    try:
        P, C = open_session(root, disc)
    except DiscFail as e:
        print("error: %s" % e, flush=True)
        return BAD_DISC
    except (Fail, OSError) as e:
        print("error: %s" % e, flush=True)
        return 1
    log = lambda s: print(s, flush=True)
    what = cmd[0] if cmd else "status"
    try:
        if what == "status":
            print("root: %s" % P.root)
            for _k, label, ok, fix in status(P, C):
                print("%s %s%s" % ("OK " if ok else "-- ", label, "" if ok else "   (%s)" % fix))
            print("game image: %s" % C.get("disc", "none"))
        elif what == "prepare":
            return prepare(P, C, accept, log)
        elif what == "download":
            install_toolchain(P, log)
            install_project(P, C, log, want=release_tag())
        elif what == "update":
            install_project(P, C, log)
        elif what == "update-launcher":
            update_launcher(P, C, log)
        elif what == "build":
            build_all(P, C, C.get("disc"), log)
        elif what == "play":
            play(P, C, log)
        elif what == "run":            # like play, but stays until the game ends and returns its exit code;
            return play(P, C, log, wait=True, extra=cmd[1:])   # the words after it go to the game
        else:
            print(__doc__)
            return 2
    except DiscFail as e:
        print("error: %s" % e, flush=True)
        return BAD_DISC
    except (Fail, OSError) as e:
        print("error: %s" % e, flush=True)
        return 1
    return 0


def attach_std_streams():
    """The packaged program has no console, so Python gives it no stdout and stderr. When whoever started it handed
    it a pipe or a file for them (RecompLauncher reads the setup step's progress lines that way), write there;
    otherwise, as when it is started by a double click, what it prints goes nowhere."""
    if sys.stdout is not None:
        return
    streams = []
    try:
        import ctypes
        import msvcrt
        k32 = ctypes.windll.kernel32
        k32.GetStdHandle.restype = ctypes.c_void_p
        for which in (-11, -12):    # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            h = k32.GetStdHandle(which)
            if h in (None, 0, ctypes.c_void_p(-1).value) or k32.GetFileType(ctypes.c_void_p(h)) == 0:
                streams.append(None)
                continue
            streams.append(os.fdopen(msvcrt.open_osfhandle(h, os.O_WRONLY), "w", encoding="utf-8", errors="replace"))
    except (OSError, AttributeError, ValueError, ImportError):
        streams = []
    out = streams[0] if streams else None
    err = streams[1] if len(streams) > 1 else None
    sink = None if (out and err) else open(os.devnull, "w")
    sys.stdout = out or err or sink
    sys.stderr = err or out or sink


def message_box(text):
    """Say something when started without a console (a double click), where nothing printed is seen."""
    if not WIN:     # the desktop's own dialog tool, when there is one and a display
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return
        for cmd in (["zenity", "--info", "--title", GAME_NAME, "--text", text],
                    ["kdialog", "--title", GAME_NAME, "--msgbox", text]):
            if shutil.which(cmd[0]):
                try:
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
                except OSError:
                    pass
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, GAME_NAME, 0x40)
    except (OSError, AttributeError, ImportError):
        pass


COMMANDS = {"status", "prepare", "download", "update", "build", "play", "run", "update-launcher", "-h", "--help", "help"}


def main(argv):
    attach_std_streams()
    if any(a in COMMANDS for a in argv):
        return cli(argv)
    # no command (a double click, or RecompLauncher with Easy Setup skipped): start the game when it is built
    try:
        root, disc, _accept, _words = parse_args(argv)
        P, C = open_session(root, disc)
        if ready_to_play(P, C):
            return play(P, C, lambda s: print(s, flush=True), wait=True, extra=_words)   # the player's launch options
        pick = "pick it again (--disc=FILE, or Easy Setup in RecompLauncher)."
        chosen = C.get("disc")
        if os.path.isfile(P.exe) and chosen and not image_present(chosen):
            message = "The game is built, but its disc image is not where it was (%s). Put it back, or %s" % (chosen, pick)
        elif os.path.isfile(P.exe) and chosen:
            message = ("The game is built, but %s is no longer %s (%s): %s" % (chosen, GAME_NAME, GAME_SERIAL, pick))
        elif os.path.isfile(P.exe):
            message = "The game is built, but no disc image is chosen: %s" % pick
        elif os.environ.get("RECOMPLAUNCHER") == "1":
            message = ("The game is not set up yet. Turn Easy Setup back on for it in RecompLauncher, pick your "
                       "disc image there and let it build the game.")
        else:
            message = ("The game is not set up yet. Install it with RecompLauncher (recomplauncher.com), "
                       "which builds it from your own disc, or run this program with "
                       "--disc=<your disc image> prepare --accept-downloads.")
    except (Fail, OSError) as e:
        message = "%s cannot start: %s" % (GAME_NAME, e)
    print(message, flush=True)
    message_box(message)
    return 1


def guarded_main(argv):
    """main, but nothing escapes: in the packaged program an uncaught error would open a dialog and hold up
    RecompLauncher's windowless setup step until it gives up on it."""
    try:
        return main(argv)
    except Exception as e:      # the last stop: say what happened where it can be seen, then fail
        text = "%s: %s: %s" % (GAME_NAME, type(e).__name__, e)
        try:
            print("error: " + text, flush=True)
        except Exception:
            pass
        if not any(a in COMMANDS for a in argv):   # a double click: nobody sees what was printed
            message_box(text)                      # (never for prepare: the setup step must not wait on a dialog)
        return 1


if __name__ == "__main__":
    sys.exit(guarded_main(sys.argv[1:]))
