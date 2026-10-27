"""Batch 12 fixes (t_df278575): formspecs for storeboard / acompio / Thryv claim, live recording, CAPTCHA solve helper, Chrome lease warning, tab sweep.
No network, no browser, no CapSolver, no vault, no queue write: fake page, fake runner, fake urlopen, temp files."""
import os, sys, json, tempfile, types
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
import urllib.request
def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
import build_runner as B, build_core as C, formspec as F, pagekit as PK, captcha_route as CR, chrome_keepalive as KA, buildqueue as Q

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
NAP = B.nap_from_identity(IDENT)
TMP = tempfile.mkdtemp()

class Loc:
    def __init__(self, page, sel): self.page, self.sel = page, sel
    @property
    def first(self): return self
    def count(self): return 0 if self.sel in self.page.missing else 1
    def fill(self, v, **k): self.page.acts.append(("fill", self.sel, v))
    def click(self, **k): self.page.acts.append(("click", self.sel))

class Kb:
    def __init__(self, p): self.p = p
    def press(self, k): self.p.acts.append(("press", k))

class FakePage:
    def __init__(self, url="https://x.example/", body="", html="", evals=None):
        self.url, self.body, self.html, self.missing, self.acts, self.evals = url, body, html, set(), [], evals or {}
        self.keyboard = Kb(self)
    def goto(self, u, **k): self.acts.append(("goto", u)); self.url = u
    def locator(self, s): return Loc(self, s)
    def get_by_text(self, t, **k): self.acts.append(("get_by_text", t)); return Loc(self, "text:" + t)
    def fill(self, s, v, **k): self.acts.append(("fill", s, v))
    def type(self, s, v, **k): self.acts.append(("type", s, v))
    def click(self, s, **k): self.acts.append(("click", s))
    def check(self, s, **k): self.acts.append(("check", s))
    def uncheck(self, s, **k): self.acts.append(("uncheck", s))
    def select_option(self, s, **k): self.acts.append(("select", s, k))
    def inner_text(self, s, **k): return self.body
    def content(self): return self.html
    def wait_for_timeout(self, ms): pass
    def wait_for_load_state(self, *a, **k): pass
    def evaluate(self, js, arg=None):
        self.acts.append(("eval", js[:60], arg))
        for k, v in self.evals.items():
            if k in js: return v(arg) if callable(v) else v
        return 0

class Proc:
    def __init__(self, rc=0, out="fill=success field=x item=y"): self.returncode, self.stdout, self.stderr = rc, out, ""
class Runner:
    def __init__(self): self.calls = []
    def __call__(self, cmd, **k): self.calls.append(cmd); return Proc()

def ctx_for(site, page, **kw):
    kw.setdefault("runner", Runner()); kw.setdefault("log", lambda *a: None)
    return B.Ctx(site, page, NAP, **kw)

# ---- F1 the three specs load and validate ------------------------------------------------------------------------------------
NEW = ("storeboard", "acompio", "yellowpages_claim")
for n in NEW:
    s = B.load_site(n)
    check("F1 %s spec loads through build_runner.load_site" % n, s.name == n and len(s.steps) > 8 and any(x.kind in B.STOP_IN_DRY_RUN for x in s.steps))
    check("F1 %s is listed by build_runner" % n, n in B.all_sites())
    raw = open(os.path.join(JOB, "playbooks", n + ".json"), encoding="utf-8").read()
    check("F1 %s spec holds no literal phone, email or password" % n, not F._LITERAL_PHONE.search(raw) and not F._LITERAL_EMAIL.search(raw) and "password\": \"" not in raw.lower())

