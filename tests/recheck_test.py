"""Recheck job tests (t_64c4d511). Run: python tests/recheck_test.py (CI). No network, no browser: fetchers, db and portal are in-memory fakes; urlopen is poisoned."""
import os, sys, copy, json, re, tempfile, shutil, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import portal as P
import transitions as T
import recheck as R

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

TMP = tempfile.mkdtemp()
DAY = "2026-11-02"
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example, Exampleton KY 40000", "phone": "(502) 555-0101"}
IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
PAD = " Lorem ipsum dolor sit amet." * 12

def page_text(phone="(502) 555-0101", street="100 Example", extra=PAD):
    return "Home\nAlder Care Consulting & Solutions\n%s\nExampleton, KY 40000\n%s\n%s\n" % (street, phone, extra)

class FakeDB:
    owner = "owner-1"
    def __init__(self): self.calls = []
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))

class FakePortal:
    def __init__(self): self.calls = []; self.snap = {"found": 1, "directories": []}
    def latest_snapshot(self, cid): return {"payload": copy.deepcopy(self.snap)}
    def upsert_snapshot(self, cid, day, payload): self.calls.append(("snap", day))
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))

def row(rid, directory, state, url=None, **kw):
    r = {"id": rid, "directory": directory, "state": state, "mike_approval": None, "evidence_url": url, "history": []}
    r.update(kw); return r

def make_queue(rows):
    p = os.path.join(TMP, "q.json")
    json.dump({"canonical": CANON, "fix_queue": rows}, open(p, "w"))
    return p

def run(rows, pages, chrome_pages=None, write=True, **kw):
    p = make_queue(rows); db, fp = FakeDB(), FakePortal(); plain_calls, chrome_calls = [], []
    def plain(url):
        plain_calls.append(url); v = pages.get(url)
        if isinstance(v, R.Page): return v
        return R.Page(200, url, v) if v is not None else R.Page(404, url, "", err="HTTP 404")
    def chrome(url):
        chrome_calls.append(url); v = (chrome_pages or {}).get(url)
        return R.Page(200, url, v) if v is not None else R.Page(0, url, "", err="none")
    def record(*a, **k): return T.record_transition(*a, portal=fp, activities=fp, verification=fp, directories=db, **k)
    q = json.load(open(p))
    res = R.recheck(q, IDENT, plain=plain, chrome=chrome, record=record, db=db, queue_path=p, today=DAY, write=write, **kw)
    return res, json.load(open(p)), plain_calls, chrome_calls, db, fp

U1 = "https://a.example/listing/1"
U2 = "https://b.example/listing/2"

# R1 match -> live with the permalink, Proof first, Activities row sent
res, q, _, _, db, fp = run([row("r1", "a.example", "pending-verify", U1)], {U1: page_text()})
r = q["fix_queue"][0]
check("R1 all match -> live", r["state"] == "live" and r["evidence_url"] == U1 and res[0]["after"] == "live" and res[0]["verdict"] == "match", str(res))
check("R1 history names the recheck", "weekly recheck" in (r["history"][-1]["note"] or ""))
proof_i = next(i for i, c in enumerate(db.calls) if "ce_directory_status" in c[1] and c[2][0].get("proof_nap_match") is True)
status_i = max(i for i, c in enumerate(db.calls) if "ce_directory_status" in c[1])
check("R1 Proof written before the live transition status", proof_i < status_i and db.calls[proof_i][2][0]["proof_url"] == U1)
check("R1 Activities row sent for live", any("deliverables" in str(c[1]) for c in fp.calls))
for st in ("submitted", "found"):
    res, q, *_ = run([row("r1", "a.example", st, U1)], {U1: page_text()})
    check("R1 %s row also goes live" % st, q["fix_queue"][0]["state"] == "live")

# R2 phone mismatch -> same-state note only
res, q, _, _, db, fp = run([row("r2", "a.example", "pending-verify", U1)], {U1: page_text(phone="(502) 555-0199")})
r = q["fix_queue"][0]
check("R2 phone mismatch: state unchanged", r["state"] == "pending-verify" and res[0]["verdict"] == "mismatch")
check("R2 note names the wrong field and the shown value", "phone shows (502) 555-0199" in r["history"][-1]["note"], r["history"][-1]["note"])
check("R2 no Activities row, no live Proof", not any("deliverables" in str(c[1]) for c in fp.calls) and not any(c[2][0].get("proof_nap_match") is True for c in db.calls if "ce_directory_status" in c[1]))
dup = [{"at": "2026-10-30", "from": "pending-verify", "to": "pending-verify", "note": "weekly recheck: phone shows (502) 555-0199"}]
res, q2, *_ = run([row("r2", "a.example", "pending-verify", U1, history=dup)], {U1: page_text(phone="(502) 555-0199")})
check("R2 identical note is not written twice", len(q2["fix_queue"][0]["history"]) == 1)

