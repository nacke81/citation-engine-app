"""Category-fit filter for queued build rows (kanban t_d13bd638). Stops the build spending rows on Directories that cannot list a senior-care consulting business.

For each `queued` row in build_order: verdict fit | no-fit | dead, plus a one-line reason.
  fit      general local or senior-care Directory, or no mismatch signal
  no-fit   contractors-only, CPA-only, kids-only, non-US or non-English, developer platform, or a duplicate of another row
  dead     DNS / connection failure, HTTP 404/410, or a parked-domain page
Sources, in order: the batch 7 KNOWN table, ce_directories (category, dead flag), the playbook file (Obsidian playbooks/build/<domain>.md), one homepage GET.
Keyword gates read only category + page title + meta description + the playbook "Outcome/Blocker" lines, never the whole body, and a senior-care word in the
title or description keeps the row fit.

  python job/fit.py [--queue PATH] [--playbooks DIR] [--no-db] [--no-fetch] [--row ID ...]      dry-run table (default)
  python job/fit.py --write                                                                      move no-fit / dead rows to `rejected` through transitions.py
--write never creates a client Activities row (a fit reject is not client news) and is NOT run by the card that built it.
"""
import concurrent.futures, json, os, re, socket, sys, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buildqueue as Q

HERE = os.path.dirname(os.path.abspath(__file__))
PLAYBOOKS = os.environ.get("CE_PLAYBOOKS") or ""   # the vault playbooks/build folder: pass --playbooks or set CE_PLAYBOOKS (no vault path lives in this repo; the leak check denies it)
SEED = os.path.join(HERE, "..", "db", "directories_seed.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
VERDICTS = ("fit", "no-fit", "dead")

# Batch 7 (t_db09baa9) findings, keyed by brand label (the part before the first dot).
KNOWN = {
    "here":            ("no-fit", "developer platform (HERE Technologies), no business listing"),
    "infobel":         ("no-fit", "duplicate of us-info.com (same data source)"),
    "activityhero":    ("no-fit", "kids activities only"),
    "vivinavi":        ("no-fit", "Japanese-language Directory"),
    "fyple":           ("dead", "domain dead (batch 7)"),
    "buildzoom":       ("no-fit", "contractors only"),
    "accountantfinder": ("no-fit", "CPA / accountants only"),
}
ALLOWED_TLDS = {"com", "org", "net", "us", "biz", "info", "co", "io", "me", "tv", "app", "online", "site", "directory", "city", "pro"}
SENIOR_RE = re.compile(r"(?i)\b(senior|seniors|elder|eldercare|aging|caregiv\w*|home care|assisted living|retirement)\b")
GATES = (  # (verdict reason, regex over category + title + description + playbook outcome lines)
    ("kids-only", re.compile(r"(?i)\b(kids|children'?s|childrens|for children|camps? for|after-?school|child ?care)\b[^.]{0,40}\b(activities|camps?|classes|directory|programs?)\b|\bactivities for (kids|children)\b|\bkids activities\b")),
    ("contractors-only", re.compile(r"(?i)\b(find|hire|compare|top|licensed|vetted)\b[^.]{0,30}\b(contractors?|roofers?|plumbers?|remodelers?)\b|\bcontractor (directory|reviews|licen[sc]e)\b|\bcontractors only\b")),
    ("CPA / accountants only", re.compile(r"(?i)\b(find|hire|directory of|compare)\b[^.]{0,30}\b(accountants?|cpas?|bookkeepers?)\b|\baccountant (directory|finder)\b|\bcpa(s)? only\b")),
    ("industrial / manufacturing only", re.compile(r"(?i)\b(industrial|manufacturing|manufacturers?)\b[^.|]{0,30}\b(directory|suppliers?|sourcing)\b|\bblue book\b[^.]{0,20}\bindustrial\b")),
    ("home-improvement pros only", re.compile(r"(?i)\b(software for construction|design professionals|home services?|homeowners?)\b[^.]{0,60}\b(pros?|professionals|design|remodel\w*|projects?)\b|\bhome improvement pros\b")),
    ("developer platform", re.compile(r"(?i)\b(developer (platform|portal|sign-?up|account)|location platform|maps? api|sdk|api keys?)\b|\bnot a directory\b")),
)
PARKED_RE = re.compile(r"(?i)domain (is )?(for sale|may be for sale)|buy this domain|this domain is parked|parked free|sedo domain parking|hugedomains|domain has expired")
LANG_RE = re.compile(r"(?is)<html[^>]*\blang\s*=\s*[\"']?([A-Za-z-]+)")
TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
DESC_RE = re.compile(r"(?is)<meta[^>]+name\s*=\s*[\"']description[\"'][^>]*content\s*=\s*[\"']([^\"']*)[\"']|<meta[^>]+content\s*=\s*[\"']([^\"']*)[\"'][^>]*name\s*=\s*[\"']description[\"']")


def label(domain):
    return (domain or "").lower().split(".")[0]


def tld(domain):
    return (domain or "").lower().rsplit(".", 1)[-1]


def fetch_home(domain, timeout=12):
    """One public homepage GET. Never raises. -> {status, html, err, dns}"""
    url = "https://%s/" % domain
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"status": r.status, "html": r.read(400000).decode("utf-8", "replace"), "err": None, "dns": False}
    except urllib.error.HTTPError as e:
        try: html = e.read(100000).decode("utf-8", "replace")
        except Exception: html = ""
        return {"status": e.code, "html": html, "err": "HTTP %s" % e.code, "dns": False}
    except urllib.error.URLError as e:
        dns = isinstance(e.reason, socket.gaierror)
        return {"status": 0, "html": "", "err": "DNS lookup failed" if dns else type(e.reason).__name__, "dns": dns}
    except Exception as e:
        return {"status": 0, "html": "", "err": type(e).__name__, "dns": False}


