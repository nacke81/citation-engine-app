"""Batch 18 fix tests (t_962161f4): bbb/businessyab owner specs match the LIVE pages, us-info final URL after redirects, public-read backoff.
No network, no browser, no vault, no real queue: fakes and temp files only. Run: python tests/batch18_test.py (CI).
Lesson applied: urlopen / subprocess.run are blocked FIRST, so a test that forgets a fake fails loudly; the live-page shapes below are copied from the
real pages seen on 2026-10-27 (not invented), because a fixture-only spec is what failed in batch 18."""
import os, sys, json, tempfile, copy, io, subprocess, urllib.request, contextlib, types
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
os.environ["CE_ACTIVITIES_WRITE"] = "0"
os.environ["CE_DIRECTORIES_WRITE"] = "0"
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
def _no_net(*a, **k): raise AssertionError("network call attempted")
def _no_proc(*a, **k): raise AssertionError("subprocess attempted: %r" % (a[:1],))
urllib.request.urlopen = _no_net
subprocess.run = _no_proc
import formspec as F, recheck as R, transitions as T, buildqueue as Q

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f" [{d}]" if d else ""), flush=True)

IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
PB = os.path.join(JOB, "playbooks")

# ---- 1/2 owner specs: the paths seen on the live sites ----------------------------------------------------------------------------------------------
bb = json.load(open(os.path.join(PB, "bbb_owner.json"), encoding="utf-8"))
st = F.build_site(F.load_spec("bbb_owner"))
check("1 bbb: the spec opens the real login URL (the header Sign in modal only links there), no click on the home page",
      bb["steps"][0]["do"] == "open" and bb["steps"][0]["url"] == "https://www.bbb.org/account/login" and not any(s["do"] == "click_text" for s in bb["steps"]))
lg = next(s for s in bb["steps"] if s["do"] == "login")
check("1 bbb: the login selectors name the live form (input#email / input#password) and still accept type=email", "input#email" in lg["user_selector"] and "input#password" in lg["password_selector"] and lg.get("from_page") is True)
check("1 bbb: read only, no submit step", bb["record"] == "none" and all(x.kind != "submit" for x in st.steps))
by = json.load(open(os.path.join(PB, "businessyab_owner.json"), encoding="utf-8"))
ct = by["steps"][1]
check("2 businessyab: the control is 'Log in' inside #user-links li.quest (the home page has no 'Sign in'); no /login URL is used",
      ct["do"] == "click_text" and ct["text"] == "Log in" and ct["tag"] == "#user-links li.quest" and ct["exact"] is True and not any("login" in (s.get("url") or "") for s in by["steps"]))
check("2 businessyab: the old 'Sign in' text is gone", "Sign in" not in json.dumps(by["steps"]))
# the click really lands on the visible header control, not the hidden modal tab: run the page's own click JS over the DOM shape seen live
class El:
    def __init__(s, tag, text, parent_sel, visible): s.tag, s.text, s.parent_sel, s.visible = tag, text, parent_sel, visible
live_dom = [El("li", "Log in", "#login-tabs", False), El("button", "Log in", ".tabsContent", False), El("li", "Log in", "#user-links", True)]
def first_match(sel, text, exact):   # mimics CLICK_TEXT_JS: document.querySelectorAll(tag).find(text match)
    want = text.strip().lower()
    for e in live_dom:
        if sel == "#user-links li.quest" and e.parent_sel != "#user-links": continue
        if e.text.strip().lower() == want or (not exact and want in e.text.lower()): return e
check("2 businessyab: the selector skips the hidden modal tab and the hidden Log in button and picks the header control", first_match(ct["tag"], ct["text"], ct["exact"]).visible)
check("2 the click JS takes the tag as a CSS selector (a compound selector works)", "querySelectorAll(a.tag)" in F.CLICK_TEXT_JS)
for nm in ("bbb_owner", "businessyab_owner"):
    raw = open(os.path.join(PB, nm + ".json"), encoding="utf-8").read()
    check("1/2 %s: no password / email / phone literal in the file; notes say LIVE-SEEN" % nm, not F._LITERAL_EMAIL.search(raw) and not F._LITERAL_PHONE.search(raw) and "LIVE-SEEN" in raw and "UNPROVEN" not in raw)

