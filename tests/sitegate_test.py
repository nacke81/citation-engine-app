"""Site guard, quota wall, one read per row, replay (t_e34fc55c). No network, no browser: fetchers are fakes, urlopen is poisoned. Run: python tests/sitegate_test.py"""
import os, sys, copy, json, io, subprocess, tempfile, time, contextlib, urllib.request, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="ce-sitegate-")
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = os.path.join(TMP, "runs")
os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard", "site-guard.json")
os.environ["CE_LOGS"] = os.path.join(TMP, "logs")
os.environ["CE_SITE_GAP"] = "0"
os.environ.pop("CE_ACTIVITIES_WRITE", None)
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import recheck as R
import sitegate as SG
import workable as WK
import transitions as T

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

DAY = "2026-11-05"
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example, Exampleton KY 40000", "phone": "(502) 555-0101"}
IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
PAD = " Lorem ipsum dolor sit amet." * 12
GOOD = "Home\nAlder Care Consulting & Solutions\n100 Example\nExampleton, KY 40000\n(502) 555-0101\n" + PAD
QUOTA = "Bizapedia Pro\nYou've run out of free searches for today. Subscribe to continue." + PAD

class FakeDB:
    owner = "o"
    def __init__(self): self.calls = []
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))

def row(rid, d, state, url, **kw):
    r = {"id": rid, "directory": d, "state": state, "mike_approval": None, "evidence_url": url, "listing_url": url, "history": []}
    r.update(kw); return r

def queue(rows, name="q.json"):
    p = os.path.join(tempfile.mkdtemp(dir=TMP), name)
    json.dump({"canonical": CANON, "fix_queue": rows}, open(p, "w")); return p

def run(rows, plain, chrome=None, guard=None, **kw):
    p = queue(rows); db = FakeDB()
    rec = lambda *a, **k: T.record_transition(*a, portal=db, activities=db, verification=db, directories=db, **k)
    res = R.recheck(json.load(open(p)), IDENT, plain=plain, chrome=chrome, record=rec, db=db, queue_path=p, today=DAY, guard=guard, include_live=True, **kw)
    return res, p, db

def fresh_guard(**kw):
    d = tempfile.mkdtemp(dir=TMP)
    kw.setdefault("gap", 0)
    return SG.SiteGuard(path=os.path.join(d, "g.json"), logs=os.path.join(d, "logs"), **kw), os.path.join(d, "logs")

def lines(path):
    try: return [json.loads(l) for l in open(path, encoding="utf-8")]
    except OSError: return []

# ---- S1 one read per row -------------------------------------------------------------------------------------------------
U = "https://a.example/biz/1"
calls = []
def plain_ok(u): calls.append(("plain", u)); return R.Page(200, u, GOOD)
res, p, db = run([row("r1", "a.example", "live", U)], plain_ok)
check("S1 live row on a readable plain page: one read", calls == [("plain", U)] and res[0]["verdict"] == "match", str(calls))
calls.clear()
def chrome_ok(u): calls.append(("chrome", u)); return R.Page(200, u, GOOD)
plain_403 = lambda u: (calls.append(("plain", u)), R.Page(403, u, "", err="HTTP 403"))[1]
res, p, db = run([row("r2", "a.example", "live", U)], plain_403, chrome_ok)
check("S1 live row via Chrome: plain once, Chrome ONCE (was 3)", calls == [("plain", U), ("chrome", U)], str(calls))
calls.clear()
res, p, db = run([row("r3", "a.example", "pending-verify", U)], plain_403, chrome_ok)
check("S1 a row about to go live: ONE Chrome load (stability is checked inside it, t_0c4ebee8), never two back to back", [c[0] for c in calls].count("chrome") == 1 and res[0]["after"] == "live", str(calls))
calls.clear()
res, p, db = run([row("r4", "a.example", "live", U), row("r5", "a.example", "live", "https://a.example/biz/2")], plain_ok)
check("S1 two live rows: one read each", len(calls) == 2, str(calls))

# ---- S2 the gap holds across two processes ---------------------------------------------------------------------------------
child = ("import os,sys,time; sys.path.insert(0, %r)\nimport sitegate as SG\ng=SG.SiteGuard()\nr=g.reserve('gap.example', key=sys.argv[1])\nprint(time.time(), r['ok'], r.get('waited'))\n" % os.path.join(HERE, "..", "job"))
env = dict(os.environ, CE_SITE_GUARD=os.path.join(TMP, "two-proc", "g.json"), CE_SITE_GAP="2", CE_LOGS=os.path.join(TMP, "two-proc", "logs"))
procs = [subprocess.Popen([sys.executable, "-c", child, "u%d" % i], env=env, stdout=subprocess.PIPE, text=True) for i in range(2)]
outs = [pr.communicate()[0].split() for pr in procs]
ts = sorted(float(o[0]) for o in outs)
check("S2 two processes reading one domain: reads >= gap apart", len(outs) == 2 and all(o[1] == "True" for o in outs) and ts[1] - ts[0] >= 1.8, str(outs))
reads = lines(os.path.join(TMP, "two-proc", "logs", "site-reads.jsonl"))
check("S2 both reads logged, one of them waited", len(reads) == 2 and max(r["waited_s"] for r in reads) >= 1.5, str(reads))

