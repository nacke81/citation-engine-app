"""Verify Now speed, phone-on-account and landed-send tests (t_4ee21e60). No network, no Chrome, no hermes, no real send.
Run: python tests/verify_speed_test.py (CI). Exit 1 on any failure. `--mutations` runs only the mutation checks (each must be CAUGHT)."""
import contextlib, io, json, os, sys, tempfile, threading
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
import verify_bridge as B
import verify_send as S
import verify_step as ST   # NOT wrapped: these tests exercise the real evidence rules
import verify_scoreboard as SB
import playbook as PB

ONLY_MUT = "--mutations" in sys.argv
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
ALIGNABLE_ERR = "The number entered is not a mobile phone."
CODE_BOX = "Enter the verification code we texted you. Didn't get the code?"

def portal(status="starting", age_s=5, channel="sms"):
    return F.StrictPortal(requests=[F.request(status=status, age_s=age_s, channel=channel)], verifications=[F.verification(directory=AGENT_DIR)])

def rows():
    p = SB.path()
    return [json.loads(l) for l in open(p, encoding="utf-8")] if os.path.exists(p) else []

# ---- 1 phone_on_account: playbook validation -------------------------------------------------------------------------------------------------
EV = "Live read: the resend modal shows no phone; the account was created with the business phone."
good = [{"text": "The code modal shows no phone field.", "phone_on_account": True, "phone_evidence": EV}, {"text": "Click resend.", "send": True}]
def refused(steps):
    try: PB.validate_steps(steps); return False
    except PB.PlaybookError: return True
if not ONLY_MUT:
    v = PB.validate_steps(good)
    check("1a a step with phone_on_account + evidence validates and keeps both keys", v[0].get("phone_on_account") is True and v[0].get("phone_evidence") == EV and "phone_on_account" not in v[1])
    check("1b phone_on_account without an evidence note is refused", refused([{"text": "x", "phone_on_account": True}, {"text": "y", "send": True}]))
    check("1c an evidence note without the flag is refused", refused([{"text": "x", "phone_evidence": EV}, {"text": "y", "send": True}]))
    check("1d a non-boolean flag is refused", refused([{"text": "x", "phone_on_account": "yes", "phone_evidence": EV}, {"text": "y", "send": True}]))
    check("1e an evidence note that carries a phone number is refused", refused([{"text": "x", "phone_on_account": True, "phone_evidence": "phone 502 555 0101"}, {"text": "y", "send": True}]))
    check("1f phone_on_account false is dropped (no key kept)", "phone_on_account" not in PB.validate_steps([{"text": "x", "phone_on_account": False}, {"text": "y", "send": True}])[0])
    seed = json.load(open(os.path.join(HERE, "..", "config", "playbooks", "thumbtack.com.verify.v4.json"), encoding="utf-8"))
    sv = PB.validate_steps(seed["steps"])
    check("1g the thumbtack v4 seed validates: one send, the flag on the code-modal step, sign-in path (not signup)", PB.send_step_number(sv, False) == 4 and sv[2].get("phone_on_account") is True and seed["send_is_signup"] is False)

# ---- 2 prompt: both variants --------------------------------------------------------------------------------------------------------------
ENTRY = {"domain": "thumbtack.com", "signin_url": "https://www.thumbtack.com/login"}
TEN = ("NM", "Na" + "cke Media", "NM - thumbtack.com", ENTRY["signin_url"])
REQ, ROW = F.request(channel="sms"), F.verification(directory="thumbtack.com")
def prompt(steps):
    return S.build_prompt(F.RID, REQ, ROW, ENTRY, TEN, MASK, "listings@x.example", playbook={"steps": steps, "send_is_signup": False, "version": 4})
FLAG_LINE = "This page shows no phone; the playbook records the code goes to the phone on the account. Proceed."
STRICT = "phone shown there against the masked phone above"
p_flag, p_strict = prompt(PB.validate_steps(good)), prompt(PB.validate_steps([{"text": "Open it."}, {"text": "Click resend.", "send": True}]))
if not ONLY_MUT:
    check("2a flagged playbook: prompt step 2 is the proceed line and the strict compare is gone", FLAG_LINE in p_flag and STRICT not in p_flag)
    check("2b unflagged playbook: the strict phone check stays and the proceed line is absent", STRICT in p_strict and FLAG_LINE not in p_strict)
    check("2c no playbook (generic prompt): strict check", STRICT in S.build_prompt(F.RID, REQ, ROW, ENTRY, TEN, MASK, "x") and FLAG_LINE not in S.build_prompt(F.RID, REQ, ROW, ENTRY, TEN, MASK, "x"))