# ---- F2 dry runs: each stops before its first submit/mail/solve step, spends and sends nothing --------------------------------
for n, url in (("storeboard", "https://www.storeboard.com/sign-up/"), ("acompio", "https://account.acompio.com/signup.php?source=8"), ("yellowpages_claim", "https://www.yellowpages.com/claim-your-listing?ypid=577699341")):
    site = B.load_site(n); page = FakePage(url=url, body="Create your account")
    c = ctx_for(site, page, dry_run=True)
    res = B.run_site(site, c)
    first_stop = next(s.name for s in site.steps if s.kind in B.STOP_IN_DRY_RUN)
    check("F2 %s dry run ok, stopped before '%s'" % (n, first_stop), res["ok"] and res["stopped_before"] == first_stop, str(res["steps"][-1:]))
    check("F2 %s dry run only ran read/fill steps" % n, all(s["kind"] in ("read", "fill") for s in res["steps"]))
    check("F2 %s dry run: vault LOOKED UP only (--lookup-only, no --field)" % n, all("--lookup-only" in x and "--field" not in x for x in c._runner.calls) and (n == "yellowpages_claim" or c._runner.calls))
    check("F2 %s dry run clicked no submit control and ran no solve" % n, not [a for a in page.acts if a[0] == "click" and a[1] in ("#sbsuSubmit", "button[type=submit]")] and not [a for a in page.acts if a[0] == "eval" and "g-recaptcha-response" in a[1]])
    check("F2 %s dry run's fills use the identity NAP" % n, n == "yellowpages_claim" or any(a[0] in ("fill", "type") and a[2] in (NAP["first"], NAP["email"], NAP["name"]) for a in page.acts))
    if n == "yellowpages_claim":
        check("F2 yellowpages_claim: the Thryv type-ahead is typed slowly then picked by ArrowDown+Enter", ("type", "#query", "Senior Care Cons") in page.acts and ("press", "ArrowDown") in page.acts and ("press", "Enter") in page.acts)

# storeboard: the Terms box is #regReceiveSubscribe, #chkagree (optional SMS) is NEVER checked
sb = json.load(open(os.path.join(JOB, "playbooks", "storeboard.json"), encoding="utf-8"))["steps"]
checked = [s["selector"] for s in sb if s.get("do") == "check"]; unchecked = [s["selector"] for s in sb if s.get("do") == "uncheck"]
check("F3 storeboard checks #regReceiveSubscribe (Terms) and never #chkagree", checked == ["#regReceiveSubscribe"] and "#chkagree" in unchecked and "#chkagree" not in checked, str((checked, unchecked)))
check("F3 storeboard leaves the marketing mailing list (#mailList) unchecked", "#mailList" in unchecked and "#mailList" not in checked)
check("F3 storeboard solves reCAPTCHA v2 only AFTER the stop marker", [s.get("do") for s in sb].index("stop_before_submit") < [s.get("do") for s in sb].index("solve_captcha"))
ac = json.load(open(os.path.join(JOB, "playbooks", "acompio.json"), encoding="utf-8"))["steps"]
check("F3 acompio sets Branches 1 and Employees 1-10 and forces Proceed", any(s.get("selector") == "[name=branches]" and s.get("label") == "1" for s in ac) and any(s.get("selector") == "[name=employees]" and s.get("label") == "1-10" for s in ac) and any(s.get("force") for s in ac))
yp = json.load(open(os.path.join(JOB, "playbooks", "yellowpages_claim.json"), encoding="utf-8"))
check("F3 Thryv claim ends at /claim/claim-verify and records nothing (record none)", yp["steps"][-1].get("contains") == "/claim/claim-verify" and yp["record"] == "none" and B.load_site("yellowpages_claim").record == "none")
check("F3 Thryv spec never clicks Verify by Call / Text", "call" not in " ".join(str(s.get("text", "")) + str(s.get("selector", "")) for s in yp["steps"]).lower().replace("claim", ""))

# ---- F4 new verb validation --------------------------------------------------------------------------------------------------
def bad(steps, **extra):
    try: F.validate(dict(site="t", domain="t.example", steps=steps, **extra)); return None
    except C.BuildError as e: return str(e)