def playbook_text(dirpath, domain):
    """Outcome / Blocker / Steps-summary lines of the playbook file, or ''."""
    p = os.path.join(dirpath or "", "%s.md" % domain)
    try: txt = open(p, encoding="utf-8").read()
    except OSError: return ""
    return "\n".join(l for l in txt.splitlines() if re.match(r"(?i)^\s*(#|outcome|blocker|steps)\b", l))[:1500]


def _meta(html):
    t = TITLE_RE.search(html or ""); d = DESC_RE.search(html or "")
    return " ".join((t.group(1) if t else "").split())[:200], " ".join(((d.group(1) or d.group(2) or "") if d else "").split())[:300]


def classify(row, cat, pb, page, others):
    """-> (verdict, reason). row: queue row; cat: ce_directories row or None; pb: playbook text; page: fetch_home result or None; others: other queue rows."""
    dom = row["directory"]; lab = label(dom)
    if lab in KNOWN:
        return KNOWN[lab]
    if cat and cat.get("dead"):
        return "dead", "Catalog flagged dead: %s" % (cat.get("dead_reason") or "no reason recorded")
    if page is not None:
        html = page.get("html") or ""
        if page.get("dns"): return "dead", "DNS lookup failed for %s" % dom
        if page.get("status") in (404, 410): return "dead", "homepage HTTP %s" % page["status"]
        if page.get("status") == 0 and page.get("err") in ("ConnectionRefusedError", "ConnectionResetError"): return "dead", "homepage unreachable (%s)" % page["err"]
        if PARKED_RE.search(html[:6000]): return "dead", "parked or for-sale domain"
    for o in others:  # duplicate: same brand on another TLD, already a row that is further along or sorts first
        if o["id"] != row["id"] and label(o.get("directory")) == lab and o.get("directory") != dom and (o.get("state") != "queued" or o["directory"] < dom):
            return "no-fit", "duplicate of %s (same brand, other TLD)" % o["directory"]
    t = tld(dom)
    if len(t) == 2 and t not in ALLOWED_TLDS:
        return "no-fit", "non-US Directory (.%s)" % t
    title = desc = ""
    if page is not None and page.get("html"):
        title, desc = _meta(page["html"])
        m = LANG_RE.search(page["html"][:3000])
        if m and not m.group(1).lower().startswith("en"):
            return "no-fit", "non-English site (html lang=%s)" % m.group(1)
    sig = " | ".join(x for x in ((cat or {}).get("category") or "", title, desc, pb) if x)
    senior = bool(SENIOR_RE.search(" ".join((title, desc, (cat or {}).get("category") or ""))))
    if not senior:
        generic = (cat or {}).get("category") == "general" or re.search(r"(?i)\b(local )?businesses\b[^.]{0,20}(,| and |&)", " ".join((title, desc)))  # a general Directory that lists contractors among many trades
        for why, rx in GATES:
            m = rx.search(sig)
            if m and not (generic and why in ("contractors-only", "CPA / accountants only", "home-improvement pros only")): return "no-fit", "%s (matched %r)" % (why, " ".join(m.group(0).split())[:40])
    if re.search(r"(?i)\b(japanese|korean|chinese|spanish)[- ]language\b", pb):
        return "no-fit", "non-English Directory (playbook)"
    c = (cat or {}).get("category")
    return "fit", ("senior-care Directory" if c == "niche-senior" or senior else "general local Directory" if c in ("general", "local", "aggregator") else "no mismatch signal (category %s)" % (c or "unknown"))


