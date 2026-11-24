"""Offline checks for the launcher's download/unpack helpers (no network).

    python -I launcher/test_launcher.py
"""
import importlib.util
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
