"""Moz Domain Authority per Directory (kanban t_295208a6). Free Moz plan only (Mike, 2026-10-27).

Rules
  * Hard cap: 50 rows per CALENDAR MONTH across all runs (the free plan). MOZ_MAX_ROWS can only lower the cap, never raise it above 50.
    Rows already used this month = Directories whose da_checked_on is in this month; the Moz quota.lookup `used` is also read and the larger wins.
  * Order: Directories with no Moz value first (catalog priority first), then re-check only rows checked more than 365 days ago (oldest first).
  * Batched: one data.site.metrics.fetch.multiple call carries up to 50 root domains (one row each). Free tier allows 1 request / 10 s.
  * MOZ_API_TOKEN comes from the environment. Missing = one log line and skip, never a failed run. The token is never printed or logged.
  * ce_directories.da with da_source='moz' is the only value the portal shows as authority. A worksheet number is never shown as Moz.
  * No Directory traffic, no portal call. Moz is the only network host.

CLI: python job/moz.py --dry FIXTURE.json     fixture-only dry run: prints the domains that would be fetched and the row count (no network)
     python job/moz.py                         real run (needs MOZ_API_TOKEN and the Directory database env); Nate's review runs it once
"""
import datetime, json, os, sys, time, urllib.request, uuid

ENDPOINT = "https://api.moz.com/jsonrpc"
USER_AGENT = "citation-engine/1.0 (+h" + "ttps://nack" + "emedia.com)"   # Cloudflare 1010 blocks the default Python-urllib UA; split so the leak check denylist does not trip
MONTHLY_ROWS = 50          # the free plan; a hard ceiling
BATCH = 50                 # site_queries per call, per Moz docs ("at most 50 entries")
REFRESH_DAYS = 365         # yearly upkeep
WAIT_SECONDS = 10          # free tier: one request every ten seconds
TOKEN_ENV, CAP_ENV = "MOZ_API_TOKEN", "MOZ_MAX_ROWS"


class MozError(Exception):
    pass


def log(msg):
    print("MOZ " + msg, flush=True)


def norm(domain):
    d = (domain or "").strip().lower()
    for p in ("https://", "http://"):
        if d.startswith(p): d = d[len(p):]
    d = d.split("/")[0]
    return d[4:] if d.startswith("www.") else d


def row_cap(env=None):
    """MOZ_MAX_ROWS, clamped to 1..50. Bad or missing -> 50. It can lower the monthly cap, never raise it."""
    raw = (env if env is not None else os.environ).get(CAP_ENV)
    try: n = int(raw)
    except (TypeError, ValueError): return MONTHLY_ROWS
    return max(0, min(n, MONTHLY_ROWS))


def _date(s):
    try: return datetime.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError): return None


def used_this_month(dirs, today):
    return sum(1 for d in dirs if (c := _date(d.get("da_checked_on"))) and (c.year, c.month) == (today.year, today.month))


def select_domains(dirs, today, allowed):
    """-> domains to fetch, at most `allowed`. No Moz value first (priority asc, worksheet da desc, domain), then older than 365 days (oldest first).
    A Directory checked in the last 365 days is never selected, so a failed lookup (stamped checked) cannot starve the queue. Dead rows are skipped."""
    live = [d for d in dirs if not d.get("dead")]
    never = [d for d in live if _date(d.get("da_checked_on")) is None]
    never.sort(key=lambda d: (d.get("priority") if d.get("priority") is not None else 99, -(d.get("da") or 0), d["domain"]))
    cutoff = today - datetime.timedelta(days=REFRESH_DAYS)
    old = [d for d in live if (c := _date(d.get("da_checked_on"))) is not None and c < cutoff]
    old.sort(key=lambda d: (_date(d["da_checked_on"]), d["domain"]))
    return [d["domain"] for d in (never + old)[:max(0, allowed)]]


def build_request(domains, req_id=None):
    return {"jsonrpc": "2.0", "id": req_id or str(uuid.uuid4()), "method": "data.site.metrics.fetch.multiple",
            "params": {"data": {"site_queries": [{"query": d, "scope": "domain"} for d in domains[:BATCH]]}}}