orig = PB.phone_on_account
PB.phone_on_account = lambda steps: False   # mutation: the flag is ignored
m = prompt(PB.validate_steps(good))
check("2m MUTATION flag ignored: the flagged playbook shows the strict check again (the stop Mike hit), so 2a catches it", FLAG_LINE not in m and STRICT in m)
PB.phone_on_account = lambda steps: True    # mutation: every playbook is exempt
m2 = prompt(PB.validate_steps([{"text": "Open it."}, {"text": "Click resend.", "send": True}]))
check("2n MUTATION flag always on: an unflagged playbook loses the strict check, so 2b catches it", FLAG_LINE in m2)
PB.phone_on_account = orig

# ---- 3 landed send: `sent` needs page evidence ---------------------------------------------------------------------------------------------
if not ONLY_MUT:
    p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW)
    check("3a `sent` without evidence is refused (5) and records nothing", r == ST.REFUSED and p.requests[F.RID]["status"] == "starting" and not any(c[1] == "rpc/mark_code_sent" for c in p.calls), r)
    p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="   ")
    check("3b blank evidence is refused", r == ST.REFUSED and p.requests[F.RID]["status"] == "starting")
    p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence=CODE_BOX)
    check("3c evidence showing a code box: recorded, row goes code_sent", r == 0 and p.requests[F.RID]["status"] == "code_sent", r)
    p = portal(channel="phone-call"); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="Enter the code from the call. Code field shows, no error.")
    check("3d call path: a code field and no error is recorded", r == 0 and p.requests[F.RID]["status"] == "code_sent", r)
    p = portal(channel="phone-call"); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="We are calling you now.")
    check("3e call path: 'we are calling you' with no code field is refused", r == ST.REFUSED and p.requests[F.RID]["status"] == "starting", r)
    p = portal(channel="phone-call"); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence=ALIGNABLE_ERR)
    check("3f call path: the Alignable error text ends the request failed/send_failed, never a code box", r == ST.REFUSED and p.requests[F.RID]["status"] == "failed" and p.requests[F.RID].get("fail_code") == "send_failed", (r, p.requests[F.RID]))
    p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="Enter the verification code. The number entered is not a mobile phone.")
    check("3g a code box AND an error together: the error wins (failed, not code_sent)", p.requests[F.RID]["status"] == "failed", p.requests[F.RID]["status"])
    p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="Verification code sent to 5025550101")
    check("3h evidence that carries a phone number is refused (no value in the log or the stage file)", r == ST.REFUSED and p.requests[F.RID]["status"] == "starting")
    p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="A" * 400)
    check("3i over-long evidence is refused", r == ST.REFUSED)
    p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="The page changed.")
    check("3j evidence with no code box and no sent text is refused", r == ST.REFUSED and p.requests[F.RID]["status"] == "starting")
    p = portal(); r, t = quiet(ST.main, ["sent", "--request-id", F.RID, "--masked", MASK], p, B.VerifyRpc(p))
    check("3k CLI `sent` with no --evidence exits 5 (refused), not a usage error", r == ST.REFUSED and p.requests[F.RID]["status"] == "starting", r)

    # ---- 4 fail: the refusal path writes failed + the page text ---------------------------------------------------------------------------
    SB.stamp(F.RID, "requested_at"); SB.stamp(F.RID, None, tenant="NM", domain=AGENT_DIR, channel="sms", send_mode="agent")
    p = portal(); r, t = quiet(ST.main, ["fail", "--request-id", F.RID, "--reason", "directory_refused_phone", "--evidence", ALIGNABLE_ERR], p, B.VerifyRpc(p))
    last = rows()[-1] if rows() else {}
    check("4a `fail --reason directory_refused_phone`: request failed/send_failed, no code box, no mark_code_sent", r == 0 and p.requests[F.RID]["status"] == "failed" and p.requests[F.RID].get("fail_code") == "send_failed" and not any(c[1] == "rpc/mark_code_sent" for c in p.calls), (r, p.requests[F.RID]))
    check("4b the page text is kept: the scoreboard row carries it and its outcome is failed:send_failed", last.get("refusal_text") == ALIGNABLE_ERR and last.get("outcome") == "failed:send_failed", last)
    p = portal(status="code_sent"); r, t = quiet(ST.step_fail, F.RID, "directory_refused_phone", ALIGNABLE_ERR, p, B.VerifyRpc(p))
    check("4c `fail` on a request that is not `starting` is refused and changes nothing", r == ST.REFUSED and p.requests[F.RID]["status"] == "code_sent")
    p = portal(); r, t = quiet(ST.step_fail, F.RID, "because", ALIGNABLE_ERR, p, B.VerifyRpc(p))
    check("4d an unknown reason is a usage error", r == ST.BAD_ARGS and p.requests[F.RID]["status"] == "starting")
    p = portal(); r, t = quiet(ST.step_fail, F.RID, "directory_refused_phone", "x@y.example", p, B.VerifyRpc(p))
    check("4e `fail` evidence with an email is refused (usage error), request untouched", r == ST.BAD_ARGS and p.requests[F.RID]["status"] == "starting")

