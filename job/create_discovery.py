"""Create-queue discovery: is SCC absent from a Catalog Directory outside the weekly 25? (kanban t_76d7b129)

GET-only. No Directory login, signup or submit, no portal call, no spend. Non-production: nothing here is imported by run.py or portal.py.
A Directory is `absent` ONLY when (a) every SCC query returned a recognised zero-result page AND (b) a positive control (a known listing of
another business, same method, same run) was found. No control, a wall, an error or an unrecognised page = `couldnt`, never absent (golden 2).
Only `absent` makes a create row (state queued, mike_approval null). Usage: python job/create_discovery.py --out create-queue.json
"""
import json, os, re, sys
from datetime import date
from urllib.parse import quote_plus as qp, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import judge_listing, classify, Result, HttpFetcher  # noqa: E402
from cfg import S  # noqa: E402

BIZ_KEY = "SCC"
CTRL_NAME = "Walmart"          # another business with a known listing in the same city (checked live per run)
CTRL_TOKEN = re.compile(r"(?i)walmart")
NBSP = "[\\s\\xa0]*"


def _city():
    x = S(BIZ_KEY); return qp(f"{x['city']}, {x['st']}"), qp(x["city"])


def _acompio(n):
    return f"https://www.acompio.us/search.php?name={qp(n)}&place={_city()[1]}"


def _citysquares(n):
    return f"https://www.citysquares.com/search?search%5Bterm%5D={qp(n)}&search%5Blocation%5D={_city()[0]}"


def _ibegin(n):
    x = S(BIZ_KEY); return f"https://www.ibegin.com/search/?q={qp(n + ' ' + x['city'] + ' ' + x['st'])}"


def _clp(n):
    return f"https://citylocalpro.com/search?q={qp(n)}&location={_city()[0]}"


def _fla(n):
    return f"https://www.freelistingusa.com/location/{S(BIZ_KEY)['city'].lower().replace(' ', '-')}-{S(BIZ_KEY)['st'].lower()}/search/{qp(n).replace('+', '-')}"


def _tupalo(n):
    x = S(BIZ_KEY); return f"https://www.tupalo.com/en/search?q={qp(n + ' ' + x['city'] + ' ' + x['st'])}"


# Per Directory. search: the Directory's own site-search URL builder (None = no public own-search found 2026-10-19).
# zero / one: regexes proving the results page was understood (0 results / >=1 result); None = no verified marker, so never `absent`.
# signup_url / cost / login_needed come re-read live 2026-10-19 (checked_on, GET only, nothing submitted); cost free|paid|unknown.
CREATE_DIRS = {
    "caring.com": dict(cost_class="free", search=None, zero=None, one=None, signup_url="https://www.caring.com/partners/get-listed", cost="free (page: 'Claim Your Free Caring.com Listing'; it edits an existing community listing, so fit for a consultant is unconfirmed; partner referrals are a separate sign-in at partner-portal.caring.com, cost not published)", login_needed="no login stated on the get-listed form; partner portal needs sign-in"),
    "citysquares.com": dict(cost_class="free", search=_citysquares, zero=None, one=None, signup_url="https://citysquares.com/add_business", cost="free (page: 'add it now, for free'; Premium is $9/month, optional)", login_needed="yes: account sign-up first"),
    "botw.org": dict(cost_class="unknown", search=None, zero=None, one=None, signup_url="https://botw.org/", cost="unknown", login_needed="unknown (Cloudflare wall, not read)"),
    "enrollbusiness.com": dict(cost_class="unknown", search=None, zero=None, one=None, signup_url="https://www.enrollbusiness.com/", cost="unknown", login_needed="unknown (Cloudflare wall, not read)"),
    "storeboard.com": dict(cost_class="unknown", search=None, zero=None, one=None, signup_url="https://www.storeboard.com/", cost="unknown", login_needed="unknown (Cloudflare wall, not read)"),
    "acompio.us": dict(cost_class="free", search=_acompio, zero=re.compile(r"resulted in" + NBSP + r"0 Results", re.I), one=re.compile(r"resulted in" + NBSP + r"[1-9]\d* Results", re.I),
                       signup_url="https://account.acompio.com/signup.php?source=8", cost="free (FAQ: basic profile free; Premium optional)", login_needed="yes: account sign-up (name, email, password)"),
    "ibegin.com": dict(cost_class="unknown", search=_ibegin, zero=None, one=None, signup_url="https://www.ibegin.com/business-center/submit/", cost="unknown", login_needed="yes: register link at /account/register/"),
    "citylocalpro.com": dict(cost_class="free", search=_clp, zero=None, one=None, signup_url="https://citylocalpro.com/add-your-business", cost="free listing ('free, it takes less than 2 minutes'); paid SEO plans from $300/mo on /pricing, not required", login_needed="yes: register"),
    "freelistingusa.com": dict(cost_class="free", search=_fla, zero=None, one=None, signup_url="https://www.freelistingusa.com/create-listing", cost="free (site describes itself as a free listing site)", login_needed="yes: pre-register / register"),
    "tupalo.com": dict(cost_class="unknown", search=_tupalo, zero=None, one=None, signup_url="https://www.tupalo.com/en/users/signin", cost="unknown", login_needed="yes: sign in"),
}


