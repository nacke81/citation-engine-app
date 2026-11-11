"""build_chrome.py must not leak pythons (t_15f7ec86): hold loop exits when Chrome dies, --seconds 0 idle cap + lease, pidfile kill on --stop, --reap.
Offline: fake runner, fake clock, fake process list. No browser, no network, no real taskkill. Run: python tests/build_chrome_leak_test.py (CI, any OS)."""
import os, sys, json, tempfile, types, subprocess, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="ce-leak-")
os.environ["CE_BUILD_PIDFILE"] = os.path.join(TMP, "build-chrome.pid")
os.environ["CE_BUILD_LEASE"] = os.path.join(TMP, "build-chrome.lease")
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB)
def _no_net(*a, **k): raise AssertionError("network call attempted")
def _no_proc(*a, **k): raise AssertionError("subprocess attempted: %r" % (a[:1],))
urllib.request.urlopen = _no_net
subprocess.run = _no_proc
import chrome_keepalive as KA
import build_chrome as B
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f" [{d}]" if d else ""), flush=True)

class Clock:
    def __init__(s, t=1000.0): s.t = t
    def now(s): return s.t
    def sleep(s, n): s.t += n
LP = os.path.join(TMP, "lease.json")

# ---- 1 hold loop exits when Chrome dies --------------------------------------------------------------------------------------------------------------
c, lines = Clock(), []
state = {"n": 0}
def alive_dies():
    state["n"] += 1
    return state["n"] <= 2          # answers twice, then dead
r = B.hold(9333, None, alive=alive_dies, lease_path=LP, now=c.now, sleep=c.sleep, out=lines.append, max_s=14400, check_every=5)
check("1 hold loop exits by itself when the owned Chrome stops answering, prints chrome_gone=1", r == "chrome_gone" and "chrome_gone=1" in lines, str(lines))
check("1 ...within about a minute, not hours", c.t - 1000 < 60, str(c.t - 1000))
c, lines = Clock(), []
flaps = iter([True, False, True, True, False, True] + [True] * 100000)
r = B.hold(9333, 1000 + 60, alive=lambda: next(flaps), lease_path=LP, now=c.now, sleep=c.sleep, out=lines.append, check_every=5)
check("1 a single missed CDP check does not end the loop (needs 2 in a row); a --seconds timer still ends it", r == "timer" and "chrome_gone=1" not in lines, str(lines))

# ---- 2 --seconds 0 idle cap + lease ------------------------------------------------------------------------------------------------------------------
c, lines = Clock(), []
r = B.hold(9333, None, alive=lambda: True, lease_path=LP, now=c.now, sleep=c.sleep, out=lines.append, max_s=600)
check("2 --seconds 0 with no lease closes at the cap", r == "cap" and 600 <= c.t - 1000 < 610 and any(l.startswith("idle_cap_reached=1") for l in lines), str(c.t - 1000))
c, lines = Clock(), []
class LeaseClock(Clock):
    def sleep(s, n):
        s.t += n
        if s.t < 1000 + 1500: KA.lease_write("t_card", LP, s.now)       # a card keeps refreshing the lease for 1500 s
LC = LeaseClock()
KA.lease_write("t_card", LP, LC.now)
r = B.hold(9333, None, alive=lambda: True, lease_path=LP, now=LC.now, sleep=LC.sleep, out=lines.append, max_s=600)
check("2 a fresh lease holds the cap open; it closes after the lease goes stale", r == "cap" and LC.t - 1000 >= 1500 + KA.LEASE_TTL - 5, str(LC.t - 1000))
KA.lease_release(LP)
check("2 CE_BUILD_MAX_SECONDS default is 14400 (4 h); env overrides; garbage falls back", B.max_seconds({}) == 14400 and B.max_seconds({"CE_BUILD_MAX_SECONDS": "90"}) == 90 and B.max_seconds({"CE_BUILD_MAX_SECONDS": "x"}) == 14400 and B.max_seconds({"CE_BUILD_MAX_SECONDS": "0"}) == 14400)
src = open(os.path.join(JOB, "build_chrome.py"), encoding="utf-8").read()
check("2 docstring says 4 h idle cap and never 'forever'", "4 h idle cap" in src and "forever" not in src.split('"""')[1].lower().replace("never forever", ""))

