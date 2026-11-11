"""Build browser for Lis (citation-submitter): the owned REAL Chrome, headful, with a persistent build profile.

Same launcher as the finder (owned_chrome.OwnedChrome: Job Object kills the whole tree on exit or crash, never attaches to an
existing Chrome). Difference: the profile is persistent (%LOCALAPPDATA%/citation-engine/build-profile) so Directory logins and
cookies survive between batches, and the CDP port is fixed (default 9333) so the submitter can be pointed at it.
This is an ordinary Chrome. No spoofing, no stealth flags, no CAPTCHA handling. A human still solves any challenge.

  python job/build_chrome.py                 # start, print cdp_url, run until Ctrl+C
  python job/build_chrome.py --seconds 600   # start, run 10 minutes, close (logs a WARNING line 5 minutes before)
  python job/build_chrome.py --reap          # FIRST step of a batch: kill build_chrome.py trees older than 60 min (--older-than-minutes N); a fresh card lease is never killed
  python job/build_chrome.py --stop          # LAST step of a batch: kill the Chrome on CDP 9333 AND this script's own python (pidfile), whole trees
  python job/build_chrome.py --seconds 0     # a BATCH: run until stopped or the 4 h idle cap (CE_BUILD_MAX_SECONDS=14400; a fresh card lease holds it open)
Output lines: cdp_url=..., windows_before/during/after. Window count before must equal after.
The hold loop also ends by itself when its Chrome is gone (chrome_gone=1), so no build_chrome.py python outlives its batch (t_15f7ec86).
"""
import os, sys, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chrome_keepalive as KA

PROFILE = os.environ.get("CE_BUILD_PROFILE") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/build-profile")
PORT = 9333
LOCAL = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
MAX_SECONDS_DEFAULT = 14400
GONE_AFTER_MISSES = 2     # consecutive failed CDP checks before the Chrome counts as gone
CHECK_EVERY = 5           # seconds between Chrome-alive checks


def build_chrome(profile=None, port=None):
    """OwnedChrome on the persistent build profile and the fixed build port. Use as a context manager."""
    from owned_chrome import OwnedChrome
    return OwnedChrome(profile=profile or PROFILE, port=port or PORT)


def pidfile_path(): return os.environ.get("CE_BUILD_PIDFILE") or os.path.join(LOCAL, "citation-engine", "build-chrome.pid")


def max_seconds(env=None):
    try: v = int((os.environ if env is None else env).get("CE_BUILD_MAX_SECONDS") or MAX_SECONDS_DEFAULT)
    except ValueError: v = MAX_SECONDS_DEFAULT
    return v if v > 0 else MAX_SECONDS_DEFAULT


def pidfile_write(port, path=None, now=time.time, pid=None):
    import json
    path = path or pidfile_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: json.dump({"pid": pid or os.getpid(), "port": port, "started": now()}, f)


def pidfile_read(path=None):
    import json
    try:
        with open(path or pidfile_path(), encoding="utf-8") as f: return json.load(f)
    except Exception:
        return None


def pidfile_remove(path=None, only_pid=None):
    path = path or pidfile_path()
    if only_pid is not None and (pidfile_read(path) or {}).get("pid") != only_pid: return
    try: os.remove(path)
    except OSError: pass


def hold(port, end, alive=None, lease_path=None, now=time.time, sleep=time.sleep, out=lambda s: print(s, flush=True), max_s=None, check_every=CHECK_EVERY):
    """The hold loop. Returns "timer" (--seconds ran out, no lease), "cap" (--seconds 0 hit the idle cap, no lease) or "chrome_gone" (the owned Chrome stopped answering).
    --seconds 0 (end None) closes after CE_BUILD_MAX_SECONDS unless a card lease is fresh (KA.should_close asks again every second)."""
    alive = alive or (lambda: KA.cdp_alive(port))
    cap = end is None
    limit = max_s or max_seconds()
    stop_at = now() + limit if cap else end
    warned, misses, last = False, 0, now()
    while not KA.should_close(stop_at, lease_path or KA.LEASE_PATH, now):
        w = KA.close_warning(end, warned)
        if w: out(w); warned = True
        sleep(1)
        if now() - last >= check_every or check_every <= 1:
            last = now()
            misses = 0 if alive() else misses + 1
            if misses >= GONE_AFTER_MISSES:
                out("chrome_gone=1"); return "chrome_gone"
    if cap: out("idle_cap_reached=1 (--seconds 0 closes after %d s with no fresh card lease)" % limit)
    return "cap" if cap else "timer"