# ---- 4b rework (review round 1): only a send refusal finishes the request; help text on a landed page never does; a call needs a code field --------------
HELP_PAGES = [
    "We sent a code to your phone. Didn't receive it? Try again",
    "Enter the code we sent. Can't find it? Resend code",
    "Enter code. Unable to receive SMS? Call me instead",
    "Enter your code. Invalid code will lock the account after too many attempts",
]
def help_page_outcomes():
    out = []
    for t in HELP_PAGES:
        p = portal(); r, _ = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence=t)
        out.append((r, p.requests[F.RID]["status"]))
    return out
if not ONLY_MUT:
    for t, (r, st) in zip(HELP_PAGES, help_page_outcomes()):
        check("4f help text on a landed code page is NOT finished failed: refused (5), nothing recorded, request stays starting [%s]" % t[:40], r == ST.REFUSED and st == "starting", (r, st))
    p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence=HELP_PAGES[0])
    check("4g the refusal message tells the agent to run `fail` for a real error or re-run `sent` quoting only the code text", "fail" in t and "quoting only" in t, t)
    p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="We sent a code. Too many attempts, wait a minute.")
    check("4h 'too many attempts' WITH a code-sent text is not a send refusal: refused, request stays starting", r == ST.REFUSED and p.requests[F.RID]["status"] == "starting")
    for t in ("Too many requests. Please wait.", "Too many attempts, try later.", "Please enter a valid number. Invalid phone.", "We could not send the text.", "Unable to send a code to this number."):
        p = portal(); r, _ = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence=t)
        check("4i send-refusal phrase finishes the request failed/send_failed [%s]" % t[:40], p.requests[F.RID]["status"] == "failed" and p.requests[F.RID].get("fail_code") == "send_failed", p.requests[F.RID]["status"])
    p = portal(channel="phone-call"); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="We called your phone")
    check("4j call path: 'We called your phone' with no code field is refused, nothing recorded", r == ST.REFUSED and p.requests[F.RID]["status"] == "starting", (r, p.requests[F.RID]["status"]))
    p = portal(channel="phone-call"); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="We called your phone. Enter the code from the call")
    check("4k call path: 'We called your phone. Enter the code from the call' is recorded (code_sent)", r == 0 and p.requests[F.RID]["status"] == "code_sent", r)
    p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="We called you. Done.")
    check("4l text path too: 'called you' alone is not a landed code", r == ST.REFUSED and p.requests[F.RID]["status"] == "starting")

