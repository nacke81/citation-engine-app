"""Build browser for Lis (citation-submitter): the owned REAL Chrome, headful, with a persistent build profile.

Same launcher as the finder (owned_chrome.OwnedChrome: Job Object kills the whole tree on exit or crash, never attaches to an
existing Chrome). Difference: the profile is persistent (%LOCALAPPDATA%/citation-engine/build-profile) so Directory logins and
cookies survive between batches, and the CDP port is fixed (default 9333) so the submitter can be pointed at it.
This is an ordinary Chrome. No spoofing, no stealth flags, no CAPTCHA handling. A human still solves any challenge.

  python job/build_chrome.py                 # start, print cdp_url, run until Ctrl+C
  python job/build_chrome.py --seconds 600   # start, run 10 minutes, close (logs a WARNING line 5 minutes before)
  python job/build_chrome.py --stop          # LAST step of a batch: kill the Chrome listening on CDP 9333 and its whole process tree
  python job/build_chrome.py --seconds 0     # a BATCH: run until stopped (taskkill /PID <pid> /T /F); never closes on a timer
Output lines: cdp_url=..., windows_before/during/after. Window count before must equal after.
"""
import os, sys, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from owned_chrome import OwnedChrome, window_count
import chrome_keepalive as KA

PROFILE = os.environ.get("CE_BUILD_PROFILE") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/build-profile")
PORT = 9333


def build_chrome(profile=None, port=None):
    """OwnedChrome on the persistent build profile and the fixed build port. Use as a context manager."""
    return OwnedChrome(profile=profile or PROFILE, port=port or PORT)


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


def stop(port=PORT, runner=None, out=print):
    """--stop (t_89f4aebf): kill the process tree of whatever listens on the CDP port (`taskkill /PID n /T /F`). A Chrome started by an earlier card cannot be
    killed by the process manager. Returns 0 when nothing is left listening, 1 when a listener survived, 2 when nothing was listening."""
    import subprocess
    run = runner or subprocess.run
    pids = listener_pids(port, runner)
    if not pids: out("no listener on port %d (nothing to stop)" % port); return 2
    for pid in pids:
        r = run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=60)
        out("taskkill /PID %d /T /F -> exit %s" % (pid, getattr(r, "returncode", "?")))
    left = listener_pids(port, runner)
    out("port %d listener after: %s" % (port, ",".join(map(str, left)) or "none"))
    return 1 if left else 0


def main(argv=None):
    a = argparse.ArgumentParser(description="Start the owned real Chrome for Lis (persistent profile, CDP port)")
    a.add_argument("--port", type=int, default=PORT)
    a.add_argument("--profile", default=PROFILE)
    a.add_argument("--seconds", type=int, default=0, help="close after N seconds (0 = until Ctrl+C)")
    a.add_argument("--stop", action="store_true", help="kill the process tree listening on --port (taskkill /PID n /T /F) and exit; starts nothing")
    n = a.parse_args(argv)
    if n.stop: return stop(n.port)
    before = window_count()
    print("windows_before=%d" % before, flush=True)
    try:
        with build_chrome(n.profile, n.port) as oc:
            print("cdp_url=%s" % oc.cdp_url, flush=True)
            print("profile=%s (persistent, kept on exit)" % oc.profile, flush=True)
            print("windows_during=%d" % window_count(oc.job), flush=True)
            end = time.time() + n.seconds if n.seconds else None
            print("lease=%s" % ("until stopped (--seconds 0), pid %d" % os.getpid() if end is None else "closes in %d s unless a card lease is fresh" % n.seconds), flush=True)
            try:
                swept = KA.sweep_foreign_tabs(oc.port)
                print("tabs_closed=%d%s" % (len(swept), (" (" + ", ".join(swept) + ")") if swept else ""), flush=True)
            except Exception as e:
                print("tabs_closed=0 (sweep skipped: %s)" % str(e)[:80], flush=True)
            warned = False
            try:
                # t_d7a907d5: the timer does not fire while a card holds the lease (job/chrome_keepalive.py); it asks again every second.
                while end is None or not KA.should_close(end):
                    w = KA.close_warning(end, warned)
                    if w: print(w, flush=True); warned = True
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    finally:
        time.sleep(1)
        after = window_count()
        print("windows_after=%d  %s" % (after, "OK" if after == before else "MISMATCH"), flush=True)
    return 0 if after == before else 3


if __name__ == "__main__":
    sys.exit(main())
