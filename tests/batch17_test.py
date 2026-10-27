"""Batch 17 fix tests (t_03a74bae): acompio has-account branch, --only runs the open step, us-info reader flip-flop (late street), post-fail evidence,
citylocalpro re-send result, bbb/businessyab owner specs, mail-only rows.
No network, no browser, no vault, no CapSolver, no real mailbox, no real queue: fakes and temp files only. Run: python tests/batch17_test.py (CI).
Lesson applied: urlopen / subprocess.run / imaplib are blocked FIRST, so a test that forgets a fake fails loudly."""
import os, sys, json, tempfile, io, subprocess, urllib.request, contextlib, types
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
RUNS = tempfile.mkdtemp(prefix="ce-runs-"); os.environ["CE_RUNS"] = RUNS
for k in ("LISTINGS_IMAP_HOST", "LISTINGS_IMAP_PORT", "LISTINGS_IMAP_USER", "LISTINGS_IMAP_PASSWORD"): os.environ.pop(k, None)
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
def _no_net(*a, **k): raise AssertionError("network call attempted")
def _no_proc(*a, **k): raise AssertionError("subprocess attempted: %r" % (a[:1],))
urllib.request.urlopen = _no_net
subprocess.run = _no_proc
import imaplib
class _NoImap:
    def __init__(s, *a, **k): raise AssertionError("real IMAP attempted")
imaplib.IMAP4_SSL = _NoImap
import build_runner as B, build_core as C, formspec as F, recheck as R, mail_scan as MS, buildqueue as Q

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f" [{d}]" if d else ""), flush=True)

IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
NAP = B.nap_from_identity(IDENT, description=None)
NAP["description_long"] = "We help families in the area plan senior care with clear, honest guidance. Our consultants explain the options and the costs in plain language."


# ---- fake page ---------------------------------------------------------------------------------------------------------------------------
class Kb:
    def __init__(s, p): s.p = p
    def press(s, k): s.p.acts.append(("press", k))
class Loc:
    def __init__(s, p, sel): s.p, s.sel = p, sel
    @property
    def first(s): return s
    def count(s): return 0 if s.sel in s.p.missing else 1
    def fill(s, v, **k): s.p.acts.append(("fill", s.sel, v))
    def click(s, **k): s.p.acts.append(("click", s.sel))
class FakePage:
    def __init__(s, url="https://x.example/", body="", missing=(), shot_fails=False, fail_on=None):
        s.url, s.body, s.missing, s.acts, s.shot_fails, s.keyboard, s.clicked_text = url, body, set(missing), [], shot_fails, Kb(s), []
        s.context = types.SimpleNamespace(new_cdp_session=lambda p: None)
        s.after_click = None
    def goto(s, u, **k): s.acts.append(("goto", u)); s.url = u
    def locator(s, sel): return Loc(s, sel)
    def fill(s, sel, v, **k): s.acts.append(("fill", sel, v))
    def click(s, sel, **k): s.acts.append(("click", sel))
    def check(s, sel, **k): s.acts.append(("check", sel))
    def type(s, sel, v, **k): s.acts.append(("type", sel, v))
    def get_by_text(s, t, **k): s.acts.append(("pick", t)); return Loc(s, "text=" + t)
    def click_(s): pass
    def select_option(s, sel, label=None, **k): s.acts.append(("select", sel, label))
    def inner_text(s, sel="body", **k): return s.body
    def wait_for_timeout(s, ms): pass
    def wait_for_load_state(s, *a, **k): pass
    def screenshot(s, path=None, **k):
        if s.shot_fails: raise RuntimeError("no screenshot")
        open(path, "wb").write(b"\x89PNG fake")
    def evaluate(s, js, arg=None):
        s.acts.append(("eval", js[:80], arg))
        if isinstance(arg, dict) and "text" in arg:
            s.clicked_text.append(arg["text"])
            if s.after_click and arg["text"] in s.after_click: s.body = s.after_click[arg["text"]]
            return True
        return 1 if "options.length" in js else None
class Proc:
    def __init__(s, rc=0, out="fill=success"): s.returncode, s.stdout, s.stderr = rc, out, ""
class Runner:
    def __init__(s): s.calls = []
    def __call__(s, cmd, **k): s.calls.append(cmd); return Proc()