def load_rows(q):
    rows = list(q.get("fix_queue") or []) + list(q.get("create_rows") or [])
    cq = q.get("create_queue")
    rows += list(cq.get("rows") or []) if isinstance(cq, dict) else (list(cq) if isinstance(cq, list) else [])
    return rows


def queued_in_order(q):
    by = {r["id"]: r for r in load_rows(q)}
    return [by[i] for i in (q.get("build_order") or []) if i in by and by[i].get("state") == "queued"]


def load_catalog(use_db=True):
    """domain -> {category, dead, dead_reason}. DB first (GET only); seed file when the DB is off or fails."""
    if use_db:
        try:
            import directories as D
            rows = D.DirDB().call("GET", "ce_directories?select=domain,category,dead,dead_reason&limit=1000", None, "return=representation") or []
            return {r["domain"]: r for r in rows}, "db"
        except Exception:
            pass
    try:
        return {r["domain"]: r for r in json.load(open(SEED, encoding="utf-8"))}, "seed"
    except Exception:
        return {}, "none"


def run_filter(q, catalog, playbooks, fetch=fetch_home, only=None, workers=8):
    """-> [(row, verdict, reason)] for queued rows in build_order. fetch=None skips the homepage GET."""
    rows = queued_in_order(q)
    if only: rows = [r for r in rows if r["id"] in only]
    allrows = load_rows(q)
    pbs = {r["id"]: playbook_text(playbooks, r["directory"]) for r in rows}
    def page_for(r):
        if fetch is None or label(r["directory"]) in KNOWN or (catalog.get(r["directory"]) or {}).get("dead"): return None
        return fetch(r["directory"])
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        pages = list(ex.map(page_for, rows))
    return [(r,) + classify(r, catalog.get(r["directory"]), pbs[r["id"]], pg, allrows) for r, pg in zip(rows, pages)]


def table(results):
    w = max([len(r["id"]) for r, _, _ in results] + [3])
    out = ["%-*s  %-7s  %s" % (w, "row", "verdict", "reason"), "%s  %s  %s" % ("-" * w, "-" * 7, "-" * 40)]
    out += ["%-*s  %-7s  %s" % (w, r["id"], v, why) for r, v, why in results]
    c = {v: sum(1 for _, x, _ in results if x == v) for v in VERDICTS}
    out.append("")
    out.append("fit %d, no-fit %d, dead %d (of %d queued rows)" % (c["fit"], c["no-fit"], c["dead"], len(results)))
    return "\n".join(out)


def write_rejects(results, queue_path, record=None, today=None):
    """Move no-fit / dead rows to rejected with the reason. Returns [(row_id, ok, message)]. Never writes a client Activities row."""
    if record is None:
        import transitions
        record = transitions.record_transition
    out = []
    for r, v, why in results:
        if v == "fit": continue
        try:
            res = record("SCC", r["id"], "rejected", None, "%s: %s" % (v, why), queue_path=queue_path, today=today, activities_flag=False)
            out.append((r["id"], not res.get("errors"), "; ".join(res.get("errors") or []) or "rejected"))
        except Exception as e:
            out.append((r["id"], False, "refused: %s" % e))
    return out


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Category-fit filter for queued SCC build rows (dry run unless --write)")
    a.add_argument("--queue", default=None); a.add_argument("--playbooks", default=PLAYBOOKS)
    a.add_argument("--no-db", action="store_true", help="use db/directories_seed.json instead of ce_directories")
    a.add_argument("--no-fetch", action="store_true", help="skip the homepage GET")
    a.add_argument("--row", action="append", default=None); a.add_argument("--write", action="store_true")
    n = a.parse_args(argv)
    path = n.queue or Q.QUEUE_PATH
    q = json.load(open(path, encoding="utf-8"))
    cat, src = load_catalog(not n.no_db)
    res = run_filter(q, cat, n.playbooks, None if n.no_fetch else fetch_home, set(n.row) if n.row else None)
    print("catalog source: %s; playbooks: %s" % (src, n.playbooks))
    print(table(res))
    if n.write:
        for rid, ok, msg in write_rejects(res, path): print("%-6s %s  %s" % ("WROTE" if ok else "FAILED", rid, msg))
    else:
        print("dry run: nothing written (use --write to reject no-fit / dead rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