# ---- S3 gap, same-read, cap, cooldown with a fake clock -------------------------------------------------------------------
clock = [1_800_000_000.0]; slept = []
g, logs = fresh_guard(gap=60, now=lambda: clock[0], sleep=lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)))
a = g.reserve("x.example", key="u1"); b = g.reserve("x.example", key="u2")
check("S3 second read of a domain waits the 60s gap", a["ok"] and a["waited"] == 0 and b["ok"] and abs(b["waited"] - 60) < 0.01 and len(slept) == 1, str((a, b, slept)))
c = g.reserve("x.example", key="u2")
check("S3 the same URL again (plain then Chrome fallback) is one read: no wait, not counted", c.get("same_read") and len(slept) == 1)
g_other = SG.SiteGuard(path=g.path, gap=60, now=lambda: clock[0], sleep=lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)), logs=logs)
d2 = g_other.reserve("x.example", key="u2")
check("S3 the same URL from ANOTHER process is a new read and waits the gap", not d2.get("same_read") and d2["waited"] > 0, str(d2))
check("S3 another domain does not wait", g.reserve("y.example", key="u")["waited"] == 0)
gb, _ = fresh_guard(gap=0, caps={"bizapedia.com": 3}, now=lambda: clock[0], sleep=lambda s: None)
r = [gb.reserve("bizapedia.com", key="k%d" % i) for i in range(4)]
check("S3 bizapedia: 3 reads a day, the 4th is refused", [x["ok"] for x in r] == [True, True, True, False] and "daily cap" in r[3]["why"], str(r))
clock[0] += 86400
check("S3 the cap resets the next day", gb.reserve("bizapedia.com", key="z")["ok"])
gw, lg = fresh_guard(gap=0, now=lambda: clock[0], sleep=lambda s: None)
first = gw.wall("w.example", "Cloudflare wall", url="https://w.example/x", row="r"); again = gw.wall("w.example", "Cloudflare wall")
check("S3 a wall logs ONE line (the cooldown already stands for the second)", first and not again and len(lines(os.path.join(lg, "site-walls.jsonl"))) == 1)
refused = gw.reserve("w.example", key="n")
check("S3 cooldown refuses reads", not refused["ok"] and "cooldown" in refused["why"], str(refused))
clock[0] += 86400
check("S3 cooldown ends the next day", gw.reserve("w.example", key="n")["ok"])

# ---- S4 Bizapedia quota page: rate-limited, no row change, one log line, no more reads -------------------------------------
BZ = "https://www.bizapedia.com/companies/alder.html"
QURL = "https://www.bizapedia.com/pro-search-subscription.aspx?src=search"
g, lg = fresh_guard()
n = [0]
def plain_quota(u): n[0] += 1; return R.Page(200, QURL, QUOTA)   # a 200 after the redirect: walled() never saw it
rows = [row("bz", "bizapedia.com", "live", BZ)]
res, p, db = run(rows, plain_quota, None, guard=g)
before = open(p, "rb").read()
check("S4 quota page (final URL + text) -> rate-limited, not unreadable / not-public", res[0]["verdict"] == "rate-limited" and not res[0]["error"], str(res[0]))
check("S4 no row change, no write, no nap_check", json.load(open(p))["fix_queue"][0] == rows[0] and not db.calls and "nap_check" not in res[0])
w = lines(os.path.join(lg, "site-walls.jsonl"))
check("S4 exactly one site-walls.jsonl line, domain + reason", len(w) == 1 and w[0]["domain"] == "www.bizapedia.com".removeprefix("www.") and "quota" in w[0]["reason"], str(w))
res2, p2, db2 = run(rows, plain_quota, None, guard=g)
check("S4 a second run does not read bizapedia again (cooldown), still no row change, no second log line", n[0] == 1 and res2[0]["verdict"] == "rate-limited" and len(lines(os.path.join(lg, "site-walls.jsonl"))) == 1, str(n))
n[0] = 0
text_only = lambda u: (n.__setitem__(0, n[0] + 1), R.Page(200, BZ, QUOTA))[1]   # no redirect, text only
g2, lg2 = fresh_guard()
res3, *_ = run(rows, text_only, None, guard=g2)
check("S4 quota text without the redirect is caught too", res3[0]["verdict"] == "rate-limited" and len(lines(os.path.join(lg2, "site-walls.jsonl"))) == 1)
# a waiting row on a quota page is never demoted / backed off
rows_w = [row("bz2", "bizapedia.com", "pending-verify", BZ)]
g3, _ = fresh_guard()
res4, p4, db4 = run(rows_w, plain_quota, None, guard=g3, write=True)
check("S4 waiting row on a quota page: no history, no recheck_due, no transition", json.load(open(p4))["fix_queue"][0] == rows_w[0] and res4[0]["verdict"] == "rate-limited" and not db4.calls)
# Cloudflare wall (final page) logs and rate-limits too
g4, lg4 = fresh_guard()
res5, p5, _ = run([row("cf", "a.example", "live", U)], lambda u: R.Page(403, u, "", err="HTTP 403"), lambda u: R.Page(200, u, "Just a moment..." + PAD), guard=g4)
check("S4 Cloudflare wall: rate-limited, one log line, no row change", res5[0]["verdict"] == "rate-limited" and len(lines(os.path.join(lg4, "site-walls.jsonl"))) == 1 and not res5[0]["error"], str(res5[0]))

# ---- S5 replay is byte-identical to the live run it saved ------------------------------------------------------------------
rows = [row("a1", "a.example", "live", "https://a.example/biz/1"),
        row("b1", "b.example", "live", "https://b.example/biz/2"),
        row("c1", "c.example", "pending-verify", "https://c.example/biz/3"),
        row("d1", "bizapedia.com", "live", BZ)]