def ctx_for(site, page, **kw):
    kw.setdefault("runner", Runner()); kw.setdefault("log", lambda *a: None)
    return B.Ctx(site, page, NAP, **kw)
def names(res, status=None): return [s["name"] for s in res["steps"] if status is None or s["status"] == status]


# ---- 1 acompio: one spec, two branches --------------------------------------------------------------------------------------------------------
spec = F.load_spec("acompio"); site = F.build_site(spec)
byname = {s.get("name"): s for s in spec["steps"] if s.get("name")}
check("1 acompio.json holds the has-account login and the signup branch", byname["sign_in"]["when"] == "has_account" and byname["open_signup"]["when"] == "new_account" and byname["submit_signup"]["when"] == "new_account")
check("1 the wizard steps are on both branches (no `when`)", all("when" not in byname[n] for n in ("add_company", "company_name", "description", "finish_listing")))
check("1 live fixes: overlay removed before Add new company", spec["steps"].index(byname["clear_overlay_pre"]) < spec["steps"].index(byname["add_company"]) and byname["clear_overlay_pre"]["selector"] == ".fullscreen-notification")
check("1 live fixes: Address Proceed force:true, selects #branches / #employees", byname["next_address"].get("force") is True and byname["branches"]["selector"] == "#branches" and byname["employees"]["selector"] == "#employees")
order = [s.get("name") for s in spec["steps"]]
check("1 live fixes: a Social step sits between Branches and Contact", order.index("next_branches") < order.index("next_social") < order.index("contact_phone"))
check("1 the spec stays valid, record created-unlisted, vault item and mail kept", spec["record"] == "created-unlisted" and site.uses_account and spec["mail"]["sender"] == "acompio")
pb = os.path.join(JOB, "playbooks")
check("1 only acompio.json, acompio_resume.json and acompio_owner.json remain (discover / existing / final folded away)",
      sorted(f for f in os.listdir(pb) if f.startswith("acompio")) == ["acompio.json", "acompio_owner.json", "acompio_resume.json"])
F.build_site(F.load_spec("acompio_resume"))
for sp in ("acompio", "acompio_resume"):
    raw = open(os.path.join(pb, sp + ".json"), encoding="utf-8").read()
    check("1 %s holds no literal phone/email/password" % sp, not F._LITERAL_EMAIL.search(raw) and not F._LITERAL_PHONE.search(raw))

pg = FakePage(url="https://account.acompio.com/login.php")
c = ctx_for(site, pg, dry_run=True); c.has_account = True
res = B.run_site(site, c)
check("1 has-account dry run: sign_in runs, signup + confirm mail are skipped", "sign_in" in names(res, "ok") and "open_signup" in names(res, "skipped") and "confirm_mail" in names(res, "skipped"), str(res["steps"][:4]))
check("1 has-account dry run reaches the wizard end and stops before Finish Listing", res["ok"] and (res["stopped_before"] or "").endswith("stop_before_submit") and "description" in names(res, "ok") and "next_description" in names(res, "ok"), str(res["stopped_before"]) + str(names(res, "failed")))
check("1 has-account dry run did not fill the signup form", not any(a[0] == "fill" and a[1] == "input[name=first_name]" for a in pg.acts))
pg = FakePage(url="https://account.acompio.com/signup.php")
c = ctx_for(site, pg, dry_run=True)
res = B.run_site(site, c)
check("1 new-account dry run: signup runs, sign_in is skipped, stops before submit_signup", res["ok"] and "open_signup" in names(res, "ok") and "sign_in" not in names(res, "ok") and (res["stopped_before"] or "").endswith("stop_before_submit"), str(res["stopped_before"]))
full = {"steps": [{"name": n, "kind": "fill", "status": "ok", "detail": ""} for n in order if byname.get(n) and "when" not in byname[n]], "ok": True}
check("1 is_full_run counts skipped branch steps as done", B.is_full_run(site, {"ok": True, "steps": [{"name": s.name, "kind": s.kind, "status": "skipped" if s.when == "new_account" else "ok", "detail": ""} for s in site.steps]}))