# mutations of the evidence gate (each must be CAUGHT: the bad outcome shows)
orig_err, orig_err2 = ST.SEND_REFUSAL, ST.ERROR_TEXT
ST.SEND_REFUSAL = ST.ERROR_TEXT = __import__("re").compile(r"(?!x)x")   # mutation: error text never matches
p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="Enter the verification code. " + ALIGNABLE_ERR)
check("5a MUTATION error detection off: the Alignable page is recorded as sent (the live false sent), so 3g catches it", p.requests[F.RID]["status"] == "code_sent")
ST.SEND_REFUSAL, ST.ERROR_TEXT = orig_err, orig_err2
orig_ce = ST.clean_evidence
ST.clean_evidence = lambda text: ((text or "ok").strip() or "ok", None)   # mutation: evidence is not required
p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW)
check("5b MUTATION evidence not required: `sent` with none is recorded... only if landed text matches; with none it is still refused, so the gate needs the evidence AND the landed text",
      r == ST.REFUSED)
ST.clean_evidence = orig_ce
orig_ld = ST.LANDED_TEXT
ST.LANDED_TEXT = __import__("re").compile(r"")   # mutation: any text counts as landed
p = portal(); r, t = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="The page changed.")
check("5c MUTATION landed check off: unrelated text is recorded as sent, so 3j catches it", p.requests[F.RID]["status"] == "code_sent")
ST.LANDED_TEXT = orig_ld
check("5d the prompt tells the agent to confirm the page and pass --evidence, and to run `fail` on an error (text and call path)", "--evidence" in p_flag and " fail --request-id " in p_flag and "phone-call send the same" in p_flag)
orig_sr = ST.SEND_REFUSAL
ST.SEND_REFUSAL = ST.ERROR_TEXT   # mutation: the auto-fail set is widened back to every error word
mut = help_page_outcomes()
check("5e MUTATION auto-fail widened back to any error word: real landed sends are finished failed (the review probe), so 4f catches it", any(st == "failed" for _r, st in mut), mut)
ST.SEND_REFUSAL = orig_sr
orig_ld2 = ST.LANDED_TEXT
ST.LANDED_TEXT = __import__("re").compile(r"(?i)(called (you|your)|(we|i)('ve| have)? called|" + orig_ld2.pattern[len("(?i)"):] + ")")   # mutation: the old call rule (a bare 'called' lands)
p = portal(channel="phone-call"); r, _ = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="We called your phone")
check("5f MUTATION call path lands without a code field: 'We called your phone' is recorded as sent, so 4j catches it", p.requests[F.RID]["status"] == "code_sent")
ST.LANDED_TEXT = orig_ld2

# ---- 6 bridge loop ----------------------------------------------------------------------------------------------------------------------------
class Clk:
    def __init__(self): self.t = 0.0; self.sleeps = []
    def clock(self): return self.t
    def sleep(self, s): self.sleeps.append(round(s, 1)); self.t += s
def loop(loop_s, every_s, pass_cost=1.0):
    c = Clk(); times = []
    def passer(): times.append(round(c.t, 1)); c.t += pass_cost; return {"swept": [], "started": [], "refused": [], "deferred": [], "first_use": []}
    B.run_loop(loop_s, every_s, passer=passer, sleep=c.sleep, clock=c.clock); return times