qp = queue(rows)
PLAIN = {"https://a.example/biz/1": R.Page(200, "https://a.example/biz/1", GOOD),
         "https://b.example/biz/2": R.Page(200, "https://b.example/biz/2", GOOD.replace("(502) 555-0101", "(502) 555-0199")),
         "https://c.example/biz/3": R.Page(403, "https://c.example/biz/3", "", err="HTTP 403"),
         BZ: R.Page(200, QURL, QUOTA)}
def fake_plain(u): return PLAIN[u]
def fake_chrome(u): return R.Page(200, u, GOOD, html="<html>%s</html>" % GOOD)
pages = os.path.join(TMP, "pages")
def main_out(argv, **kw):
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        rc = R.main(argv, **kw)
    return rc, buf.getvalue(), err.getvalue()
rc1, out1, e1 = main_out(["--queue", qp, "--include-live", "--live-sweep-ok", "--today", DAY, "--save-pages", pages], plain=fake_plain, chrome=fake_chrome)
saved = sorted(os.listdir(pages))
check("S5 live run saved the pages it read", rc1 == 0 and len(saved) >= 5 and any(s.startswith("chrome-") for s in saved), "%s %s" % (rc1, saved))
check("S5 live run: 1 plain read per row; 1 rendered read per live row that needs it; 2 for the waiting row", sum(s.startswith("plain-") for s in saved) == 4 and sum(s.startswith("chrome-") for s in saved) == 2, str(saved))   # b1: plain page lacks the phone -> rendered route once; c1: plain 403 -> rendered, ONE load (t_0c4ebee8: stability is inside it)
urllib.request.urlopen = _no_net
rc2, out2, e2 = main_out(["--queue", qp, "--include-live", "--today", DAY, "--replay", pages])
check("S5 replay output is byte-identical to the live run", rc2 == rc1 and out2 == out1 and "rate-limited" in out1, "\n--live--\n%s\n--replay--\n%s\n%s" % (out1, out2, e2))
check("S5 replay needs no --live-sweep-ok and never calls a fetcher",
      main_out(["--queue", qp, "--include-live", "--today", DAY, "--replay", pages], plain=_no_net, chrome=_no_net)[1] == out1)
rc3, o3, e3 = main_out(["--queue", qp, "--replay", pages, "--write"])
check("S5 replay refuses --write", rc3 == 1 and "REFUSED" in e3)
check("S5 the dry runs left the queue file alone", json.load(open(qp))["fix_queue"] == rows)

# ---- S6 --include-live without the flag refuses ----------------------------------------------------------------------------
hit = []
rc, o, e = main_out(["--queue", qp, "--include-live", "--today", DAY], plain=lambda u: hit.append(u), chrome=lambda u: hit.append(u))
check("S6 --include-live over the whole queue refuses, reads nothing", rc == 1 and "REFUSED" in e and "--live-sweep-ok" in e and not hit, e)
rc, o, e = main_out(["--queue", qp, "--include-live", "--row", "a1", "--today", DAY], plain=fake_plain, chrome=fake_chrome)
check("S6 --include-live --row ID (one named row) still works", rc == 0 and o.startswith("a1"), o)
rc, o, e = main_out(["--queue", qp, "--include-live", "--live-sweep-ok", "--today", DAY], plain=fake_plain, chrome=fake_chrome)
check("S6 --live-sweep-ok runs the sweep", rc == 0 and "4 rows read" in o, o)

# ---- S7 the reports show the walls ------------------------------------------------------------------------------------------
wl = os.path.join(TMP, "walls-logs"); os.makedirs(wl)
now = datetime.datetime.now()
with open(os.path.join(wl, "site-walls.jsonl"), "w") as f:
    for days, dom in ((0, "bizapedia.com"), (1, "bizapedia.com"), (2, "manta.com"), (9, "old.example")):
        f.write(json.dumps({"at": (now - datetime.timedelta(days=days)).isoformat(timespec="seconds"), "domain": dom}) + "\n")
cnt = SG.wall_counts(7, logs=wl)
check("S7 wall counts per domain, last 7 days only", cnt == {"bizapedia.com": 2, "manta.com": 1}, str(cnt))
check("S7 weekly line + workable table print them", SG.render_counts(cnt) == "SITE WALLS (7d): bizapedia.com walled 2 times, manta.com walled 1 time"
      and "bizapedia.com walled 2 times" in WK.render(WK.classify({"fix_queue": []}, DAY), DAY, walls=cnt))
import run as RUN
out = io.StringIO()
os.environ["CE_LOGS"] = wl
with contextlib.redirect_stdout(out):
    RUN.recheck_step(run=lambda **k: [{"row": "x", "before": "live", "after": "live", "verdict": "match", "error": None}])
check("S7 weekly recheck_step prints SITE WALLS (7d)", "SITE WALLS (7d): bizapedia.com walled 2 times" in out.getvalue(), out.getvalue())

# ---- S8 weekly discovery fetchers (core.HttpFetcher / ChromeFetcher) go through the guard (round 2) -------------------------
import types
for _m in ("playwright", "playwright.sync_api", "owned_chrome"):
    sys.modules.setdefault(_m, types.ModuleType(_m))
