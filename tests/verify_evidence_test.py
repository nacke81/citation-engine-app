"""Verify Now page evidence, signed-out pre-flight and send_unconfirmed tests (t_761c9558). A mock page stands in for the tenant's Chrome: no network,
no Chrome, no hermes, no real send, and no CAPTCHA is ever attempted. Run: python tests/verify_evidence_test.py (CI). Exit 1 on any failure."""
import contextlib, io, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ["CE_LOGS"] = os.path.join(TMP, "logs")
os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json")
os.environ["CE_VERIFY_LOCKS"] = os.path.join(TMP, "locks")
os.environ["CE_VERIFY_DIRECTORIES"] = os.path.join(HERE, "verify_directories_fixture.json")
os.environ["CE_NO_CARDS"] = "1"
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json"); os.environ["CE_RUNS"] = tempfile.mkdtemp()
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
import verify_fakes as F
os.environ["CE_PORTAL_ENV"] = os.path.join(HERE, "no-such-portal.env")   # fail closed, never the prod portal
import verify_bridge as B
import verify_send as S
import verify_step as ST
import verify_scoreboard as SB
import verify_evidence as VE
import playbook as PB

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else ""), flush=True)

def quiet(fn, *a, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        r = fn(*a, **kw)
    return r, out.getvalue() + err.getvalue()

AGENT_DIR = "agentdir.example"
MASK = "(502) ***-0101"
PNG = b"\x89PNG\r\n\x1a\nmock"
def page(url="https://www.agentdir.example/pro/setup", text="Jobs Messages Performance Services Profile", password=False, frames=(), code_input=False, png=PNG):
    return {"url": url, "text": text, "password": password, "frames": list(frames), "png": png, "on_domain": True, "code_input": code_input}

SIGNED_IN = page()
SIGNED_OUT = page(url="https://www.agentdir.example/login?next=%2Fpro", text="Log in to your account\nEmail\nPassword", password=True)
CAPTCHA = page(url="https://www.agentdir.example/login", text="Verify you are human\nPress and hold the button", password=True)
LOADING = page(text="We\u2019ll text you a verification code. Carrier rates may apply.\n\nTerms apply.\n\nLoading\n\nBy clicking Continue, you agree to the Terms of Use")
CODEBOX = page(text="Enter the verification code we texted you", code_input=True)

def fresh():
    SB_DIR = os.path.join(os.environ["CE_LOGS"])
    for sub in ("verify-stages", "verify-evidence"):
        d = os.path.join(SB_DIR, sub)
        if os.path.isdir(d):
            for r, _ds, fs in os.walk(d):
                for f in fs: os.remove(os.path.join(r, f))
    if os.path.exists(SB.path()): os.remove(SB.path())

def use(p):
    VE.READER = (lambda cdp, doms: p) if not callable(p) else p

def mk(status="starting", age_s=5, agent=True):
    if agent: SB.stamp(F.RID, "agent_start_at", F.NOW)   # the agent started: the end capture applies
    return F.StrictPortal(requests=[F.request(status=status, age_s=age_s)], verifications=[F.verification(directory=AGENT_DIR)])

def rows():
    return [json.loads(l) for l in open(SB.path(), encoding="utf-8")] if os.path.exists(SB.path()) else []

def stage():
    f = SB._stage_file(F.RID)
    return json.load(open(f, encoding="utf-8")) if os.path.exists(f) else {}

def evfiles():
    d = os.path.join(VE.evidence_root(), F.RID)
    return sorted(os.listdir(d)) if os.path.isdir(d) else []

class Clock:
    def __init__(self): self.t = 1000.0
    def now(self): return self.t
    def sleep(self, s): self.t += s

# ---- 1 classify (pure) ----------------------------------------------------------------------------------------------------------------------
check("1a signed-in page", VE.classify(SIGNED_IN) == "signed_in")
check("1b login URL / password box / log-in text = signed out", VE.classify(SIGNED_OUT) == "signed_out" and VE.classify(page(url="https://x.example/sign-in")) == "signed_out"
      and VE.classify(page(text="Log in to your account")) == "signed_out" and VE.classify(page(password=True)) == "signed_out")
check("1c a CAPTCHA page is captcha, signup or not", VE.classify(CAPTCHA) == "captcha" and VE.classify(CAPTCHA, True) == "captcha")
check("1d a challenge frame is a CAPTCHA; the invisible recaptcha badge frame and 'protected by reCAPTCHA' text are not",
      VE.classify(page(frames=["https://www.google.com/recaptcha/api2/bframe?hl=en"])) == "captcha"
      and VE.classify(page(frames=["https://www.google.com/recaptcha/api2/anchor?ar=1"], text="Jobs Messages\nThis site is protected by reCAPTCHA and the Google Privacy Policy.")) == "signed_in")
check("1e a signup Directory on its signup page is not 'signed out'", VE.classify(page(url="https://x.example/signup", password=True, text="Create your account"), True) == "signed_in")
check("1f unreadable page decides nothing", VE.classify(None) is None)
check("1g redaction: email and 6+ digit runs go, a 4-digit year and a masked phone stay", VE.redact("a@b.example 123456 2026 (502) ***-0101") == "[x] [x] 2026 (502) ***-0101", VE.redact("a@b.example 123456 2026 (502) ***-0101"))

# ---- 2 pre-flight at sign-in: signed out / CAPTCHA stop at once -----------------------------------------------------------------------------
fresh(); use(SIGNED_OUT); p = mk(); rpc = B.VerifyRpc(p)
r, _t = quiet(ST.step_stage, F.RID, "signed_in", p, F.NOW, rpc)
row = rows()[-1] if rows() else {}
check("2a signed-out page: `stage signed_in` is refused (5)", r == ST.REFUSED, r)
check("2b the request ends failed with the portal code signin_failed (client sees a sign-in problem, not a retry-tomorrow)", p.requests[F.RID]["status"] == "failed" and p.requests[F.RID].get("fail_code") == "signin_failed", p.requests[F.RID])
check("2c signed_in_at stays null (the stamp needs a confirmed signed-in page)", row.get("signed_in_at") is None and "signed_in_at" in row, row)
check("2d the scoreboard row says failed:session_signed_out and fence_skip true (the platform fence must not count it)", row.get("outcome") == "failed:session_signed_out" and row.get("fence_skip") is True, row)
check("2e no send was recorded", not any(c[1] == "rpc/mark_code_sent" for c in p.calls) and row.get("send_clicked_at") is None)
ev = (row.get("evidence") or {}).get("signin") or {}
check("2f the row links a sign-in screenshot and page text that exist on disk", ev.get("png", "").endswith(".png") and ev.get("txt", "").endswith(".txt")
      and os.path.exists(os.path.join(os.environ["CE_LOGS"], ev.get("png", "x"))) and os.path.exists(os.path.join(os.environ["CE_LOGS"], ev.get("txt", "x"))), ev)
txt = open(os.path.join(os.environ["CE_LOGS"], ev["txt"]), encoding="utf-8").read() if ev else ""
check("2g the saved text shows what the page said, query string dropped", "Log in to your account" in txt and "next=" not in txt, txt[:120])
check("2h the end-of-run page is saved too", "end" in (row.get("evidence") or {}), sorted((row.get("evidence") or {})))

fresh(); use(CAPTCHA); p = mk(); r, _t = quiet(ST.step_stage, F.RID, "signed_in", p, F.NOW, B.VerifyRpc(p)); row = rows()[-1]
check("2i CAPTCHA at sign-in: refused, failed:captcha, fence_skip, signed_in_at null, nothing clicked", r == ST.REFUSED and row["outcome"] == "failed:captcha" and row["fence_skip"] is True and row["signed_in_at"] is None, row)

# ---- 3 pre-flight passes: signed in, evidence saved, stamp set ------------------------------------------------------------------------------
fresh(); use(SIGNED_IN); p = mk(); r, _t = quiet(ST.step_stage, F.RID, "signed_in", p, F.NOW, B.VerifyRpc(p))
st = stage()
check("3a signed-in page: ok, signed_in_at stamped, request still starting", r == 0 and st.get("signed_in_at") and p.requests[F.RID]["status"] == "starting", (r, st))
check("3b the sign-in capture is on disk (png + txt)", [f for f in evfiles() if f.endswith("signin.png")] and [f for f in evfiles() if f.endswith("signin.txt")], evfiles())

fresh(); use(None); p = mk(); r, _t = quiet(ST.step_stage, F.RID, "signed_in", p, F.NOW, B.VerifyRpc(p)); st = stage()
check("3c page unreadable: no stop, but signed_in_at is NOT stamped", r == 0 and not st.get("signed_in_at") and p.requests[F.RID]["status"] == "starting", (r, st))
check("3d an unreadable page still leaves a text file saying so (a missing file is not evidence)", any(f.endswith("signin.txt") for f in evfiles()) and "could not be read" in open(os.path.join(VE.evidence_root(), F.RID, [f for f in evfiles() if f.endswith("signin.txt")][0]), encoding="utf-8").read())

fresh(); use(SIGNED_IN); p = mk(); quiet(ST.step_stage, F.RID, "ready", p, F.NOW)
check("3e `stage --name ready` does not read the page or stamp signed_in_at", not stage().get("signed_in_at") and evfiles() == [])

# ---- 4 arm: the same stop right before the click; arm never stamps signed_in_at -------------------------------------------------------------
fresh(); use(SIGNED_OUT); p = mk(); B.mark_vault_ok(F.RID); r, _t = quiet(ST.step_arm, F.RID, p, F.NOW, rpc=B.VerifyRpc(p))
check("4a arm on a signed-out page: refused, request failed, failed:session_signed_out", r == ST.REFUSED and p.requests[F.RID]["status"] == "failed" and rows()[-1]["outcome"] == "failed:session_signed_out", (r, rows()))
fresh(); use(SIGNED_IN); p = mk(); r, _t = quiet(ST.step_arm, F.RID, p, F.NOW, rpc=B.VerifyRpc(p))
check("4b arm on a signed-in page: ok, signed_in_at not stamped by arm", r == 0 and not stage().get("signed_in_at") and p.requests[F.RID]["status"] == "starting", (r, stage()))
fresh(); use(CAPTCHA); p = mk(); r, _t = quiet(ST.step_arm, F.RID, p, F.NOW, rpc=B.VerifyRpc(p))
check("4c arm on a CAPTCHA: refused, failed:captcha", r == ST.REFUSED and rows()[-1]["outcome"] == "failed:captcha", rows())

# ---- 5 watch: after the click ----------------------------------------------------------------------------------------------------------------
fresh(); use(CODEBOX); p = mk(); c = Clock(); r, _t = quiet(ST.step_watch, F.RID, p, B.VerifyRpc(p), F.NOW, c.sleep, c.now)
st = stage()
check("5a code box shows: exit 0, send_clicked_at stamped (a CDP click gets the stamp), after_send evidence saved, request untouched",
      r == 0 and st.get("send_clicked_at") and "after_send" in (st.get("evidence") or {}) and p.requests[F.RID]["status"] == "starting", (r, st))

fresh(); use(LOADING); p = mk(); c = Clock(); r, t = quiet(ST.step_watch, F.RID, p, B.VerifyRpc(p), F.NOW, c.sleep, c.now); row = rows()[-1] if rows() else {}
check("5b 40 s of Loading with no code box: exit 5, failed with portal code send_failed", r == ST.REFUSED and p.requests[F.RID]["status"] == "failed" and p.requests[F.RID].get("fail_code") == "send_failed", (r, p.requests[F.RID]))
check("5c the scoreboard says failed:send_unconfirmed (not a generic send_failed) and is NOT fence_skip", row.get("outcome") == "failed:send_unconfirmed" and "fence_skip" not in row, row)
check("5d it waited the full 40 s before giving up", c.t - 1000.0 >= 40, c.t - 1000.0)
check("5e send_clicked_at is on the row; no code_sent_at; mark_code_sent never called (no retry, no false send)", row.get("send_clicked_at") and row.get("code_sent_at") is None and not any(c_[1] == "rpc/mark_code_sent" for c_ in p.calls), row)
evr = row.get("evidence") or {}
check("5f the row links after_send, after_send_wait and end captures with the Loading text on disk", {"after_send", "after_send_wait", "end"} <= set(evr)
      and "Loading" in open(os.path.join(os.environ["CE_LOGS"], evr["after_send_wait"]["txt"]), encoding="utf-8").read(), sorted(evr))
check("5g the refusal text names the Loading hang", "Loading" in (row.get("refusal_text") or ""), row.get("refusal_text"))

fresh(); c = Clock(); seq = {"n": 0}
def slow(cdp, doms):
    seq["n"] += 1
    return CODEBOX if c.t - 1000.0 >= 20 else LOADING
use(slow); p = mk(); r, _t = quiet(ST.step_watch, F.RID, p, B.VerifyRpc(p), F.NOW, c.sleep, c.now)
check("5h Loading that clears into the code boxes at 20 s is fine: exit 0, request untouched", r == 0 and p.requests[F.RID]["status"] == "starting" and not rows(), (r, c.t))

fresh(); use(page(text="Jobs Messages")); p = mk(); c = Clock(); r, _t = quiet(ST.step_watch, F.RID, p, B.VerifyRpc(p), F.NOW, c.sleep, c.now)
check("5i no code box and no Loading text: not send_unconfirmed; exit 0 and `sent` decides (it refuses a page that shows nothing)", r == 0 and p.requests[F.RID]["status"] == "starting")

fresh(); use(None); p = mk(); c = Clock(); r, _t = quiet(ST.step_watch, F.RID, p, B.VerifyRpc(p), F.NOW, c.sleep, c.now)
check("5j unreadable page: no stop (cannot tell), exit 0, still stamps send_clicked_at", r == 0 and stage().get("send_clicked_at") and p.requests[F.RID]["status"] == "starting")

fresh(); use(CAPTCHA); p = mk(); c = Clock(); r, _t = quiet(ST.step_watch, F.RID, p, B.VerifyRpc(p), F.NOW, c.sleep, c.now)
check("5k a CAPTCHA after the click: exit 5, failed:captcha, never attempted", r == ST.REFUSED and rows()[-1]["outcome"] == "failed:captcha", rows())

fresh(); use(LOADING); p = mk("code_sent"); c = Clock(); r, _t = quiet(ST.step_watch, F.RID, p, B.VerifyRpc(p), F.NOW, c.sleep, c.now)
check("5l watch on a request that is not `starting` is refused and records nothing", r == ST.REFUSED and p.requests[F.RID]["status"] == "code_sent" and not rows())

# ---- 6 the fail reasons and the CLI ----------------------------------------------------------------------------------------------------------
for reason, code in (("session_signed_out", "signin_failed"), ("captcha", "signin_failed"), ("send_unconfirmed", "send_failed")):
    fresh(); use(None); p = mk(); r, _t = quiet(ST.main, ["fail", "--request-id", F.RID, "--reason", reason, "--evidence", "The page showed Loading."], p, B.VerifyRpc(p))
    row = rows()[-1] if rows() else {}
    check("6 `fail --reason %s` is accepted: portal code %s, scoreboard failed:%s" % (reason, code, reason), r == 0 and p.requests[F.RID].get("fail_code") == code and row.get("outcome") == "failed:" + reason, (r, row))
fresh(); use(None); p = mk(); r, _t = quiet(ST.main, ["fail", "--request-id", F.RID, "--reason", "directory_refused_phone", "--evidence", "The number entered is not a mobile phone."], p, B.VerifyRpc(p))
check("6d the old reason still ends failed:send_failed", r == 0 and rows()[-1]["outcome"] == "failed:send_failed", rows())
fresh(); p = mk(); r, _t = quiet(ST.main, ["fail", "--request-id", F.RID, "--reason", "nonsense", "--evidence", "x"], p, B.VerifyRpc(p))
check("6e an unknown reason is a bad argument", r == ST.BAD_ARGS and p.requests[F.RID]["status"] == "starting", r)
fresh(); use(CODEBOX); p = mk(); r, _t = quiet(ST.main, ["watch", "--request-id", F.RID, "--wait-s", "1"], p, B.VerifyRpc(p))
check("6f the `watch` command is wired in main", r == 0 and stage().get("send_clicked_at"), r)

# ---- 7 the row of a normal verified run links its evidence -----------------------------------------------------------------------------------
fresh(); use(CODEBOX); p = mk(); rpc = B.VerifyRpc(p)
SB.stamp(F.RID, "requested_at", F.NOW); SB.stamp(F.RID, "agent_start_at", F.NOW)
quiet(ST.step_stage, F.RID, "signed_in", p, F.NOW, rpc); quiet(ST.step_watch, F.RID, p, rpc, F.NOW); quiet(rpc.finish, F.RID, "failed", "other")
row = rows()[-1]
check("7a a run that reaches the end links signin, after_send and end", {"signin", "after_send", "end"} <= set(row.get("evidence") or {}), sorted(row.get("evidence") or {}))
check("7b a request whose agent never started gets no end capture (a swept row)", (lambda: (fresh(), use(SIGNED_IN), SB.stamp(F.RID, "requested_at", F.NOW), quiet(B.VerifyRpc(mk(agent=False)).finish, F.RID, "could_not_start", "timeout"), "evidence" not in rows()[-1])[-1])())

# ---- 8 saved text never carries a value -------------------------------------------------------------------------------------------------------
fresh(); VE.save(F.RID, "end", page(text="Code 987654 sent to me@client.example, call 5025550101")); d = os.path.join(VE.evidence_root(), F.RID)
body = open(os.path.join(d, [f for f in os.listdir(d) if f.endswith(".txt")][0]), encoding="utf-8").read()
check("8a saved page text has no email and no 6+ digit run", "987654" not in body and "me@client" not in body and "5025550101" not in body, body)

# ---- 9 prompt + playbook ----------------------------------------------------------------------------------------------------------------------
ENTRY = {"domain": "thumbtack.com", "signin_url": "https://www.thumbtack.com/login"}
TEN = ("NM", "Na" + "cke Media", "NM - thumbtack.com", ENTRY["signin_url"])
seed = json.load(open(os.path.join(HERE, "..", "config", "playbooks", "thumbtack.com.verify.v4.json"), encoding="utf-8"))
sv = PB.validate_steps(seed["steps"])
pr = S.build_prompt(F.RID, F.request(channel="sms"), F.verification(directory="thumbtack.com"), ENTRY, TEN, MASK, "x@y.example", playbook={"steps": sv, "send_is_signup": False, "version": 4})
check("9a the prompt tells the agent to run `watch` right after the click and to stop on exit 5", "watch --request-id %s" % F.RID in pr and "Never click send again" in pr)
check("9b the prompt makes a nonzero `stage signed_in` a STOP (no CAPTCHA solving)", "exit 5 means the session is signed out or a CAPTCHA shows" in pr and "never solve or click a CAPTCHA" in pr)
check("9c the stale `carry on` for the sign-in stage is gone", "If either exits nonzero, carry on" not in pr)
txt3 = sv[2]["text"]; txt4 = sv[3]["text"]
check("9d thumbtack v4 step 3: Next opens the SMS consent panel and its Continue is the send, not the code modal", "SMS consent panel" in txt3 and "Continue is the send button" in txt3 and "Next does NOT open the code modal" in txt3, txt3[:200])
check("9e thumbtack v4 send step clicks Continue once on the consent panel (still exactly one marked send step, number 4)", "'Continue' ONCE" in txt4 and PB.send_step_number(sv, False) == 4 and sum(1 for s in sv if s.get("send")) == 1)
check("9f a playbook with send_is_signup stamps signup in the stage file", (lambda: (fresh(), SB.stamp(F.RID, None, signup="1"), VE.classify(page(url="https://x.example/signup", password=True), bool(stage().get("signup"))) == "signed_in")[-1])())

print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