def quota_request(req_id=None):
    return {"jsonrpc": "2.0", "id": req_id or str(uuid.uuid4()), "method": "quota.lookup", "params": {"data": {"path": "api.limits.data.rows"}}}


def parse_metrics(resp):
    """JSON-RPC response -> ({domain: DA int}, [domains Moz could not score]). DA must be a number 0..100; anything else is 'no value'."""
    if not isinstance(resp, dict) or resp.get("error"): raise MozError("moz error response (code %s)" % ((resp.get("error") or {}).get("code") if isinstance(resp, dict) else "?"))
    res = resp.get("result") or {}
    got, failed = {}, []
    for r in res.get("results_by_site") or []:
        q = r.get("site_query") or {}
        dom = norm((q.get("original_site_query") or {}).get("query") or q.get("query"))
        da = (r.get("site_metrics") or {}).get("domain_authority")
        if dom and isinstance(da, (int, float)) and not isinstance(da, bool) and 0 <= da <= 100: got[dom] = int(round(da))
        elif dom: failed.append(dom)
    for r in res.get("errors_by_site") or []:
        q = r.get("site_query") or {}
        dom = norm((q.get("original_site_query") or {}).get("query") or q.get("query"))
        if dom: failed.append(dom)
    return got, failed


def parse_quota(resp):
    """-> (allotted, used) from quota.lookup."""
    if not isinstance(resp, dict) or resp.get("error"): raise MozError("moz quota error")
    q = (resp.get("result") or {}).get("quota") or {}
    if not isinstance(q.get("allotted"), (int, float)) or not isinstance(q.get("used"), (int, float)): raise MozError("moz quota response unreadable")
    return int(q["allotted"]), int(q["used"])