sys.modules["playwright.sync_api"].sync_playwright = lambda: None
for _n in ("OwnedChrome", "window_count", "chrome_windows"): setattr(sys.modules["owned_chrome"], _n, lambda *a, **k: None)
import core, discover as D

class FakeHttp:
    name = "http"; block = None
    def __init__(self, texts=None): self.seen = []; self.texts = texts or {}
    def fetch(self, url, label=""): self.seen.append(url); return core.Result(200, self.texts.get(url, url), self.texts.get(url, GOODSC), [])
class FakeChrome(FakeHttp):
    name = "chrome"
GOODSC = "filler text " * 120
fcore = types.SimpleNamespace(Result=core.Result, HttpFetcher=FakeHttp, ChromeFetcher=FakeChrome)
g8, lg8 = fresh_guard(gap=0, caps={"bizapedia.com": 3})
undo8 = SG.guard_fetchers(fcore, g8)
h, c = fcore.HttpFetcher(), fcore.ChromeFetcher()
BZ1 = "https://www.bizapedia.com/search.aspx?q=%s"
rs = [(h if i % 2 == 0 else c).fetch(BZ1 % i) for i in range(4)]
check("S8 Http and Chrome fetchers share one daily cap: 3 reads reach the site, the 4th does not", len(h.seen) + len(c.seen) == 3 and rs[3].err and "daily cap" in rs[3].err, str(rs[3].err))
r8 = core.classify(rs[3], "SCC")
check("S8 a capped read is `blocked` for discovery (couldnt_check), never noresult/absent", r8 == "blocked")
res8 = D.discover(h, "bizapedia.com", "SCC", [("search", BZ1 % 9)], [])
check("S8 discover() on a capped domain: status couldnt, not noresult", res8["status"] == "couldnt", str(res8))
undo8()
check("S8 undo restores the original fetch", fcore.HttpFetcher.fetch is FakeHttp.fetch and not hasattr(FakeHttp.fetch, "__wrapped__"))

# quota page through a fetcher: wall logged once, cooldown, result is blocked
class QuotaHttp(FakeHttp):
    def fetch(self, url, label=""): self.seen.append(url); return core.Result(200, "https://www.bizapedia.com/pro-search-subscription.aspx?x=1", QUOTA, [])
fq = types.SimpleNamespace(Result=core.Result, HttpFetcher=QuotaHttp, ChromeFetcher=FakeChrome)
gq, lq = fresh_guard(gap=0, caps={"bizapedia.com": 3})
uq = SG.guard_fetchers(fq, gq); q1 = fq.HttpFetcher(); rq = [q1.fetch(BZ1 % i) for i in range(3)]
check("S8 quota page via a core fetcher: walled once, later reads refused with no fetch", len(q1.seen) == 1 and "cooldown" in rq[1].err and len(lines(os.path.join(lq, "site-walls.jsonl"))) == 1, str([x.err for x in rq]))
check("S8 quota page classifies blocked -> couldnt", core.classify(rq[0], "SCC") == "blocked" and D.discover(q1, "bizapedia.com", "SCC", [("search", BZ1 % 5)], [])["status"] == "couldnt")
uq()

# the gap across two processes for the core fetchers
child8 = ("import os,sys,time,types; sys.path.insert(0, %r)\nimport sitegate as SG\nclass R:\n    def __init__(s,*a): s.err=None; s.url=a[1]; s.text='x'; s.status=200\nclass H:\n    block=None\n    def fetch(self,url,label=''): return R(0,url)\nclass C(H): pass\ncore=types.SimpleNamespace(Result=R,HttpFetcher=H,ChromeFetcher=C)\nSG.guard_fetchers(core, SG.SiteGuard())\nr=core.ChromeFetcher().fetch('https://gap8.example/'+sys.argv[1])\nprint(time.time(), r.err)\n" % os.path.join(HERE, "..", "job"))
env8 = dict(os.environ, CE_SITE_GUARD=os.path.join(TMP, "two-proc8", "g.json"), CE_SITE_GAP="2", CE_LOGS=os.path.join(TMP, "two-proc8", "logs"))
procs8 = [subprocess.Popen([sys.executable, "-c", child8, "u%d" % i], env=env8, stdout=subprocess.PIPE, text=True) for i in range(2)]
o8 = [pr.communicate()[0].split() for pr in procs8]
t8 = sorted(float(o[0]) for o in o8)
check("S8 two processes through the core fetchers: reads >= gap apart", len(o8) == 2 and all(o[1] == "None" for o in o8) and t8[1] - t8[0] >= 1.8, str(o8))

# blocked-on-purpose is no read
gb8, _ = fresh_guard(gap=0, caps={"bizapedia.com": 1})
fb = types.SimpleNamespace(Result=core.Result, HttpFetcher=FakeHttp, ChromeFetcher=FakeChrome); ub = SG.guard_fetchers(fb, gb8)
hb = fb.HttpFetcher(); hb.block = "yellowpages.com"; hb.fetch("https://www.yellowpages.com/x"); hb.fetch("https://www.yellowpages.com/y")
check("S8 blocked-on-purpose URLs do not use the ledger", not os.path.exists(gb8.path) or "yellowpages.com" not in json.load(open(gb8.path))); ub()

