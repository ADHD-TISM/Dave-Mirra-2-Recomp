"""Offline checks for the launcher's download/unpack helpers (no network).

    python -I launcher/test_launcher.py
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("bmx2launcher", os.path.join(HERE, "bmx2launcher.py"))
bl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bl)


def check(cond, what):
    """assert that survives python -O"""
    if not cond:
        raise AssertionError(what)


def expect_fail(fn, text):
    try:
        fn()
    except bl.Fail as e:
        check(text in str(e), "Fail text %r lacks %r" % (str(e), text))
    else:
        raise AssertionError("no Fail (wanted %r)" % text)


def files_under(d):
    return sorted(os.path.relpath(os.path.join(r, f), d).replace(os.sep, "/") for r, _, fs in os.walk(d) for f in fs)


def make_zip(path, names):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, "x")


def test_only_takes_the_project_folder(d):
    z = os.path.join(d, "repo.zip")
    make_zip(z, ["repo-v1/LICENSE", "repo-v1/launcher/bmx2launcher.py", "repo-v1/bmx2recomp/build.sh",
                 "repo-v1/bmx2recomp/tools/recomp_ee.py", "repo-v1/bmx2recompX/evil.txt"])
    out = os.path.join(d, "out")
    bl.safe_extract(z, out, strip=2, only="bmx2recomp/")
    check(files_under(out) == ["build.sh", "tools/recomp_ee.py"], files_under(out))


def test_damaged_zip_is_a_clear_error(d):
    bad = os.path.join(d, "bad.zip")
    with open(bad, "wb") as f:
        f.write(b"PK\x03\x04 cut off")
    expect_fail(lambda: bl.safe_extract(bad, os.path.join(d, "o")), "damaged")


def test_bad_crc_is_a_clear_error(d):
    z = os.path.join(d, "crc.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as f:
        f.writestr("top/a.txt", "hello world")
    data = bytearray(open(z, "rb").read())
    data[data.index(b"hello world")] ^= 0xff          # corrupt the stored data, keep the index
    open(z, "wb").write(bytes(data))
    expect_fail(lambda: bl.safe_extract(z, os.path.join(d, "o2"), strip=1), "damaged")


def test_replace_dir_swaps_and_cleans_up(d):
    final, tmp = os.path.join(d, "final"), os.path.join(d, "tmp")
    os.makedirs(final); open(os.path.join(final, "old.txt"), "w").close()
    os.makedirs(tmp); open(os.path.join(tmp, "new.txt"), "w").close()
    bl.replace_dir(tmp, final)
    check(os.listdir(final) == ["new.txt"], os.listdir(final))
    check(not os.path.exists(tmp) and not os.path.exists(final + ".old"), "tmp or .old left")


def test_replace_dir_into_missing_final(d):
    final, tmp = os.path.join(d, "f2"), os.path.join(d, "t2")
    os.makedirs(tmp); open(os.path.join(tmp, "a"), "w").close()
    bl.replace_dir(tmp, final)
    check(os.listdir(final) == ["a"], os.listdir(final))


def test_replace_dir_rolls_back_when_the_swap_fails(d):
    final, tmp = os.path.join(d, "final"), os.path.join(d, "tmp")
    os.makedirs(final); open(os.path.join(final, "old.txt"), "w").close()
    os.makedirs(tmp); open(os.path.join(tmp, "new.txt"), "w").close()
    real = bl.rename_dir
    def failing(src, dst):
        if src == tmp:
            raise PermissionError("simulated: tmp is locked")
        real(src, dst)
    bl.rename_dir = failing
    try:
        bl.replace_dir(tmp, final)
    except PermissionError:
        pass
    else:
        raise AssertionError("the simulated failure did not surface")
    finally:
        bl.rename_dir = real
    check(os.listdir(final) == ["old.txt"], "old folder not put back: %r" % os.listdir(final))
    check(not os.path.exists(final + ".old"), ".old left")


def test_replace_dir_no_restore_without_a_move(d):
    # no final to move aside: the only rename is the swap, and when it fails nothing is "restored"
    final, tmp = os.path.join(d, "final"), os.path.join(d, "tmp")
    os.makedirs(tmp)
    real, calls = bl.rename_dir, []
    def failing(src, dst):
        calls.append((src, dst))
        if src == tmp:
            raise PermissionError("simulated: tmp is locked")
        real(src, dst)
    bl.rename_dir = failing
    try:
        bl.replace_dir(tmp, final)
    except PermissionError:
        pass
    else:
        raise AssertionError("the simulated failure did not surface")
    finally:
        bl.rename_dir = real
    check(calls == [(tmp, final)], "unexpected renames: %r" % calls)
    check(not os.path.exists(final), "a folder appeared although none was moved aside")


def test_replace_dir_refuses_a_stuck_old_folder(d):
    if os.name != "nt":
        print("skip %s (needs Windows: an open file blocks deleting its folder)" % "test_replace_dir_refuses_a_stuck_old_folder")
        return
    final, tmp = os.path.join(d, "final"), os.path.join(d, "tmp")
    os.makedirs(final); open(os.path.join(final, "keep.txt"), "w").close()
    os.makedirs(tmp)
    os.makedirs(final + ".old")
    held = open(os.path.join(final + ".old", "locked.txt"), "w")   # an open file: Windows cannot delete it
    try:
        expect_fail(lambda: bl.replace_dir(tmp, final), "left from an earlier update")
    finally:
        held.close()
    check(os.listdir(final) == ["keep.txt"], "final changed: %r" % os.listdir(final))


def test_unsafe_path_is_refused(d):
    z = os.path.join(d, "evil.zip")
    make_zip(z, ["top/../../escape.txt"])
    expect_fail(lambda: bl.safe_extract(z, os.path.join(d, "o"), strip=1), "unsafe path")
    check(not os.path.exists(os.path.join(os.path.dirname(d), "escape.txt")), "file escaped")


def test_only_needs_strip_and_slash(d):
    z = os.path.join(d, "a.zip")
    make_zip(z, ["top/bmx2recomp/a"])
    for kw in (dict(strip=0, only="bmx2recomp/"), dict(strip=2, only="bmx2recomp")):
        try:
            bl.safe_extract(z, os.path.join(d, "o"), **kw)
        except ValueError:
            continue
        raise AssertionError("no ValueError for %r" % kw)


def test_bad_offsets_are_a_clear_error(d):
    # central directory intact but pointing past moved data: zipfile seeks to a negative offset (EINVAL)
    z = os.path.join(d, "off.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as f:
        f.writestr("top/a.txt", "A" * 4000)
        f.writestr("top/b.txt", "B" * 4000)
    data = open(z, "rb").read()
    cut = data.index(b"B" * 100)
    open(z, "wb").write(data[:cut - 2000] + data[cut:])   # drop 2000 bytes before b.txt's data
    expect_fail(lambda: bl.safe_extract(z, os.path.join(d, "o"), strip=1), "damaged")


def _dirrec(name, lba, size, is_dir):
    """One ISO 9660 directory record."""
    n = name.encode("ascii")
    rec = bytearray(33 + len(n) + (1 - len(n) % 2))
    rec[0] = len(rec)
    rec[2:6] = lba.to_bytes(4, "little"); rec[6:10] = lba.to_bytes(4, "big")
    rec[10:14] = size.to_bytes(4, "little"); rec[14:18] = size.to_bytes(4, "big")
    rec[25] = 2 if is_dir else 0
    rec[32] = len(n)
    rec[33:33 + len(n)] = n
    return bytes(rec)


def _make_iso(path):
    """32 sectors: root (sector 20) with ASSETS/ and SLUS_201.59; ASSETS (sectors 21-22) with ICON.DAT
    in its second sector; file data at 30 and 31."""
    sec = [bytearray(2048) for _ in range(32)]
    sec[16][0:6] = b"\x01CD001"
    sec[16][156:156 + 34] = _dirrec("\0", 20, 2048, True)
    sec[20][:] = (_dirrec("\0", 20, 2048, True) + _dirrec("\1", 20, 2048, True) + _dirrec("ASSETS", 21, 4096, True)
                  + _dirrec("SLUS_201.59;1", 30, 5, False)).ljust(2048, b"\0")
    sec[21][:] = (_dirrec("\0", 21, 4096, True) + _dirrec("\1", 20, 2048, True)
                  + _dirrec("A.BIN;1", 30, 5, False)).ljust(2048, b"\0")
    sec[22][:] = _dirrec("ICON.DAT;1", 31, 6, False).ljust(2048, b"\0")
    sec[30][:5] = b"slus!"
    sec[31][:6] = b"icon!!"
    with open(path, "wb") as f:
        f.write(b"".join(sec))


def test_image_reads_subfolders(d):
    p = os.path.join(d, "game.iso")
    _make_iso(p)
    im = bl.Image(p)
    try:
        check(im.read("SLUS_201.59") == b"slus!", "root file")
        check(im.read("ASSETS/ICON.DAT") == b"icon!!", "file in the second sector of a subfolder")
        check(im.read("assets/icon.dat") == b"icon!!", "names are case-insensitive")
        check(set(im.root(dirs=True)) == {"ASSETS"}, "subfolders: %r" % im.root(dirs=True))
        check(set(im.root()) == {"SLUS_201.59"}, "root files: %r" % im.root())
        for bad in ("ASSETS/NOPE.DAT", "NOPE/ICON.DAT", "ASSETS/X/Y", "ASSETS"):
            expect_fail(lambda b=bad: im.read(b), "is not on this disc")
    finally:
        im.close()


def test_image_reads_a_chd_through_chdread(d):
    iso = os.path.join(d, "game.iso")
    _make_iso(iso)
    with open(iso, "rb") as f:
        data = f.read()
    p = os.path.join(d, "game.chd")
    with open(p, "wb") as f:
        f.write(bl.CHD_MAGIC + b"\0" * 2040)      # only the magic matters: chdread is stubbed below
    calls = []

    def fake_chdread(self, *args):
        calls.append(args)
        if args[0] == "info":
            return b"sectors 32\n"
        lba, n = int(args[2]), int(args[3])
        return data[lba * 2048:(lba + n) * 2048]
    old = bl.Image._chdread
    bl.Image._chdread = fake_chdread
    try:
        im = bl.Image(p)
        check(im.read("SLUS_201.59") == b"slus!" and im.read("ASSETS/ICON.DAT") == b"icon!!", "files from a CHD")
        check(im.sector(40) == b"\0" * 2048, "past the end is zeros")
        reads = [a for a in calls if a[0] == "read"]
        check(reads == [("read", p, "0", "32")], "one chunked read for a small disc: %r" % reads)
        im.close()
    finally:
        bl.Image._chdread = old
    check(bl.is_chd(p) and not bl.is_chd(iso), "is_chd")


def test_a_newer_pinned_compiler_is_installed_over_an_old_one(d):
    P = bl.Paths(d)
    os.makedirs(os.path.dirname(P.clang))
    open(P.clang, "w").close()
    mark = os.path.join(P.llvm, bl.TOOL_MARK)
    old_env = os.environ.pop("BMX2_CLANG", None)
    old_name = bl.LLVM_NAME
    try:
        check(bl.UNMARKED == {"llvm": "llvm-mingw-20261104-ucrt-x86_64", "python": "python-3.12.8-embed-amd64"},
              "UNMARKED is frozen: never change it on a version bump")
        bl.LLVM_NAME = bl.UNMARKED["llvm"]
        check(bl.compiler_current(P), "an unmarked install from v0.2.1 or older is kept")
        with open(mark, encoding="utf-8") as f:
            check(f.read().strip() == bl.LLVM_NAME, "and it gets its mark")
        bl.LLVM_NAME = "llvm-mingw-20990101-ucrt-x86_64"     # a later release pins a newer compiler
        check(not bl.compiler_current(P) and not bl.toolchain_ok(P), "a newer pinned compiler is not current")
        os.remove(mark)
        check(not bl.compiler_current(P), "an unmarked install is not taken for a newer pinned compiler")
        bl.LLVM_NAME = bl.UNMARKED["llvm"]     # where it matters: else it would be re-marked and accepted
        with open(mark, "wb") as f:
            f.write(bytes([0xff, 0xfe]) + b" junk")
        check(not bl.compiler_current(P), "an unreadable mark means install again, not a crash")
        old_id = bl.compiler_id(P)
        bl.LLVM_NAME = "llvm-mingw-21000101-ucrt-x86_64"
        check(bl.compiler_id(P) != old_id, "a new pinned compiler changes the object keys, so everything recompiles")
        os.environ["BMX2_CLANG"] = P.clang
        check(bl.compiler_current(P), "a developer's own compiler (BMX2_CLANG) is never replaced")
        own = bl.compiler_id(P)
        with open(P.clang, "w") as f:
            f.write("a newer compiler at the same path")
        check(bl.compiler_id(P) != own, "a new own compiler at the same path recompiles everything")
    finally:
        bl.LLVM_NAME = old_name
        os.environ.pop("BMX2_CLANG", None)
        if old_env is not None:
            os.environ["BMX2_CLANG"] = old_env


def test_install_toolchain_marks_a_new_pinned_compiler_and_python(d):
    P = bl.Paths(d)
    clang_rel = os.path.relpath(P.clang, P.llvm).replace(os.sep, "/")

    def fake_fetch(url, dest, log, sha256=None, label=None):     # a tiny "download" with the files that matter
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with zipfile.ZipFile(dest, "w") as z:
            if url == bl.LLVM_URL:
                z.writestr("llvm-mingw-x/" + clang_rel, "clang")
            else:
                z.writestr("python.exe", "python")
    old = (bl.LLVM_NAME, bl.FROZEN, os.environ.pop("BMX2_CLANG", None), bl.PY_NAME)
    bl.LLVM_NAME, bl.FROZEN = "llvm-mingw-21000101-ucrt-x86_64", True     # a later release, packaged,
    bl.PY_NAME = "python-3.99.0-embed-amd64"                               # pinning a newer compiler and Python
    try:
        with _Stubs(fetch=fake_fetch):
            bl.install_toolchain(P, lambda s: None)
        check(bl.toolchain_ok(P), "after installing a newer pinned compiler and Python, the tools are current")
        for folder, want in ((P.llvm, bl.LLVM_NAME), (P.pydir, bl.PY_NAME)):
            with open(os.path.join(folder, bl.TOOL_MARK), encoding="utf-8") as f:
                check(f.read().strip() == want, "%s is marked %s" % (folder, want))
            check(not os.path.exists(os.path.join(folder, bl.TOOL_MARK + ".new")), "no half-written mark left")
    finally:
        bl.LLVM_NAME, bl.FROZEN, bl.PY_NAME = old[0], old[1], old[3]
        if old[2] is not None:
            os.environ["BMX2_CLANG"] = old[2]


def test_a_new_compiler_changes_the_build_and_object_keys(d):
    root = os.path.join(d, "r")
    for sub, f in (("bmx2recomp/runtime", "main.c"), ("work/gen", "code.c"), ("work/gen_iop", "iop.c"),
                   ("work/gen_vu", "vu.h")):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
        with open(os.path.join(root, sub, f), "w") as fh:
            fh.write("int x;\n")
    P = bl.Paths(root)
    src = os.path.join(root, "bmx2recomp", "runtime", "main.c")
    old = (bl.LLVM_NAME, os.environ.pop("BMX2_CLANG", None))
    try:
        keys = (bl.build_key(P), bl.object_key(P, "h", bl.compiler_id(P), src))
        bl.LLVM_NAME = "llvm-mingw-21000101-ucrt-x86_64"
        new = (bl.build_key(P), bl.object_key(P, "h", bl.compiler_id(P), src))
        check(new[0] != keys[0], "a new pinned compiler makes the game out of date")
        check(new[1] != keys[1], "a new pinned compiler gives every object a new key")
        own = os.path.join(d, "own-clang.exe")
        with open(own, "w") as fh:
            fh.write("v1")
        os.environ["BMX2_CLANG"] = own
        k1 = bl.build_key(P)
        with open(own, "w") as fh:
            fh.write("version 2")
        check(bl.build_key(P) != k1, "a changed own compiler (BMX2_CLANG) makes the game out of date")
    finally:
        bl.LLVM_NAME = old[0]
        os.environ.pop("BMX2_CLANG", None)
        if old[1] is not None:
            os.environ["BMX2_CLANG"] = old[1]


def test_a_chd_needs_a_build_that_reads_chd(d):
    P = bl.Paths(d)
    os.makedirs(P.game)
    open(P.exe, "w").close()
    chd = os.path.join(d, "game.chd")
    with open(chd, "wb") as f:
        f.write(bl.CHD_MAGIC + b"\0" * 2040)
    expect_fail(lambda: bl.play(P, _FakeConfig(disc=chd), lambda s: None), "cannot read .chd images")


def test_a_wrong_or_missing_disc_exits_7(d):
    iso = os.path.join(d, "other.iso")
    _make_iso(iso)          # an ISO 9660 image with no SYSTEM.CNF: not this game
    def no_download(*a, **k):
        raise AssertionError("the disc must be refused before any download")
    with _Stubs(install_toolchain=no_download, install_project=no_download):
        for args in (["--disc=" + iso, "prepare", "--accept-downloads"], ["--disc=" + os.path.join(d, "gone.iso"), "run"]):
            code = bl.cli(["--root", os.path.join(d, "root")] + args)
            check(code == bl.BAD_DISC == 7, "%r gave %r" % (args, code))
    P = bl.Paths(os.path.join(d, "root"))     # a built game, but no disc chosen at all
    os.makedirs(P.game, exist_ok=True)
    open(P.exe, "w").close()
    with _Stubs(install_toolchain=no_download, install_project=no_download):
        # the error text ties each 7 to "no disc chosen", not to a disc saved by an earlier call
        for cmd, said in (("run", "no game image chosen"), ("play", "no game image chosen"),
                          ("prepare", "no disc image given"), ("build", "choose it with --disc")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = bl.cli(["--root", P.root, cmd, "--accept-downloads"])
            check(code == 7 and said in out.getvalue(), "%s with no disc chosen gave %r: %r" % (cmd, code, out.getvalue()))


def test_identify_does_not_cache_a_chdread_failure(d):
    p = os.path.join(d, "game.chd")
    with open(p, "wb") as f:
        f.write(bl.CHD_MAGIC + b"\0" * 2040)

    def fake_chdread(self, *args):
        if args[0] == "info":
            return b"sectors 32\n"
        raise bl.ChdFail("game.chd: read error at sector 16")
    old = bl.Image._chdread
    bl.Image._chdread = fake_chdread
    C = _FakeConfig()
    try:
        expect_fail(lambda: bl.identify(C, p), "read error")
        check(not C.d.get("ident"), "the failure was cached: %r" % C.d.get("ident"))
    finally:
        bl.Image._chdread = old


class _Stubs:
    """Replace launcher functions for one test; put them back after."""
    def __init__(self, **fns):
        self.fns, self.old = fns, {}

    def __enter__(self):
        for k, v in self.fns.items():
            self.old[k] = getattr(bl, k)
            setattr(bl, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            setattr(bl, k, v)


class _FakeConfig:
    def __init__(self, **d):
        self.d = d

    def get(self, k, default=None):
        return self.d.get(k, default)


def _prepare(accept, **stubs):
    """Run prepare with stubs; (exit code, printed lines, the calls the stubs saw)."""
    import io
    calls = []
    base = dict(toolchain_ok=lambda P: True, project_ok=lambda P: True, generated_ok=lambda P, C, d: True,
                built_ok=lambda P, C: True, release_tag=lambda: None,
                install_toolchain=lambda P, log: calls.append("toolchain"),
                install_project=lambda P, C, log, force=False, want=None: calls.append(("project", want)),
                generate=lambda P, C, disc, log: calls.append("generate"),
                compile_game=lambda P, C, log, progress=None: (calls.append("compile"), progress(1, 1), log("linking")))
    base.update(stubs)
    out, real = io.StringIO(), sys.stdout
    sys.stdout = out
    try:
        with _Stubs(**base):
            code = bl.prepare(None, _FakeConfig(disc="game.cue"), accept, lambda s: print(s))
    finally:
        sys.stdout = real
    return code, out.getvalue().splitlines(), calls


def test_prepare_needs_the_downloads_allowed(d):
    code, lines, calls = _prepare(False, toolchain_ok=lambda P: False)
    check(code == bl.NEEDS_DOWNLOADS == 10 and calls == [], (code, calls))
    check(any("--accept-downloads" in l for l in lines), lines)


def test_prepare_already_built(d):
    code, lines, calls = _prepare(False)
    check(code == 0 and lines[-1] == "progress 1.000 Already built" and calls == [], (code, lines, calls))


def test_prepare_builds_its_release_version(d):
    code, lines, calls = _prepare(True, release_tag=lambda: "v1.2.3", built_ok=lambda P, C: False)
    check(code == 0 and calls == [("project", "v1.2.3"), "generate", "compile"], calls)
    check("progress 0.970 Linking" in lines and lines[-1] == "progress 1.000 Ready to play", lines)
    check(all(0 <= float(l.split()[1]) <= 1 for l in lines if l.startswith("progress ")), lines)


def test_prepare_wants_downloads_for_a_new_release(d):
    code, lines, calls = _prepare(False, release_tag=lambda: "v1.2.3", is_working_copy=lambda P: False)
    check(code == bl.NEEDS_DOWNLOADS and calls == [] and any("v1.2.3" in l for l in lines), (code, lines, calls))


def test_prepare_keeps_the_project_under_recomplauncher(d):
    old = os.environ.get("RECOMPLAUNCHER")
    os.environ["RECOMPLAUNCHER"] = "1"
    try:
        code, _lines, calls = _prepare(True)     # no release version packed in
    finally:
        if old is None:
            os.environ.pop("RECOMPLAUNCHER")
        else:
            os.environ["RECOMPLAUNCHER"] = old
    check(code == 0 and calls == [], calls)


def test_release_tag_reads_only_a_plain_version(d):
    old = getattr(sys, "_MEIPASS", None)
    sys._MEIPASS = d
    old_frozen, bl.FROZEN = bl.FROZEN, True
    try:
        for text, want in (("v0.2.0\n", "v0.2.0"), ("v1\n", "v1"), ("v0.2.0-beta1\n", None), ("\n", None)):
            with open(os.path.join(d, "release_tag.txt"), "w") as f:
                f.write(text)
            check(bl.release_tag() == want, (text, bl.release_tag()))
        bl.FROZEN = False
        check(bl.release_tag() is None, "run from source: no pin")
    finally:
        bl.FROZEN = old_frozen
        if old is None:
            del sys._MEIPASS
        else:
            sys._MEIPASS = old


def test_parse_args_both_disc_forms(d):
    check(bl.parse_args(["--root", "R", "--disc=a b.cue", "run", "--frames", "600"]) ==
          ("R", "a b.cue", False, ["run", "--frames", "600"]), "disc= form")
    check(bl.parse_args(["--disc", "x.iso", "--accept-downloads", "prepare"]) == (None, "x.iso", True, ["prepare"]),
          "disc FILE form")


def test_run_passes_the_words_after_it(d):
    seen = {}

    def fake_play(P, C, log, wait=False, extra=()):
        seen.update(wait=wait, extra=list(extra))
        return 7
    with _Stubs(open_session=lambda root, disc: (None, _FakeConfig()), play=fake_play):
        code = bl.cli(["--disc=x.cue", "run", "--frames", "600"])
    check(code == 7 and seen == {"wait": True, "extra": ["--frames", "600"]}, (code, seen))


def test_no_command_uses_recomplauncher_data(d):
    """Easy Setup skipped: no --root, but RECOMPLAUNCHER_DATA names the folder with the build."""
    seen = {}
    keep = {k: os.environ.get(k) for k in ("RECOMPLAUNCHER_DATA", "RECOMPLAUNCHER")}
    os.environ["RECOMPLAUNCHER_DATA"], os.environ["RECOMPLAUNCHER"] = d, "1"

    def fake_play(P, C, log, wait=False, extra=()):
        seen.update(root=P.root, wait=wait, extra=list(extra))
        return 0
    try:
        with _Stubs(adopt_disc=lambda P, C: False, ready_to_play=lambda P, C: True, play=fake_play):
            code = bl.main(["--fast"])
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    check(code == 0 and seen == {"root": os.path.abspath(d), "wait": True, "extra": ["--fast"]}, (code, seen))


def _no_command_message(d, disc):
    """main() with no command, a built game in d and the chosen disc; the message box text."""
    os.makedirs(os.path.join(d, "game"), exist_ok=True)
    open(os.path.join(d, "game", "bmx2.exe"), "w").close()
    boxes = []
    keep = os.environ.get("RECOMPLAUNCHER_DATA")
    os.environ["RECOMPLAUNCHER_DATA"] = d
    try:
        with _Stubs(open_session=lambda root, disc_: (bl.Paths(d), _FakeConfig(disc=disc)),
                    ready_to_play=lambda P, C: False, message_box=boxes.append):
            check(bl.main([]) == 1, "not 1")
    finally:
        if keep is None:
            os.environ.pop("RECOMPLAUNCHER_DATA", None)
        else:
            os.environ["RECOMPLAUNCHER_DATA"] = keep
    check(len(boxes) == 1, boxes)
    return boxes[0]


def test_no_command_says_what_is_wrong_with_the_disc(d):
    check("not where it was" in _no_command_message(d, os.path.join(d, "gone.cue")), "moved")
    here = os.path.join(d, "other.iso")
    open(here, "w").close()
    check("is no longer" in _no_command_message(d, here), "not this game's disc")
    check("no disc image is chosen" in _no_command_message(d, None), "none chosen")


def test_download_progress_only_goes_up(d):
    def fake_toolchain(P, log):
        for s in ("  compiler: 0% of 190.0 MB", "  compiler: 100% of 190.0 MB", "  python: 0% of 11.0 MB",
                  "  python: 100% of 11.0 MB"):
            log(s)
    code, lines, _calls = _prepare(True, toolchain_ok=lambda P: False, project_ok=lambda P: False,
                                   install_toolchain=fake_toolchain, built_ok=lambda P, C: False)
    values = [float(l.split()[1]) for l in lines if l.startswith("progress ")]
    check(code == 0 and values == sorted(values), values)


def test_prepare_keeps_an_installed_project_when_only_the_tools_are_missing(d):
    old = os.environ.get("RECOMPLAUNCHER")
    os.environ["RECOMPLAUNCHER"] = "1"
    try:
        code, _lines, calls = _prepare(True, toolchain_ok=lambda P: False)   # unpinned, project already there
    finally:
        if old is None:
            os.environ.pop("RECOMPLAUNCHER")
        else:
            os.environ["RECOMPLAUNCHER"] = old
    check(code == 0 and calls == ["toolchain"], calls)


def test_build_key_does_not_depend_on_the_folder(d):
    keys = []
    for name in ("one", "two place"):
        root = os.path.join(d, name)
        for sub, f in (("bmx2recomp/runtime", "main.c"), ("work/gen", "code.c"), ("work/gen_iop", "iop.c"),
                       ("work/gen_vu", "vu.h")):
            os.makedirs(os.path.join(root, sub), exist_ok=True)
            with open(os.path.join(root, sub, f), "w") as fh:
                fh.write("int x;\n")
        keys.append(bl.build_key(bl.Paths(root)))
    check(keys[0] == keys[1], "build_key changed with the folder")


def test_resources_add_the_manifest_with_or_without_the_icon(d):
    P = bl.Paths(d)
    rt = os.path.join(P.project, "runtime")
    os.makedirs(rt)
    os.makedirs(P.gen)
    rc, man, ico = os.path.join(rt, "bmx2.rc"), os.path.join(rt, "bmx2.manifest"), os.path.join(P.gen, "bmx2.ico")
    check(bl._resources(P) == [], "resources without bmx2.rc")
    for p in (rc, ico):
        open(p, "w").close()
    res = bl._resources(P)      # v0.1.9 to v0.2.0: no manifest, the rc names the icon unconditionally
    check(res == [rc, ico] and "-DBMX2_ICON" not in bl._res_args(P, res), "old project: %r" % res)
    open(man, "w").close()
    res = bl._resources(P)
    check(res == [rc, man, ico] and "-DBMX2_ICON" in bl._res_args(P, res), "manifest and icon: %r" % res)
    os.remove(ico)
    res = bl._resources(P)      # no icon made: the manifest is still added
    check(res == [rc, man] and "-DBMX2_ICON" not in bl._res_args(P, res), "manifest only: %r" % res)
    check(bl._res_args(P, res)[-4:-2] == ["-i", rc], "windres input: %r" % bl._res_args(P, res))


def test_an_unexpected_error_does_not_escape(d):
    def boom(argv):
        raise TypeError("odd data")
    boxes = []
    with _Stubs(main=boom, message_box=boxes.append):
        check(bl.guarded_main([]) == 1, "guarded_main did not return 1")
        check(len(boxes) == 1 and "odd data" in boxes[0], "no message box after a double click: %r" % boxes)
        check(bl.guarded_main(["prepare"]) == 1 and len(boxes) == 1, "a message box during prepare")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        d = tempfile.mkdtemp(prefix="bmx2lt-")
        try:
            t(d)
            print("ok   %s" % t.__name__)
        except Exception as e:      # report every test, then exit non-zero
            failed += 1
            print("FAIL %s: %r" % (t.__name__, e))
        finally:
            shutil.rmtree(d, ignore_errors=True)
    print("%d of %d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
