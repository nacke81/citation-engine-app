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
pg = Pg([(GOOD if n % 2 else GOOD.replace("555-0101", "555-9999")) for n in range(100)])   # a page whose phone never stops changing (round 1: a changing body with a stable NAP stops early, see F8)
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

# ---- F8 round 1: the wait judges the NAP READ; a page whose NAP never settles is never live, in either phase ------------------
BAD = GOOD.replace("(502) 555-0101", "(502) 555-9999")   # the old phone
def chrome_via(pg):
    def chrome(u):
        info = {}
        st, t, l, raw = R.read_rendered(pg, u, 30, CANON, None, info)
        return R.Page(st, u, t, l, html=raw, unstable=info.get("unstable"))
    return chrome
def flip(first, second): return Pg([first, second] * 40)
def listing(mod, pg):
    return mod.read_listing(U, plain_403, chrome_via_mod(mod, pg), CANON)
def chrome_via_mod(mod, pg):
    def chrome(u):
        info = {}
        st, t, l, raw = mod.read_rendered(pg, u, 30, CANON, None, info)
        return mod.Page(st, u, t, l, html=raw, unstable=info.get("unstable"))
    return chrome
res_ab = listing(R, flip(GOOD, BAD)); res_ba = listing(R, flip(BAD, GOOD))
check("F8 flip-forever, phase match-first: not live, unstable listed", res_ab[2]["verdict"] != "match" and res_ab[2].get("unstable"), str(res_ab[2]))
check("F8 flip-forever, phase mismatch-first: same non-live verdict, unstable listed", res_ba[2]["verdict"] == res_ab[2]["verdict"] and res_ba[2].get("unstable"), str(res_ba[2]["verdict"]))
pg = flip(GOOD, BAD); listing(R, pg)
check("F8 the unstable page was still read in ONE load and cut at the 20s cap", sum(pg.waits[1:]) <= R.STABLE_MAX_S * 1000, str(pg.waits))
ad = Pg([GOOD + " ad%d" % n for n in range(60)])   # body text always changes, NAP never does
r = listing(R, ad)
check("F8 a rotating ad with a stable NAP still matches, and stops early", r[2]["verdict"] == "match" and not r[2].get("unstable") and ad.waits == [2000, 3000], str(ad.waits))
late = Pg([LATE, LATE, GOOD, GOOD]); r = listing(R, late)
check("F8 a late street (LATE, LATE, GOOD, GOOD) still resolves to match inside one load", r[2]["verdict"] == "match" and not r[2].get("unstable"))
never = Pg([LATE] * 30); r = listing(R, never)
check("F8 a street that never appears is nap-incomplete, not unstable", r[2]["verdict"] == "nap-incomplete" and not r[2].get("unstable"), str(r[2]["verdict"]))
# the saved page keeps `unstable`, so --write --from-read scores it the same as the dry run
sp = R.PageStore(os.path.join(TMP, "unst"))
_pg = R.Page(200, U, BAD, html="<html></html>", unstable=["match", "mismatch"])
sp.saving(lambda u: _pg, "chrome")(U)
back = R.PageStore(os.path.join(TMP, "unst")).reusing(lambda u: None, "chrome")(U)
check("F8 a saved unstable page is reused as unstable (same verdict on --write)", back is not None and back.unstable == ["match", "mismatch"])
# round 2: the loop running out of iterations (wall/slow polls first, or a small wait_s) is not an early stable stop either: still unstable, same verdict both phases
def listing_w(mod, pg, wait_s):
    def chrome(u):
        info = {}
        st, t, l, raw = mod.read_rendered(pg, u, wait_s, CANON, None, info)
        return mod.Page(st, u, t, l, html=raw, unstable=info.get("unstable"))
    return mod.read_listing(U, plain_403, chrome, CANON)
SLOW = "Loading..."   # <= 200 chars: counts as a slow poll, not readable
def slow_then_flip(K, first, second, mod=R, wait_s=30): return listing_w(mod, Pg([SLOW] * K + [first, second] * 40), wait_s)
for K in (9, 14):
    a, b = slow_then_flip(K, GOOD, BAD), slow_then_flip(K, BAD, GOOD)
    check("F8b %d slow polls then a flip: not live and unstable in BOTH phases, same verdict" % K, a[2]["verdict"] != "match" and b[2]["verdict"] != "match" and a[2].get("unstable") and b[2].get("unstable") and a[2]["verdict"] == b[2]["verdict"], "%s / %s" % (a[2]["verdict"], b[2]["verdict"]))
