"""Batch 15 fix tests (t_bbc32230): hidden-banner = not-public, mail URL -> permalink gate -> listing_url -> recheck reads it, formspec `login` + acompio_owner spec,
foursquare unreadable-public, citylocalpro search log. (Item 1, the walls try counter, is in tests/walls_test.py W7.)
No network, no browser, no vault, no CapSolver, no real mailbox, no real queue: fakes and temp files only. Run: python tests/batch15_test.py (CI)."""
import os, sys, json, tempfile, copy, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
import build_runner as B, formspec as F, recheck as R, mail_scan as MS, transitions as T, claim as CL

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
NAP = B.nap_from_identity(IDENT)
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
PAD = " Lorem ipsum dolor sit amet." * 12

# ---- 2 hidden banner: full NAP + "HIDDEN until ACTIVATED" is not-public, never match ------------------------------------------
# Text shaped like the real showmelocal public page (t_b881042d): full NAP in the body AND the banner.
SML = ("This Listing is HIDDEN until ACTIVATED. ACTIVATE LISTING\nAlder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n(502) 555-0101\n"
       "Health Consultant\n" + PAD)
c = R.compare(SML, CANON)
check("2 showmelocal page (full NAP + HIDDEN banner) -> not-public, not match", c["verdict"] == "not-public" and c["verdict"] != "match" and c["gaps"] == ["listing visibility"], str(c))
check("2 the same page without the banner is a match (the banner is what decides)", R.compare(SML.split("\n", 1)[1], CANON)["verdict"] == "match")
for label, banner in (("hidden", "This listing is hidden"), ("paused", "Your listing is currently paused"), ("not activated", "This account is not yet activated"),
                      ("pending approval", "Pending approval"), ("awaiting review", "Awaiting review by our team"), ("unpublished", "This listing has been unpublished")):
    cc = R.compare(banner + "\n" + SML.split("\n", 1)[1], CANON)
    check("2 marker '%s' with a full NAP -> not-public" % label, cc["verdict"] == "not-public", str(cc))
check("2 a wrong phone plus the banner is still not-public (not live either way)", R.compare(SML.replace("555-0101", "555-0199"), CANON)["verdict"] == "not-public")
check("2 marker list is exposed and covers hidden / paused / not activated / pending approval", all(R.UNLISTED_RE.search(x) for x in ("hidden until activated", "listing is paused", "not yet activated", "pending approval")))
# the other created-unlisted pages: their public text has NO marker, so a complete page stays a match and a gap stays nap-incomplete
check("2 tupalo-style page with no phone is nap-incomplete (no marker invented)", R.compare("Alder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\nNo phone number has been added for this place.\n" + PAD, CANON)["verdict"] == "nap-incomplete")
# recheck end to end (dry run): a created-unlisted row on the showmelocal text reads not-public and would not go live
Q1 = {"canonical": CANON, "fix_queue": [{"id": "create-showmelocal", "directory": "showmelocal.com", "state": "created-unlisted", "evidence_url": "https://www.showmelocal.com/10000002-alder-care-exampleton", "history": []}]}
res = R.recheck(Q1, IDENT, plain=lambda u: R.Page(200, u, SML), chrome=lambda u: R.Page(200, u, SML), record=lambda *a, **k: (_ for _ in ()).throw(AssertionError("wrote")), today="2026-10-28", write=False, use_chrome=False)
check("2 recheck on the showmelocal page: verdict not-public, row stays created-unlisted", res[0]["verdict"] == "not-public" and res[0]["after"] == "created-unlisted", str(res[0]))

# ---- 3 mail URL -> permalink gate -> transitions listing_url -> recheck reads it ---------------------------------------------------
def msg(uid, frm, subj, body, date="2026-10-27T10:00"): return {"uid": uid, "from": frm, "subject": subj, "body": body, "date": date}
GOOD = "https://www.bbb.org/us/ky/exampleton/profile/consulting/alder-care-consulting-solutions-0012-99887766"
M_GOOD = [msg(1, "BBB <info@bbb.org>", "Your BBB Business Profile is now live", "Congratulations! View it at " + GOOD)]
M_SEARCH = [msg(2, "BBB <info@bbb.org>", "Your BBB Business Profile is now live", "Congratulations! Find us: https://www.bbb.org/search?find_text=alder&find_loc=Exampleton")]
M_CAT = [msg(3, "BBB <info@bbb.org>", "Your BBB Business Profile is now live", "Congratulations! See https://www.bbb.org/category/business-consultants")]
check("3 gate: a profile URL passes, a search URL and a category URL do not", MS.gate_ok("bbb.org", GOOD) and not MS.gate_ok("bbb.org", "https://www.bbb.org/search?find_text=alder") and not MS.gate_ok("bbb.org", "https://www.bbb.org/category/business-consultants"))
check("3 a mail whose only URL is a search page yields no hit", MS.find_approval("bbb.org", M_SEARCH, CANON["name"]) is None)
check("3 a mail whose only URL is a category page yields no hit", MS.find_approval("bbb.org", M_CAT, CANON["name"]) is None)
check("3 a mail with a search AND a profile URL yields the profile", MS.find_approval("bbb.org", [msg(4, "BBB <info@bbb.org>", "Your profile is now live", "Search https://www.bbb.org/search?find_text=a and view " + GOOD)], CANON["name"])["url"] == GOOD)

