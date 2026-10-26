"""Recheck reads signed out (t_ac8b1bdd). Run: python tests/recheck_signedout_test.py (CI). No network, no browser: a stub Playwright where the
profile context (contexts[0], signed in) shows the canonical phone and a fresh context (signed out) shows the old public phone."""
import os, sys, types, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")   # test identity only (leak check)
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import recheck as R

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
PAD = " Lorem ipsum dolor sit amet." * 12
def body(phone): return "Home\nAlder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n%s\n%s\n" % (phone, PAD)

LOG = {"profile_pages": 0, "fresh_ctx": 0, "closed": 0}
class Resp:
    status = 200
class Page:
    def __init__(s, text, kind): s.text, s.kind, s.url = text, kind, "https://a.example/x"
    def goto(s, *a, **k): return Resp()
    def wait_for_timeout(s, ms): pass
    def inner_text(s, sel, timeout=0): return s.text
    def evaluate(s, js): return []
    def content(s): return "<html><body>%s</body></html>" % s.text
    def close(s): pass
class Ctx:
    def __init__(s, text, kind): s.text, s.kind = text, kind
    def new_page(s):
        if s.kind == "profile": LOG["profile_pages"] += 1
        return Page(s.text, s.kind)
    def close(s): LOG["closed"] += 1
class Browser:
    def __init__(s, fresh_text, profile_text, walled=False):
        s.fresh_text = fresh_text
        s.contexts = [Ctx(profile_text, "profile")]
    def new_context(s): LOG["fresh_ctx"] += 1; return Ctx(s.fresh_text, "fresh")

def install(browser):
    class PW:
        def start(s): return s
        class chromium:
            @staticmethod
            def connect_over_cdp(u): return browser
        def stop(s): pass
    m = types.ModuleType("playwright"); sy = types.ModuleType("playwright.sync_api"); sy.sync_playwright = lambda: PW()
    sys.modules["playwright"], sys.modules["playwright.sync_api"] = m, sy

# 1 profile (signed in) shows the canonical phone; the public (fresh context) shows the old phone -> mismatch phone, never live
install(Browser(fresh_text=body("(502) 555-0199"), profile_text=body("(502) 555-0101")))
pg = R.chrome_fetch("https://a.example/x")
check("chrome_fetch reads the fresh context's phone, not the profile's", "555-0199" in pg.text and "555-0101" not in pg.text, pg.text[:80])
check("chrome_fetch never opened a page in contexts[0]", LOG["profile_pages"] == 0, str(LOG))
check("chrome_fetch closed the fresh context", LOG["fresh_ctx"] == 1 and LOG["closed"] == 1, str(LOG))
c = R.compare(pg.text, CANON, pg.html)
check("signed-out read of the old phone: mismatch phone", c["verdict"] == "mismatch" and c["wrong"][0][0] == "phone", str(c))

# 2 same through the whole get_page path (plain walled -> Chrome): verdict is not match
walled = lambda u: R.Page(403, u, "Just a moment...")
page, how = R.get_page("https://a.example/x", walled, R.chrome_fetch, CANON)
check("get_page via Chrome gives the public (fresh) page", how == "chrome" and "555-0199" in page.text)
check("verdict from get_page is mismatch, not match", R.compare(page.text, CANON, page.html)["verdict"] == "mismatch")

# 3 fresh context hits a wall the profile would clear -> unreadable, never match
install(Browser(fresh_text="Just a moment...", profile_text=body("(502) 555-0101")))
page, how = R.get_page("https://a.example/x", walled, R.chrome_fetch, CANON)
check("walled fresh context: page is walled, profile text never read", R.walled(page) and "555-0101" not in page.text, page.text[:60])
check("walled fresh context: verdict unreadable", R.compare(page.text, CANON, page.html)["verdict"] == "unreadable", str(R.compare(page.text, CANON, page.html)))

# 3b unstable public page: first signed-out read shows the canonical phone, a later one the old phone -> not live
import json
reads = [body("(502) 555-0101"), body("(502) 555-0199"), body("(502) 555-0101")]
def flip(u):
    t = reads.pop(0) if reads else body("(502) 555-0101"); return R.Page(200, u, t, html="<html>%s</html>" % t)
IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
row = {"id": "r1", "directory": "a.example", "state": "pending-verify", "listing_url": "https://a.example/x", "evidence_url": "https://a.example/x", "history": []}
q = {"canonical": CANON, "fix_queue": [row], "create_rows": []}
def no_record(*a, **k): raise AssertionError("record called")
# the first read comes from get_page (plain walled -> chrome); the repeat reads come from the same injected chrome
res = R.recheck(q, IDENT, plain=walled, chrome=flip, record=no_record, write=False)
check("unstable page (match, then old phone): row reads mismatch phone, not live", res[0]["verdict"] == "mismatch" and res[0]["after"] == "pending-verify", str(res[0]))
reads[:] = [body("(502) 555-0101")] * 3
res = R.recheck(q, IDENT, plain=walled, chrome=flip, record=lambda *a, **k: {}, write=False)
check("three stable matching reads: match", res[0]["verdict"] == "match", str(res[0]))

# 4 source rule: recheck.py and claim_reread.py never read contexts[0]
for f in ("recheck.py", "claim_reread.py"):
    src = open(os.path.join(HERE, "..", "job", f), encoding="utf-8").read()
    check(f + " has no contexts[0] read", "contexts[0]" not in src.replace("`contexts[0]`", "").replace("contexts[0] is", ""))

print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
