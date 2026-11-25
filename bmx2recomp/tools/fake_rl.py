"""Stands in for RecompLauncher's side of the Recomp Achievements channel on Windows (a named pipe,
one JSON object per line), starts the game with RL_SESSION set, and prints every message the game sends.

usage: python -I tools/fake_rl.py [--list FILE] -- <bmx2.exe> [game args]
  --list FILE   an events list (achievements.json): every "event" message is matched against it
                and shown with the achievement it unlocks.
Exit code: the game's. The pipe instance stays open for the whole run (byte mode, like the launcher's).
"""
import ctypes, json, os, subprocess, sys, threading
from ctypes import wintypes as W

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateNamedPipeW.restype = W.HANDLE
k32.CreateNamedPipeW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.LPVOID]
k32.ConnectNamedPipe.argtypes = [W.HANDLE, W.LPVOID]
k32.ReadFile.argtypes = [W.HANDLE, W.LPVOID, W.DWORD, ctypes.POINTER(W.DWORD), W.LPVOID]
k32.WriteFile.argtypes = [W.HANDLE, W.LPCVOID, W.DWORD, ctypes.POINTER(W.DWORD), W.LPVOID]
k32.CloseHandle.argtypes = [W.HANDLE]
INVALID = W.HANDLE(-1).value


def main(argv):
    names = {}
    if "--list" in argv:
        i = argv.index("--list")
        with open(argv[i + 1], encoding="utf-8") as f:
            for a in json.load(f)["achievements"]:
                names[a.get("event")] = "%d %s (%d)" % (a["id"], a["title"], a["points"])
        del argv[i:i + 2]
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    if not argv:
        print(__doc__)
        return 2
    name = r"\\.\pipe\bmx2-fake-rl-%d" % os.getpid()
    h = k32.CreateNamedPipeW(name, 3, 0, 1, 65536, 65536, 0, None)   # duplex, byte mode, 1 instance
    if h == INVALID:
        print("fake_rl: CreateNamedPipe failed", ctypes.get_last_error())
        return 2
    got = []

    def send(obj):
        b = (json.dumps(obj) + "\n").encode()
        n = W.DWORD()
        k32.WriteFile(h, b, len(b), ctypes.byref(n), None)

    def serve():
        k32.ConnectNamedPipe(h, None)
        buf, chunk, n = b"", ctypes.create_string_buffer(65536), W.DWORD()
        while k32.ReadFile(h, chunk, 65536, ctypes.byref(n), None) and n.value:
            buf += chunk.raw[:n.value]
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                m = json.loads(line)
                got.append(m)
                extra = ""
                if m.get("t") == "event":
                    extra = "  -> " + names.get(m.get("name"), "NOT IN THE LIST") if names else ""
                print("fake_rl: got %s%s" % (json.dumps(m), extra), flush=True)
                if m.get("t") == "hello":
                    send({"t": "quiet"})
                    send({"t": "list", "achievements": []})

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    r = subprocess.run(argv, env=dict(os.environ, RL_SESSION=name)).returncode
    t.join(2)
    k32.CloseHandle(h)
    kinds = [m.get("t") for m in got]
    print("fake_rl: game exit %d; messages: %s" % (r, ", ".join("%s x%d" % (k, kinds.count(k)) for k in dict.fromkeys(kinds))))
    return r


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