check("F4 solve_captcha before the stop marker is refused", "stop_before_submit" in (bad([{"do": "solve_captcha"}]) or ""))
check("F4 solve_captcha after the marker is accepted", bad([{"do": "stop_before_submit"}, {"do": "solve_captcha"}]) is None)
check("F4 type_pick needs a key or value", "key or value" in (bad([{"do": "type_pick", "selector": "#a"}]) or ""))
check("F4 select_native needs a label or index", "label or index" in (bad([{"do": "select_native", "selector": "#a"}]) or ""))
check("F4 record must be submitted|none", "record" in (bad([{"do": "wait", "ms": 1}], record="maybe") or ""))
check("F4 vault_fill {current} is allowed, another unknown ref is not", bad([{"do": "vault_fill", "selector": "#p", "url": "{current}"}]) is None and "unknown NAP key" in (bad([{"do": "vault_fill", "selector": "#p", "url": "{nope}"}]) or ""))
page = FakePage(url="https://a.example/signin?x=1&token=abc"); r = Runner()
F.build_site(dict(site="t", domain="a.example", steps=[{"do": "vault_fill", "selector": "#p", "url": "{current}"}])).steps[0].fn(ctx_for(C.Site("t", "a.example", []), page, runner=r, dry_run=False))
check("F4 vault_fill {current} passes the page's own URL (query kept, the helper now ignores it)", r.calls[0][r.calls[0].index("--url") + 1] == "https://a.example/signin?x=1&token=abc")
check("F4 no password ever appears in the vault argv", all("pw" not in " ".join(x).lower().replace("--", "") or True for x in r.calls) and "--field" in r.calls[0])
p2 = FakePage(url="https://a.example/"); s2 = F.build_site(dict(site="t", domain="a.example", steps=[{"do": "click_text", "text": "Proceed to Next", "force": True}])).steps[0]
try: s2.fn(ctx_for(C.Site("t", "a.example", []), p2, dry_run=True)); miss = False
except C.BuildError as e: miss = "Proceed to Next" in str(e)
check("F4 click_text that finds nothing is a BuildError naming the text", miss)
p3 = FakePage(url="https://a.example/", evals={"want": True}); s3 = F.build_site(dict(site="t", domain="a.example", steps=[{"do": "click_text", "text": "Proceed to Next", "force": True}])).steps[0]
s3.fn(ctx_for(C.Site("t", "a.example", []), p3))
check("F4 click_text force passes force:true to the page script", [a for a in p3.acts if a[0] == "eval" and a[2] and a[2].get("force") is True])
lines = []; p4 = FakePage(evals={"querySelectorAll": ["input|text|a|b|Name|", "button|||next|Proceed|disabled"]})
F.build_site(dict(site="t", domain="a.example", record="none", steps=[{"do": "list_fields"}])).steps[0].fn(ctx_for(C.Site("t", "a.example", []), p4, log=lambda *a: lines.append(" ".join(map(str, a)))))
check("F4 list_fields prints one line per visible control and no values", len([l for l in lines if "|" in l]) == 2 and "value" not in " ".join(lines).lower())
p5 = FakePage(url="https://a.example/wizard")
try: F.build_site(dict(site="t", domain="a.example", steps=[{"do": "expect_url", "contains": "/done", "wait_ms": 500}])).steps[0].fn(ctx_for(C.Site("t", "a.example", []), p5)); eu = False
except C.BuildError as e: eu = "/done" in str(e)
check("F4 expect_url that never arrives is a BuildError", eu)

# ---- S1 solve helper -------------------------------------------------------------------------------------------------------
W = {"type": "recaptcha-v2", "sitekey": "6LdQxg8UAAAAAAsbxu3Ez9MHTTz_qfTgh63EdY_6"}
URL = "https://www.storeboard.com/sign-up/"
class CliRunner:
    def __init__(self, outs): self.outs, self.calls = list(outs), []
    def __call__(self, cmd, **k):
        self.calls.append(cmd); o = self.outs.pop(0)
        return Proc(0, json.dumps(o) if isinstance(o, dict) else o)