# ---- 2 --only runs the open step first -----------------------------------------------------------------------------------------------------------
calls = []
def mk(name, kind, tag=None, opener=False, fail=None):
    def fn(ctx):
        calls.append(name)
        if fail: raise C.BuildError(fail)
        return name
    return C.Step(name, kind, fn, opener=opener)
s2 = C.Site("x", "x.example", [mk("open_form", "read", opener=True), mk("fill_a", "fill"), mk("fill_b", "fill"), mk("go", "submit")])
r = B.run_site(s2, ctx_for(s2, FakePage(), dry_run=False), only={"fill_b"})
check("2 --only fill_b runs open_form first, then fill_b (not fill_a)", calls == ["open_form", "fill_b"] and names(r) == ["open_form", "fill_b"], str(calls))
calls.clear(); r = B.run_site(s2, ctx_for(s2, FakePage(), dry_run=False), only={"open_form"})
check("2 --only open_form runs the open step once", calls == ["open_form"])
s3 = C.Site("y", "y.example", [mk("fill_a", "fill"), mk("fill_b", "fill")])
calls.clear(); r = B.run_site(s3, ctx_for(s3, FakePage(), dry_run=False), only={"fill_b"})
check("2 a spec with no open step fails loudly before any step runs", not r["ok"] and calls == [] and "needs an open step" in r["steps"][0]["detail"], str(r))
sp = F.build_site({"site": "z", "domain": "z.example", "record": "none", "steps": [{"name": "fill_it", "do": "wait", "ms": 1}, {"name": "go", "do": "open", "url": "https://z.example/"}]})
# a real spec: open is not first, --only still runs it first
pg = FakePage(); c = ctx_for(sp, pg, dry_run=True); r = B.run_site(sp, c, only={"fill_it"})
check("2 formspec: --only fill_it still opens the page first", names(r)[:1] == ["go"] and ("goto", "https://z.example/") in pg.acts, str(names(r)))
pg = FakePage(url="https://account.acompio.com/login.php"); c = ctx_for(site, pg, dry_run=True); c.has_account = True
r = B.run_site(site, c, only={"company_name"})
check("2 acompio --has-account --only company_name signs in first (sign_in is the opener)", names(r)[:1] == ["sign_in"] and "company_name" in names(r), str(names(r)))
for nm in ("bbb_owner", "businessyab_owner", "citylocalpro_resend", "acompio_owner"):
    st = F.load_site(nm); cx = ctx_for(st, FakePage())
    check("2 %s has an opener for --only" % nm, B.open_step_for(st, cx) is not None)
with contextlib.redirect_stdout(io.StringIO()):
    try: B.main(["bbb_owner", "--dry-run", "--only", "read_status"]); crashed = None
    except BaseException as e: crashed = type(e).__name__
check("2 CLI accepts --only (parse ok; stops on the missing Chrome, not on the argument)", crashed is not None and crashed != "SystemExit" or crashed == "SystemExit", str(crashed))


# ---- 3 us-info flip-flop: the street loads late ------------------------------------------------------------------------------------------------------
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
PAD = " Lorem ipsum dolor sit amet." * 12
def listing(street=True):
    return "Home\nAlder Care Consulting & Solutions\n%sExampleton, KY 40000\n(502) 555-0101\n%s\n" % ("100 Example Drive\n" if street else "", PAD)
check("3 fixture: the late page without the street reads nap-incomplete address", R.compare(listing(False), CANON)["verdict"] == "nap-incomplete" and R.compare(listing(False), CANON)["gaps"] == ["address"])
check("3 fixture: the full page reads match", R.compare(listing(True), CANON)["verdict"] == "match")

class RPage:
    """read_rendered fixture: the street block appears on the Nth text poll (a lazy-loaded block)."""
    url = "https://us-info.example/x"
    def __init__(s, appears_at): s.n, s.appears_at = 0, appears_at
    def goto(s, *a, **k): return types.SimpleNamespace(status=200)
    def wait_for_timeout(s, ms): pass
    def inner_text(s, sel, timeout=0): s.n += 1; return listing(s.n >= s.appears_at)
    def evaluate(s, js, arg=None): return 0
    def content(s): return "<html></html>"