def listener_pids(port, runner=None):
    """PIDs LISTENING on 127.0.0.1/0.0.0.0/[::1]:port, from `netstat -ano -p tcp`. [] when none."""
    import subprocess, re
    r = (runner or subprocess.run)(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=30)
    pids = []
    for line in (getattr(r, "stdout", "") or "").splitlines():
        m = re.match(r"\s*TCP\s+(\S+):(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$", line)
        if m and int(m.group(2)) == int(port) and m.group(1) in ("127.0.0.1", "0.0.0.0", "[::1]", "[::]") and int(m.group(3)) not in pids:
            pids.append(int(m.group(3)))
    return pids


def _tk(pid, run, out):
    r = run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=60)
    out("taskkill /PID %d /T /F -> exit %s" % (pid, getattr(r, "returncode", "?")))


def stop(port=PORT, runner=None, out=print, pidfile=None, procs=None, lease_path=None):
    """--stop (t_89f4aebf, t_15f7ec86): kill the process tree of whatever listens on the CDP port (`taskkill /PID n /T /F`), then the build_chrome.py python recorded in
    the pidfile (its whole tree), remove the pidfile, and reap any build_chrome.py python whose Chrome is gone. Returns 0 when nothing is left listening, 1 when a
    listener survived, 2 when nothing was listening."""
    import subprocess
    run = runner or subprocess.run
    pids = listener_pids(port, runner)
    if not pids: out("no listener on port %d (nothing to stop)" % port)
    for pid in pids: _tk(pid, run, out)
    left = listener_pids(port, runner) if pids else []
    if pids: out("port %d listener after: %s" % (port, ",".join(map(str, left)) or "none"))
    pf = pidfile or pidfile_path()
    rec = pidfile_read(pf)
    if rec and rec.get("pid") and int(rec["pid"]) != os.getpid() and int(rec["pid"]) not in pids:
        out("pidfile python pid %s" % rec["pid"]); _tk(int(rec["pid"]), run, out)
    pidfile_remove(pf)
    if not left:
        reap(0, runner=runner, out=out, procs=procs, lease_path=lease_path, pidfile=pf, only_chrome_gone=port, quiet_none=True)
    return 1 if left else (0 if pids else 2)


def list_procs(runner=None):
    """[{pid, ppid, cmd, started}] for every process (Windows: PowerShell Get-CimInstance; `started` = epoch seconds). [] when the listing fails."""
    import subprocess, json
    ps = ("Get-CimInstance Win32_Process | ForEach-Object { [pscustomobject]@{pid=$_.ProcessId; ppid=$_.ParentProcessId; cmd=$_.CommandLine; "
          "started=[int64]([DateTimeOffset]$_.CreationDate).ToUnixTimeSeconds()} } | ConvertTo-Json -Compress")
    try: r = (runner or subprocess.run)(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError): return []
    try: data = json.loads(getattr(r, "stdout", "") or "[]")
    except ValueError: return []
    if isinstance(data, dict): data = [data]
    return [{"pid": int(d["pid"]), "ppid": int(d.get("ppid") or 0), "cmd": d.get("cmd") or "", "started": float(d.get("started") or 0)} for d in data if d.get("pid")]


def _is_build_cmd(cmd):
    c = (cmd or "").replace("\\", "/")
    return "job/build_chrome.py" in c and "--stop" not in c and "--reap" not in c