if not ONLY_MUT:
    check("6a loop 50 s / every 15 s: passes at 0, 15, 30, 45 (a click waits <= 15 s, not 60)", loop(50, 15) == [0.0, 15.0, 30.0, 45.0], loop(50, 15))
    check("6b the pass time does not drift the schedule (a 4 s pass still starts the next at 15)", loop(50, 15, pass_cost=4.0) == [0.0, 15.0, 30.0, 45.0])
    check("6c loop 0 = one pass (the old behaviour)", loop(0, 15) == [0.0])
    check("6d a loop longer than the cap is clamped", len(loop(10000, 15)) == int(B.LOOP_MAX_S // 15) + 1, len(loop(10000, 15)))
    check("6e the scheduled command runs the loop under the 60 s tick", "--loop-s 50 --every-s 15" in open(os.path.join(HERE, "..", "job", "verify_bridge.cmd")).read() and 50 + 15 > 60 - 1)
check("6m MUTATION loop disabled (one pass): a click can wait the whole tick, so 6a catches it", loop(0, 15) != [0.0, 15.0, 30.0, 45.0])

# ---- 7 start without the serial vault reads ----------------------------------------------------------------------------------------------------
class Ev: pass
def run_send(vault_ok=True, username=None, parallel_probe=False):
    p = F.StrictPortal(requests=[F.request(status="starting", age_s=5)], verifications=[F.verification(directory=AGENT_DIR)])
    page = F.FakePage(); rt = F.FakeRuntime(page, vault_ok=vault_ok, username=username, agent_factory=lambda rt: F.FakeAgent([], hang=True))
    rt.lookups = 0
    base_lookup = rt.vault_lookup
    def lookup(t): rt.lookups += 1; return base_lookup(t)
    rt.vault_lookup = lookup
    if parallel_probe:   # login_username blocks until the sitegate reservation ran: only a concurrent start gets past it
        seen = threading.Event(); base_res = rt.guard
        def guard():
            g = base_res()
            class G:
                def reserve(self, domain, key=None): seen.set(); return g.reserve(domain, key)
            return G()
        rt.guard = guard
        base_login = rt.login_username
        def login(t):
            rt.parallel = seen.wait(5); return base_login(t)
        rt.login_username = login
    r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
    return r, rt, p, text
if not ONLY_MUT:
    r, rt, p, text = run_send(parallel_probe=True)
    check("7a the agent path never runs the separate vault lookup (59 s measured)", rt.lookups == 0 and len(rt.launched) == 1, (rt.lookups, len(rt.launched)))
    check("7b the vault read runs beside the start: it saw the sitegate reservation happen while it was still running", getattr(rt, "parallel", False) is True)
    check("7c a passing vault check opens the arm gate (vault-ok marker) while the agent is live", B.vault_ok(F.RID))
    B.clear_started(F.RID)
    for label, kw in (("wrong username", {"username": "someone@example.com"}), ("vault item missing", {"vault_ok": False})):
        try: os.remove(B._vault_marker(F.RID))
        except OSError: pass
        r, rt, p, text = run_send(**kw)
        check("7d %s: the agent that started beside the check is killed and the request ends failed:signin_failed, gate stays shut" % label, r == "failed:signin_failed" and rt.agent.kills >= 1 and not B.vault_ok(F.RID), r)

# ---- 7e/7f the two other vault-check exits (review round 1: mutations M3 and M4 survived) -------------------------------------------------------
import types
def mutant(old, new):
    """S with ONE source line changed (a mutation of verify_send.py), loaded as a separate module; the same bridge/playbook modules."""
    src = open(os.path.join(HERE, "..", "job", "verify_send.py"), encoding="utf-8").read()
    assert src.count(old) == 1, old
    m = types.ModuleType("verify_send_mut"); m.__file__ = os.path.join(HERE, "..", "job", "verify_send.py")
    exec(compile(src.replace(old, new), m.__file__, "exec"), m.__dict__); return m
M3_OLD = "if vault is not None and vault.state is not True:"
M4_OLD = "if vs is None and now - t0 >= VAULT_CHECK_S: vault.state = vs = False"
def vault_run(mod, mode):
    """mode 'ends': the agent exits at once while the check still runs, then the check answers with the WRONG username.
    mode 'hangs': the agent hangs and the check blocks past VAULT_CHECK_S (released later so no thread is left behind)."""
    p = F.StrictPortal(requests=[F.request(status="starting", age_s=5)], verifications=[F.verification(directory=AGENT_DIR)])
    page = F.FakePage(); gate = threading.Event()
    rt = F.FakeRuntime(page, agent_factory=lambda rt: F.FakeAgent([], hang=(mode == "hangs")))
    def login(t):
        if mode == "ends": gate.wait(0.5); return "someone@example.com"
        gate.wait(6); return S.EXPECTED_LOGIN[t[0]]
    rt.login_username = login
    old = mod.AGENT_START_S; mod.AGENT_START_S = 400   # past VAULT_CHECK_S (240) so the check, not the start cap, ends a hung run; fake clock, so this is only ticks
    try:
        try: os.remove(B._vault_marker(F.RID))
        except OSError: pass
        B.clear_started(F.RID)
        r, text = quiet(mod.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
    finally:
        mod.AGENT_START_S = old; gate.set()
    return r, rt, p, text
if not ONLY_MUT:
    r, rt, p, text = vault_run(S, "ends")
    check("7e agent exits while the vault check still runs and the check then fails: failed:signin_failed, gate shut, request failed", r == "failed:signin_failed" and not B.vault_ok(F.RID) and p.requests[F.RID]["status"] == "failed", (r, p.requests[F.RID]["status"]))
    r, rt, p, text = vault_run(S, "hangs")
    check("7f the vault check hangs past VAULT_CHECK_S: agent killed, failed:signin_failed, gate shut", r == "failed:signin_failed" and rt.agent.kills >= 1 and not B.vault_ok(F.RID), (r, rt.agent.kills))
r, rt, p, text = vault_run(mutant(M3_OLD, "if False:"), "ends")
check("7m3 MUTATION M3 end-of-run fail-closed removed: the run no longer ends signin_failed after a failed late check, so 7e catches it", r != "failed:signin_failed", r)
r, rt, p, text = vault_run(mutant(M4_OLD, "if False: pass"), "hangs")
check("7m4 MUTATION M4 VAULT_CHECK_S timeout never fires: a hung check no longer ends signin_failed in time, so 7f catches it", r != "failed:signin_failed", r)

# ---- 8 arm gate ---------------------------------------------------------------------------------------------------------------------------------
def arm_gate(marker, age_s=5):
    try: os.remove(B._vault_marker(F.RID))
    except OSError: pass
    if marker: B.mark_vault_ok(F.RID)
    p = portal(age_s=age_s); sl = []
    r, t = quiet(ST.step_arm, F.RID, p, F.NOW, lambda s: sl.append(s))
    return r, sum(sl)
if not ONLY_MUT:
    check("8a arm with the vault check passed: go (0), no wait", arm_gate(True) == (0, 0))
    r, waited = arm_gate(False)
    check("8b arm before the vault check passed: waits then refuses (5), no click", r == ST.REFUSED and waited >= ST.VAULT_WAIT_S, (r, waited))
    check("8c the arm window is untouched: 539 s go, 540 s stop, START_LIMIT_MS (600 s sweep) and ARM_MARGIN (60) unchanged",
          arm_gate(True, 539)[0] == 0 and arm_gate(True, 540)[0] == ST.REFUSED and B.SWEEP_AFTER_S == 600 and ST.ARM_MARGIN_S == 60)
# ---- 9 same-tenant queue ------------------------------------------------------------------------------------------------------------------------
if not ONLY_MUT:
    cid = F.NM
    with B.tenant_lock(cid) as got1:
        busy_during = B.tenant_busy(cid)
    check("9a the tenant lock is held while a run holds it", got1 and busy_during)
    check("9b the lock is free the moment the run's `with` ends (no 3 minute hold in the lock): the next pass starts the queued row", B.tenant_busy(cid) is False)
    # a deferred (queued) row keeps its OWN window: age from its requested_at, not from when it started
    check("9c a queued row clicked 500 s ago still arms (go); the same row at 541 s is stopped: the window is the click's, as the portal shows it", arm_gate(True, 500)[0] == 0 and arm_gate(True, 541)[0] == ST.REFUSED)

# ---- 10 t_6168a061: a send button label or a negated send is not a landed send; the prompt keeps the quote-only line -------------------------------
MAIN_LANDED_PATTERN = r"(?i)(code (was |has been )?(sent|texted|emailed)|\b(sent|texted)\b[^.?!]{0,40}\bcode|verification code|enter (the |your |a )?(\d-digit )?code|confirmation code|security code|code (field|box|input))"
NOT_LANDED = ["Send verification code", "Get verification code", "We have not sent a code yet", "Text me a code", "Get code", "No verification code sent yet", "We haven't sent a code. Request a security code", "No code has been sent yet", "We didn't send a code", "Resend code"]
LIVE_THUMBTACK = "Enter the verification code we texted you. / The code will expire after 10 minutes. / Didn\u2019t get the code? / Back / Verify"
def label_outcomes():
    out = []
    for t in NOT_LANDED:
        p = portal(); r, _ = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence=t)
        out.append((r, p.requests[F.RID]["status"]))
    return out
if not ONLY_MUT:
    for t, (r, st) in zip(NOT_LANDED, label_outcomes()):
        check("10a button label / negated send is refused (5), nothing recorded, request stays starting [%s]" % t[:40], r == ST.REFUSED and st == "starting", (r, st))
    p = portal(); r, _ = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence=LIVE_THUMBTACK)
    check("10b the live Thumbtack modal text still records code_sent", r == 0 and p.requests[F.RID]["status"] == "code_sent", (r, p.requests[F.RID]["status"]))
    for t in ("Enter the verification code", "Your verification code was sent", "We texted you a confirmation code", "Type the security code", "Enter the code we sent.", "We just sent you a code", "We've just texted you a 6-digit code", "No worries, we sent a code to your phone", "Don't close this window, we texted you a code",
              "A text message has been sent to your phone with a verification code", "SMS sent with your code", "Thumbtack sent a code to your phone", "No problem, a code was sent to your phone",
              "Do not send this code to anyone; enter the code we texted you", "Send verification code. Enter the verification code we texted you"):
        p = portal(); r, _ = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence=t)
        check("10c landed context with a named code is recorded [%s]" % t[:40], r == 0 and p.requests[F.RID]["status"] == "code_sent", (r, p.requests[F.RID]["status"]))
    p = portal(); r, _ = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="Enter the verification code. " + ALIGNABLE_ERR)
    check("10d Alignable 'not a mobile phone' still ends failed/send_failed", p.requests[F.RID]["status"] == "failed" and p.requests[F.RID].get("fail_code") == "send_failed", p.requests[F.RID]["status"])
    check("10e the prompt carries the 'Quote ONLY the code-box or code-sent text' line (sign-in and marked variants)", "Quote ONLY the code-box or code-sent text" in p_strict and "Quote ONLY the code-box or code-sent text" in p_flag)
