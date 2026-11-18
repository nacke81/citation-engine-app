"""Verify Now send run starts without a visible console (t_58ea23a5). No network. Run: python tests/verify_hidden_console_test.py. Exit 1 on any failure.
Part 1 (any OS): the spawner sees the no-window flags and the same log stream. Part 2 (Windows): a real launch, window list read before/after (control: the old DETACHED flags DO open a window)."""
import os, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ["CE_LOGS"] = os.path.join(TMP, "logs")
os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json")
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json"); os.environ["CE_RUNS"] = tempfile.mkdtemp()
os.environ["CE_NO_CARDS"] = "1"
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
import verify_bridge as B

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

# Part 1
seen = {}
def spawner(argv, **kw): seen["argv"], seen["kw"] = argv, kw; return None
B.start_send("00000000-0000-0000-0000-000000000001", spawner=spawner)
check("argv is verify_send.py --request-id <id>", seen["argv"][-2:] == ["--request-id", "00000000-0000-0000-0000-000000000001"])
check("stdout goes to a log file, stderr merged into it", seen["kw"]["stdout"] is not None and seen["kw"]["stderr"] == subprocess.STDOUT)
if os.name == "nt":
    fl = seen["kw"]["creationflags"]
    check("CREATE_NO_WINDOW set", bool(fl & 0x08000000))
    check("DETACHED_PROCESS not set", not (fl & 0x00000008))
    check("own process group kept", bool(fl & 0x00000200))
    check("agent Popen in verify_send carries CREATE_NO_WINDOW", "0x08000000" in open(os.path.join(HERE, "..", "job", "verify_send.py"), encoding="utf-8").read())

# Part 2
def visible_windows():
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32; out = {}
    cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def f(h, _):
        if u.IsWindowVisible(h):
            n = u.GetWindowTextLengthW(h); b = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, b, n + 1)
            c = ctypes.create_unicode_buffer(256); u.GetClassNameW(h, c, 256)
            out[h] = (c.value, b.value)
        return True
    u.EnumWindows(cb(f), 0); return out

def probe(flags):
    """Launch a child python (flags) that starts a console child for ~6 s, like the agent. -> (new visible windows, log text)."""
    log = os.path.join(TMP, "probe-%d.log" % flags)
    code = "import subprocess,sys;print('probe line',flush=True);subprocess.run(['ping','-n','7','127.0.0.1'],stdout=subprocess.DEVNULL);print('probe done',flush=True)"
    before = visible_windows()
    with open(log, "ab") as o:
        p = subprocess.Popen([sys.executable, "-c", code], stdout=o, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, close_fds=True, creationflags=flags)
    time.sleep(3)
    new = {h: v for h, v in visible_windows().items() if h not in before}
    p.wait(timeout=30)
    return new, open(log, encoding="utf-8", errors="replace").read()

if os.name == "nt":
    old_new, _ = probe(0x00000200 | 0x00000008)
    check("control: old DETACHED flags open a visible window (probe is able to see one) %s" % list(old_new.values()), len(old_new) > 0)
    new, text = probe(B.NO_WINDOW_FLAGS)
    check("hidden launch: no new visible window %s" % list(new.values()), len(new) == 0)
    check("hidden launch: same log lines written", "probe line" in text and "probe done" in text)

print("FAILED: %s" % fails if fails else "all passed")
sys.exit(1 if fails else 0)
