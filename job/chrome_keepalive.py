"""Keep the build Chrome (CDP 9333, persistent build profile) up for a whole batch (t_d7a907d5). No Windows-only imports, so CI tests it.

Why it died in batch 9: `build_chrome.py` starts Chrome inside a Job Object (KILL_ON_JOB_CLOSE) owned by that python process. When its `--seconds` timer ran
out, or the python process ended, the whole tree went with it, mid-batch.  Three changes:
  1. ensure_up(): if nothing answers on the port, start Chrome again on the SAME profile (cookies / logins live in the profile, so they are kept) as a
     detached process, not in a Job Object, so it outlives the runner that started it.
  2. A lease file: a card that works in the build Chrome holds a lease (card id + timestamp, refreshed by every step). build_chrome.py's timer calls
     should_close(): while a fresh lease exists it does NOT close, it waits and asks again.
  3. The runner calls ensure_up() before a step whose Chrome has gone and re-opens from the last `open` step (build_runner.run_site).
The lease is advisory and expires (LEASE_TTL seconds without a refresh), so a crashed card cannot pin Chrome open forever.
"""
import json, os, subprocess, sys, time, urllib.request

LOCAL = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
PROFILE = os.environ.get("CE_BUILD_PROFILE") or os.path.join(LOCAL, "citation-engine", "build-profile")
LEASE_PATH = os.environ.get("CE_BUILD_LEASE") or os.path.join(LOCAL, "citation-engine", "build-chrome.lease")
CHROME = os.environ.get("CE_CHROME") or "C:/Program Files/Google/Chrome/Application/chrome.exe"
PORT = 9333
LEASE_TTL = 900   # seconds without a refresh before a lease no longer holds Chrome open


def cdp_alive(port=PORT, urlopen=urllib.request.urlopen, timeout=2):
    """True when something answers /json/version on 127.0.0.1:port."""
    try:
        urlopen("http://127.0.0.1:%d/json/version" % port, timeout=timeout)
        return True
    except Exception:
        return False


def chrome_args(profile=PROFILE, port=PORT, chrome=CHROME):
    return [chrome, "--remote-debugging-port=%d" % port, "--user-data-dir=%s" % profile, "--window-position=40,40", "--window-size=1400,900",
            "--no-first-run", "--no-default-browser-check", "about:blank"]


def _detached_flags():
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: not a child of this console, not in this process's Job Object
    return (0x00000008 | 0x00000200) if sys.platform == "win32" else 0


def ensure_up(port=PORT, profile=PROFILE, *, alive=None, popen=None, sleep=time.sleep, wait_s=40, chrome=CHROME):
    """-> "up" (already answering) or "restarted" (started it on the same profile). RuntimeError when it does not come up in wait_s."""
    alive = alive or (lambda: cdp_alive(port))
    if alive(): return "up"
    os.makedirs(profile, exist_ok=True)
    kw = {"creationflags": _detached_flags()} if sys.platform == "win32" else {"start_new_session": True}
    (popen or subprocess.Popen)(chrome_args(profile, port, chrome), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **kw)
    for _ in range(max(1, int(wait_s / 0.5))):
        if alive(): return "restarted"
        sleep(0.5)
    raise RuntimeError("build Chrome did not answer on port %d within %ds after a restart (profile %s)" % (port, wait_s, profile))


# ---- lease ---------------------------------------------------------------------------------------------------------------
def lease_write(card, path=LEASE_PATH, now=time.time):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: json.dump({"card": card, "at": now(), "pid": os.getpid()}, f)


def lease_read(path=LEASE_PATH):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except Exception:
        return None


def lease_active(path=LEASE_PATH, now=time.time, ttl=LEASE_TTL):
    """-> the lease dict while it is fresh, else None."""
    lease = lease_read(path)
    return lease if lease and (now() - float(lease.get("at") or 0)) < ttl else None


def lease_release(path=LEASE_PATH):
    try: os.remove(path)
    except OSError: pass


def should_close(end_time, path=LEASE_PATH, now=time.time, ttl=LEASE_TTL):
    """The `--seconds` timer's question. False while a card holds a fresh lease (the timer does not fire), True once the timer is out and nobody holds it."""
    if end_time is None or now() < end_time: return False
    return lease_active(path, now, ttl) is None


class Lease:
    """with Lease("t_xxxx"): ...  Holds the build Chrome for a card; touch() refreshes it (the runner does this before every step)."""
    def __init__(self, card, path=LEASE_PATH, now=time.time):
        self.card, self.path, self.now = card, path, now
    def touch(self): lease_write(self.card, self.path, self.now)
    def __enter__(self): self.touch(); return self
    def __exit__(self, *a): lease_release(self.path); return False