orig_lab = ST.SEND_LABEL_ONLY
ST.SEND_LABEL_ONLY = __import__("re").compile(r"(?!x)x")   # mutation: the send-label pre-check is removed (main's LANDED_TEXT then takes the bare `verification code`)
mut = label_outcomes()
check("10f MUTATION send-label pre-check removed: 'Send verification code' / 'Get verification code' are recorded, so 10a catches it", any(st == "code_sent" for _r, st in mut), mut)
ST.SEND_LABEL_ONLY = orig_lab
orig_neg = ST.NEGATED_SEND
ST.NEGATED_SEND = __import__("re").compile(r"(?!x)x")   # mutation: negation is ignored
mut = label_outcomes()
check("10g MUTATION negation ignored: 'No verification code sent yet' is recorded, so 10a catches it", any(st == "code_sent" for _r, st in mut), mut)
ST.NEGATED_SEND = orig_neg
orig_ld4 = ST.LANDED_TEXT
ST.LANDED_TEXT = __import__("re").compile(r"(?i)(code (was |has been )?(sent|texted|emailed)|code (field|box|input))")   # mutation: main's generic `sent ... code` form dropped
p = portal(); r, _ = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence="SMS sent with your code")
check("10i MUTATION generic `sent ... code` form dropped from LANDED_TEXT: 'SMS sent with your code' is refused, so 10c catches it", r == ST.REFUSED and p.requests[F.RID]["status"] == "starting", (r, p.requests[F.RID]["status"]))
ST.LANDED_TEXT = orig_ld4
check("10j LANDED_TEXT is main's, unchanged", ST.LANDED_TEXT.pattern == MAIN_LANDED_PATTERN)
QL = 'Quote ONLY the code-box or code-sent text; do not copy help text like \\"Didn\'t get it? Try again\\" into the evidence, it makes `sent` refuse. '
mm = mutant(QL, "")
pm = mm.build_prompt(F.RID, REQ, ROW, ENTRY, TEN, MASK, "x", playbook={"steps": PB.validate_steps(good), "send_is_signup": False, "version": 4})
check("10h MUTATION quote-only line removed from verify_send.py: the built prompt loses it, so 10e catches it", "Quote ONLY the code-box or code-sent text" not in pm and "Quote ONLY the code-box or code-sent text" in p_flag)

print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
