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
    assert files_under(out) == ["build.sh", "tools/recomp_ee.py"], files_under(out)


def test_damaged_zip_is_a_clear_error(d):
    bad = os.path.join(d, "bad.zip")
    with open(bad, "wb") as f:
        f.write(b"PK\x03\x04 cut off")
    try:
        bl.safe_extract(bad, os.path.join(d, "o"))
    except bl.Fail as e:
        assert "damaged" in str(e)
    else:
        raise AssertionError("no Fail for a damaged zip")


def test_bad_crc_is_a_clear_error(d):
    z = os.path.join(d, "crc.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as f:
        f.writestr("top/a.txt", "hello world")
    data = bytearray(open(z, "rb").read())
    data[data.index(b"hello world")] ^= 0xff          # corrupt the stored data, keep the index
    open(z, "wb").write(bytes(data))
    try:
        bl.safe_extract(z, os.path.join(d, "o2"), strip=1)
    except bl.Fail as e:
        assert "damaged" in str(e)
    else:
        raise AssertionError("no Fail for a bad CRC")


def test_replace_dir_swaps_and_cleans_up(d):
    final, tmp = os.path.join(d, "final"), os.path.join(d, "tmp")
    os.makedirs(final); open(os.path.join(final, "old.txt"), "w").close()
    os.makedirs(tmp); open(os.path.join(tmp, "new.txt"), "w").close()
    bl.replace_dir(tmp, final)
    assert os.listdir(final) == ["new.txt"]
    assert not os.path.exists(tmp) and not os.path.exists(final + ".old")


def test_replace_dir_into_missing_final(d):
    final, tmp = os.path.join(d, "f2"), os.path.join(d, "t2")
    os.makedirs(tmp); open(os.path.join(tmp, "a"), "w").close()
    bl.replace_dir(tmp, final)
    assert os.listdir(final) == ["a"]


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