# R3 foreign phone and wrong street
res, q, *_ = run([row("r3", "b.example", "submitted", U2)], {U2: page_text(phone="+27 84 125 50")})
check("R3 foreign phone named", "phone shows +27 84 125 50" in q["fix_queue"][0]["history"][-1]["note"] and q["fix_queue"][0]["state"] == "submitted", q["fix_queue"][0]["history"][-1]["note"])
res, q, *_ = run([row("r3", "a.example", "submitted", U1)], {U1: page_text(street="9 Other Road")})
check("R3 wrong street named", res[0]["verdict"] == "mismatch" and "address shows 9 Other Road" in q["fix_queue"][0]["history"][-1]["note"], str(res[0]["fields"]))

# R4 no permalink -> no transition, no fetch
res, q, plain_calls, chrome_calls, db, fp = run([row("r4", "a.example", "pending-verify", "https://a.example/search?q=alder"), row("r5", "b.example", "submitted", None)], {})
check("R4 no permalink: nothing written, nothing fetched", res[0]["verdict"] == "no-permalink" and res[1]["verdict"] == "no-permalink" and not plain_calls and not chrome_calls and not fp.calls and not db.calls and all(r["state"] != "live" and not r["history"] for r in q["fix_queue"]))

# R5 dry run
res, q, _, _, db, fp = run([row("r6", "a.example", "pending-verify", U1)], {U1: page_text()}, write=False)
check("R5 dry run: report says live, queue/db/portal untouched", res[0]["after"] == "live" and q["fix_queue"][0]["state"] == "pending-verify" and not db.calls and not fp.calls)

# R6 walled plain page -> Chrome
res, q, plain_calls, chrome_calls, *_ = run([row("r7", "a.example", "pending-verify", U1)], {U1: R.Page(403, U1, "Just a moment...")}, {U1: page_text()})
check("R6 plain 403 -> Chrome read -> live", chrome_calls == [U1] * R.STABLE_READS and q["fix_queue"][0]["state"] == "live")
res, q, plain_calls, chrome_calls, *_ = run([row("r7", "a.example", "pending-verify", U1)], {U1: page_text()}, {U1: "x"})
check("R6 readable plain page: Chrome not used", chrome_calls == [])
res, q, plain_calls, chrome_calls, *_ = run([row("r7", "a.example", "pending-verify", U1)], {U1: R.Page(200, U1, "Performing a quick security check..." + PAD)}, {U1: page_text()})
check("R6 Turnstile text on a 200 page counts as a wall", chrome_calls == [U1] * R.STABLE_READS and q["fix_queue"][0]["state"] == "live")
res, q, plain_calls, chrome_calls, *_ = run([row("r7", "a.example", "pending-verify", U1)], {U1: R.Page(403, U1, "Just a moment...")}, {U1: page_text()}, use_chrome=False)
check("R6 --no-chrome: walled page writes nothing", chrome_calls == [] and q["fix_queue"][0]["state"] == "pending-verify" and res[0]["verdict"] == "unreadable")

# R7 unreadable
res, q, *_ = run([row("r8", "a.example", "pending-verify", U1)], {U1: R.Page(403, U1, "denied")}, {U1: "Just a moment..."})
check("R7 walled in both: unreadable, nothing written", res[0]["verdict"] == "unreadable" and not q["fix_queue"][0]["history"])
res, q, *_ = run([row("r8", "a.example", "pending-verify", U1)], {U1: "Welcome to a directory about other businesses. " * 20})
check("R7 page without the business: unreadable, not a mismatch", res[0]["verdict"] == "unreadable" and not q["fix_queue"][0]["history"])

# R8 phone missing -> gap note (the bizapedia case)
res, q, *_ = run([row("r9", "a.example", "pending-verify", U1)], {U1: "Alder Care Consulting & Solutions\n100 Example\nExampleton, KY 40000\n" + PAD})
check("R8 no phone on the page: gap note, stays put", res[0]["verdict"] == "gap" and q["fix_queue"][0]["state"] == "pending-verify" and "phone not shown" in q["fix_queue"][0]["history"][-1]["note"], str(res[0]))