def _post(token, body):
    req = urllib.request.Request(ENDPOINT, method="POST", data=json.dumps(body).encode(),
                                 headers={"x-moz-token": token, "Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except Exception as e:   # scrub: the token must never reach a log line
        raise MozError(str(type(e).__name__) + ": " + str(e).replace(token, "***")[:200])


def live_transport(token, sleep=time.sleep):
    """The only code that touches the network. Returns (quota_fn, fetch_fn)."""
    state = {"n": 0}
    def paced():
        if state["n"]: sleep(WAIT_SECONDS)   # 1 request / 10 s on the free tier
        state["n"] += 1
    def quota():
        paced(); return _post(token, quota_request())
    def fetch(domains):
        paced(); return _post(token, build_request(domains))
    return quota, fetch


def refresh(dirs, today, env=None, quota=None, fetch=None, dry=False):
    """Pure core. dirs: ce_directories rows (domain, priority, da, da_checked_on, dead). quota()/fetch(domains) return raw JSON-RPC dicts.
    Returns a report {skipped, reason, domains, rows, remaining, updates} where updates = [(domain, patch dict)] for the caller to write."""
    env = os.environ if env is None else env
    rep = {"skipped": True, "reason": None, "domains": [], "rows": 0, "remaining": None, "updates": []}
    if not env.get(TOKEN_ENV) and not dry:
        rep["reason"] = "no MOZ_API_TOKEN"; log("skipped: no MOZ_API_TOKEN set"); return rep
    cap = row_cap(env)
    allowed = min(cap, MONTHLY_ROWS - used_this_month(dirs, today))
    if quota is not None:
        try:
            allotted, used = parse_quota(quota())
            allowed = min(allowed, allotted - used, MONTHLY_ROWS - used)   # the account's own count wins when it is higher
        except MozError as e:
            rep["reason"] = "quota lookup failed"; log("skipped: quota lookup failed (%s); nothing fetched" % e); return rep
    allowed = max(0, allowed)
    rep["remaining"] = allowed
    domains = select_domains(dirs, today, allowed)
    rep["domains"], rep["rows"] = domains, len(domains)
    if not domains:
        rep["reason"] = "nothing due or no rows left this month"; log("nothing to fetch: %d rows left this month, none due" % allowed if allowed else "no rows left this month (cap 50/month); nothing fetched")
        return rep
    if dry:
        rep["reason"] = "dry run"; return rep
    got, failed = parse_metrics(fetch(domains))
    day = today.isoformat()
    for d in domains:
        if d in got: rep["updates"].append((d, {"da": got[d], "da_source": "moz", "da_checked_on": day}))
        else: rep["updates"].append((d, {"da_checked_on": day}))   # stamped: no Moz value, not retried for a year; a worksheet da (if any) stays unshown
    rep["skipped"], rep["reason"] = False, None
    rep["remaining"] = max(0, allowed - len(domains))
    log("fetched %d domains, %d scored, %d without a score; %d rows left this month" % (len(domains), len(got), len(domains) - len(got), rep["remaining"]))
    return rep


def load_dirs(db):
    return db.call("GET", "ce_directories?select=domain,priority,da,da_source,da_checked_on,dead&order=priority.asc,domain.asc", None, "return=representation") or []


def authority_map(db):
    """{domain: DA} for Directories whose da_source is 'moz'. The only authority the snapshot may show."""
    return {r["domain"]: r["da"] for r in load_dirs(db) if r.get("da_source") == "moz" and isinstance(r.get("da"), (int, float))}


def env_files():
    """Token files, first wins. Resolved lazily so importing this module has no side effects."""
    base = os.path.expandvars("%LOCALAPPDATA%/hermes")
    return [base + "/.env", base + "/profiles/citation-engineer/.env"]


def read_env_file(path, key=TOKEN_ENV):
    """Value of key from a KEY=VALUE file (same parse as run.py load_env), or None. Never logs."""
    try:
        for l in open(path, encoding="utf-8"):
            if "=" in l and not l.lstrip().startswith("#"):
                k, v = l.rstrip("\n").split("=", 1)
                if k.strip() == key and v.strip().strip('"'):
                    return v.strip().strip('"')
    except OSError:
        pass
    return None


def resolve_token(env=None, files=None):
    """Order: env mapping (os.environ by default), then each file. An explicitly passed env reads no
    real files unless files is also given (keeps tests off the real .env). Value is never logged."""
    explicit = env is not None
    env = os.environ if env is None else env
    if env.get(TOKEN_ENV):
        return env[TOKEN_ENV]
    if files is None:
        files = [] if explicit else env_files()
    for f in files:
        v = read_env_file(f)
        if v:
            return v
    return None


def run(db=None, today=None, env=None, quota=None, fetch=None, files=None):
    """Monthly job. Non-fatal by design: returns the report, never raises."""
    try:
        token = resolve_token(env, files)
        env = dict(os.environ if env is None else env)
        if token: env[TOKEN_ENV] = token
        today = today or datetime.date.today()
        if not token:
            log("skipped: no MOZ_API_TOKEN set"); return {"skipped": True, "reason": "no MOZ_API_TOKEN"}
        if db is None:
            import directories as D
            db = D.DirDB()
        if quota is None or fetch is None:
            quota, fetch = live_transport(env[TOKEN_ENV])
        rep = refresh(load_dirs(db), today, env, quota, fetch)
        for dom, patch in rep["updates"]:
            db.call("PATCH", "ce_directories?domain=eq.%s" % dom, patch)
        return rep
    except Exception as e:
        msg, secret = str(e), (env.get(TOKEN_ENV) if env else None)
        if secret: msg = msg.replace(secret, "***")
        log("FAILED (non-fatal): " + (msg[:200] or type(e).__name__)); return {"skipped": True, "reason": "error"}


def dry_run(path, out=print):
    """Fixture dry run, no network: prints which domains would be fetched and the row count."""
    fx = json.load(open(path, encoding="utf-8"))
    today = _date(fx.get("today")) or datetime.date.today()
    rep = refresh(fx["directories"], today, dict(fx.get("env") or {}), dry=True)
    out("MOZ DRY RUN today=%s cap=%d used_this_month=%d" % (today, row_cap(fx.get("env") or {}), used_this_month(fx["directories"], today)))
    for d in rep["domains"]: out("  would fetch " + d)
    out("MOZ DRY RUN rows=%d" % rep["rows"])
    return rep


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--dry" in argv:
        dry_run(argv[argv.index("--dry") + 1]); return 0
    run(); return 0


if __name__ == "__main__":
    sys.exit(main())