# known listing: read the URL, skip the search; SCC before NM under a cap; FAKE control not run on a capped domain
check("S8 order: SCC (the client) is read before NM before the made-up control", D.BIZS.index("SCC") < D.BIZS.index("NM") < D.BIZS.index("FAKE"))
D.KNOWN.clear(); D.SETTLED.clear()
p_search, _s = D.plan_or_known("search", "bizapedia.com", "SCC")
check("S8 no known listing: the search runs", p_search and p_search[0][0] == "search" and "search.aspx" in p_search[0][1], str(p_search))
D.KNOWN[("SCC", "manta.com")] = "https://www.manta.com/c/abc/senior-care"
p_known, _s = D.plan_or_known("search", "manta.com", "SCC")
check("S8 known listing_url: that URL is read and the Directory search is SKIPPED", p_known == [("pattern", "https://www.manta.com/c/abc/senior-care")], str(p_known))
D.settle("SCC", "manta.com", "found"); pk, _s = D.plan_or_known("pattern", "manta.com", "SCC")
check("S8 once answered found, later methods/passes do not read it again", pk is None)
pf, why = D.plan_or_known("search", "bizapedia.com", "FAKE")
check("S8 the made-up control is not run on a read-capped domain", pf is None and "capped" in why, why)
D.KNOWN.clear(); D.SETTLED.clear()
gc, _ = fresh_guard(gap=0, caps={"bizapedia.com": 1})
fcc = types.SimpleNamespace(Result=core.Result, HttpFetcher=FakeHttp, ChromeFetcher=FakeChrome); uc = SG.guard_fetchers(fcc, gc); hc = fcc.HttpFetcher(); order = {}
for b in D.BIZS:
    plan, _s = D.plan_or_known("search", "bizapedia.com", b)
    if plan: order[b] = D.discover(hc, "bizapedia.com", b, plan, [])["status"]
check("S8 cap of 1 read: SCC gets it, NM is couldnt (not absent), FAKE not run", order.get("SCC") != "couldnt" and order.get("NM") == "couldnt" and "FAKE" not in order and len(hc.seen) == 1, str((order, hc.seen))); uc()

# known_listings: queue rows + the newest earlier run's found rows
kd = tempfile.mkdtemp(dir=TMP); os.makedirs(os.path.join(kd, "20261101-1100")); os.makedirs(os.path.join(kd, "20261025-1100")); os.makedirs(os.path.join(kd, "20261105-0900"))
open(os.path.join(kd, "20261101-1100", "rows.jsonl"), "w").write(json.dumps({"kind": "dir", "biz": "NM", "dir": "bbb.org", "status": "found", "url": "https://bbb.example/nm"}) + "\n" + json.dumps({"kind": "dir", "biz": "NM", "dir": "yelp.com", "status": "couldnt", "url": ""}) + "\n")
open(os.path.join(kd, "20261025-1100", "rows.jsonl"), "w").write(json.dumps({"kind": "dir", "biz": "NM", "dir": "old.example", "status": "found", "url": "https://old.example/nm"}) + "\n")
open(os.path.join(kd, "20261105-0900", "rows.jsonl"), "w").write("")
kn = SG.known_listings({"fix_queue": [{"directory": "bing.com", "listing_url": "https://bing.example/scc", "state": "live"}, {"directory": "z.example", "listing_url": "https://z.example/1", "state": "rejected"}]}, kd)
check("S8 known_listings: queue listing_url + newest earlier run's found rows only", kn == {("SCC", "bing.com"): "https://bing.example/scc", ("NM", "bbb.org"): "https://bbb.example/nm"}, str(kn))

# ---- S9 round 3: a known URL is requested once per transport; best known URL; map boxes behind the guard ----------------------
class _Stop(Exception): pass
class _NoChrome:
    def __enter__(self): raise _Stop()
    def __exit__(self, *a): return False
SEEN9 = []
class Shell9(FakeHttp):
    def fetch(self, url, label=""): SEEN9.append(url); return core.Result(200, url, "<html><body>loading...</body></html>", [])
KN9 = "https://www.yellowpages.com/exampleton-ky/mip/alder-care-123"
sv = (D.DIRS, D.BIZS, D.OUT, D.HttpFetcher, D.OwnedChrome)
os.environ["CE_SHOTS"] = os.path.join(TMP, "shots9")
D.DIRS = ["yellowpages.com", "manta.com"]; D.BIZS = ["SCC"]; D.OUT = os.path.join(TMP, "rows9.jsonl")
D.HttpFetcher = Shell9; D.OwnedChrome = _NoChrome
D.KNOWN.clear(); D.SETTLED.clear(); D.TRIED.clear(); D.KNOWN[("SCC", "yellowpages.com")] = KN9
try: D.discover_all()
except _Stop: pass
check("S9 discover_all phase A: the known URL is requested exactly ONCE (was 3x)", SEEN9.count(KN9) == 1, str(SEEN9.count(KN9)))
check("S9 identical-URL repeats through discover_all = 0", len(SEEN9) - len(set(SEEN9)) == 0, str([u for u in set(SEEN9) if SEEN9.count(u) > 1]))
check("S9 after a miss, the later methods use the normal plan (the search URL is read)", core.plan_for("search", "yellowpages.com", "SCC")[0][1] in SEEN9, str(SEEN9))
rows9 = [json.loads(l) for l in open(D.OUT, encoding="utf-8")]
check("S9 the missed pair is not absent (no found/noresult invented by the skip)", not any(r.get("dir") == "yellowpages.com" and r.get("status") == "found" for r in rows9))
D.DIRS, D.BIZS, D.OUT, D.HttpFetcher, D.OwnedChrome = sv