SIGNUP_CHECKED_ON = "2026-10-19"   # signup_url / cost / login re-read by GET on this date (rebase attempt); bump when re-read
SIGNUP_NOTES = {"ibegin.com": "signup page returned 403 to a plain GET on re-read 2026-10-19; cost/login text is from the earlier read",
                "botw.org": "Cloudflare wall on re-read; not read", "enrollbusiness.com": "Cloudflare wall on re-read; not read", "storeboard.com": "Cloudflare wall on re-read; not read"}
for _k, _v in CREATE_DIRS.items():
    _v["checked_on"] = SIGNUP_CHECKED_ON; _v["signup_note"] = SIGNUP_NOTES.get(_k, "re-read live by GET")


def search_urls(key, name):
    """SCC queries for one Directory: its own site search by name, plus the phone-search form where verified (ibegin)."""
    cfg = CREATE_DIRS[key]
    if not cfg["search"]: return []
    urls = [cfg["search"](name)]
    if key == "ibegin.com": urls.append(f"https://www.ibegin.com/search/phone/?phone={S(BIZ_KEY)['phones'][0]}")
    return urls


def control_url(key):
    cfg = CREATE_DIRS[key]
    return cfg["search"](CTRL_NAME) if cfg["search"] else None


def control_listing(key, res):
    """The control passes only if the results page shows >=1 result AND links a same-host listing page naming the control business."""
    cfg = CREATE_DIRS[key]
    if res is None or res.err or not res.status or res.status >= 400 or not cfg["one"] or not cfg["one"].search(res.text): return None
    host = urlparse(res.url).netloc.replace("www.", "").split(".")[-2:]
    for l in res.links:
        h = l.get("href", "")
        if urlparse(h).netloc.replace("www.", "").split(".")[-2:] != host or re.search(r"(?i)search|login|signup", h): continue
        if CTRL_TOKEN.search(l.get("card", "") + " " + l.get("text", "")) and h != res.url: return h
    return None


def decide(key, results, ctrl):
    """results: Results of the SCC queries, ctrl: Result of the control query (same method, same run). -> dict(state found|absent|couldnt, why, ...)."""
    cfg = CREATE_DIRS[key]
    if not results: return dict(state="couldnt", why="no own-site search found")
    for r in results:
        if r.err or r.status is None or r.status >= 400 or classify(r, BIZ_KEY) == "blocked" and not r.text.strip():
            return dict(state="couldnt", why="query walled or failed: %s" % (r.err or r.status))
    for r in results:
        ok, ev, why = judge_listing(r.text, BIZ_KEY)
        if ok: return dict(state="found", why=why, url=r.url)
    if not cfg["zero"]: return dict(state="couldnt", why="no verified zero-result marker for this Directory")
    if not all(cfg["zero"].search(r.text) for r in results): return dict(state="couldnt", why="results page not recognised as a clean zero-result page")
    c = control_listing(key, ctrl)
    if not c: return dict(state="couldnt", why="no positive control (no known listing of another business found by the same method)")
    return dict(state="absent", why="zero results for every SCC query; control found", control_url=c, queries=[r.url for r in results])