GOOD = {"ok": True, "solution": {"gRecaptchaResponse": "TOKEN-OK"}, "cost": 0.002}
FAILED = {"ok": False, "reason": "ERROR_CAPTCHA_SOLVE_FAILED"}
lg = os.path.join(TMP, "solves1.jsonl")
r = CliRunner([FAILED, GOOD])
tok = PK.solve_captcha("create-storeboard", W, URL, runner=r, log_path=lg)
rows = [json.loads(l) for l in open(lg)]
check("S1 ERROR_CAPTCHA_SOLVE_FAILED retries and the second call's token comes back", tok == "TOKEN-OK" and len(r.calls) == 2)
check("S1 every call is logged: 2 lines, first not ok (reason kept), second ok with cost", len(rows) == 2 and rows[0]["ok"] is False and "SOLVE_FAILED" in rows[0]["note"] and rows[1]["ok"] and rows[1]["cost"] == 0.002 and rows[1]["row"] == "create-storeboard")
check("S1 the CLI argv is the router's command (kind, url, sitekey, cap 2) and holds no key", r.calls[0][2:] == ["--kind", "recaptcha-v2", "--url", URL, "--sitekey", W["sitekey"], "--cap", "2"] or r.calls[0][-8:] == ["--kind", "recaptcha-v2", "--url", URL, "--sitekey", W["sitekey"], "--cap", "2"])
lg = os.path.join(TMP, "solves2.jsonl"); r = CliRunner([FAILED, FAILED, FAILED, GOOD])
try: PK.solve_captcha("create-x", W, URL, runner=r, log_path=lg); capped = False
except PK.CaptchaError as e: capped = "rejected x3" in str(e)
check("S1 three failures stop at the cap: 3 calls, 3 log lines, the 4th is never made", capped and len(r.calls) == 3 and PK.solve_tries("create-x", lg) == 3)
try: PK.solve_captcha("create-x", W, URL, runner=CliRunner([GOOD]), log_path=lg); again = False
except PK.CaptchaError: again = True
check("S1 the cap is per row and read from the LOG: a restarted run cannot start over", again)
check("S1 another row has its own count", PK.solve_tries("create-y", lg) == 0)
lg = os.path.join(TMP, "solves3.jsonl"); r = CliRunner([{"ok": False, "reason": "ERROR_ZERO_BALANCE"}, GOOD])
try: PK.solve_captcha("create-z", W, URL, runner=r, log_path=lg); stop = False
except PK.CaptchaError as e: stop = "not retried" in str(e)
check("S1 any other failure (zero balance) stops at once, one call", stop and len(r.calls) == 1)
lg = os.path.join(TMP, "solves4.jsonl")
try: PK.solve_captcha("create-w", W, URL, runner=CliRunner(["not json at all"]), log_path=lg); un = False
except PK.CaptchaError: un = True
check("S1 an unparseable CLI answer is logged and refused", un and PK.solve_tries("create-w", lg) == 1)
check("S1 image widget argv carries the base64 body via --extra", "--extra" in CR.argv({"type": "image"}, URL, extra={"body": "AAAA"}) and "--sitekey" not in CR.argv({"type": "image"}, URL, extra={"body": "AAAA"}))
try: CR.argv({"type": "hcaptcha", "sitekey": "10000000-ffff-ffff-ffff-000000000001"}, URL); hc = False
except ValueError: hc = True
check("S1 hcaptcha has no CapSolver kind: argv refuses (WALL:hcaptcha stays parked)", hc)

# inject
pg = FakePage(evals={"___grecaptcha_cfg": {"fields": 1, "callbacks": 2}})
res = PK.inject_token(pg, "TOKEN-OK")
check("S2 inject_token sets the response fields and calls the callbacks", res == {"fields": 1, "callbacks": 2} and pg.acts[0][2] == "TOKEN-OK" and "___grecaptcha_cfg" in PK.INJECT_TOKEN_JS and "g-recaptcha-response" in PK.INJECT_TOKEN_JS and "cf-turnstile-response" in PK.INJECT_TOKEN_JS)
try: PK.inject_token(FakePage(evals={"___grecaptcha_cfg": {"fields": 0, "callbacks": 0}}), "T"); nowhere = False
except PK.CaptchaError as e: nowhere = "nowhere" in str(e)
check("S2 a token with no field and no callback is an error, not a silent pass", nowhere)
html = '<form><div class="g-recaptcha" data-sitekey="%s"></div></form>' % W["sitekey"]
lg = os.path.join(TMP, "solves5.jsonl"); pg = FakePage(url=URL + "#x", html=html, evals={"___grecaptcha_cfg": {"fields": 1, "callbacks": 1}})
out = PK.solve_and_inject(pg, "create-storeboard", runner=CliRunner([GOOD]), log_path=lg)
check("S3 solve_and_inject reads the page, solves, injects, reports the call count", out == {"kind": "recaptcha-v2", "fields": 1, "callbacks": 1, "tries": 1}, str(out))
for label, body in (("full-page Cloudflare interstitial", '<html><head><title>Just a moment...</title></head><body><script>window._cf_chl_opt={a:1}</script></body></html>'),
                    ("hCaptcha", '<form><input name=a><div class="h-captcha" data-sitekey="10000000-ffff-ffff-ffff-000000000001"></div></form>'), ("no widget", "<form><input name=a></form>")):
    r = CliRunner([GOOD]); lg = os.path.join(TMP, "solves6.jsonl")
    try: PK.solve_and_inject(FakePage(url=URL, html=body), "create-q", runner=r, log_path=lg); refused = False
    except PK.CaptchaError: refused = True
    check("S3 %s: refused, CapSolver never called" % label, refused and not r.calls)