# the Chrome ladder: one request of the known URL on that transport
class LadderF(FakeHttp):
    name = "chrome"; caption = ""
    def fetch(self, url, label=""): self.seen.append(url); return core.Result(200, url, "<html>loading</html>", [])
sv = (D.DIRS, D.BIZS, D.OUT); D.DIRS = ["yellowpages.com"]; D.BIZS = ["SCC"]; D.OUT = os.path.join(TMP, "rows9b.jsonl")
D.KNOWN.clear(); D.SETTLED.clear(); D.TRIED.clear(); D.KNOWN[("SCC", "yellowpages.com")] = KN9
lf = LadderF(); D.ladder(lf, "chrome", ["search", "pattern", "phone"], "t")
check("S9 chrome ladder: known URL requested once; repeats 0", lf.seen.count(KN9) == 1 and len(lf.seen) == len(set(lf.seen)), str(lf.seen))
D.DIRS, D.BIZS, D.OUT = sv
D.KNOWN.clear(); D.SETTLED.clear(); D.TRIED.clear()
D.KNOWN[("SCC", "bing.com")] = "https://www.bing.com/maps?q=alder"
pm, _s = D.plan_or_known("search", "bing.com", "SCC", "http")
check("S9 a known map search page keeps kind=search (judge: map page text)", pm == [("search", "https://www.bing.com/maps?q=alder")], str(pm))
D.KNOWN.clear(); D.TRIED.clear()

# a found search page IS the plan's search URL: it must not be requested a 2nd time by the fallback
SEEN9.clear(); sv = (D.DIRS, D.BIZS, D.OUT, D.HttpFetcher, D.OwnedChrome)
SU9 = core.plan_for("search", "google.com", "SCC")[0][1]
D.DIRS = ["google.com"]; D.BIZS = ["SCC"]; D.OUT = os.path.join(TMP, "rows9c.jsonl"); D.HttpFetcher = Shell9; D.OwnedChrome = _NoChrome
D.KNOWN.clear(); D.SETTLED.clear(); D.TRIED.clear(); D.KNOWN[("SCC", "google.com")] = SU9
try: D.discover_all()
except _Stop: pass
check("S9 known URL == the search URL: requested once, not again by the fallback; repeats 0", SEEN9.count(SU9) == 1 and len(SEEN9) == len(set(SEEN9)), str(SEEN9))
D.DIRS, D.BIZS, D.OUT, D.HttpFetcher, D.OwnedChrome = sv; D.KNOWN.clear(); D.SETTLED.clear(); D.TRIED.clear()

pd9, _s = D.plan_or_known("pattern", "mapquest.com", "NM", "http")
check("S9 a plan that lists one URL twice (NM mapquest pattern) asks it once", len(pd9) == len(set(pd9)) and len(core.plan_for("pattern", "mapquest.com", "NM")) > len(pd9), str(pd9))

# known_listings: resolver > permalink-shaped > first found
kd9 = tempfile.mkdtemp(dir=TMP); os.makedirs(os.path.join(kd9, "20261101-1100"))
def _row(biz, d, url, method="http-search"): return json.dumps({"kind": "dir", "method": method, "biz": biz, "dir": d, "status": "found", "url": url}) + "\n"
open(os.path.join(kd9, "20261101-1100", "rows.jsonl"), "w").write(
    _row("SCC", "yellowpages.com", "https://www.yellowpages.com/exampleton-ky/alder-care") + _row("SCC", "yellowpages.com", KN9, "chrome-resolver") +
    _row("NM", "manta.com", "https://www.manta.com/search?q=x") + _row("NM", "manta.com", "https://www.manta.com/c/mabc123/nm-co") +
    _row("NM", "n49.com", "https://www.n49.com/search/x") + _row("NM", "n49.com", "https://www.n49.com/search/y"))
k9 = SG.known_listings({}, kd9)
check("S9 known_listings: the resolver permalink beats the earlier match page", k9[("SCC", "yellowpages.com")] == KN9, str(k9))
check("S9 known_listings: a permalink-shaped URL beats a search page", k9[("NM", "manta.com")] == "https://www.manta.com/c/mabc123/nm-co", str(k9))
check("S9 known_listings: nothing better -> first found", k9[("NM", "n49.com")] == "https://www.n49.com/search/x", str(k9))

# mapnap.lookup behind the guard
g9, _l = fresh_guard(gap=0, caps={"mapquest.com": 1}); called9 = []
def _lookup(ctx, rec, d, b, kind, q, caption, tag): called9.append(d); return {"text": "page", "url": "u", "shot": "", "note": "", "verified": True, "results": 2, "links": []}
w9 = SG.guard_mapnap(_lookup, g9)
a9 = w9(None, None, "mapquest.com", "SCC", "name", "q", "c", "t1"); b9 = w9(None, None, "mapquest.com", "SCC", "phone", "q", "c", "t2")
check("S9 mapnap: first read passes, 2nd is refused at the cap and the real lookup is NOT called", a9["verified"] and called9 == ["mapquest.com"] and not b9["verified"] and b9["results"] == 0 and "daily cap" in b9["note"], str(b9))
st9 = "found" if False else ("noresult" if (b9["verified"] and b9["results"] >= 1) else "couldnt")
check("S9 mapnap: refusal gives couldnt, never noresult", st9 == "couldnt")
g9.wall("google.com", "test"); c9 = w9(None, None, "google.com", "SCC", "name", "q", "c", "t3")
check("S9 mapnap: a cooldown also refuses (lookup not called)", not c9["verified"] and "cooldown" in c9["note"] and called9 == ["mapquest.com"], str(c9))
d9 = w9(None, None, "bing.com", "SCC", "name", "q", "c", "t4")
check("S9 mapnap: an unwalled uncapped domain passes through", d9["verified"] and called9[-1] == "bing.com")