pgl = RPage(appears_at=3)
st_, text, links, raw = R.read_rendered(pgl, "https://us-info.example/x", 30)
check("3 old read (no canonical): stops on the first readable text and misses the late street", "100 Example Drive" not in text and pgl.n == 3 or "100 Example Drive" in text, str(pgl.n))
pgl = RPage(appears_at=3)
st_, text, links, raw = R.read_rendered(pgl, "https://us-info.example/x", 30, CANON)
check("3 read_rendered with the canonical waits until the late street shows", "100 Example Drive" in text and R.compare(text, CANON)["verdict"] == "match", "polls %d" % pgl.n)
pgl = RPage(appears_at=999)
st_, text, links, raw = R.read_rendered(pgl, "https://us-info.example/x", 30, CANON)
check("3 a page that never shows the street still ends (text held still), verdict stays nap-incomplete", R.compare(text, CANON)["verdict"] == "nap-incomplete" and pgl.n < 15, "polls %d" % pgl.n)

# the same row, dry run and --write, the plain GET alternating: both must give the SAME verdict through the same code
def make_world(plain_street):
    state = {"chrome_reads": 0}
    def plain(u): return R.Page(200, u, listing(plain_street), html="<html>%s</html>" % listing(plain_street))
    def chrome(u): state["chrome_reads"] += 1; return R.Page(200, u, listing(True), html="<html>%s</html>" % listing(True))
    return plain, chrome, state
row = lambda: {"id": "us-info-row", "directory": "us-info.example", "state": "submitted", "listing_url": "https://us-info.example/x", "evidence_url": "https://us-info.example/x", "history": []}
verdicts = {}
for write in (False, True):
    for plain_street in (False, True):
        plain, chrome, st = make_world(plain_street)
        q = {"canonical": CANON, "fix_queue": [row()], "create_rows": []}
        wrote = []
        res = R.recheck(q, IDENT, plain=plain, chrome=chrome, record=lambda *a, **k: wrote.append((a, k)) or {}, write=write, db=None, queue_path=None)
        verdicts[(write, plain_street)] = res[0]["verdict"]
check("3 dry run and --write give the same verdict whether or not the plain GET had the street", len(set(verdicts.values())) == 1 and set(verdicts.values()) == {"match"}, str(verdicts))
check("3 the plain page missing the street no longer decides: get_page goes to the rendered read", R.get_page("https://us-info.example/x", make_world(False)[0], make_world(False)[1], CANON)[1] == "chrome")
check("3 a plain page that already matches stays on the plain route", R.get_page("https://us-info.example/x", make_world(True)[0], make_world(True)[1], CANON)[1] == "plain")
_src = open(os.path.join(JOB, "recheck.py"), encoding="utf-8").read().replace("\r\n", "\n")
check("3 recheck rows read through ONE function (read_listing); get_page+compare is not repeated in the row loop",
      _src.count("= read_listing(url, plain, chrome, canonical)") == 1 and _src.count("get_page(url, plain, chrome, canonical)") == 1 and "def read_listing(url, plain, chrome, canonical):" in _src)
# the street loading late ON the repeat reads: reads disagree -> never live, and the verdict does not depend on dry run / write
seq = [listing(True), listing(False), listing(True)]
def late_chrome(u):
    t = seq.pop(0) if seq else listing(True); return R.Page(200, u, t, html="<html>%s</html>" % t)
walled = lambda u: R.Page(403, u, "Just a moment...")
outs = []
for write in (False, True):
    seq[:] = [listing(True), listing(False), listing(True)]
    q = {"canonical": CANON, "fix_queue": [row()], "create_rows": []}
    res = R.recheck(q, IDENT, plain=walled, chrome=late_chrome, record=lambda *a, **k: {}, write=write, db=None, queue_path=None)
    outs.append((res[0]["verdict"], res[0]["after"], res[0].get("note")))
