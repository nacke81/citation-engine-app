"""Citation Engine weekly job. Task Scheduler runs this. Discovery = the Spike s3 methods (job/discover.py), owned Chrome only.

Writes one ce_runs row + one ce_checks row per business x Directory to the shared Supabase project (secret key from the default
profile .env; never printed). Logs the chrome.exe-only window count before/during/after and owned_alive_after (must be empty).
No Directory login, no signup, no spend, no Directory or portal write, no NAP fix.

  python job/run.py              real run, writes to Supabase
  python job/run.py --dry        real discovery, no database write
  python job/run.py --from-rows rows.jsonl   re-combine saved rows only (no browser)
"""
import json, os, re, subprocess, sys, time, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LAD = os.path.expandvars("%LOCALAPPDATA%/citation-engine")
RUNS = os.environ.get("CE_RUNS") or LAD + "/runs"
ENV_FILE = os.path.expandvars("%LOCALAPPDATA%/hermes/.env")
os.makedirs(RUNS, exist_ok=True)
STAMP = datetime.now().strftime("%Y%m%d-%H%M")
RUN_DIR = os.path.join(RUNS, STAMP); os.makedirs(RUN_DIR, exist_ok=True)
os.environ.setdefault("CE_ROWS", os.path.join(RUN_DIR, "rows.jsonl"))
os.environ.setdefault("CE_SHOTS", os.path.join(RUN_DIR, "shots"))

import judge  # noqa: E402
from cfg import DIRS, IDENT  # noqa: E402


def load_env():
    E = {}
    for l in open(ENV_FILE, encoding="utf-8"):
        if "=" in l and not l.lstrip().startswith("#"):
            k, v = l.rstrip("\n").split("=", 1); E[k.strip()] = v.strip().strip('"')
    return E


class DB:
    def __init__(self, E):
        self.url, self.key, self.owner = E["PEOPLE_CRM_SUPABASE_URL"], E["PEOPLE_CRM_SECRET_KEY"], E["BROKER_WATCH_OWNER_ID"]

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.url + "/rest/v1/" + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"apikey": self.key, "Authorization": "Bearer " + self.key, "Content-Type": "application/json", "Prefer": "return=representation"})
        with urllib.request.urlopen(req, timeout=30) as r:
            t = r.read(); return json.loads(t) if t else None


def chrome_procs_with(profile):
    """chrome.exe processes whose command line still names the throwaway profile (ground truth for owned_alive_after)."""
    if not profile: return []
    ps = "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { $_.CommandLine -like '*%s*' } | ForEach-Object { $_.ProcessId }" % os.path.basename(profile)
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60).stdout
    return [int(x) for x in out.split() if x.strip().isdigit()]


def nap_lines(text, b):
    from core import NAME, STREET, PHONE_RE
    keep = []
    for l in text.split("\n"):
        l = l.strip()
        if l and len(l) < 220 and (NAME[b].search(l) or STREET[b].search(l) or PHONE_RE.search(l)):
            keep.append(l)
        if len(keep) >= 4: break
    return " | ".join(keep)[:400]


def discover_live():
    import core, discover, mapnap
    texts = {}
    def wrap_fetch(cls):
        orig = cls.fetch
        def f(self, url, label=""):
            r = orig(self, url, label)
            if r is not None and getattr(r, "text", None): texts[r.url] = r.text
            return r
        cls.fetch = f
    wrap_fetch(core.HttpFetcher); wrap_fetch(core.ChromeFetcher)
    ol = mapnap.lookup
    def lk(*a, **k):
        r = ol(*a, **k)
        if r.get("text"): texts[r["url"]] = r["text"]
        return r
    mapnap.lookup = lk; discover.mapnap.lookup = lk
    ob = discover.own_search_box
    def osb(*a, **k):
        r = ob(*a, **k)
        if r[0].text: texts[r[0].url] = r[0].text
        return r
    discover.own_search_box = osb
    state = {}
    def on_chrome(oc):
        state["profile"] = oc.profile; state["during"] = len(__import__("owned_chrome").chrome_windows())
    from owned_chrome import window_count
    before = window_count(); t0 = time.time()
    err = None
    try:
        discover.discover_all(on_chrome)
    except BaseException as e:
        err = f"{type(e).__name__}: {str(e)[:200]}"
    time.sleep(2)
    after = window_count()
    alive = chrome_procs_with(state.get("profile"))
    return dict(before=before, during=state.get("during"), after=after, equal=(before == after), owned_alive_after=alive,
                seconds=int(time.time() - t0), error=err), texts