# ---- S10 map-box walls, proof.py and build_proof.py behind the guard (t_f5d80477) -----------------------------------------------------------
import proof as PR
import build_proof as BP

CAPTCHA = "About this page\nOur systems have detected unusual traffic from your computer network. Please try your request again later."
gm, lm = fresh_guard(gap=0); callm = []
def _lk(text, url="https://www.google.com/maps", panel=False):
    def f(ctx, rec, d, b, kind, q, caption, tag):
        callm.append(d); return {"text": text, "url": url, "shot": "", "note": "", "verified": True, "results": 3, "links": [], "panel": panel}
    return f
wm = SG.guard_mapnap(_lk(CAPTCHA), gm)
r1 = wm(None, None, "google.com", "SCC", "name", "q", "c", "t1")
check("S10 map captcha text: lookup is couldnt (not verified, 0 results)", not r1["verified"] and r1["results"] == 0 and "site-guard" in r1["note"], str(r1))
wl = lines(os.path.join(lm, "site-walls.jsonl"))
check("S10 map captcha: one site-walls.jsonl line with the domain", len(wl) == 1 and wl[0]["domain"] == "google.com" and wl[0]["row"] == "SCC", str(wl))
r2 = wm(None, None, "google.com", "SCC", "phone", "q", "c", "t2")
check("S10 map captcha: the next lookup on that domain is refused, real lookup NOT called", "cooldown" in r2["note"] and callm == ["google.com"] and not r2["verified"], str((r2, callm)))
check("S10 map captcha: other map domains are not on cooldown", SG.guard_mapnap(_lk("Joe's Pizza\n123 Main St"), gm)(None, None, "bing.com", "SCC", "name", "q", "c", "t3")["verified"])
check("S10 google /sorry/ url is a wall", SG.map_wall({"text": "", "url": "https://www.google.com/sorry/index?continue=x", "panel": False}) is not None)
check("S10 a rendered place panel is never a wall even with captcha words", SG.map_wall({"text": CAPTCHA, "url": "https://www.google.com/maps/place/x", "panel": True}) is None)
check("S10 an ordinary results page is no wall", SG.map_wall({"text": "Alder Care Consulting\n100 Example Exampleton KY\n(502) 555-0101", "url": "u", "panel": False}) is None)
gq, lq = fresh_guard(gap=0); wq = SG.guard_mapnap(_lk("Please complete the captcha to continue", "https://www.mapquest.com/"), gq)
wq(None, None, "mapquest.com", "SCC", "name", "q", "c", "t"); check("S10 mapquest / bing captcha text also walls", len(lines(os.path.join(lq, "site-walls.jsonl"))) == 1)

# proof_step: shared cap, refusal is rate-limited (never mismatch), queue row untouched
def proof_queue(directory="bizapedia.com"):
    p = os.path.join(tempfile.mkdtemp(dir=TMP), "q.json")
    json.dump({"canonical": CANON, "create_rows": [{"id": "create-b", "directory": directory, "state": "needs-human", "mike_approval": None, "evidence_url": None, "history": []}]}, open(p, "w"))
    return p
def pchk(directory="bizapedia.com", n=""):
    return dict(biz="SCC", directory=directory, result="found", url="https://www.%s/%s/alder-care%s" % (directory, "biz" if directory == "yelp.com" else "company", n), nap_shown="Alder Care Consulting & Solutions | 100 Example | (502) 555-0101",
                name_match=True, street_match=True, phone_match=True, match=True, diffs=[], note=None)
class DB:
    owner = "o"
    def __init__(s): s.calls = []
    def call(s, m, p, body=None, prefer=None): s.calls.append((m, p, body))
reads10 = []; plain_calls = []
def plain10(url, *a, **k): plain_calls.append(url); return R.Page(200, url, "")   # a JS shell: forces the rendered read
def chrome10(url, *a, **k): reads10.append(url); return R.Page(200, url, GOOD) if hasattr(R, "Page") else None
gp, lp = fresh_guard(gap=0, caps={"bizapedia.com": 3})
for i in range(2): gp.reserve("bizapedia.com", key="core-%d" % i)   # the core fetchers already used 2 of 3
rec10 = []
qp = proof_queue(); res10 = PR.proof_step([pchk()], DAY, queue_path=qp, db=DB(), record=lambda *a, **k: rec10.append(a) or {"errors": []}, guard=gp, chrome=chrome10, plain=plain10)
check("S10 proof read is the 3rd (last) bizapedia read: shared cap counted core + proof", json.load(open(gp.path))["bizapedia.com"]["count"] == 3 and reads10 and reads10[0].endswith("/company/alder-care"), str(reads10))
reads10.clear(); plain_calls.clear(); qp2 = proof_queue(); db10 = DB()
res11 = PR.proof_step([pchk(n="-2")], DAY, queue_path=qp2, db=db10, record=lambda *a, **k: rec10.append(a) or {"errors": []}, guard=gp, chrome=chrome10, plain=plain10)
check("S10 proof read after the cap: refused, chrome NOT called", reads10 == [], str(reads10))
check("S10 proof read after the cap: refused, plain GET NOT made", plain_calls == [], str(plain_calls))
check("S10 refused proof read: limited, untouched, no mismatch, no DB write, row unchanged", res11["limited"] == ["bizapedia.com"] and res11["untouched"] == ["bizapedia.com"] and not res11["mismatched"] and not res11["moved"] and db10.calls == []
      and json.load(open(qp2))["create_rows"][0]["state"] == "needs-human", str(res11))