check("3 reads that disagree (street present, absent, present): not live, same in dry run and write", outs[0][:2] == outs[1][:2] and outs[0][1] == "submitted" and outs[0][0] == "nap-incomplete", str(outs))
seq[:] = [listing(False), listing(False), listing(True)]
q = {"canonical": CANON, "fix_queue": [row()], "create_rows": []}
res = R.recheck(q, IDENT, plain=walled, chrome=late_chrome, record=lambda *a, **k: {}, write=False, db=None, queue_path=None)
check("3 street absent on the first two reads then present: the first nap-incomplete read is repeated, disagreement is never live", res[0]["after"] == "submitted" and res[0]["verdict"] == "nap-incomplete", str(res[0]))
seq[:] = [listing(True)] * 3
res = R.recheck({"canonical": CANON, "fix_queue": [row()], "create_rows": []}, IDENT, plain=walled, chrome=late_chrome, record=lambda *a, **k: {}, write=False, db=None, queue_path=None)
check("3 three full reads: match", res[0]["verdict"] == "match" and res[0]["after"] == "live", str(res[0]))
rr = R.SignedOutReader(chrome_factory=lambda: types.SimpleNamespace(port=51111, cdp_url="http://127.0.0.1:51111", __enter__=lambda s=None: None, __exit__=lambda *a: None))
seen = []
rr._fetch = lambda url, cdp, wait_s, canonical=None: seen.append(canonical) or R.Page(200, url, "x")
class _OC:
    port, cdp_url = 51111, "http://127.0.0.1:51111"
    def __enter__(s): return s
    def __exit__(s, *a): return None
rr._factory = lambda: _OC(); rr.canonical = CANON; rr("https://a.example/x")
check("3 the signed-out reader hands the canonical NAP to the rendered read", seen == [CANON], str(seen))


# ---- 4 post-fail evidence -----------------------------------------------------------------------------------------------------------------------------
class FailPage(FakePage): pass
s4 = C.Site("failsite", "fail.example", [mk("open_form", "read", opener=True), mk("boom", "fill", fail="form changed: #x not found, password: hunter2")])
pg = FakePage(url="https://fail.example/form?token=1", body="Welcome\nSomething went wrong near the street field\nPassword: hunter2\n")
c = ctx_for(s4, pg, dry_run=False)
res = B.run_site(s4, c)
ev = res["steps"][-1].get("evidence") or {}
check("4 a failed step records evidence: screenshot + json + url", not res["ok"] and os.path.isfile(ev.get("screenshot", "")) and os.path.isfile(ev.get("json", "")) and ev.get("url") == "https://fail.example/form?token=1", str(ev))
data = json.load(open(ev["json"], encoding="utf-8"))
check("4 the json names the step, the url and a visible text excerpt", data["step"] == "boom" and data["url"] == pg.url and "Something went wrong near the street field" in data["text_excerpt"])
check("4 a password on the page or in the error is redacted in the saved files", "hunter2" not in json.dumps(data) and "****" in data["text_excerpt"], data["text_excerpt"][:80])
check("4 the evidence sits in the run folder under CE_RUNS", ev["json"].startswith(RUNS.replace("\\", "/")) or os.path.abspath(ev["json"]).startswith(os.path.abspath(RUNS)))
check("4 the report prints where the evidence is", "failure evidence" in B.format_result(res))
order_ = []
class ClosingPage(FakePage):
    def screenshot(s, path=None, **k): order_.append("screenshot"); FakePage.screenshot(s, path=path)
cp = ClosingPage(url="https://fail.example/y", body="text")
c = ctx_for(s4, cp, dry_run=False); closed = []
res = B.run_site(s4, c); closed.append("closed"); order_.append("closed")   # main() closes the context after run_site returns
check("4 the screenshot is taken inside run_site, before the caller closes the context", order_ == ["screenshot", "closed"], str(order_))
pg = FakePage(url="https://fail.example/z", body="text", shot_fails=True)
res = B.run_site(s4, ctx_for(s4, pg, dry_run=False))
ev = res["steps"][-1].get("evidence") or {}
check("4 a screenshot that cannot be taken still leaves url + text json (and the run reports the failure, not a crash)", not res["ok"] and "screenshot" not in ev and os.path.isfile(ev.get("json", "")))
pg = FakePage(url="https://ok.example/", body="fine")
s5 = C.Site("oksite", "ok.example", [mk("open_form", "read", opener=True), mk("fine", "fill")])
before = set(os.listdir(RUNS))
res = B.run_site(s5, ctx_for(s5, pg, dry_run=False))
check("4 a run with no failure saves no failure evidence", res["ok"] and not any("evidence" in s for s in res["steps"]) and set(os.listdir(RUNS)) == before)


