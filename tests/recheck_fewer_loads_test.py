"""Fewer, spaced Directory loads (t_0c4ebee8). Offline: fake readers, fake pages, fake clock, poisoned urlopen. Run: python tests/recheck_fewer_loads_test.py"""
import os, sys, json, io, tempfile, contextlib, urllib.request, time
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="ce-fewer-loads-")
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = os.path.join(TMP, "runs")
os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard", "site-guard.json")
os.environ["CE_LOGS"] = os.path.join(TMP, "logs")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
os.environ.pop("CE_CHROME_VISIBLE", None)
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import recheck as R
import sitegate as SG
import transitions as T
import chrome_keepalive as KA

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
LATE = "Home\nAlder Care Consulting & Solutions\n(502) 555-0101\n" + PAD   # street not loaded yet

class FakeDB:
    owner = "o"
    def __init__(self): self.calls = []
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))

# ---- F1 the stability wait lives INSIDE the one load, polls ~3s apart, never longer than 20s ----------------------------
class Pg:
    url = "https://a.example/biz/1"
    def __init__(self, texts): self.texts, self.waits, self.i = texts, [], 0
    def goto(self, *a, **k): return type("Resp", (), {"status": 200})()
    def wait_for_timeout(self, ms): self.waits.append(ms)
    def inner_text(self, sel, timeout=0):
        t = self.texts[min(self.i, len(self.texts) - 1)]; self.i += 1; return t
    def evaluate(self, js): return 0 if "click" in js else []
    def content(self): return "<html></html>"
pg = Pg([GOOD])
st, text, links, raw = R.read_rendered(pg, "https://a.example/biz/1", 30, CANON)
check("F1 a page that matches and holds still: read ends after 2 polls (first 2s, then one 3s poll)", pg.waits == [2000, 3000] and R.compare(text, CANON)["verdict"] == "match", str(pg.waits))
pg = Pg([LATE, LATE, GOOD, GOOD])
st, text, links, raw = R.read_rendered(pg, "https://a.example/biz/1", 30, CANON)
check("F1 a street that loads late is waited for inside the SAME load", R.compare(text, CANON)["verdict"] == "match" and pg.waits[0] == 2000 and set(pg.waits[1:]) == {3000}, str(pg.waits))
pg = Pg([GOOD + str(n) for n in range(100)])   # a page that never stops changing
R.read_rendered(pg, "https://a.example/biz/1", 30, CANON)
check("F1 a page that never settles is cut off: no more than 20s of polling after it first read", sum(pg.waits[1:]) <= R.STABLE_MAX_S * 1000 and len(pg.waits) >= 3, str(pg.waits))

# ---- F2 a row about to go live: ONE load, ONE guard reservation, no second back-to-back load (fake clock) -----------------
clock = [1_800_000_000.0]; slept = []
def fresh_guard(**kw):
    d = tempfile.mkdtemp(dir=TMP)
    return SG.SiteGuard(path=os.path.join(d, "g.json"), logs=os.path.join(d, "logs"), now=lambda: clock[0], sleep=lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)), **kw), os.path.join(d, "logs")
U = "https://a.example/biz/1"
def row(rid, state="pending-verify", url=U):
    return {"id": rid, "directory": "a.example", "state": state, "mike_approval": None, "evidence_url": url, "listing_url": url, "history": []}
def qfile(rows):
    p = os.path.join(tempfile.mkdtemp(dir=TMP), "q.json"); json.dump({"canonical": CANON, "fix_queue": rows}, open(p, "w")); return p
def go(rows, plain, chrome, guard=None, write=False, **kw):
    p = qfile(rows); db = FakeDB()
    rec = lambda *a, **k: {}   # the transition writers have their own tests; here only what was READ matters
    res = R.recheck(json.load(open(p)), IDENT, plain=plain, chrome=chrome, record=rec, db=db, queue_path=p, today=DAY, guard=guard, write=write, **kw)
    return res, p, db
calls = []
def plain_403(u): calls.append(("plain", u)); return R.Page(403, u, "", err="HTTP 403")
def chrome_ok(u): calls.append(("chrome", u)); return R.Page(200, u, GOOD, html="<html>%s</html>" % GOOD)
g, lg = fresh_guard(gap=30)
res, p, db = go([row("r1")], plain_403, chrome_ok, guard=g)
resv = [json.loads(l) for l in open(os.path.join(lg, "site-reads.jsonl"), encoding="utf-8")]
check("F2 dry run on a not-yet-live row: one plain, ONE Chrome load, 1 guard reservation, nothing slept", [c[0] for c in calls] == ["plain", "chrome"] and len(resv) == 1 and not slept and res[0]["verdict"] == "match", "%s %s %s" % (calls, resv, slept))