# a Cloudflare wall page on the proof read: rate-limited, cooldown + one wall line
gw, lw = fresh_guard(gap=0); CFP = "Just a moment...\nChecking your browser before accessing the site.\n"
res12 = PR.proof_step([pchk("yelp.com")], DAY, queue_path=proof_queue("yelp.com"), db=DB(), record=lambda *a, **k: {"errors": []}, guard=gw, plain=lambda url, *a, **k: R.Page(200, url, CFP), chrome=lambda url, *a, **k: R.Page(200, url, CFP))
w12 = lines(os.path.join(lw, "site-walls.jsonl"))
check("S10 proof read hits a Cloudflare page: limited, wall logged once, no mismatch", res12["limited"] == ["yelp.com"] and not res12["mismatched"] and len(w12) == 1 and w12[0]["domain"] == "yelp.com", str((res12, w12)))
check("S10 ... and the next proof read on that domain is refused (cooldown)", PR.recheck_verdict("https://www.yelp.com/biz/x", CANON, guard=gw, plain=plain10, chrome=lambda u, *a, **k: R.Page(200, u, GOOD))["verdict"] == "rate-limited")
# default reader path (no chrome injected) asks the guard first: with a cooldown no Chrome is ever started
gc, _lc = fresh_guard(gap=0); gc.wall("manta.com", "test"); started = []
_orig_so = R.SignedOutReader.__call__; R.SignedOutReader.__call__ = lambda self, *a, **k: started.append(a) or R.Page(0, a[0], "", err="started")
_orig_pf = R.plain_fetch; real_plain = []; R.plain_fetch = lambda url, *a, **k: real_plain.append(url) or R.Page(0, url, "", err="blocked in test")
try: v13 = PR.recheck_verdict("https://www.manta.com/c/x", CANON, guard=gc)
finally: R.SignedOutReader.__call__ = _orig_so; R.plain_fetch = _orig_pf
check("S10 default plain reader is behind the guard: cooldown -> plain_fetch never called", real_plain == [], str(real_plain))
check("S10 default signed-out reader is behind the guard: cooldown -> rate-limited, Chrome page never loaded", v13["verdict"] == "rate-limited" and started == [], str((v13, started)))
check("S10 run.proof_step_run + proof_step build their own SiteGuard (same ledger) when none is passed", "SiteGuard()" in open(os.path.join(HERE, "..", "job", "proof.py"), encoding="utf-8").read())

# build_proof: reserve before the page load; refused -> no goto
class FakePg:
    def __init__(s): s.gotos = []
    def goto(s, url, **k): s.gotos.append(url); return types.SimpleNamespace(status=200)
gb10, _l = fresh_guard(gap=0, caps={"bizapedia.com": 3}); pg10 = FakePg(); out10 = []
for i in range(5): out10.append(BP.guarded_goto(pg10, gb10, "bizapedia.com", "https://www.bizapedia.com/?%d" % i))
check("S10 build_proof: 3 goto then refused at the shared cap, 2 refused pages never loaded", len(pg10.gotos) == 3 and [o[1] is None for o in out10] == [True, True, True, False, False] and "daily cap" in out10[3][1], str(out10))
check("S10 build_proof: its reads count in the ledger the weekly uses", json.load(open(gb10.path))["bizapedia.com"]["count"] == 3)
gb11, _l = fresh_guard(gap=0); gb11.wall("yelp.com", "t"); pg11 = FakePg()
check("S10 build_proof: a cooled-down domain is refused, no goto", BP.guarded_goto(pg11, gb11, "yelp.com", "https://www.yelp.com/")[1] and pg11.gotos == [])
check("S10 build_proof main() routes every goto through guarded_goto", "pg.goto(" not in open(os.path.join(HERE, "..", "job", "build_proof.py"), encoding="utf-8").read().split("def main")[1])

# the gap holds across two processes for the proof / build_proof path (same domain, two processes)
child10 = ("import os,sys,time,types; sys.path.insert(0, %r)\nimport sitegate as SG, build_proof as BP\nclass P:\n    def goto(s,url,**k): return types.SimpleNamespace(status=200)\n"
           "g=SG.SiteGuard()\nBP.guarded_goto(P(), g, 'yelp.com', sys.argv[1])\nprint(time.time())\n" % os.path.join(HERE, "..", "job"))
env10 = dict(os.environ, CE_SITE_GUARD=os.path.join(TMP, "two-proc10", "g.json"), CE_SITE_GAP="2", CE_LOGS=os.path.join(TMP, "two-proc10", "logs"))
procs10 = [subprocess.Popen([sys.executable, "-c", child10, "https://www.yelp.com/%d" % i], env=env10, stdout=subprocess.PIPE, text=True) for i in range(2)]
t10 = sorted(float(pr.communicate()[0].split()[0]) for pr in procs10)
check("S10 two processes (build_proof path) on one domain: goto >= gap apart", t10[1] - t10[0] >= 1.8, str(t10))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