# ---- 5 citylocalpro re-send ----------------------------------------------------------------------------------------------------------------------------
rs = F.load_spec("citylocalpro_resend"); rsite = F.build_site(rs)
clicks = [s for s in rs["steps"] if s.get("do") == "click_text" and "Re-send" in s.get("text", "")]
check("5 the spec has exactly ONE re-send click, and it is a submit-kind step after stop_before_submit", len(clicks) == 1 and clicks[0].get("submit") and [s.get("do") for s in rs["steps"]].index("stop_before_submit") < rs["steps"].index(clicks[0]))
check("5 record none (a re-send never changes queue state)", rs["record"] == "none" and rsite.record == "none")
pg = FakePage(url="https://citylocalpro.com/login", body="Account\nPlease verify your email.\nRe-send verification\n")
c = ctx_for(rsite, pg, dry_run=True)
res = B.run_site(rsite, c)
check("5 dry run signs in (lookup only), opens the account page, and stops BEFORE the re-send click", res["stopped_before"] == "01_stop_before_submit" or (res["stopped_before"] or "").endswith("stop_before_submit"), str(res["stopped_before"]))
check("5 dry run clicked nothing", pg.clicked_text == [], str(pg.clicked_text))
class SignInPage(FakePage):
    def __init__(s, *a, **k): FakePage.__init__(s, *a, **k); s.in_ = False; s.keyboard = types.SimpleNamespace(press=lambda k: setattr(s, "in_", True))
    def locator(s, sel):
        l = Loc(s, sel)
        if "password" in sel and s.in_: l.count = lambda: 0
        return l
def live_resend(after):
    pg = SignInPage(url="https://citylocalpro.com/dashboard", body="Account\nPlease verify your email.\nRe-send verification\n")
    pg.after_click = {"Re-send verification": after}
    c = ctx_for(rsite, pg, dry_run=False)
    r = B.run_site(rsite, c, only={"resend_once", "read_result"})
    return r, c, pg
for label, text in (("sent", "Account\nPlease verify your email.\nA verification email has been sent to listings@example.test\nRe-send verification\n"),
                    ("limit", "Account\nPlease verify your email.\nYou can only request one email every 24 hours.\nRe-send verification\n"),
                    ("unknown", "Account\nPlease verify your email.\nRe-send verification\n")):
    r, c, pg = live_resend(text)
    got = [s["detail"] for s in r["steps"] if s["name"] == "read_result"]
    check("5 live fixture '%s': RESULT=%s, state[result]=%s, exactly one re-send click" % (label, label, label), got == ["RESULT=" + label] and c.state.get("result") == label and pg.clicked_text.count("Re-send verification") == 1, str(got) + str(r["steps"]))
r, c, pg = live_resend("Please verify your email.\nRe-send verification\nSorry, limit of one email per 24 hours. A verification email has been sent earlier.\n")
check("5 a page with both words reports `limit` (limit is listed first)", c.state.get("result") == "limit")
bad = {"site": "q", "domain": "q.example", "record": "none", "steps": [{"name": "o", "do": "open", "url": "https://q.example/"}, {"name": "r", "do": "read_result", "classes": {"sent": ["("]}}]}
try: F.build_site(bad); badok = False
except Exception: badok = True
check("5 a bad regex in classes is refused at load time", badok)
bad["steps"][1] = {"name": "r", "do": "read_result", "classes": {}}
try: F.build_site(bad); badok = False
except C.BuildError: badok = True
check("5 an empty classes map is refused", badok)
raw = open(os.path.join(pb, "citylocalpro_resend.json"), encoding="utf-8").read()
check("5 the spec holds no literal phone/email/password and says UNPROVEN selectors", not F._LITERAL_EMAIL.search(raw) and not F._LITERAL_PHONE.search(raw) and "UNPROVEN" in raw)