class FakeDB:
    owner = "owner-1"
    def __init__(self): self.calls = []
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))
class FakePortal(FakeDB):
    def __init__(self): super().__init__(); self.snap = {"found": 1, "directories": []}
    def latest_snapshot(self, cid): return {"payload": copy.deepcopy(self.snap)}
    def upsert_snapshot(self, cid, day, payload): self.calls.append(("snap", day))
TMP = tempfile.mkdtemp(prefix="b15-")
qp = os.path.join(TMP, "q.json")
json.dump({"canonical": CANON, "fix_queue": [{"id": "create-bbb", "directory": "bbb.org", "state": "submitted", "mike_approval": None,
           "evidence_url": "https://www.bbb.org/get-listed/success", "history": []}]}, open(qp, "w"))
db, fp = FakeDB(), FakePortal()
rec = lambda *a, **k: T.record_transition(*a, portal=fp, activities=fp, verification=fp, directories=db, **k)
PAGE = "Alder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n(502) 555-0101\n" + PAD
fetched = []
def plain(u): fetched.append(u); return R.Page(200, u, PAGE)
# run 1: no permalink in the row; the approval mail has it; --write stores it as listing_url through transitions
q = json.load(open(qp))
r1 = R.recheck(q, IDENT, plain=plain, chrome=plain, record=rec, db=db, queue_path=qp, today="2026-10-28", write=True, use_chrome=False, mail=MS.MailScanner(messages=M_GOOD, name=CANON["name"]))
row = json.load(open(qp))["fix_queue"][0]
check("3 run 1: the profile URL from the mail is stored as listing_url", row.get("listing_url") == GOOD, str(row.get("listing_url")))
check("3 run 1: the mail URL was recorded as listing_url, not evidence_url (first history entry carries no evidence)", row["history"][0]["evidence_url"] is None and row["history"][0]["from"] == "submitted" and row["history"][0]["to"] == "submitted", str(row["history"][:1]))
check("3 run 1: the page at that URL was read and matched, so the row went live with the permalink", r1[0]["url"] == GOOD and r1[0]["verdict"] == "match" and row["state"] == "live", str(r1[0]))
# run 2 (a later week, NO mail): recheck reads listing_url from the row by itself
json.dump({"canonical": CANON, "fix_queue": [dict(row, state="submitted")]}, open(qp, "w"))
fetched.clear()
r2 = R.recheck(json.load(open(qp)), IDENT, plain=plain, chrome=plain, record=rec, db=db, queue_path=qp, today="2026-11-04", write=False, use_chrome=False, mail=None)
check("3 run 2: with no mail, recheck reads the stored listing_url", r2[0]["url"] == GOOD and fetched and fetched[0] == GOOD, str(r2[0]))
# a refused URL never reaches transitions
json.dump({"canonical": CANON, "fix_queue": [{"id": "create-bbb", "directory": "bbb.org", "state": "submitted", "mike_approval": None, "evidence_url": "https://www.bbb.org/get-listed/success", "history": []}]}, open(qp, "w"))
wrote = []
r3 = R.recheck(json.load(open(qp)), IDENT, plain=plain, chrome=plain, record=lambda *a, **k: wrote.append((a, k)), db=db, queue_path=qp, today="2026-10-28", write=True, use_chrome=False, mail=MS.MailScanner(messages=M_SEARCH, name=CANON["name"]))
check("3 a search-only approval mail: no listing URL recorded, verdict no-permalink; only the no-URL backoff date is written (t_8d1865a3)", all(k.get("listing_url") is None and k.get("backoff") == "no-permalink" and a[2] == "submitted" for a, k in wrote) and len(wrote) == 1 and r3[0]["verdict"] == "no-permalink" and r3[0]["url"] is None, str(r3[0]))
# transitions itself refuses a non-http listing_url
try:
    T.record_transition("SCC", "create-bbb", "submitted", None, "x", queue_path=qp, today="2026-10-28", portal=fp, activities=fp, verification=fp, directories=db, listing_url="javascript:alert(1)")
    refused = False