a, b = listing_w(R, flip(GOOD, BAD), 12), listing_w(R, flip(BAD, GOOD), 12)
check("F8b wait_s=12 with a flip: not live and unstable in BOTH phases, same verdict", a[2]["verdict"] != "match" and b[2]["verdict"] != "match" and a[2].get("unstable") and b[2].get("unstable") and a[2]["verdict"] == b[2]["verdict"], "%s / %s" % (a[2]["verdict"], b[2]["verdict"]))
r = slow_then_flip(9, GOOD, GOOD)
check("F8b slow polls then a stable match still matches (no false unstable)", r[2]["verdict"] == "match" and not r[2].get("unstable"))
# mutation 2: with the post-loop rule removed, the K=9 flip goes live in one phase
cut2 = 'if canonical is not None and not settled and same == 0 and len(set(seen)) > 1 and info is not None: info["unstable"] = list(seen)'
assert src_all.count(cut2) == 1 if (src_all := open(os.path.join(HERE, "..", "job", "recheck.py"), encoding="utf-8").read()) else False
mut2 = {"__name__": "recheck_mut2", "__file__": os.path.join(HERE, "..", "job", "recheck.py")}
exec(compile(src_all.replace(cut2, "pass"), "recheck_mut2", "exec"), mut2)
M2 = type("M2", (), {k: v for k, v in mut2.items() if not k.startswith("__")})
n_ab, n_ba = slow_then_flip(9, GOOD, BAD, M2), slow_then_flip(9, BAD, GOOD, M2)
check("F8b MUTATION: without the post-loop unstable rule the K=9 flip goes live in one phase (so the F8b tests would fail)", "match" in (n_ab[2]["verdict"], n_ba[2]["verdict"]), "%s / %s" % (n_ab[2]["verdict"], n_ba[2]["verdict"]))
# mutation: with the unstable handling cut out of read_listing, the flip test must FAIL (phase match-first goes live)
src = open(os.path.join(HERE, "..", "job", "recheck.py"), encoding="utf-8").read()
cut = 'if getattr(page, "unstable", None):'
assert src.count(cut) == 1
mut = {"__name__": "recheck_mut", "__file__": os.path.join(HERE, "..", "job", "recheck.py")}
exec(compile(src.replace(cut, "if False:"), "recheck_mut", "exec"), mut)
class M: pass
M = type("M", (), {k: v for k, v in mut.items() if not k.startswith("__")})
m_ab = M.read_listing(U, plain_403, chrome_via_mod(M, flip(GOOD, BAD)), CANON); m_ba = M.read_listing(U, plain_403, chrome_via_mod(M, flip(BAD, GOOD)), CANON)
check("F8 MUTATION: without the unstable handling the flip goes live in one phase (so the F8 tests above would fail)", "match" in (m_ab[2]["verdict"], m_ba[2]["verdict"]) and not (m_ab[2].get("unstable") and m_ba[2].get("unstable")), "%s / %s" % (m_ab[2]["verdict"], m_ba[2]["verdict"]))

# ---- F9 chrome_keepalive --show / --hide moves every window over CDP (fake CDP, no Chrome) ----------------------------------------
class FakeCDP:
    def __init__(self): self.log = []
    def __call__(self, m, params=None):
        self.log.append((m, params))
        if m == "Target.getTargets": return {"targetInfos": [{"type": "page", "targetId": "t1"}, {"type": "page", "targetId": "t2"}, {"type": "service_worker", "targetId": "sw"}, {"type": "page", "targetId": "t3"}]}
        if m == "Browser.getWindowForTarget": return {"windowId": {"t1": 7, "t2": 7, "t3": 9}[params["targetId"]]}
        return {}
f = FakeCDP(); moved = KA.set_window(True, cdp=f)
sets = [(p_["windowId"], p_["bounds"]) for m, p_ in f.log if m == "Browser.setWindowBounds"]
check("F9 --show: each window (not each tab) moved once to 40,40, state normalised first", moved == [7, 9] and (7, {"left": 40, "top": 40}) in sets and (9, {"left": 40, "top": 40}) in sets and (7, {"windowState": "normal"}) in sets and len(sets) == 4, str(sets))
f = FakeCDP(); moved = KA.set_window(False, cdp=f)
sets = [(p_["windowId"], p_["bounds"]) for m, p_ in f.log if m == "Browser.setWindowBounds"]
check("F9 --hide: both windows go to -32000,-32000", moved == [7, 9] and (7, {"left": -32000, "top": -32000}) in sets and (9, {"left": -32000, "top": -32000}) in sets, str(sets))
import subprocess
rr = subprocess.run([sys.executable, os.path.join(HERE, "..", "job", "chrome_keepalive.py"), "--show", "--hide"], capture_output=True, text=True)
check("F9 --show and --hide together are refused by the CLI", rr.returncode != 0 and "not allowed" in rr.stderr, rr.stderr[-120:])
notes = open(os.path.join(HERE, "..", "job", "captcha_route.py"), encoding="utf-8").read() + open(os.path.join(HERE, "..", "job", "workable.py"), encoding="utf-8").read()
check("F9 the cloudflare-click park note and the workable message name chrome_keepalive.py --show", notes.count("chrome_keepalive.py --show") >= 2)
rd = open(os.path.join(HERE, "..", "README.md"), encoding="utf-8").read()
check("F9 README names CE_CHROME_VISIBLE and --show/--hide", "CE_CHROME_VISIBLE" in rd and "chrome_keepalive.py --show" in rd and "--hide" in rd)

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