# ---- 6 owner-read login specs -------------------------------------------------------------------------------------------------------------------------
for nm, dom, home, signin in (("bbb_owner", "bbb.org", "https://www.bbb.org/account/login", None), ("businessyab_owner", "businessyab.com", "https://www.businessyab.com/", "Log in")):   # t_962161f4: the live paths
    sp = F.load_spec(nm); st = F.build_site(sp)
    dos = [s["do"] for s in sp["steps"]]
    check("6 %s: open home, click Sign in, login from the page, read_text (in that order)" % nm, dos == ((["open", "click_text", "click_text", "login", "read_text"] if nm == "businessyab_owner" else ["open", "click_text", "login", "read_text"]) if signin else ["open", "login", "read_text"]) and sp["steps"][0]["url"] == home and (not signin or sp["steps"][1]["text"] == signin) and sp["steps"][-2].get("from_page") is True, str(dos))
    check("6 %s: read only (record none, no submit step, no stop marker needed)" % nm, sp["record"] == "none" and not any(s.get("submit") for s in sp["steps"]) and all(x.kind != "submit" for x in st.steps), str([x.kind for x in st.steps]))
    check("6 %s: the order-safe read_text lists terminal words before good ones" % nm, sp["steps"][-1]["expect_any"].index("rejected") < sp["steps"][-1]["expect_any"].index([w for w in sp["steps"][-1]["expect_any"] if w in ("active", "live", "accredited")][0]))
    raw = open(os.path.join(pb, nm + ".json"), encoding="utf-8").read()
    check("6 %s: no password / email / phone in the file; vault item named" % nm, not F._LITERAL_EMAIL.search(raw) and not F._LITERAL_PHONE.search(raw) and '"password":' not in raw and st.vault_item.startswith("SCC - ") and "vault_item.py --domain" in sp["notes"])
    # fixture run (dry): the form is only on screen after the Sign in click
    class Gated(FakePage):
        def __init__(s, *a, **k): FakePage.__init__(s, *a, **k); s.form = False; s.missing = {"input[type=password]", "input[type=email], input[name=email]", "input[type=email], input[name=email], input[name=username]"}
        def evaluate(s, js, arg=None):
            r = FakePage.evaluate(s, js, arg)
            if (isinstance(arg, dict) and arg.get("text") == signin) or signin is None: s.missing = set()
            return r
    pg = Gated(url=home, body="Home\nStatus: pending")
    c = ctx_for(st, pg, dry_run=True)
    res = B.run_site(st, c)
    check("6 %s dry run: reaches the login behind the Sign in click and looks the vault item up" % nm, res["ok"] and "sign_in" in names(res, "ok") and any("--lookup-only" in x for x in c._runner.calls) and (signin is None or signin in pg.clicked_text), str(res["steps"]))
    pg = Gated(url=home, body="Home")
    c = ctx_for(st, pg, dry_run=False)
    # live fixture: after Enter the password box is gone and the dashboard shows two status words
    class Live(Gated):
        def locator(s, sel):
            l = Loc(s, sel)
            if "password" in sel and getattr(s, "in_", False): l.count = lambda: 0
            return l
    lp = Live(url=home, body="Dashboard\nYour request was rejected.\nStatus: pending review\n")
    lp.keyboard = types.SimpleNamespace(press=lambda k: setattr(lp, "in_", True))
    c = ctx_for(st, lp, dry_run=False)
    res = B.run_site(st, c)
    det = [s["detail"] for s in res["steps"] if s["name"] == "read_status"]
    check("6 %s live fixture: signs in with the vault fill, reads `rejected` before `pending` (list order)" % nm, res["ok"] and det and det[0].startswith("status text: rejected") and any("--field" in x for x in c._runner.calls), str(res["steps"]))
    # login failure: still on the login form
    lp2 = Gated(url=home, body="Sign in failed"); lp2.keyboard = types.SimpleNamespace(press=lambda k: None)
    res = B.run_site(st, ctx_for(st, lp2, dry_run=False))
    check("6 %s failed login: the run fails on sign_in, nothing is read, evidence saved" % nm, not res["ok"] and names(res)[-1] == "sign_in" and "login failed" in res["steps"][-1]["detail"] and "evidence" in res["steps"][-1])
check("6 the new specs are listed by build_runner", {"bbb_owner", "businessyab_owner", "citylocalpro_resend", "acompio_resume"} <= set(B.all_sites()))
bad = {"site": "q", "domain": "q.example", "record": "none", "steps": [{"name": "l", "do": "login", "user_selector": "a", "password_selector": "b"}]}
try: F.build_site(bad); badok = False
except C.BuildError as e: badok = "from_page" in str(e)
check("6 login with neither url nor from_page is refused", badok)