# ---- F3 --write --from-read: a fresh saved read makes 0 network reads -------------------------------------------------------
pages = os.path.join(TMP, "pages")
calls.clear()
g, lg = fresh_guard(gap=30)
res1, p1, db1 = go([row("r1")], plain_403, chrome_ok, guard=g, store=R.PageStore(pages))
saved = sorted(os.listdir(pages))
check("F3 dry run saved its pages", any(s.startswith("chrome-") for s in saved) and any(s.startswith("plain-") for s in saved), str(saved))
n_dry = len(calls); n_resv = len(open(os.path.join(lg, "site-reads.jsonl")).readlines())
def boom(u): raise AssertionError("network read on a fresh --from-read: %s" % u)
reuse = R.PageStore(pages, replay=True)
res2, p2, db2 = go([row("r1")], boom, boom, guard=g, write=True, from_read=reuse)
check("F3 write from a fresh saved read: 0 plain / Chrome reads, 0 new guard reservations", reuse.reused >= 2 and len(open(os.path.join(lg, "site-reads.jsonl")).readlines()) == n_resv, "reused=%s" % reuse.reused)
check("F3 ... and the row still goes live with the same verdict as the dry run", res2[0]["after"] == "live" and res2[0]["verdict"] == res1[0]["verdict"] == "match", str(res2[0]))

# ---- F4 stale saved read -> falls back to ONE live read per route -------------------------------------------------------------
old = time.time() - (R.SAVED_MAX_AGE_S + 60)
for s in os.listdir(pages): os.utime(os.path.join(pages, s), (old, old))
calls.clear()
res3, p3, db3 = go([row("r1")], plain_403, chrome_ok, guard=g, write=True, from_read=R.PageStore(pages, replay=True))
check("F4 stale (16 min) saved read: ignored, exactly one live read (one plain + one Chrome, as a normal write)", [c[0] for c in calls] == ["plain", "chrome"] and res3[0]["after"] == "live", str(calls))
# fresh just under the limit still counts
young = time.time() - (R.SAVED_MAX_AGE_S - 120)
for s in os.listdir(pages): os.utime(os.path.join(pages, s), (young, young))
calls.clear()
res3b, *_ = go([row("r1")], boom, boom, guard=g, write=True, from_read=R.PageStore(pages, replay=True))
check("F4 a 13-minute-old saved read is still fresh", res3b[0]["after"] == "live" and not calls)

# ---- F5 mismatched URL -> live read ------------------------------------------------------------------------------------------
now = time.time()
for s in os.listdir(pages): os.utime(os.path.join(pages, s), (now, now))
U2 = "https://a.example/biz/2"
calls.clear()
res4, *_ = go([row("r1", url=U2)], plain_403, chrome_ok, guard=g, write=True, from_read=R.PageStore(pages, replay=True))
check("F5 row URL differs from the saved read: live read of the NEW url only", [c[1] for c in calls] == [U2, U2] and res4[0]["after"] == "live", str(calls))
# a saved file whose body names another url (renamed / copied file) is not reused either
for s in os.listdir(pages):
    d = json.load(open(os.path.join(pages, s), encoding="utf-8")); d["url"] = "https://a.example/other"; json.dump(d, open(os.path.join(pages, s), "w", encoding="utf-8"))
calls.clear()
res5, *_ = go([row("r1")], plain_403, chrome_ok, guard=g, write=True, from_read=R.PageStore(pages, replay=True))
check("F5 saved body names a different url: not reused, one live read", [c[0] for c in calls] == ["plain", "chrome"], str(calls))
# a guard-refused / quota page is never reused
for s in os.listdir(pages):
    d = json.load(open(os.path.join(pages, s), encoding="utf-8")); d["url"] = U; d["limited"] = "daily cap"; json.dump(d, open(os.path.join(pages, s), "w", encoding="utf-8"))
calls.clear()
go([row("r1")], plain_403, chrome_ok, guard=g, write=True, from_read=R.PageStore(pages, replay=True))
check("F5 a saved page marked limited is not reused", [c[0] for c in calls] == ["plain", "chrome"], str(calls))
# no saved pages at all -> reads once as today
calls.clear()
go([row("r1")], plain_403, chrome_ok, guard=g, write=True, from_read=R.PageStore(os.path.join(TMP, "nothing"), replay=True))
check("F5 empty folder: reads as a normal write", [c[0] for c in calls] == ["plain", "chrome"])

# ---- F6 the CLI -----------------------------------------------------------------------------------------------------------------
def cli(argv):
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        rc = R.main(argv)
    return rc, err.getvalue()
qp = qfile([row("r1")])
rc, e = cli(["--queue", qp, "--from-read", pages])
check("F6 --from-read without --write is refused", rc == 1 and "REFUSED" in e, e)
rc, e = cli(["--queue", qp, "--write", "--from-read", pages, "--replay", pages])
check("F6 --from-read with --replay is refused", rc == 1 and "REFUSED" in e, e)
rc, e = cli(["--queue", qp, "--write", "--from-read", pages, "--save-pages", pages])
check("F6 --from-read with --save-pages is refused", rc == 1 and "REFUSED" in e, e)

# ---- F7 the Chrome window starts off-screen ------------------------------------------------------------------------------------
check("F7 build Chrome launch args carry --window-position=-32000,-32000 by default", "--window-position=-32000,-32000" in KA.chrome_args(), str(KA.chrome_args()))
os.environ["CE_CHROME_VISIBLE"] = "1"
check("F7 CE_CHROME_VISIBLE=1 brings the window back to 40,40", "--window-position=40,40" in KA.chrome_args())
del os.environ["CE_CHROME_VISIBLE"]
src = open(os.path.join(HERE, "..", "job", "owned_chrome.py"), encoding="utf-8").read()
check("F7 the signed-out reader's OwnedChrome uses the same off-screen position (no hard-coded 40,40)", "window_pos()" in src and "40,40" not in src)

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