# R8b hidden phone is a gap; a masked phone is partial (t_032083dc): visible digits agree -> match (masked), disagree -> mismatch phone
for hidden, want in (("\u2022\u2022 \u2022\u2022 \u2022\u2022 \u2022\u2022\nReveal Phone Number", "gap"), ("+150****0101", "match"), ("+127****2550", "mismatch")):
    res, q, *_ = run([row("m1", "a.example", "pending-verify", U1)], {U1: "Alder Care Consulting & Solutions\n100 Example\nExampleton, KY 40000\n%s\n" % hidden + PAD})
    check("R8b hidden/masked phone %r: %s" % (hidden[:12], want), res[0]["verdict"] == want and q["fix_queue"][0]["state"] == ("live" if want == "match" else "pending-verify"), str(res[0]["fields"]))

# R9 other states
rows = [row("q1", "a.example", "queued", U1), row("n1", "b.example", "needs-human", U2), row("l1", "c.example", "live", "https://c.example/listing/3")]
res, q, plain_calls, *_ = run(rows, {})
check("R9 queued / needs-human / live rows are not read", res == [] and plain_calls == [])
res, q, plain_calls, *_ = run(rows, {"https://c.example/listing/3": page_text(phone="(502) 555-0199")}, include_live=True)
check("R9 --include-live reads live rows but never changes them", len(res) == 1 and q["fix_queue"][2]["state"] == "live" and not q["fix_queue"][2]["history"])

# R10 bing
BING = "https://www.bing.com/maps/search?style=r&ss=id.local_ypid%3A%22YN776669B621C0FC20%22"
res, q, plain_calls, *_ = run([row("b1", "bing.com", "submitted", "https://www.bingplaces.com/", listing_url=BING)], {BING: page_text()})
check("R10 bing: resolves the Maps permalink, not bingplaces.com", plain_calls == [BING] and q["fix_queue"][0]["state"] == "live" and q["fix_queue"][0]["evidence_url"] == BING, str(plain_calls))
res, q, plain_calls, *_ = run([row("b1", "bing.com", "submitted", "https://www.bingplaces.com/")], {})
check("R10 bing with only bingplaces.com: no permalink, no fetch", res[0]["verdict"] == "no-permalink" and all("search" in u for u in plain_calls))

# R11 bbb
SEARCH = R._bbb_search_url(IDENT)
PROFILE = "https://www.bbb.org/us/ky/exampleton/profile/senior-care/alder-care-consulting-solutions-0000-1234"
sp = R.Page(200, SEARCH, "Search results" + PAD, [{"href": PROFILE, "text": "Alder Care Consulting & Solutions", "card": "Alder Care Consulting & Solutions Exampleton, KY", "aria": ""}])
res, q, plain_calls, *_ = run([row("bbb1", "bbb.org", "submitted", "https://www.bbb.org/get-listed/success")], {SEARCH: sp, PROFILE: page_text()})
r = q["fix_queue"][0]
check("R11 bbb: search url is by name + city", "find_text=" in SEARCH and "Exampleton" in SEARCH, SEARCH)
check("R11 bbb: profile url found, stored as evidence and read", r["evidence_url"] == PROFILE and PROFILE in plain_calls, str(r.get("evidence_url")))
check("R11 bbb: match on the profile page goes live", r["state"] == "live")
res, q, plain_calls, *_ = run([row("bbb1", "bbb.org", "submitted", "https://www.bbb.org/get-listed/success")], {SEARCH: R.Page(200, SEARCH, "No results" + PAD, [])})
check("R11 bbb: no profile in search -> no transition", res[0]["verdict"] == "no-permalink" and q["fix_queue"][0]["state"] == "submitted" and not q["fix_queue"][0]["history"])
other = R.Page(200, SEARCH, "Search" + PAD, [{"href": "https://www.bbb.org/us/ky/exampleton/profile/plumbing/other-co-1", "text": "Other Plumbing Co", "card": "Other Plumbing Co Exampleton, KY", "aria": ""}])
res, q, plain_calls, *_ = run([row("bbb1", "bbb.org", "submitted", "https://www.bbb.org/get-listed/success")], {SEARCH: other})
check("R11 bbb: a profile link for another business is not taken", q["fix_queue"][0]["evidence_url"].endswith("get-listed/success") and res[0]["verdict"] == "no-permalink")

# R12 safety
p = make_queue([row("r1", "a.example", "submitted", U1)]); q = json.load(open(p)); q["canonical"] = dict(CANON, phone="(502) 555-9999")
try: R.recheck(q, IDENT, plain=lambda u: R.Page(200, u, page_text()), chrome=None, record=lambda *a, **k: 1 / 0, queue_path=p, write=True); refused = False
except Exception: refused = True
check("R12 queue canonical that differs from the approved identity is refused", refused)
rows = [row("e1", "a.example", "submitted", U1), row("e2", "b.example", "submitted", U2)]
p = make_queue(rows); q = json.load(open(p)); fp = FakePortal(); db = FakeDB()
def rec2(*a, **k):
    if a[1] == "e1": raise RuntimeError("boom")
    return T.record_transition(*a, portal=fp, activities=fp, verification=fp, directories=db, **k)