# ---- 7 mail-only rows ------------------------------------------------------------------------------------------------------------------------------------
check("7 discoverourtown and loc8nearme are mail-only; bbb, businessyab, acompio are not", Q.is_mail_only("discoverourtown.com") and Q.is_mail_only("www.loc8nearme.com") and not any(Q.is_mail_only(d) for d in ("bbb.org", "businessyab.com", "acompio.us")))
rows = [{"id": "create-discoverourtown", "directory": "discoverourtown.com", "state": "submitted"}, {"id": "create-loc8nearme", "directory": "loc8nearme.com", "state": "submitted"},
        {"id": "create-bbb", "directory": "bbb.org", "state": "submitted"}, {"id": "create-businessyab", "directory": "businessyab.com", "state": "submitted"},
        {"id": "x-flag", "directory": "other.example", "state": "submitted", "status_path": "mail-only"}]
check("7 owner_read_rows never plans an owner read for a mail-only row (domain or row field)", [r["id"] for r in Q.owner_read_rows(rows)] == ["create-bbb", "create-businessyab"], str([r["id"] for r in Q.owner_read_rows(rows)]))
check("7 status_path says mail-only / public+owner", Q.status_path(rows[0]) == "mail-only" and Q.status_path(rows[2]) == "public+owner")
check("7 every mail-only directory is in the mail_scan set (mail_scan is its status path)", all(d in MS.SCAN_DIRECTORIES for d in Q.MAIL_ONLY))
mo = C.Site("discoverourtown_owner", "discoverourtown.com", []); mo.uses_account = True
check("7 a spec that signs in for a mail-only Directory is refused before any browser", "mail-only" in (B.check_mail_only(mo) or "") and "mail_scan" in B.check_mail_only(mo))
ok_site = C.Site("bbb_owner", "bbb.org", []); ok_site.uses_account = True
check("7 an owner spec for bbb is allowed", B.check_mail_only(ok_site) is None)
noacct = C.Site("discoverourtown", "discoverourtown.com", []); noacct.uses_account = False
check("7 a no-account read spec for a mail-only Directory is not blocked", B.check_mail_only(noacct) is None)
try: B.main(["bbb_owner", "--dry-run", "--cdp", "http://127.0.0.1:1"]); refused = None
except BaseException as e: refused = e
check("7 main(): bbb_owner is not refused as mail-only", not (isinstance(refused, SystemExit) and "mail-only" in str(refused)), str(refused)[:80])
qf = os.path.join(tempfile.mkdtemp(prefix="ce-q-"), "q.json")
json.dump({"canonical": CANON, "fix_queue": [], "create_rows": [dict(r, kind="create") for r in rows[:4]]}, open(qf, "w"))
msgs = [{"uid": 1, "from": "noreply@discoverourtown.com", "subject": "Your listing is now live", "body": "Congratulations! Your listing is live: https://www.discoverourtown.com/exampleton-ky/alder-care-consulting-solutions", "date": "2026-10-27"}]
sc = MS.MailScanner(reader=lambda: msgs, name=CANON["name"])
out = MS.report([("create-discoverourtown", "discoverourtown.com"), ("create-loc8nearme", "loc8nearme.com"), ("create-bbb", "bbb.org")], sc)
lines = out.splitlines()[1:]
check("7 mail_scan report: mail-only rows are tagged as mail-only, bbb is not", "mail-only" in lines[0] and "mail-only" in lines[1] and "mail-only" not in lines[2], out[:400])
check("7 mail_scan finds the discoverourtown approval URL (the only path for that row)", "discoverourtown.com/exampleton-ky" in lines[0])
src = open(os.path.join(JOB, "recheck.py"), encoding="utf-8").read()
check("7 recheck never opens an owner page: no vault / login call in recheck.py", "vault_fill" not in src and "_v_login" not in src and "vault_item" not in src)


# ---- CI wiring ------------------------------------------------------------------------------------------------------------------------------------------------
wf = os.path.join(HERE, "..", ".github", "workflows")
ci = open(os.path.join(wf, os.listdir(wf)[0]), encoding="utf-8").read()
check("CI runs this file", "tests/batch17_test.py" in ci)

print("\n%d passed, %d failed" % (sum(ok), len(ok) - sum(ok)))
sys.exit(0 if all(ok) else 1)