def create_row(key, d, day):
    if d["state"] != "absent": return None
    cfg = CREATE_DIRS[key]
    return dict(id="create-" + key.split(".")[0], directory=key, kind="create", state="queued", mike_approval=None, found_on=day,
                proof_of_absence=dict(method="Directory's own site search, GET, name + city (same method as the weekly 25); zero results page recognised",
                                      queries=d["queries"], control_url=d["control_url"], control_business=CTRL_NAME),
                signup_url=cfg["signup_url"], cost=cfg["cost"], cost_class=cfg["cost_class"], login_needed=cfg["login_needed"],
                checked_on=cfg["checked_on"], signup_note=cfg["signup_note"])


def merge_create_queue(queue, decisions, rows, day):
    """Merge discovery output into queue['create_queue'] (a dict; 'rows' list). Idempotent by row id.
    Never overwrites an existing row's state / mike_approval / any field; a Directory that now reads found or couldnt keeps its queued row
    and only gains last_seen_state. Does not touch fix_queue or anything else. Returns the same queue dict."""
    cq = queue.get("create_queue")
    if not isinstance(cq, dict): cq = {} if cq is None else {"legacy": cq}
    cq.setdefault("rows", []); cq.setdefault("last_seen", {})
    have = {r["id"]: r for r in cq["rows"]}
    for r in rows:
        if r["id"] not in have:
            cq["rows"].append(r); have[r["id"]] = r
    for key, d in decisions.items():
        rid = "create-" + key.split(".")[0]
        cq["last_seen"][key] = dict(state=d["state"], why=d["why"], on=day)
        if rid in have and d["state"] != "absent": have[rid]["last_seen_state"] = dict(state=d["state"], why=d["why"], on=day)
    cq["status"] = "Discovery runs weekly on the 10 Directories in create_discovery.CREATE_DIRS (positive control required). %d queued create row(s); last run %s. Rows never change state here; Mike approval is set by hand." % (len(cq["rows"]), day)
    queue["create_queue"] = cq
    return queue


def weekly_merge(queue_path, fetcher=None, day=None):
    """Weekly-run hook (after the 25): GET-only discovery, then merge into the SCC queue file. No portal call, no payload schema change."""
    dec, rows = run_all(fetcher, day); day = day or date.today().isoformat()
    q = json.load(open(queue_path, encoding="utf-8"))
    merge_create_queue(q, dec, rows, day)
    tmp = queue_path + ".tmp"; json.dump(q, open(tmp, "w", encoding="utf-8"), indent=1); os.replace(tmp, queue_path)
    return dec, rows


def run_all(fetcher=None, day=None):
    f = fetcher or HttpFetcher(); day = day or date.today().isoformat(); x = S(BIZ_KEY)
    decisions, rows = {}, []
    for key in CREATE_DIRS:
        names = [x["name"], x["short"]]
        results = [f.fetch(u, key) for n in names for u in search_urls(key, n)]
        cu = control_url(key); ctrl = f.fetch(cu, key + " control") if cu else None
        d = decide(key, results, ctrl); decisions[key] = d
        row = create_row(key, d, day)
        if row: rows.append(row)
        print(key, d["state"], d["why"], flush=True)
    return decisions, rows


if __name__ == "__main__":
    if "--merge-into" in sys.argv:  # merge into a copy/queue file: python job/create_discovery.py --merge-into PATH
        dec, rows = weekly_merge(sys.argv[sys.argv.index("--merge-into") + 1]); print("merged", len(rows), "absent rows"); sys.exit(0)
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "create-queue.json"
    dec, rows = run_all()
    json.dump(dict(business=S(BIZ_KEY)["name"], generated=date.today().isoformat(), decisions=dec, create_queue=rows), open(out, "w", encoding="utf-8"), indent=1)
    print("wrote", out, len(rows), "create rows")