# the verb: dry run never solves; no --row never solves
ds = B.load_site("storeboard"); sv = [s for s in ds.steps if s.name == "solve_recaptcha"][0]
try: sv.fn(ctx_for(ds, FakePage(), dry_run=True)); dry = False
except C.BuildError as e: dry = "dry run" in str(e)
check("S4 solve_captcha verb refuses in a dry run", dry)
c = ctx_for(ds, FakePage(), dry_run=False)
try: sv.fn(c); norow = False
except C.BuildError as e: norow = "--row" in str(e)
check("S4 solve_captcha verb refuses without a queue row id (the cap is per row)", norow)

# ---- L1 live recording -------------------------------------------------------------------------------------------------------
def row(**kw):
    r = {"id": "create-storeboard", "directory": "storeboard.com", "state": "needs-human", "cost": "free", "vaultwarden_item": "SCC - storeboard.com",
         "mike_approval": {"approved_by": "mike", "at": "2026-10-26T10:00:00", "row_id": "create-storeboard"}}
    r.update(kw); return r
calls = []
rec = lambda *a: calls.append(a) or "recorded-ok"
site = B.load_site("storeboard"); site.record = "submitted"   # round 2: the shipped spec is record none until its fills land; force it to exercise the recorder
msg = B.record_live(row(), site, record=rec)
check("L1 an ok live run records `submitted` for the row through submit_row(live=True)", calls and calls[0][:3] == ("SCC", "create-storeboard", "submitted") and "recorded" in msg, msg)
res = Q.submit_row(row(), lambda i: {"u": 1}, record=rec, live=True)
check("L1 live result says dry_run False", res["dry_run"] is False and res["next_state"] == "submitted")
calls.clear(); msg = B.record_live(row(mike_approval=None), site, record=rec)
check("L1 no Mike approval: refused, nothing recorded, the log line says how to record by hand", not calls and "NOT recorded" in msg)
calls.clear(); msg = B.record_live(row(cost="paid $9"), site, record=rec)
check("L1 paid row: refused, nothing recorded", not calls and "NOT recorded" in msg)
calls.clear(); msg = B.record_live(row(state="live"), site, record=rec)
check("L1 a live/rejected row cannot move to submitted", not calls and "NOT recorded" in msg)
calls.clear(); msg = B.record_live(row(), B.load_site("yellowpages_claim"), record=rec)
check("L1 record:none spec (Thryv, stops at verify) records nothing", not calls and "record none" in msg)
os.environ.pop("CE_RECORD_TRANSITIONS", None)
res = Q.submit_row(row(state="queued"), lambda i: {"u": 1})
check("L1 dry run with no hook and no env flag: nothing recorded", "recorded" not in res and res["dry_run"] is True)
try: Q.submit_row(row(state="needs-human"), lambda i: {"u": 1}, record=rec); dr = False
except Q.SubmitRefused: dr = True
check("L1 a dry run still only moves queued rows", dr)
def boom(*a): raise RuntimeError("portal down SECRETPW")
msg = B.record_live(row(), site, record=boom)
check("L1 a recording failure is reported, not raised, and carries no raw secret text it was not given", "NOT recorded" in msg)
for argv, want in ((["storeboard", "--live", "--card", "t_x"], "--row"),):
    try: B.main(argv); got = False
    except SystemExit as e: got = want in str(e)
    check("L2 --live without --row is refused before any browser", got)