# ---- 4 us-info: the final URL after redirects ---------------------------------------------------------------------------------------------------------
OLD = "https://www.us-info.com/USKY100000000-2700000001/businessdetails.aspx"
NEW = "https://www.us-info.com/USKY100000000-2700000002/businessdetails.aspx"
check("4 final_url: a same-host redirect to a new slug returns the new URL", R.final_url(OLD, R.Page(200, NEW, "x")) == NEW)
check("4 final_url: no redirect (or only a trailing slash / fragment) keeps the stored URL", R.final_url(OLD, R.Page(200, OLD + "#top", "x")) == OLD and R.final_url(OLD, R.Page(200, OLD + "/", "x")) == OLD)
check("4 final_url: a redirect to ANOTHER host (a login wall, a parking page) is never stored", R.final_url(OLD, R.Page(200, "https://evil.example/x", "x")) == OLD and R.final_url(OLD, R.Page(200, "javascript:alert(1)", "x")) == OLD)
check("4 final_url: a URL with credentials is never stored", R.final_url(OLD, R.Page(200, "https://u:p@www.us-info.com/z", "x")) == OLD)

CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
PAD = " Lorem ipsum dolor sit amet." * 12
GOOD = "Home\nAlder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n(502) 555-0101\n%s\n" % PAD
QP = os.path.join(tempfile.mkdtemp(), "queue.json")
def row(i, d, state="submitted", **kw): return dict({"id": i, "directory": d, "state": state, "mike_approval": None, "history": []}, **kw)
def write_q(rows): json.dump({"canonical": CANON, "fix_queue": [], "create_rows": rows}, open(QP, "w"))
class FakePortal:
    def __init__(s): s.snap = {"directories": [], "totals": {}}
    def latest_snapshot(s, cid): return {"payload": copy.deepcopy(s.snap)}
    def upsert_snapshot(s, cid, day, payload): s.snap = payload
    def call(s, *a, **k): pass
def real_record(*a, **k):
    return T.record_transition(*a, portal=FakePortal(), **k)
class FakeDB:
    owner = "x"
    def call(s, *a, **k): return []
def redirecting(final):
    return lambda u: R.Page(200, final, GOOD, html="<html>%s</html>" % GOOD)

# a live row whose stored URL is the OLD slug; the site redirects to the NEW slug. --write stores the final URL as listing_url AND evidence_url, state stays live.
write_q([row("create-us-info", "us-info.com", "live", evidence_url=OLD, listing_url=OLD, history=[{"at": "2026-10-26", "from": "submitted", "to": "live", "evidence_url": OLD, "note": "x"}])])
q = json.load(open(QP))
res = R.recheck(q, IDENT, plain=redirecting(NEW), chrome=None, record=real_record, write=True, include_live=True, only={"create-us-info"}, db=FakeDB(), queue_path=QP, today="2026-10-27", use_chrome=False)
r0 = json.load(open(QP))["create_rows"][0]
check("4 recheck --write on a live row stores the FINAL url as evidence_url and listing_url", r0["evidence_url"] == NEW and r0["listing_url"] == NEW, str((r0.get("evidence_url"), r0.get("listing_url"))))
check("4 the row stays live, history gets one dated live->live entry with the new URL", r0["state"] == "live" and r0["history"][-1]["from"] == "live" and r0["history"][-1]["to"] == "live" and r0["history"][-1]["evidence_url"] == NEW, str(r0["history"][-1]))
check("4 the result reports the move", res[0]["final_url"] == NEW and "moved" in (res[0]["note"] or ""), str(res[0]))
write_q([row("create-us-info", "us-info.com", "live", evidence_url=OLD, listing_url=OLD)])
R.recheck(json.load(open(QP)), IDENT, plain=redirecting(NEW), chrome=None, record=real_record, write=False, include_live=True, only={"create-us-info"}, db=FakeDB(), queue_path=QP, today="2026-10-27", use_chrome=False)
check("4 a dry run (no --write) writes nothing", json.load(open(QP))["create_rows"][0]["evidence_url"] == OLD)
write_q([row("create-us-info", "us-info.com", "live", evidence_url=OLD, listing_url=OLD)])
res = R.recheck(json.load(open(QP)), IDENT, plain=redirecting(OLD), chrome=None, record=real_record, write=True, include_live=True, only={"create-us-info"}, db=FakeDB(), queue_path=QP, today="2026-10-27", use_chrome=False)
r0 = json.load(open(QP))["create_rows"][0]
check("4 no redirect: nothing is rewritten", r0["evidence_url"] == OLD and not r0["history"] and "final_url" not in res[0])
# a waiting row going live stores the final URL too
write_q([row("create-us-info", "us-info.com", "submitted", evidence_url=OLD, listing_url=OLD)])
import directories as D
D._upsert_status = lambda *a, **k: None
D._status_row = lambda *a, **k: {}
R.recheck(json.load(open(QP)), IDENT, plain=redirecting(NEW), chrome=None, record=real_record, write=True, db=FakeDB(), queue_path=QP, today="2026-10-27", use_chrome=False)
r0 = json.load(open(QP))["create_rows"][0]
check("4 a submitted row going live from a redirected page stores the final URL as both fields", r0["state"] == "live" and r0["evidence_url"] == NEW and r0["listing_url"] == NEW, str((r0["state"], r0.get("evidence_url"), r0.get("listing_url"))))