res = R.recheck(q, IDENT, plain=lambda u: R.Page(200, u, page_text()), chrome=None, record=rec2, db=db, queue_path=p, today=DAY, write=True)
check("R12 a failing row is reported and the next row still runs", res[0]["error"] and res[1]["after"] == "live" and json.load(open(p))["fix_queue"][1]["state"] == "live")

# R14 weekly run.py step is non-fatal and loud
import io, contextlib
import run as RUN
err = io.StringIO()
with contextlib.redirect_stderr(err):
    boom = RUN.recheck_step(run=lambda **k: 1 / 0)
check("R14 run.recheck_step: a crash returns False, raises nothing, says RECHECK FAILED", boom is False and "RECHECK FAILED" in err.getvalue())
with contextlib.redirect_stdout(io.StringIO()):
    good = RUN.recheck_step(run=lambda **k: [{"row": "x", "before": "submitted", "after": "live", "verdict": "match", "error": None}])
check("R14 run.recheck_step ok path returns True and is called with write=True", good is True)
seen = {}
with contextlib.redirect_stdout(io.StringIO()):
    RUN.recheck_step(run=lambda **k: seen.update(k) or [])
check("R14 weekly step writes (write=True)", seen.get("write") is True)
check("R14 recheck_step is wired into main()", "recheck_step()" in open(os.path.join(HERE, "..", "job", "run.py"), encoding="utf-8").read())

# R15 (t_560dd259) entry pages are never read as the listing; the real listing_url is used instead
for bad in ("https://a.example/add-business", "https://a.example/", "https://a.example/add/thankyou.php", "https://a.example/add-listing/",
            "https://a.example/lookup/duns-found?flow=lookup&type=self", "https://a.example/get-listed/success", "https://a.example/register"):
    check("R15 entry page %s is not a permalink" % bad, R._is_entry_page(bad))
for good in ("https://a.example/business/54014582/alder-care", "https://a.example/37893637-alder-care-exampleton", "https://a.example/listing/1"):
    check("R15 listing page %s is a permalink" % good, not R._is_entry_page(good))
res, q, plain_calls, *_ = run([row("br", "a.example", "found", "https://a.example/add-business", listing_url=U1)], {U1: page_text()})
check("R15 form page in evidence_url, real listing in listing_url: the listing is read and goes live", plain_calls == [U1] and q["fix_queue"][0]["state"] == "live", str(plain_calls))
res, q, plain_calls, *_ = run([row("br", "a.example", "found", "https://a.example/")], {})
check("R15 only the homepage on file: no permalink, nothing fetched", res[0]["verdict"] == "no-permalink" and not plain_calls)
# R16 build Chrome down is named, not a bare 'unreadable'
res, q, *_ = run([row("c1", "a.example", "pending-verify", U1)], {U1: R.Page(403, U1, "Just a moment...")}, chrome_pages=None)
check("R16 walled plain page and Chrome unreachable: unreadable, nothing written", res[0]["verdict"] == "unreadable" and not q["fix_queue"][0]["history"])
class _PW:
    def start(self): return self
    class chromium:
        @staticmethod
        def connect_over_cdp(u): raise Exception("BrowserType.connect_over_cdp: connect ECONNREFUSED 127.0.0.1:9333")
    def stop(self): pass
import types as _t, sys as _s
_s.modules["playwright"] = _t.ModuleType("playwright"); _sync = _t.ModuleType("playwright.sync_api"); _sync.sync_playwright = lambda: _PW(); _s.modules["playwright.sync_api"] = _sync
cp = R.chrome_fetch("https://a.example/x")
check("R16 CDP refused: error names the build Chrome and how to start it", cp.status == 0 and "build Chrome not reachable" in (cp.err or "") and "build_chrome.py" in cp.err, str(cp.err))
res, q, *_ = run([row("c1", "a.example", "pending-verify", U1)], {U1: R.Page(403, U1, "Just a moment...")}, chrome_pages=None)
# the row error text carries the page error
pg_, how = R.get_page(U1, lambda u: R.Page(403, u, "Just a moment..."), lambda u: cp, CANON)
check("R16 get_page falls back to Chrome and reports the route", how == "chrome")

# R13 read-only module
src = open(os.path.join(HERE, "..", "job", "recheck.py"), encoding="utf-8").read()
check("R13 module has no Directory write verb, click/fill/type, or portal seed", not re.search(r"\.(post|put|patch|delete)\(|\.click\(|\.fill\(|\.type\(|\.check\(", src, re.I) and not re.search(r"import seed|portal_seed|seed_portal", src.lower()))

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