except T.TransitionRefused: refused = True
check("3 transitions refuses a listing_url that is not plain http(s)", refused)

# ---- 4 login step + acompio_owner spec ------------------------------------------------------------------------------------------
class Loc:
    def __init__(s, page, sel): s.page, s.sel = page, sel
    @property
    def first(s): return s
    def count(s): return 0 if (s.sel == "input[name=password]" and s.page.signed_in) else 1
    def fill(s, v, **k): s.page.acts.append(("fill", s.sel, v))
    def click(s, **k): s.page.acts.append(("click", s.sel))
class Kb:
    def __init__(s, p): s.p = p
    def press(s, k):
        s.p.acts.append(("press", k))
        if k == "Enter" and s.p.accept: s.p.signed_in = True; s.p.url = "https://account.acompio.com/dashboard.php"
class FakePage:
    def __init__(s, accept=True, body="Company 10000001 Free Listing Status: Pending"):
        s.url, s.acts, s.keyboard, s.body, s.accept, s.signed_in = "https://account.acompio.com/login.php", [], Kb(s), body, accept, False
    def bring_to_front(s): s.acts.append(("focus", s.url))
    def goto(s, u, **k): s.acts.append(("goto", u)); s.url = u
    def locator(s, sel): return Loc(s, sel)
    def fill(s, sel, v, **k): s.acts.append(("fill", sel, v))
    def type(s, sel, v, **k): s.acts.append(("type", sel, v))
    def click(s, sel, **k): s.acts.append(("click", sel))
    def inner_text(s, sel, **k): return s.body
    def content(s): return ""
    def wait_for_timeout(s, ms): pass
    def wait_for_load_state(s, *a, **k): pass
    def evaluate(s, js, arg=None): s.acts.append(("eval", js[:40], arg)); return 1
class PRun:
    returncode, stdout, stderr = 0, "lookup=success", ""
    def __init__(s): s.calls = []
    def __call__(s, cmd, **k): s.calls.append(cmd); return s

spec = F.load_spec("acompio_owner"); site = F.build_site(spec)
raw = open(os.path.join(JOB, "playbooks", "acompio_owner.json"), encoding="utf-8").read()
check("4 acompio_owner spec loads, validates and is listed by build_runner", site.name == "acompio_owner" and "acompio_owner" in B.all_sites())
check("4 vault item is `SCC - acompio` and the spec holds no password, email or phone", site.vault_item == "SCC - acompio" and not F._LITERAL_EMAIL.search(raw) and not F._LITERAL_PHONE.search(raw) and '"password": "' not in raw.lower())
check("4 read only: record none, no submit step, no wizard click", site.record == "none" and all(s.kind in ("read", "fill") for s in site.steps) and not any(s["do"] in ("click", "click_text", "wait_mail", "solve_captcha") for s in spec["steps"]))
check("4 first step is the reusable `login` verb", spec["steps"][0]["do"] == "login")
page, runner = FakePage(), PRun()
res = B.run_site(site, B.Ctx(site, page, NAP, runner=runner, log=lambda *a: None, dry_run=True))
check("4 dry run ok: login page opened, email typed from the identity, vault only LOOKED UP (no --field), password not entered", res["ok"] and ("fill", "input[name=user]", NAP["email"]) in page.acts
      and runner.calls and all("--lookup-only" in c and "--field" not in c for c in runner.calls) and ("press", "Enter") not in page.acts, str(res)[:300])
check("4 the vault lookup names the item `SCC - acompio`", any("SCC - acompio" in c for c in runner.calls[0]))
page2, runner2 = FakePage(), PRun()
res2 = B.run_site(site, B.Ctx(site, page2, NAP, runner=runner2, log=lambda *a: None, dry_run=False))
check("4 live fixture: password filled by the vault helper into input[name=password], Enter pressed, dashboard status read", res2["ok"] and any("--field" in c and "input[name=password]" in c for c in runner2.calls)
      and ("press", "Enter") in page2.acts and res2["steps"][-1]["detail"] == "status text: pending", str(res2["steps"]))