# the transitions door for the ONE existing row: --refresh-url, live -> live only
write_q([row("create-us-info", "us-info.com", "live", evidence_url=OLD, listing_url=OLD, mike_approval={"approved_by": "mike"})])
def raises(fn, exc):
    try: fn(); return None
    except exc as e: return str(e)
before = open(QP, "rb").read()
d = T.record_transition("SCC", "create-us-info", "live", NEW, "the Directory redirected the listing to a new slug", queue_path=QP, today="2026-10-27", dry_run=True, refresh_url=True, portal=FakePortal())
check("4 --refresh-url dry run writes nothing", open(QP, "rb").read() == before and d["to"] == "live")
T.record_transition("SCC", "create-us-info", "live", NEW, "the Directory redirected the listing to a new slug", queue_path=QP, today="2026-10-27", refresh_url=True, portal=FakePortal())
r0 = json.load(open(QP))["create_rows"][0]
check("4 --refresh-url sets evidence_url and listing_url, keeps state live and Mike's approval", r0["evidence_url"] == NEW and r0["listing_url"] == NEW and r0["state"] == "live" and r0["mike_approval"] == {"approved_by": "mike"})
m = raises(lambda: T.record_transition("SCC", "create-us-info", "live", NEW, None, queue_path=QP, today="2026-10-27", refresh_url=True, portal=FakePortal()), T.TransitionRefused)
check("4 --refresh-url without a note is refused", m and "note" in m, str(m))
m = raises(lambda: T.record_transition("SCC", "create-us-info", "live", None, "moved", queue_path=QP, today="2026-10-27", refresh_url=True, portal=FakePortal()), T.TransitionRefused)
check("4 --refresh-url without --evidence is refused", m and "--evidence" in m, str(m))
write_q([row("create-x", "x.example", "submitted")])
m = raises(lambda: T.record_transition("SCC", "create-x", "live", NEW, "moved", queue_path=QP, today="2026-10-27", refresh_url=True, portal=FakePortal()), T.TransitionRefused)
check("4 --refresh-url on a row that is not live is refused (it is not a back door to live)", m and "live -> live" in m, str(m))
m = raises(lambda: T.record_transition("SCC", "create-x", "submitted", NEW, "moved", queue_path=QP, today="2026-10-27", refresh_url=True, portal=FakePortal()), T.TransitionRefused)
check("4 --refresh-url to any other state is refused", m is not None)

# ---- 5 public-read backoff -------------------------------------------------------------------------------------------------------------------------
HIDDEN = "Home\nAlder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n(502) 555-0101\nThis listing is HIDDEN until ACTIVATED.\n%s\n" % PAD
def plain_of(text): return lambda u: R.Page(200, u, text, html="<html>%s</html>" % text)
def run(rows, plain, today="2026-10-27", write=True, **kw):
    write_q(rows)
    res = R.recheck(json.load(open(QP)), IDENT, plain=plain, chrome=None, record=real_record, write=write, db=FakeDB(), queue_path=QP, today=today, use_chrome=False, **kw)
    return res, json.load(open(QP))["create_rows"]