def reap(older_than_minutes=60, runner=None, out=print, procs=None, now=time.time, lease_path=None, pidfile=None, only_chrome_gone=None, quiet_none=False, alive=None):
    """--reap (t_15f7ec86): kill (taskkill /PID n /T /F) every tree whose root is a `job/build_chrome.py` process older than N minutes. A command line with --stop or
    --reap is never a target. A tree holding the process that owns a FRESH card lease (lease pid, and the pidfile python while a lease is fresh) is left alone.
    only_chrome_gone=<port>: only trees whose Chrome no longer answers on that port. Returns 0 when none are left, 1 when one survived or was skipped."""
    import subprocess
    run = runner or subprocess.run
    plist = procs if procs is not None else list_procs(runner)
    by_pid = {p["pid"]: p for p in plist}
    me, x = {os.getpid()}, os.getpid()
    while x in by_pid and by_pid[x]["ppid"] not in me:   # never kill our own ancestors
        x = by_pid[x]["ppid"]; me.add(x)
    cand = {p["pid"] for p in plist if _is_build_cmd(p["cmd"]) and p["pid"] not in me}
    roots = [pid for pid in cand if by_pid[pid]["ppid"] not in cand]   # topmost build_chrome line of each wrapper chain

    def tree(root):
        t, todo = {root}, [root]
        while todo:
            c = todo.pop()
            for p in plist:
                if p["ppid"] == c and p["pid"] not in t: t.add(p["pid"]); todo.append(p["pid"])
        return t
    lease = KA.lease_active(lease_path or KA.LEASE_PATH, now)
    guard = set()
    if lease:
        if lease.get("pid"): guard.add(int(lease["pid"]))
        pf = pidfile_read(pidfile)
        if pf and pf.get("pid"): guard.add(int(pf["pid"]))
    gone = True
    if only_chrome_gone is not None:
        gone = not (alive() if alive else KA.cdp_alive(only_chrome_gone))
    reaped = left = 0
    for root in sorted(roots):
        p = by_pid[root]
        age_min = (now() - p["started"]) / 60.0 if p["started"] else 1e9
        if age_min < older_than_minutes or not gone: continue
        t = tree(root)
        if t & guard:
            out("skip tree %d (%d procs): owns a fresh card lease" % (root, len(t))); left += 1; continue
        out("reap tree %d (%d procs, %.0f min old): %s" % (root, len(t), min(age_min, 99999), (p["cmd"] or "")[:100]))
        _tk(root, run, out); reaped += 1
    if reaped or left or not quiet_none: out("reaped=%d left=%d" % (reaped, left))
    return 0 if left == 0 else 1


def main(argv=None):
    a = argparse.ArgumentParser(description="Start the owned real Chrome for Lis (persistent profile, CDP port)")
    a.add_argument("--port", type=int, default=PORT)
    a.add_argument("--profile", default=PROFILE)
    a.add_argument("--seconds", type=int, default=0, help="close after N seconds (0 = until stopped or the CE_BUILD_MAX_SECONDS idle cap, default 4 h)")
    a.add_argument("--stop", action="store_true", help="kill the process tree listening on --port (taskkill /PID n /T /F), the pidfile python, and exit; starts nothing")
    a.add_argument("--reap", action="store_true", help="kill build_chrome.py trees older than --older-than-minutes (skips a fresh card lease) and exit; starts nothing")
    a.add_argument("--older-than-minutes", type=int, default=60)
    n = a.parse_args(argv)
    if n.stop: return stop(n.port)
    if n.reap: return reap(n.older_than_minutes)
    from owned_chrome import window_count
    before = window_count()
    print("windows_before=%d" % before, flush=True)
    try:
        with build_chrome(n.profile, n.port) as oc:
            print("cdp_url=%s" % oc.cdp_url, flush=True)
            print("profile=%s (persistent, kept on exit)" % oc.profile, flush=True)
            print("windows_during=%d" % window_count(oc.job), flush=True)
            pidfile_write(oc.port)
            end = time.time() + n.seconds if n.seconds else None
            print("lease=%s" % ("until stopped or %d s idle cap (--seconds 0), pid %d" % (max_seconds(), os.getpid()) if end is None else "closes in %d s unless a card lease is fresh" % n.seconds), flush=True)
            try:
                swept = KA.sweep_foreign_tabs(oc.port)
                print("tabs_closed=%d%s" % (len(swept), (" (" + ", ".join(swept) + ")") if swept else ""), flush=True)
            except Exception as e:
                print("tabs_closed=0 (sweep skipped: %s)" % str(e)[:80], flush=True)
            try:
                # t_d7a907d5: the timer does not fire while a card holds the lease (job/chrome_keepalive.py); it asks again every second.
                # t_15f7ec86: the loop also ends when its Chrome is gone, and --seconds 0 has a 4 h idle cap.
                hold(oc.port, end)
            except KeyboardInterrupt:
                pass
    finally:
        pidfile_remove(only_pid=os.getpid())
        time.sleep(1)
        after = window_count()
        print("windows_after=%d  %s" % (after, "OK" if after == before else "MISMATCH"), flush=True)
    return 0 if after == before else 3


if __name__ == "__main__":
    sys.exit(main())
