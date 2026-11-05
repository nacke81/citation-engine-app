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
check("S1 a row about to go live: ONE confirming read, not two", [c[0] for c in calls].count("chrome") == R.STABLE_READS == 2 and res[0]["after"] == "live", str(calls))
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
check("S5 live run: 1 plain read per row; 1 rendered read per live row that needs it; 2 for the waiting row", sum(s.startswith("plain-") for s in saved) == 4 and sum(s.startswith("chrome-") for s in saved) == 3, str(saved))   # b1: plain page lacks the phone -> rendered route once; c1: plain 403 -> rendered, 2 reads (about to go live)
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

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