res, rows = run([row("create-tupalo", "tupalo.com", "submitted", listing_url="https://tupalo.example/x")], plain_of(HIDDEN))
check("5 a not-public verdict (hidden banner) sets recheck_due = today + 2 days", res[0]["verdict"] == "not-public" and rows[0].get("recheck_due") == "2026-10-29", str((res[0]["verdict"], rows[0].get("recheck_due"))))
check("5 ...the state is unchanged and the history says when to look again", rows[0]["state"] == "submitted" and "recheck due 2026-10-29" in rows[0]["history"][-1]["note"], str(rows[0]["history"][-1:]))
with contextlib.redirect_stdout(io.StringIO()):
    c1 = R.candidates(json.load(open(QP)), today="2026-10-28"); c2 = R.candidates(json.load(open(QP)), today="2026-10-29")
check("5 the next batch skips the row the day after, and reads it again on day +2", not c1 and len(c2) == 1)
check("5 a dry run reports the date and writes nothing", run([row("create-tupalo", "tupalo.com", "submitted", listing_url="https://tupalo.example/x")], plain_of(HIDDEN), write=False)[1][0].get("recheck_due") is None
      and run([row("create-tupalo", "tupalo.com", "submitted", listing_url="https://tupalo.example/x")], plain_of(HIDDEN), write=False)[0][0]["recheck_due"] == "2026-10-29")
# a Directory page that answers 'we could not find' (signed-out page shows no listing)
NOTFOUND = "Page not found\nSorry, we could not find the page you were looking for.\n" + PAD
res, rows = run([row("create-cc", "chamberofcommerce.com", "submitted", listing_url="https://coc.example/x")], plain_of(NOTFOUND))
check("5 a page with no listing on it (not-public) also backs off 2 days", res[0]["verdict"] == "not-public" and rows[0].get("recheck_due") == "2026-10-29", str((res[0]["verdict"], res[0].get("error"), rows[0].get("recheck_due"))))
# foursquare-style: no public source
fs = next(iter(R.UNREADABLE_PUBLIC))
res, rows = run([row("create-fs", fs, "submitted", listing_url="https://fs.example/x")], plain_of(GOOD))
check("5 an unreadable-public Directory (no public source) backs off 2 days too and is never fetched", res[0]["verdict"] == "unreadable-public" and rows[0].get("recheck_due") == "2026-10-29", str((res[0]["verdict"], rows[0].get("recheck_due"))))
# only the verdicts named: a mismatch or a match does NOT set recheck_due, a LIVE row is never touched
MISM = GOOD.replace("100 Example Drive", "999 Wrong Street")
res, rows = run([row("create-m", "m.example", "submitted", listing_url="https://m.example/x")], plain_of(MISM))
check("5 a mismatch does not back off (the fix is wanted soon)", res[0]["verdict"] == "mismatch" and "recheck_due" not in rows[0], str(rows[0].get("recheck_due")))
res, rows = run([row("create-l", "l.example", "live", listing_url="https://l.example/x", evidence_url="https://l.example/x")], plain_of(HIDDEN), include_live=True)
check("5 a row already live is never given a recheck_due", "recheck_due" not in rows[0] and rows[0]["state"] == "live", str(rows[0]))
write_q([row("create-t", "tupalo.com", "submitted", recheck_due="2026-10-29")])
check("5 a row named with --row is read despite the backoff", len(R.candidates(json.load(open(QP)), today="2026-10-27", only={"create-t"})) == 1)
src = open(os.path.join(JOB, "recheck.py"), encoding="utf-8").read().replace("\r\n", "\n")
check("5 BACKOFF_DAYS is 2", R.BACKOFF_DAYS == 2 and src.count("_backoff(") >= 5)

# ---- CI wiring ------------------------------------------------------------------------------------------------------------------------------------------
wf = os.path.join(HERE, "..", ".github", "workflows")
ci = open(os.path.join(wf, os.listdir(wf)[0]), encoding="utf-8").read()
check("CI runs this file", "tests/batch18_test.py" in ci)

print("\n%d passed, %d failed" % (sum(ok), len(ok) - sum(ok)))
sys.exit(0 if all(ok) else 1)