# ---- 3 pidfile + --stop ------------------------------------------------------------------------------------------------------------------------------
NETSTAT = "  TCP    127.0.0.1:9333         0.0.0.0:0              LISTENING       22460\r\n"
class Runner:
    def __init__(s, procs=(), listening=True): s.cmds, s.procs, s.listening = [], list(procs), listening
    def __call__(s, cmd, **k):
        s.cmds.append(cmd)
        if cmd[0] == "netstat": return types.SimpleNamespace(stdout=NETSTAT if s.listening else "", returncode=0)
        if cmd[0] == "taskkill":
            if cmd[2] == "22460": s.listening = False
            return types.SimpleNamespace(stdout="SUCCESS", returncode=0)
        if cmd[0] == "powershell": return types.SimpleNamespace(stdout=json.dumps(s.procs), returncode=0)
        raise AssertionError("unexpected command %r" % (cmd,))
    def killed(s): return [int(c[2]) for c in s.cmds if c[0] == "taskkill"]
pf = os.path.join(TMP, "pid.json")
B.pidfile_write(9333, pf, now=lambda: 5.0, pid=7777)
rec = json.load(open(pf))
check("3 pidfile holds pid, port and start time", rec == {"pid": 7777, "port": 9333, "started": 5.0}, str(rec))
rn, lines = Runner(), []
rc = B.stop(9333, rn, lines.append, pidfile=pf, lease_path=LP)
check("3 --stop kills the Chrome listener tree AND the pidfile pid tree, then removes the pidfile", rn.killed() == [22460, 7777] and not os.path.exists(pf) and rc == 0, str(rn.killed()))
check("3 every kill is `taskkill /PID n /T /F`", all(c[1] == "/PID" and c[3:] == ["/T", "/F"] for c in rn.cmds if c[0] == "taskkill"))
B.pidfile_write(9333, pf, pid=8888)
rn, lines = Runner(listening=False), []
rc = B.stop(9333, rn, lines.append, pidfile=pf, lease_path=LP)
check("3 --stop with Chrome already gone still kills the pidfile python (exit 2: nothing was listening)", rn.killed() == [8888] and not os.path.exists(pf) and rc == 2, str(rn.killed()))
rn = Runner(listening=False)
check("3 --stop with no listener and no pidfile kills nothing", B.stop(9333, rn, lambda s: None, pidfile=pf, lease_path=LP) == 2 and rn.killed() == [])
B.pidfile_write(9333, pf, pid=1234)
B.pidfile_remove(pf, only_pid=999); still = os.path.exists(pf)
B.pidfile_remove(pf, only_pid=1234)
check("3 a python removes only its own pidfile", still and not os.path.exists(pf))