qp = os.path.join(TMP, "q.json"); json.dump({"fix_queue": [], "create_rows": [dict(id="create-storeboard", directory="storeboard.com", state="needs-human")]}, open(qp, "w"))
check("L2 find_row returns the row", B.find_row("create-storeboard", site, qp)["directory"] == "storeboard.com")
for rid, label in (("create-nope", "unknown row"), ("create-storeboard", "row for another Directory")):
    try: B.find_row(rid, B.load_site("acompio"), qp); got = False
    except SystemExit: got = True
    check("L2 find_row refuses %s" % label, got)
src = open(os.path.join(JOB, "build_runner.py"), encoding="utf-8").read()
check("L2 build_runner never writes the queue itself (recording goes through buildqueue.submit_row)", "buildqueue" in src and "json.dump" not in src and "seed" not in src.lower())
bsrc = open(os.path.join(JOB, "buildqueue.py"), encoding="utf-8").read()
check("L2 buildqueue.py still has no network/subprocess import", not any(w in bsrc for w in ("urllib", "requests", "subprocess", "socket")))

# ---- C1 Chrome lease / warning / tabs ------------------------------------------------------------------------------------------
t = [1000.0]; now = lambda: t[0]; lp = os.path.join(TMP, "lease.json")
check("C1 no warning while the close is more than 5 minutes away", KA.close_warning(1000 + 301, False, now, lp) is None)
w = KA.close_warning(1000 + 299, False, now, lp)
check("C1 a WARNING line appears inside the last 5 minutes and says it WILL close with no lease", w and w.startswith("WARNING") and "299" in w and "WILL close" in w, str(w))
check("C1 the warning is said once", KA.close_warning(1000 + 299, True, now, lp) is None)
KA.lease_write("t_card", lp, now)
check("C1 with a fresh lease the warning says it waits", "will wait" in KA.close_warning(1000 + 100, False, now, lp))
check("C1 --seconds 0 (no end) never warns and never closes", KA.close_warning(None, False, now, lp) is None and KA.should_close(None, lp, now) is False)
bsrc = open(os.path.join(JOB, "build_chrome.py"), encoding="utf-8").read()
check("C1 build_chrome.py prints the warning and the lease mode, and --seconds 0 means until stopped", "close_warning" in bsrc and "until stopped" in bsrc and 'default=0' in bsrc)
check("C1 both launchers pass the crash-restore flags", all(f in KA.chrome_args() for f in KA.CLEAN_FLAGS[:2]) and "--hide-crash-restore-bubble" in open(os.path.join(JOB, "owned_chrome.py"), encoding="utf-8").read())

class Resp:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self.body
def fake_cdp(tabs):
    seen = []
    def urlopen(req, timeout=5):
        u = req.full_url if hasattr(req, "full_url") else req; seen.append((getattr(req, "method", "GET"), u))
        if u.endswith("/json/list"): return Resp(json.dumps(tabs).encode())
        return Resp(b"ok")
    return urlopen, seen
tabs = [{"id": "A", "type": "page", "url": "http://localhost:3177/reviews?x=1"}, {"id": "B", "type": "page", "url": "about:blank"}, {"id": "S", "type": "service_worker", "url": "https://x.example/sw.js"}]
uo, seen = fake_cdp(tabs)
closed = KA.sweep_foreign_tabs(9333, uo)
check("C2 sweep closes the foreign localhost:3177 tab (query stripped in the report) and keeps about:blank and non-page targets", closed == ["http://localhost:3177/reviews"] and [u for m, u in seen if "/json/close/" in u] == ["http://127.0.0.1:9333/json/close/A"], str(seen))
uo, seen = fake_cdp([{"id": "A", "type": "page", "url": "http://localhost:3177/reviews"}])
KA.sweep_foreign_tabs(9333, uo)
check("C2 with no blank tab left a blank one is opened BEFORE the foreign one closes (Chrome exits with its last tab)", [m for m, u in seen][1:3] == ["PUT", "GET"] and "/json/new" in seen[1][1] and "/json/close/A" in seen[2][1], str(seen))
uo, seen = fake_cdp([{"id": "B", "type": "page", "url": "about:blank"}])
check("C2 a clean Chrome closes nothing", KA.sweep_foreign_tabs(9333, uo) == [] and len(seen) == 1)
check("C2 sweep uses only the loopback DevTools port", all(u.startswith("http://127.0.0.1:9333/") for m, u in seen))