def load_rows(p): return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def build(rows, texts):
    unsearch = set(IDENT.get("UNSEARCHABLE", []))
    comb = judge.combine(rows, DIRS, unsearch)
    out = []
    for (b, d), (res, src) in comb.items():
        if b == "FAKE": continue
        c = dict(biz=b, directory=d, result=res, url=None, nap_shown=None, name_match=None, street_match=None, phone_match=None, match=None, method=None, note=None)
        if res == "found" and src:
            fl = judge.nap_flags(src)
            u = src.get("url") or ""
            c.update(url=u, name_match=fl["name_match"], street_match=fl["street_match"], phone_match=fl["phone_match"], match=fl["match"],
                     method=src.get("method"), nap_shown=nap_lines(texts.get(u, ""), b) if texts.get(u) else None,
                     note=("stale phone shown" if fl["stale_phone"] else "") + ("; old street shown" if fl["old_street"] else ""))
        out.append(c)
    return comb, out


def main():
    dry = "--dry" in sys.argv
    if "--from-rows" in sys.argv:
        rows = load_rows(sys.argv[sys.argv.index("--from-rows") + 1]); texts = {}
        wc = dict(before=None, during=None, after=None, equal=None, owned_alive_after=[], seconds=0, error="offline recombine")
    else:
        wc, texts = discover_live(); rows = load_rows(os.environ["CE_ROWS"])
    comb, checks = build(rows, texts)
    unsearch = set(IDENT.get("UNSEARCHABLE", []))
    guards = dict(hard_negative=judge.hard_negative_ok(rows, IDENT["HARDNEG_ID"]), made_up_zero=judge.made_up_ok(comb), blocked_ok=judge.blocked_ok(comb, rows))
    truth = judge.load_truth(IDENT["TRUTH_MD"]) if os.path.exists(IDENT.get("TRUTH_MD", "")) else {}
    sc = judge.score(comb, truth, unsearch) if truth else None
    n = {b: dict({k: sum(1 for c in checks if c["biz"] == b and c["result"] == k) for k in ("found", "absent", "couldnt_check", "unsearchable")}, label=IDENT["LABEL"][b]) for b in ("SCC", "NM")}
    summary = dict(window_count=wc, guards=guards, counts=n, score=({"hits": sc["hits"], "denom": sc["denom"], "bar": sc["bar"],
                   "false_absent": [list(k) for k in sc["false_absent"]], "wrong_business": [list(k) for k in sc["wrong_business"]]} if sc else None))
    # local artifacts: the decisive real pages (real NAP, stays on this PC, input for scrubbed fixtures) + the summary
    pages = []
    for c in checks:
        if c["result"] == "found" and texts.get(c["url"]): pages.append(dict(biz=c["biz"], directory=c["directory"], url=c["url"], text=texts[c["url"]]))
    for r in rows:
        if r.get("kind") == "hardneg" and texts.get(r.get("url")): pages.append(dict(biz="SCC", directory=r["dir"], url=r["url"], text=texts[r["url"]], hardneg=True))
    json.dump(pages, open(os.path.join(RUN_DIR, "pages.local.json"), "w", encoding="utf-8"))
    json.dump(summary, open(os.path.join(RUN_DIR, "summary.json"), "w"), indent=1)
    print("SUMMARY", json.dumps(summary), flush=True)
    ok_run = wc["error"] is None and wc.get("equal") is not False and not wc.get("owned_alive_after") and all(guards.values())
    if dry:
        print("dry run: no database write"); return 0 if ok_run else 1
    E = load_env(); db = DB(E)
    status = "ok" if ok_run else "failed"
    run = db.call("POST", "ce_runs", {"owner": db.owner, "started_at": datetime.fromtimestamp(time.time() - wc["seconds"], timezone.utc).isoformat(),
                  "finished_at": datetime.now(timezone.utc).isoformat(), "status": status,
                  "chrome_before": wc["before"], "chrome_during": wc["during"], "chrome_after": wc["after"], "chrome_equal": wc["equal"],
                  "owned_alive_after": wc["owned_alive_after"], "guards": guards, "counts": n, "score": summary["score"], "error": wc["error"]})[0]
    db.call("POST", "ce_checks", [dict(c, owner=db.owner, run_id=run["id"], checked_on=datetime.now().date().isoformat()) for c in checks])
    print("wrote run", run["id"], status, len(checks), "checks", flush=True)
    return 0 if ok_run else 1


if __name__ == "__main__":
    sys.exit(main())
