"""Per-domain read guard shared across processes (t_e34fc55c). A Directory is read once per need, spaced out, and a quota / block page stops reads to that site.

A file ledger (CE_SITE_GUARD, default %LOCALAPPDATA%/citation-engine/site-guard.json) holds per domain: last read time, reads today, cooldown_until.
  reserve(domain, key)  -> {"ok": True, "waited": s} after sleeping out the min gap (CE_SITE_GAP, default 60s), or {"ok": False, "why": ...} on cooldown / daily cap
  wall(domain, ...)     -> cooldown until the next local midnight; ONE line to logs/site-walls.jsonl
  wall_counts(days)     -> {domain: n} from site-walls.jsonl
Two processes serialise on an O_EXCL lock file; the gap slot is claimed inside the lock and slept out after it, so concurrent readers queue instead of stampeding.
Reads only. Never touches a Directory itself.
"""
import datetime, json, os, time

GAP_S = 60
DAILY_CAP = {"bizapedia.com": 3}   # free searches a day; the site's own quota wall is lower than our habit
SAME_READ_S = 300                  # the same URL asked again inside this window (plain, then the Chrome fallback) is one read


def _lad():
    return os.path.expandvars("%LOCALAPPDATA%/citation-engine")


def ledger_path():
    return os.environ.get("CE_SITE_GUARD") or os.path.join(_lad(), "site-guard.json")


def logs_dir():
    return os.environ.get("CE_LOGS") or os.path.join(_lad(), "logs")


def gap_s():
    try: return float(os.environ.get("CE_SITE_GAP", GAP_S))
    except ValueError: return GAP_S


def domain_of(url):
    from urllib.parse import urlparse
    h = (urlparse(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _append(name, rec, logs=None):
    d = logs or logs_dir()
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "a", encoding="utf-8") as f: f.write(json.dumps(rec, sort_keys=True) + "\n")
    except OSError:
        pass   # a log line must never stop a read decision


class _Lock:
    def __init__(self, path, timeout=60):
        self.p, self.timeout = path + ".lock", timeout

    def __enter__(self):
        end = time.time() + self.timeout
        while True:
            try:
                self.fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY); return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.p) > 30: os.remove(self.p); continue   # a crashed holder
                except OSError: pass
                if time.time() > end: raise TimeoutError("site guard lock busy")
                time.sleep(0.05)

    def __exit__(self, *a):
        try: os.close(self.fd)
        except OSError: pass
        try: os.remove(self.p)
        except OSError: pass


class SiteGuard:
    def __init__(self, path=None, gap=None, caps=None, now=time.time, sleep=time.sleep, logs=None):
        self.path, self.gap, self.caps = path or ledger_path(), gap_s() if gap is None else gap, DAILY_CAP if caps is None else caps
        self.now, self.sleep, self.logs = now, sleep, logs
        self._mine = {}   # domain -> the URL THIS process reserved last: only our own plain-then-Chrome fallback is "the same read", never another process
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f: return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self, led):
        tmp = self.path + ".tmp%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f: json.dump(led, f, sort_keys=True)
        os.replace(tmp, self.path)

    def _day(self, t): return datetime.datetime.fromtimestamp(t).date().isoformat()

    def reserve(self, domain, key=None):
        with _Lock(self.path):
            led = self._load(); t = self.now(); e = led.setdefault(domain, {})
            if e.get("cooldown_until", 0) > t:
                return {"ok": False, "why": "cooldown until %s after a wall" % datetime.datetime.fromtimestamp(e["cooldown_until"]).strftime("%Y-%m-%d %H:%M")}
            if key and self._mine.get(domain) == key and e.get("last_key") == key and t - e.get("last", 0) < SAME_READ_S:
                return {"ok": True, "waited": 0.0, "same_read": True}
            today = self._day(t)
            n = e.get("count", 0) if e.get("day") == today else 0
            cap = self.caps.get(domain)
            if cap is not None and n >= cap:
                return {"ok": False, "why": "daily cap %d reached for %s" % (cap, domain)}
            slot = max(t, e.get("last", 0) + self.gap)   # claim the slot now; others queue behind it
            e.update(last=slot, last_key=key, day=today, count=n + 1)
            self._mine[domain] = key
            self._save(led)
        waited = max(0.0, slot - t)
        if waited > 0: self.sleep(waited)
        _append("site-reads.jsonl", {"at": datetime.datetime.fromtimestamp(slot).isoformat(timespec="seconds"), "domain": domain, "waited_s": round(waited, 1), "read": n + 1}, self.logs)
        return {"ok": True, "waited": waited}

    def wall(self, domain, reason, url=None, row=None):
        """Cooldown to the next local midnight; one line in site-walls.jsonl (not again while the cooldown already stands)."""
        with _Lock(self.path):
            led = self._load(); t = self.now(); e = led.setdefault(domain, {})
            if e.get("cooldown_until", 0) > t: return False
            nxt = datetime.datetime.combine(datetime.datetime.fromtimestamp(t).date() + datetime.timedelta(days=1), datetime.time(0, 5))
            e["cooldown_until"] = nxt.timestamp()
            self._save(led)
        _append("site-walls.jsonl", {"at": datetime.datetime.fromtimestamp(t).isoformat(timespec="seconds"), "domain": domain, "reason": reason, "url": (url or "")[:200], "row": row,
                                     "cooldown_until": nxt.isoformat(timespec="minutes")}, self.logs)
        return True


def wall_counts(days=7, logs=None, today=None):
    """{domain: walls in the last `days` days} from site-walls.jsonl. Missing file = {}."""
    p = os.path.join(logs or logs_dir(), "site-walls.jsonl")
    cut = (today or datetime.date.today()) - datetime.timedelta(days=days)
    out = {}
    try:
        for ln in open(p, encoding="utf-8"):
            try: r = json.loads(ln)
            except ValueError: continue
            if str(r.get("at", ""))[:10] > cut.isoformat(): out[r["domain"]] = out.get(r["domain"], 0) + 1
    except OSError:
        pass
    return dict(sorted(out.items()))


def render_counts(counts):
    if not counts: return "SITE WALLS (7d): none"
    return "SITE WALLS (7d): " + ", ".join("%s walled %d time%s" % (d, n, "" if n == 1 else "s") for d, n in counts.items())