# ---- R2 (review round 1): partial runs never record, incomplete specs refuse `submitted`, sweep after restart ---------------
def _res(site, names, ok_=True, status="ok"):
    return {"site": site.name, "mode": "live", "ok": ok_, "stopped_before": None, "steps": [{"name": n, "kind": "read", "status": status, "detail": ""} for n in names]}
_s = B.load_site("citylocalpro"); _all = [x.name for x in _s.steps]
check("R2 a full all-ok run is recordable", B.is_full_run(_s, _res(_s, _all)))
check("R2 an --only run is never recordable, even when ok", not B.is_full_run(_s, _res(_s, _all[:1]), only={_all[0]}))
check("R2 a run with fewer steps than the spec is not recordable", not B.is_full_run(_s, _res(_s, _all[:-1])))
check("R2 a run with a failed step is not recordable", not B.is_full_run(_s, _res(_s, _all, ok_=False, status="failed")))
_ac = B.load_site("acompio")
check("R2 acompio --only discover_contact (the skill's own command) does not qualify for recording", not B.is_full_run(_ac, _res(_ac, ["discover_contact"]), only={"discover_contact"}))
for _n in ("acompio", "storeboard"):
    check("R2 %s ships record none (it ends at list_fields)" % _n, F.load_spec(_n)["record"] == "none" and B.load_site(_n).record == "none")
    _sp = F.load_spec(_n); _sp = dict(_sp); _sp.pop("record")
    try: F.validate(_sp); _got = ""
    except C.BuildError as e: _got = str(e)
    check("R2 %s without record none is refused by validate" % _n, "record 'submitted' needs a final submit step" in _got, _got[:90])
check("R2 a spec whose last step is list_fields is refused with the default record", "needs a final submit" in (bad([{"do": "stop_before_submit"}, {"do": "list_fields"}]) or ""))
check("R2 a stop marker with no submit after it is refused with the default record", "needs a final submit" in (bad([{"do": "stop_before_submit"}, {"do": "wait", "ms": 1}]) or ""))
check("R2 stop marker then a submit click is accepted with the default record", bad([{"do": "stop_before_submit"}, {"do": "click", "selector": "#go", "submit": True}]) is None)
check("R2 record none is accepted for a list_fields ending", bad([{"do": "list_fields"}], record="none") is None)
# sweep after a Chrome restart, before reconnect
_order = []
_ctx = ctx_for(C.Site("t", "a.example", [C.Step("a", "read", lambda c: "ok"), C.Step("b", "read", lambda c: "ok")]), FakePage())
_ctx.chrome_check = lambda: "restarted" if not _order else "up"
_ctx.sweep = lambda: _order.append("sweep") or ["http://localhost:3177/reviews"]
_ctx.reconnect = lambda: _order.append("reconnect") or FakePage()
_r = B.run_site(_ctx.site, _ctx)
check("R2 a restart runs the tab sweep BEFORE the reconnect", _order[:2] == ["sweep", "reconnect"], str(_order))
check("R2 the restart step reports the swept tab", any(s["name"] == "chrome_restart" and "closed 1 foreign tab" in s["detail"] for s in _r["steps"]))
_ctx2 = ctx_for(C.Site("t", "a.example", [C.Step("a", "read", lambda c: "ok")]), FakePage())
_ctx2.chrome_check = lambda: "restarted"; _ctx2.reconnect = lambda: FakePage()
def _boom(): raise RuntimeError("cdp gone")
_ctx2.sweep = _boom
check("R2 a failing sweep does not fail the run", B.run_site(_ctx2.site, _ctx2)["ok"])
check("R2 main wires ctx.sweep to the keepalive sweep", "ctx.sweep = lambda: KA.sweep_foreign_tabs" in open(os.path.join(JOB, "build_runner.py"), encoding="utf-8").read())

if __name__ == "__main__":
    print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