# ---- 4 --reap ----------------------------------------------------------------------------------------------------------------------------------------
NOW = 100000.0
def proc(pid, ppid, cmd, age_min): return {"pid": pid, "ppid": ppid, "cmd": cmd, "started": NOW - age_min * 60}
BC = "C:\\Python\\python.exe C:\\app\\job\\build_chrome.py --seconds 0"
PROCS = [
    proc(10, 1, 'bash -c "python job/build_chrome.py --seconds 0"', 1600),      # old tree: bash -> python -> python
    proc(11, 10, BC, 1600), proc(12, 11, BC, 1600),
    proc(20, 1, BC, 30),                                                         # young
    proc(30, 1, "python job/build_chrome.py --stop", 900),                       # --stop line
    proc(31, 1, "python job/build_chrome.py --reap --older-than-minutes 5", 900),# --reap line
    proc(40, 1, "chrome.exe --remote-debugging-port=9333", 900),                 # not a build_chrome line
    proc(50, 1, "python other.py", 900),
    proc(60, 1, BC.replace("\\", "/"), 200),                                     # old, forward slashes
]
rn, lines = Runner(procs=PROCS), []
rc = B.reap(60, runner=rn, out=lines.append, procs=PROCS, now=lambda: NOW, lease_path=LP, pidfile=pf)
check("4 --reap kills only old build_chrome.py trees, by their top line (10 covers 11, 12), once each", sorted(rn.killed()) == [10, 60], str(rn.killed()))
check("4 it skips --stop / --reap lines, young trees, chrome.exe and other pythons", not set(rn.killed()) & {20, 30, 31, 40, 50, 11, 12})
check("4 one line per tree and a final reaped=2 left=0, exit 0", lines[-1] == "reaped=2 left=0" and sum(l.startswith("reap tree") for l in lines) == 2 and rc == 0, str(lines))
rn, lines = Runner(procs=PROCS), []
B.reap(0, runner=rn, out=lines.append, procs=PROCS, now=lambda: NOW, lease_path=LP, pidfile=pf)
check("4 --older-than-minutes 0 also takes the young tree", sorted(rn.killed()) == [10, 20, 60], str(rn.killed()))
rn, lines = Runner(procs=PROCS), []
B.reap(60, runner=rn, out=lines.append, procs=[p for p in PROCS if p["pid"] in (30, 31, 40, 50)], now=lambda: NOW, lease_path=LP, pidfile=pf)
check("4 nothing to reap -> reaped=0 left=0, no taskkill", rn.killed() == [] and lines == ["reaped=0 left=0"], str(lines))
# lease owner
KA.lease_write("t_card", LP, lambda: NOW)
lease_pid_inside = json.load(open(LP)); lease_pid_inside["pid"] = 12; json.dump(lease_pid_inside, open(LP, "w"))
rn, lines = Runner(procs=PROCS), []
rc = B.reap(60, runner=rn, out=lines.append, procs=PROCS, now=lambda: NOW, lease_path=LP, pidfile=pf)
check("4 a tree holding the FRESH lease owner is never killed (reported, counted as left, exit 1)", rn.killed() == [60] and lines[-1] == "reaped=1 left=1" and any("fresh card lease" in l for l in lines) and rc == 1, str(lines))
lease_pid_inside["at"] = NOW - KA.LEASE_TTL - 10; json.dump(lease_pid_inside, open(LP, "w"))
rn, lines = Runner(procs=PROCS), []
B.reap(60, runner=rn, out=lines.append, procs=PROCS, now=lambda: NOW, lease_path=LP, pidfile=pf)
check("4 a STALE lease protects nothing", sorted(rn.killed()) == [10, 60], str(rn.killed()))
KA.lease_write("t_card", LP, lambda: NOW)
B.pidfile_write(9333, pf, pid=60)
rn, lines = Runner(procs=PROCS), []
B.reap(60, runner=rn, out=lines.append, procs=PROCS, now=lambda: NOW, lease_path=LP, pidfile=pf)
check("4 while a lease is fresh, the pidfile python (the live batch's own build_chrome) is protected too", 60 not in rn.killed(), str(rn.killed()))
KA.lease_release(LP); B.pidfile_remove(pf)
# own ancestry
me = os.getpid()
mine = [proc(me, 900, "python job/build_chrome.py --reap", 500), proc(900, 1, 'bash -c "python job/build_chrome.py --reap"', 500)]
rn, lines = Runner(procs=mine), []
B.reap(0, runner=rn, out=lines.append, procs=mine, now=lambda: NOW, lease_path=LP, pidfile=pf)
check("4 --reap never targets itself or its own wrapper", rn.killed() == [])
# --stop's reap: only when Chrome is gone
rn, lines = Runner(procs=PROCS, listening=True), []
rc = B.stop(9333, rn, lines.append, pidfile=pf, procs=PROCS, lease_path=LP)
check("5 --stop ends with a reap(0) of build_chrome.py pythons once the Chrome is gone", sorted(rn.killed()) == [10, 20, 60, 22460] and rc == 0, str(rn.killed()))
rn, lines = Runner(procs=PROCS, listening=True), []
B.reap(0, runner=rn, out=lines.append, procs=PROCS, now=lambda: NOW, lease_path=LP, pidfile=pf, only_chrome_gone=9333, alive=lambda: True, quiet_none=True)
check("5 ...and leaves them alone while a Chrome still answers", rn.killed() == [], str(rn.killed()))

# ---- 6 wiring ----------------------------------------------------------------------------------------------------------------------------------------
for flag in ('"--reap"', '"--older-than-minutes"', "if n.reap: return reap(n.older_than_minutes)", "pidfile_write(oc.port)", "hold(oc.port, end)", "pidfile_remove(only_pid=os.getpid())"):
    check("6 build_chrome.py main wires " + flag, flag in src)
check("6 --reap starts no Chrome (returns before window_count)", src.index("if n.reap") < src.index("before = window_count()"))
check("6 code under test calls taskkill only through the injected runner", "os.system" not in src and "Popen" not in src)
ci = open(os.path.join(HERE, "..", ".github", "workflows", os.listdir(os.path.join(HERE, "..", ".github", "workflows"))[0]), encoding="utf-8").read()
check("CI runs this file", "tests/build_chrome_leak_test.py" in ci)

print("\n%d passed, %d failed" % (sum(ok), len(ok) - sum(ok)))
sys.exit(0 if all(ok) else 1)