check("4 the page text is never in the step detail", "10000001" not in json.dumps(res2["steps"]))
page3 = FakePage(accept=False)
res3 = B.run_site(site, B.Ctx(site, page3, NAP, runner=PRun(), log=lambda *a: None, dry_run=False))
check("4 a rejected login fails the step and the run stops before the status read", not res3["ok"] and "login failed" in res3["steps"][0]["detail"] and len(res3["steps"]) == 1, str(res3["steps"]))
page4 = FakePage(body="Welcome")
res4 = B.run_site(site, B.Ctx(site, page4, NAP, runner=PRun(), log=lambda *a: None, dry_run=False))
check("4 a dashboard with no status word fails read_status (no silent pass)", not res4["ok"] and res4["steps"][-1]["name"] == "read_status")
def bad(steps):
    try: F.validate({"site": "z", "domain": "z.example", "steps": steps}); return None
    except Exception as e: return str(e)
check("4 login without a password selector is refused", "password_selector" in (bad([{"do": "login", "url": "https://z.example/l", "user_selector": "#u"}]) or ""))
check("4 read_text without expect_any is refused", "expect_any" in (bad([{"do": "read_text"}]) or ""))

# ---- 5 foursquare: no public source -> unreadable-public, never live, never fetched -------------------------------------------------
Q5 = {"canonical": CANON, "fix_queue": [{"id": "create-foursquare", "directory": "foursquare.com", "state": "submitted", "mike_approval": None,
      "evidence_url": "https://foursquare.com/v/alder-care/0123456789abcdef01234567", "listing_url": "https://app.foursquare.com/v/alder-care/0123456789abcdef01234567", "history": []}]}
hits = []
def spy(u): hits.append(u); return R.Page(200, u, PAGE)   # even a page that would MATCH must not make it live
w5 = []
r5 = R.recheck(Q5, IDENT, plain=spy, chrome=spy, record=lambda *a, **k: w5.append(a), today="2026-10-28", write=True, use_chrome=False)
check("5 foursquare row: verdict unreadable-public, state unchanged, never fetched; only a recheck_due backoff note is written (t_962161f4)", r5[0]["verdict"] == "unreadable-public" and r5[0]["after"] == "submitted" and not hits and all(a[2] == "submitted" and a[1] == "create-foursquare" for a in w5) and len(w5) <= 1, str(r5[0]))
check("5 foursquare is never fetched (no signed-in or login-wall read)", not hits, str(hits))
check("5 the report says why, with no error flag (the exit code stays 0)", "no public source" in (r5[0]["note"] or "") and r5[0]["error"] is None)
check("5 other Directories are not in the unreadable-public list", set(R.UNREADABLE_PUBLIC) == {"foursquare.com"})
check("5 report line carries the note for the new verdict", "unreadable-public" in R.format_report(r5))

# ---- 6 citylocalpro: the reader logs the search it ran and what it got (no page text) -----------------------------------------------
Q6 = {"canonical": CANON, "fix_queue": [{"id": "create-citylocalpro", "directory": "citylocalpro.com", "state": "submitted", "mike_approval": None, "evidence_url": None, "history": []}]}
SEARCH_PAGE = "Search results. Nothing here for your terms. " + PAD
r6 = R.recheck(Q6, IDENT, plain=lambda u: R.Page(200, u, SEARCH_PAGE, links=[{"href": "https://citylocalpro.com/x", "text": "Other Plumbing", "card": "Other Plumbing Co", "aria": ""}]), chrome=lambda u: R.Page(200, u, SEARCH_PAGE), record=lambda *a, **k: None, today="2026-10-28", write=False, use_chrome=False)
cl_rep = R.format_report(r6)
if r6[0].get("search"):
    check("6 citylocalpro: the search ran is logged (host+path, status, link count, result)", "searched citylocalpro.com" in r6[0]["search"] and "status 200" in r6[0]["search"], r6[0]["search"])
    check("6 the log carries no page text and no business name", "Nothing here" not in cl_rep and "Alder" not in r6[0]["search"] and "?" not in r6[0]["search"])
    check("6 the not-public note ends with that search line", r6[0]["verdict"] == "not-public" and r6[0]["search"] in (r6[0]["note"] or ""), str(r6[0]))
else:
    check("6 citylocalpro has a search URL (Catalog template or create-discovery)", False, str(r6[0]))
check("6 search_log pure: status, links and outcome only", R.search_log("https://x.example/s?q=Alder+Care", R.Page(200, "u", "t", links=["a", "b"]), "chrome", None) == "searched x.example/s via chrome: status 200, 2 links, no card for the business")

print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
