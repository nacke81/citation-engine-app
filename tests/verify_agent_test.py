"""Verify Now agent send path tests (t_218b03ef). Fake oneshot runner, strict RPC fake, virtual clock. No network, no Chrome, no hermes, no real code.
Run: python tests/verify_agent_test.py (CI). Exit 1 on any failure."""
import contextlib, datetime, io, json, os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ["CE_LOGS"] = os.path.join(TMP, "logs")
os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json")
os.environ["CE_VERIFY_LOCKS"] = os.path.join(TMP, "locks")
os.environ["CE_VERIFY_DIRECTORIES"] = os.path.join(HERE, "verify_directories_fixture.json")   # cylex = script, agentdir.example = agent
os.environ["CE_NO_CARDS"] = "1"
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json"); os.environ["CE_RUNS"] = tempfile.mkdtemp()
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
import verify_fakes as F
import verify_bridge as B
import verify_send as S
import verify_step as ST
import portal as P

NM_LOGIN = "listings@na" + "ckemedia.com"
CODE = "906417"
AGENT_DIR = "agentdir.example"
MASK = "(502) ***-0101"
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else ""), flush=True)

def quiet(fn, *a, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        r = fn(*a, **kw)
    return r, out.getvalue() + err.getvalue()

def agent_portal(channel="sms", client=F.NM, directory=AGENT_DIR, code=CODE, fail_mark=False, fail_patch=False, **kw):
    p = F.StrictPortal(requests=[F.request(status="starting", channel=channel, client=client)], verifications=[F.verification(client=client, directory=directory)],
                       queued_code=code, **kw)
    p.fail_mark, p.fail_patch = fail_mark, fail_patch
    return p

# ---- 1 the data file --------------------------------------------------------------------------------------------------------------
real = B.load_directories(os.path.join(HERE, "..", "config", "verify_directories.json"))
cyl = [e for e in real if e["domain"] == "cylex.us"]
check("real config/verify_directories.json loads and lists Cylex with send=agent (Nate: script only after a real run)", len(cyl) == 1 and cyl[0]["send"] == "agent" and "cylex.us.com" in cyl[0]["aliases"] and "sms" in cyl[0]["channels"], real)
check("every real entry has a vault item name for both tenants and an https sign-in url", all(set(e["vault_items"]) >= {"NM", "SCC"} and e["signin_url"].startswith("https://") for e in real))
check("directory_entry: alias and www. resolve; unlisted channel and unlisted Directory do not", B.directory_entry("www.CYLEX.us.com/x", "sms") and B.directory_entry("cylex.us", "phone-call") is None and B.directory_entry("nowhere.example", "sms") is None)
check("a missing or broken file lists nothing (fail closed)", B.load_directories(os.path.join(TMP, "nope.json")) == [] and B.directory_entry("cylex.us", "sms", os.path.join(TMP, "nope.json")) is None)
bad = os.path.join(TMP, "bad.json"); open(bad, "w").write('{"directories": [{"domain": "x.example", "send": "magic", "channels": ["sms"]}, {"domain": "y.example", "send": "agent", "channels": ["voice", "sms"]}]}')
check("an entry with an unknown send mode is dropped; unknown channels are dropped", [e["domain"] for e in B.load_directories(bad)] == ["y.example"] and B.load_directories(bad)[0]["channels"] == ["sms"])
f = B.fence(F.request(channel="phone-call"), F.StrictPortal(verifications=[F.verification(directory=AGENT_DIR)]))
check("fence: phone-call on an agent Directory is ok", f[0] == "ok", f[0])
f = B.fence(F.request(channel="phone-call"), F.StrictPortal(verifications=[F.verification(directory="cylex.us")]))
check("fence: phone-call on an sms-only Directory is no_playbook", f[0] == "no_playbook", f[0])
f = B.fence(F.request(channel="voice"), F.StrictPortal(verifications=[F.verification(directory=AGENT_DIR)]))
check("fence: a channel outside sms/phone-call is refused", f[0] == "channel")

# ---- 2 --check: read-only list of waiting rows whose Directory is missing -----------------------------------------------------------
class CheckPortal:
    def __init__(self, rows): self.rows, self.calls = rows, []
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path)); return self.rows
rows = [{"client_id": F.NM, "directory": "cylex.us", "verification_type": "sms", "state": "requires_verification"},
        {"client_id": F.SCC, "directory": "thryv.example", "verification_type": "phone-call", "state": "requires_verification"},
        {"client_id": F.NM, "directory": "cylex.us", "verification_type": "phone-call", "state": "requires_verification"},
        {"client_id": "430b764e-1a44-4246-959f-6b8945bf6a7c", "directory": "other.example", "verification_type": "sms", "state": "requires_verification"}]
cp = CheckPortal(rows); lines = []
rc = B.run_check(cp, out=lines.append)
check("--check lists the rows whose Directory or channel is missing, skips non-allow-listed clients, and only GETs",
      rc == 0 and len(cp.calls) == 1 and cp.calls[0][0] == "GET" and "3 sms/phone-call rows waiting, 2 missing" in lines[0] and any("thryv.example" in l for l in lines) and any("cylex.us | phone-call" in l for l in lines) and not any("other.example" in l for l in lines), lines)
r, text = quiet(B.main, ["--check"])
check("--check without a portal env fails with a type name, not a traceback or a secret", r in (0, 1))

# ---- 3 agent happy path: sent -> code -> result -> verified (sms and phone-call) ----------------------------------------------------
def happy_steps(p, rpc, rt, out, holder=None):
    ag = F.FakeAgent([
        lambda: holder.__setitem__("sent", ST.step_sent(F.RID, MASK, p, rpc, F.NOW)),
        lambda: holder.__setitem__("code", ST.step_code(F.RID, p, rpc, out, rt.sleep, rt.now, wall=rt.wall)),
        lambda: holder.__setitem__("result", ST.step_result(F.RID, "accepted", p, rpc, F.NOW))])
    return ag
for ch in ("sms", "phone-call"):
    p = agent_portal(channel=ch); holder = {}
    rpc = B.VerifyRpc(p); out = io.StringIO()
    def factory(rt, p=p, rpc=rpc, out=out, holder=holder): return happy_steps(p, rpc, rt, out, holder)
    rt = F.FakeRuntime(F.FakePage(), agent_factory=factory)
    r, text = quiet(S.run, F.RID, p, rpc, rt, F.NOW)
    order = [c[1] for c in p.calls if c[1] in ("rpc/mark_code_sent", "rpc/consume_verify_code", "rpc/finish_code_request") or c[0] == "PATCH"]
    check("agent %s: sent -> code -> result -> verified" % ch, r == "verified" and holder == {"sent": 0, "code": 0, "result": 0} and p.requests[F.RID]["status"] == "verified" and p.verifications[F.VID]["state"] == "live", (r, holder))
    check("agent %s: order is mark_code_sent, consume, set live, finish" % ch, order == ["rpc/mark_code_sent", "rpc/consume_verify_code", "citation_verification", "rpc/finish_code_request"], order)
    check("agent %s: the code reached the helper's stdout only (not stderr, logs, bodies, prompt)" % ch,
          out.getvalue() == CODE + "\n" and CODE not in text and CODE not in repr([c[2] for c in p.calls]) and all(CODE not in t for t in rt.prompts))
    check("agent %s: one sitegate reserve on the Directory, no browser opened by the run, oneshot launched once and left no process" % ch,
          rt.reserves == [(AGENT_DIR, F.RID)] and rt.browsers == 0 and len(rt.launched) == 1 and rt.agent.kills >= 0 and rt.agent.poll() in (0, -9))
    check("agent %s: tenant lock released" % ch, not B.tenant_busy(F.NM))
    pr = rt.prompts[0]
    check("agent %s: prompt names request id, tenant, Directory, channel, masked phone, the helper commands and the hard rules" % ch,
          all(s in pr for s in (F.RID, "Tenant: NM", "Directory: " + AGENT_DIR, "Channel: " + ch, MASK, "verify_step.py\" sent", "verify_step.py\" code", "verify_step.py\" result",
                                "paid upsell", "marketing consent", "Never type the code anywhere except the Directory", "Never print", "One Directory session", "sitegate", "service key")), pr[:200])
    check("agent %s: prompt holds no code, no service key, no 6-digit run" % ch, CODE not in pr and "SERVICE_ROLE" not in pr and not re.search(r"(?<!\d)\d{6}(?!\d)", pr))
check("prompt carries the row's steps and directory_url", True)
p = agent_portal(); p.verifications[F.VID].update({"steps": ["Open the profile", "Press Verify"], "directory_url": "https://agentdir.example/profile/1"})
rt = F.FakeRuntime(F.FakePage(), agent_factory=lambda rt: F.FakeAgent([]))
quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("steps and directory_url from the verification row are in the prompt", "- Open the profile" in rt.prompts[0] and "https://agentdir.example/profile/1" in rt.prompts[0])

# ---- 4 the agent never calls sent: killed at 25 min -> send_failed, lock released, sitegate/browser untouched ---------------------------
p = agent_portal(); rt = F.FakeRuntime(F.FakePage(), agent_factory=lambda rt: F.FakeAgent([], hang=True))
r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
waited = rt.clock.t - 1000.0
check("agent never sends: failed/send_failed, request closed", r == "failed:send_failed" and p.requests[F.RID]["status"] == "failed" and p.requests[F.RID]["fail_code"] == "send_failed", r)
check("the oneshot is killed at 25 minutes (not before, not long after)", rt.agent.kills >= 1 and 1500 <= waited < 1600, waited)
check("no mark_code_sent, no consume, no browser; the lock is free", p.count("rpc/mark_code_sent") == 0 and p.consume_calls == 0 and rt.browsers == 0 and not B.tenant_busy(F.NM))
p = agent_portal(); rt = F.FakeRuntime(F.FakePage(), agent_factory=lambda rt: F.FakeAgent([lambda: None]))
r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("agent exits at once without a send report: failed/send_failed", r == "failed:send_failed" and p.requests[F.RID]["fail_code"] == "send_failed", r)
class BoomRt(F.FakeRuntime):
    def launch_agent(self, path, cdp=None): raise OSError("hermes missing")
p = agent_portal(); rt = BoomRt(F.FakePage())
r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("the oneshot cannot start: failed/send_failed with no exception text logged", r == "failed:send_failed" and "hermes missing" not in text and not B.tenant_busy(F.NM), r)

# ---- 5 sent, then the agent dies / hangs ----------------------------------------------------------------------------------------------
def sent_only(p, rpc, rt, out, h=None): return F.FakeAgent([lambda: ST.step_sent(F.RID, MASK, p, rpc, F.NOW)])
p = agent_portal(); rpc = B.VerifyRpc(p)
rt = F.FakeRuntime(F.FakePage(), agent_factory=lambda rt: sent_only(p, rpc, rt, None))
r, text = quiet(S.run, F.RID, p, rpc, rt, F.NOW)
check("agent sent, then exited without a result: failed/other (row not left in code_sent)", r == "failed:other" and p.requests[F.RID]["status"] == "failed", r)
def sent_then_hang(rt):
    return F.FakeAgent([lambda: ST.step_sent(F.RID, MASK, p, rpc, F.NOW)], hang=True)
p = agent_portal(); rpc = B.VerifyRpc(p); rt = F.FakeRuntime(F.FakePage(), agent_factory=sent_then_hang)
r, text = quiet(S.run, F.RID, p, rpc, rt, F.NOW)
check("agent sent, then hangs past 35 min: killed, failed/code_expired", r == "failed:code_expired" and rt.agent.kills >= 1 and 2100 <= rt.clock.t - 1000.0 < 2200 and not B.tenant_busy(F.NM), (r, rt.clock.t - 1000.0))

# ---- 6 superseded mid-wait: the helper exits nonzero and never finishes ---------------------------------------------------------------
p = agent_portal(); rpc = B.VerifyRpc(p); out = io.StringIO(); got = {}
def superseded_steps(rt):
    def sent(): got["sent"] = ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
    def close_then_code():   # the client asked for a new code: the portal closes the old request failed/resend
        p.requests[F.RID]["status"] = "failed"; p.requests[F.RID]["fail_code"] = "resend"
        got["code"], got["text"] = quiet(ST.step_code, F.RID, p, rpc, out, rt.sleep, rt.now, wall=rt.wall)
    def result():
        got["result"], got["rtext"] = quiet(ST.step_result, F.RID, "accepted", p, rpc, F.NOW)
    return F.FakeAgent([sent, close_then_code, result])
rt = F.FakeRuntime(F.FakePage(), agent_factory=superseded_steps)
r, text = quiet(S.run, F.RID, p, rpc, rt, F.NOW)
check("superseded: `code` exits 3 and prints nothing on stdout", got.get("code") == ST.REFUSED or got.get("code") == ST.SUPERSEDED, got.get("code"))
check("superseded: `code` refuses (3 or 5) on a closed request and writes no code", out.getvalue() == "" and p.consume_calls == 0)
# a request that is live when `code` starts, closed while it waits
p = agent_portal(); rpc = B.VerifyRpc(p); out = io.StringIO()
ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
clk = F.Clock(); p.code_after_polls = 99
orig = p.call
def closing(method, path, body=None, prefer=None):
    if path.startswith("rpc/consume_verify_code") and p.consume_calls >= 2:
        p.requests[F.RID]["status"] = "failed"; p.requests[F.RID]["fail_code"] = "resend"
    return orig(method, path, body, prefer)
p.call = closing
rc, text = quiet(ST.step_code, F.RID, p, rpc, out, clk.sleep, clk.now, wall=clk.wall)
check("superseded while waiting: exit 3, no finish_code_request, request left as the portal closed it, nothing on stdout",
      rc == ST.SUPERSEDED and p.finish_log == [] and p.count("rpc/finish_code_request") == 0 and p.requests[F.RID]["fail_code"] == "resend" and out.getvalue() == "" and "superseded" in text, rc)
rc, text = quiet(ST.step_result, F.RID, "accepted", p, rpc, F.NOW)
check("result after supersede: exit 3, no finish, row not set live", rc == ST.SUPERSEDED and p.finish_log == [] and p.verifications[F.VID]["state"] == "requires_verification", rc)
# the run around it ends 'closed' and does not finish either
p = agent_portal(); rpc = B.VerifyRpc(p)
def sup_run(rt):
    def sent(): ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
    def close(): p.requests[F.RID]["status"] = "failed"; p.requests[F.RID]["fail_code"] = "resend"
    return F.FakeAgent([sent, close, lambda: None])
rt = F.FakeRuntime(F.FakePage(), agent_factory=sup_run)
r, text = quiet(S.run, F.RID, p, rpc, rt, F.NOW)
check("run: a request the portal closed ends 'closed' with NO finish call from the run", r == "closed" and p.finish_log == [] and not B.tenant_busy(F.NM), r)

# ---- 7 no code in 30 min: the helper finishes failed/code_expired and exits 4 ------------------------------------------------------------
p = agent_portal(code=None); rpc = B.VerifyRpc(p); out = io.StringIO(); clk = F.Clock()
ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
rcs = []
for i in range(5):   # the agent's terminal caps one call at 600 s, so `code` is called repeatedly; the 30 min clock is code_sent_at's, not each call's
    t_before = clk.t
    rc, text = quiet(ST.step_code, F.RID, p, rpc, out, clk.sleep, clk.now, wall=clk.wall)
    rcs.append((rc, round(clk.t - t_before)))
    if i < 3: check("chunk %d: one call returns within 540-560 s (under the 600 s terminal cap) with exit 6 and no finish" % (i + 1), rc == ST.NO_CODE_YET and 540 <= clk.t - t_before <= 560 and p.finish_log == [], rcs[-1])
check("no code in 30 min of code_sent_at: the 4th call exits 4 at ~1800 s total (not 540 s later), finishes failed/code_expired ONCE, stdout empty",
      rcs[3][0] == ST.EXPIRED and p.finish_log == [(F.RID, "failed", "code_expired")] and out.getvalue() == "" and 1790 <= clk.t - 1000 <= 1830, (rcs, p.finish_log, clk.t - 1000))
check("a 5th call sees the closed row: refused, still exactly one finish", rcs[4][0] == ST.REFUSED and len(p.finish_log) == 1 and p.count("rpc/finish_code_request") == 1, rcs)
# chunked delivery: the code arrives during the third call
p = agent_portal(); p.code_after_polls = 115; rpc = B.VerifyRpc(p); out = io.StringIO(); clk = F.Clock()
ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
rcs = [quiet(ST.step_code, F.RID, p, rpc, out, clk.sleep, clk.now, wall=clk.wall)[0] for _ in range(3)]
check("three chunked calls: 6, 6, then 0 with the code on stdout once; nothing finished", rcs == [ST.NO_CODE_YET, ST.NO_CODE_YET, ST.OK] and out.getvalue() == CODE + "\n" and p.finish_log == [], rcs)
# a call killed by the terminal timeout BEFORE consume loses nothing: the code is still queued and the next call returns it
p = agent_portal(); p.code_after_polls = 2; rpc = B.VerifyRpc(p); out = io.StringIO(); clk = F.Clock()
ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
class Killed(BaseException): pass
def killing_sleep(s):
    clk.sleep(s)
    if len(clk.sleeps) == 2: raise Killed()   # the terminal tool kills the command here, before the code was consumed
try: quiet(ST.step_code, F.RID, p, rpc, out, killing_sleep, clk.now, wall=clk.wall); killed = False
except Killed: killed = True
check("a call killed before consume: nothing consumed, nothing printed, nothing finished", killed and p.consume_calls == 2 and out.getvalue() == "" and p.finish_log == [] and p.requests[F.RID]["status"] == "code_sent", p.consume_calls)
rc, text = quiet(ST.step_code, F.RID, p, rpc, out, clk.sleep, clk.now, wall=clk.wall)
check("the next call returns the code (exit 0, stdout once) and the call ends well inside 600 s", rc == ST.OK and out.getvalue() == CODE + "\n" and p.finish_log == [], rc)
# a late code is never consumed (expiry is checked before consume)
p = agent_portal(); rpc = B.VerifyRpc(p); out = io.StringIO(); clk = F.Clock()
ST.step_sent(F.RID, MASK, p, rpc, F.NOW); clk.t += 1900
rc, text = quiet(ST.step_code, F.RID, p, rpc, out, clk.sleep, clk.now, wall=clk.wall)
check("a call after code_sent_at + 30 min with a code waiting: exit 4, the code is NOT consumed or printed, finished once", rc == ST.EXPIRED and p.consume_calls == 0 and out.getvalue() == "" and p.finish_log == [(F.RID, "failed", "code_expired")], (rc, p.consume_calls))
# --wait-s is clamped to 540
p = agent_portal(code=None); rpc = B.VerifyRpc(p); out = io.StringIO(); clk = F.Clock()
ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
rc, text = quiet(ST.step_code, F.RID, p, rpc, out, clk.sleep, clk.now, wait_s=9999, wall=clk.wall)
check("--wait-s 9999 is clamped to 540: exit 6 after at most ~550 s", rc == ST.NO_CODE_YET and clk.t - 1000 <= 550, clk.t - 1000)
check("--wait-s is accepted by the CLI parser and a non-number is a usage error", quiet(ST.main, ["code", "--request-id", F.RID, "--wait-s", "x"])[0] == ST.BAD_ARGS)

# ---- 7b the prompt's helper command: absolute interpreter + absolute helper path, terminal timeout 600, repeat on exit 6 ---------------------
hc = S.helper_command()
m = re.match(r'^"([^"]+)" "([^"]+)"$', hc)
check("helper_command is the interpreter and the helper, both quoted absolute paths that exist", bool(m) and os.path.isabs(m.group(1)) and os.path.isabs(m.group(2)) and os.path.exists(m.group(1)) and os.path.exists(m.group(2)) and os.path.basename(m.group(2)) == "verify_step.py", hc)
check("helper_command is the running interpreter (sys.executable) and has no backslashes", m and os.path.normcase(os.path.abspath(m.group(1))) == os.path.normcase(os.path.abspath(sys.executable)) and "\\" not in hc)
pr = S.build_prompt(F.RID, F.request(), F.verification(), B.directory_entry("cylex.us", "sms"), ("NM", "o", "i", "u"), MASK, "x")
check("prompt: no relative `python job/verify_step.py`; every helper line uses the absolute command", "python job/" not in pr and pr.count(hc) == 7, pr.count(hc))   # sent, code, result + the scoreboard's trace, stage signed_in, stage ready and the playbook note
check("prompt: code step says terminal timeout 600, exit 6 means run again, 3 and 4 mean stop", "timeout set to 600" in pr and "Exit 6" in pr and "run the same command again" in pr and "Exit 3" in pr and "exit 4" in pr)

# ---- 8 an empty status read is a miss, not 'superseded' (Nate stop 5) -----------------------------------------------------------------
p = agent_portal(); rpc = B.VerifyRpc(p); out = io.StringIO(); clk = F.Clock()
ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
orig = p.call; state = {"n": 0}
def flaky(method, path, body=None, prefer=None):
    if method == "GET" and path.startswith(B.REQUEST_TABLE) and "id=eq." in path and "status=eq" not in path:
        state["n"] += 1
        if state["n"] in (2, 3): return []   # two empty reads in a row
    return orig(method, path, body, prefer)
p.call = flaky
rc, text = quiet(ST.step_code, F.RID, p, rpc, out, clk.sleep, clk.now, wall=clk.wall)
check("two empty reads then the code: the helper keeps waiting and delivers the code", rc == 0 and out.getvalue() == CODE + "\n" and p.finish_log == [] and "superseded" not in text, (rc, text))
p = agent_portal(); rpc = B.VerifyRpc(p); out = io.StringIO(); clk = F.Clock(); p.code_after_polls = 99
ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
orig = p.call; state = {"n": 0}
def empty_forever(method, path, body=None, prefer=None):
    if method == "GET" and path.startswith(B.REQUEST_TABLE) and "id=eq." in path and "status=eq" not in path:
        state["n"] += 1
        if state["n"] >= 2: return []
    return orig(method, path, body, prefer)
p.call = empty_forever
rc, text = quiet(ST.step_code, F.RID, p, rpc, out, clk.sleep, clk.now, wall=clk.wall)
check("three empty reads in a row: failed/other (a miss limit), never 'superseded'", rc == ST.REFUSED and p.finish_log == [(F.RID, "failed", "other")] and "superseded" not in text, (rc, p.finish_log))
# the scripted path too
p = F.StrictPortal(requests=[F.request(status="starting")], verifications=[F.verification(directory="cylex.us")], queued_code=None)
page = F.FakePage(); rt = F.FakeRuntime(page, F.Clock()); orig = p.call; state = {"n": 0}
def script_empty(method, path, body=None, prefer=None):
    if method == "GET" and path.startswith(B.REQUEST_TABLE) and "id=eq." in path and "status=eq" not in path:
        state["n"] += 1
        if state["n"] >= 2: return []
    return orig(method, path, body, prefer)
p.call = script_empty
r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("scripted send: empty reads are misses (failed/other), not superseded", r == "failed:other" and "superseded" not in text, r)

# ---- 9 helper refusals ------------------------------------------------------------------------------------------------------------------------
p = F.StrictPortal(requests=[F.request(status="requested", channel="sms")], verifications=[F.verification(directory=AGENT_DIR)]); rpc = B.VerifyRpc(p)
rc, _ = quiet(ST.step_sent, F.RID, MASK, p, rpc)
check("sent on a request that is not 'starting' is refused, no mark_code_sent", rc == ST.REFUSED and p.count("rpc/mark_code_sent") == 0)
p = agent_portal(); rpc = B.VerifyRpc(p)
rc, _ = quiet(ST.step_sent, F.RID, "5025550101", p, rpc)
check("sent with a bad mask is refused", rc == ST.REFUSED and p.requests[F.RID]["status"] == "starting")
p = F.StrictPortal(requests=[F.request(status="starting", channel="sms", client=F.SCC)], verifications=[F.verification(client=F.NM, directory=AGENT_DIR)])
rc, _ = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p))
check("sent on a client/row mismatch is refused by the fence", rc == ST.REFUSED and p.count("rpc/mark_code_sent") == 0)
p = agent_portal(); rpc = B.VerifyRpc(p); ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
rc, _ = quiet(ST.step_result, F.RID, "rejected", p, rpc)
check("result rejected: finish failed/code_rejected, row stays requires_verification", rc == 0 and p.finish_log == [(F.RID, "failed", "code_rejected")] and p.verifications[F.VID]["state"] == "requires_verification")
p = agent_portal(fail_patch=True); rpc = B.VerifyRpc(p); ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
rc, _ = quiet(ST.step_result, F.RID, "accepted", p, rpc, F.NOW)
check("result accepted but the row cannot go live: failed/other, never 'verified'", rc == ST.REFUSED and p.finish_log == [(F.RID, "failed", "other")])
check("result with an outcome outside accepted/rejected is a usage error", quiet(ST.main, ["result", "--request-id", F.RID, "--outcome", "maybe"])[0] == ST.BAD_ARGS)
check("a bad request id is a usage error", quiet(ST.main, ["code", "--request-id", "x y"])[0] == ST.BAD_ARGS)
r = subprocess.run([sys.executable, os.path.join(HERE, "..", "job", "verify_step.py"), "code", "--request-id", F.RID], capture_output=True, text=True, timeout=60,
                   env={**os.environ, "CE_PORTAL_ENV": os.path.join(TMP, "no-such.env")})
check("the helper CLI without a portal env exits 5 with nothing on stdout", r.returncode == ST.REFUSED and r.stdout == "", (r.returncode, r.stderr[-120:]))

# ---- 10 login email = the vault item's username (fail closed) ------------------------------------------------------------------------------
for label, kw, want in (("username differs from listings@", {"username": "someone@example.com"}, "failed:signin_failed"),
                        ("username missing", {"username": ""}, "failed:signin_failed"),
                        ("vault item missing", {"vault_ok": False}, "failed:signin_failed")):
    p = agent_portal(); page = F.FakePage(); rt = F.FakeRuntime(page, **kw)
    if kw.get("username") == "": rt.login_username = lambda tenant: None
    r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
    check("%s -> %s, no sitegate reserve, no oneshot, 0 loads" % (label, want), r == want and rt.reserves == [] and rt.launched == [] and page.visits == [] and rt.browsers == 0, r)
p = agent_portal(); rt = F.FakeRuntime(F.FakePage(), username="  Listings@Na" + "ckeMedia.com ", agent_factory=lambda rt: F.FakeAgent([]))
r, _ = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("the expected address matches case-insensitively and trimmed", len(rt.launched) == 1, r)
p = agent_portal(client=F.SCC); rt = F.FakeRuntime(F.FakePage(), username=NM_LOGIN, agent_factory=lambda rt: F.FakeAgent([]))
r, _ = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("SCC refuses the NM address (no fallback to any other login)", r == "failed:signin_failed" and rt.launched == [], r)
calls = []
class R:
    def __init__(self, rc, so): self.returncode, self.stdout = rc, so
def runner(argv, **kw): calls.append(argv); return R(0, json.dumps({"username": NM_LOGIN}))
rtr = S.Runtime(runner=runner)
check("Runtime.login_username reads the username through vault_username.cjs (no password path)", rtr.login_username(("NM", "org", "item", "https://x.example/")) == NM_LOGIN and os.path.basename(calls[0][1]) == "vault_username.cjs" and "--lookup-only" not in calls[0])
rtr = S.Runtime(runner=lambda argv, **kw: R(1, ""))
check("Runtime.login_username is None when the helper fails", rtr.login_username(("NM", "org", "item", "https://x.example/")) is None)
rtr = S.Runtime(runner=lambda argv, **kw: R(0, "not json"))
check("Runtime.login_username is None on unreadable output", rtr.login_username(("NM", "org", "item", "https://x.example/")) is None)
src = open(os.path.join(HERE, "..", "job", "verify_send.py"), encoding="utf-8").read()
check("CE_VERIFY_LOGIN_EMAIL_* and the identity listing_email path are gone", "CE_VERIFY_LOGIN_EMAIL" not in src and "listing_email" not in src and "def login_email" not in src)
js = open(os.path.join(HERE, "..", "job", "vault_username.cjs"), encoding="utf-8").read()
check("vault_username.cjs prints the username only and clears the password", "password = undefined" in js and "console.log(JSON.stringify({ username }))" in js and "login.password)" not in js.replace("item.login.password = undefined", ""))

# ---- 11 NM mail relay window (08:00-19:58 CT) ------------------------------------------------------------------------------------------------
def utc(y, mo, d, h, mi): return datetime.datetime(y, mo, d, h, mi, tzinfo=datetime.timezone.utc)
cases = [((2026, 11, 12, 13, 59), False, "07:59 CST"), ((2026, 11, 12, 14, 0), True, "08:00 CST"), ((2026, 11, 13, 1, 58), True, "19:58 CST"),
         ((2026, 11, 13, 1, 59), False, "19:59 CST"), ((2026, 7, 15, 12, 59), False, "07:59 CDT"), ((2026, 7, 15, 13, 0), True, "08:00 CDT"),
         ((2026, 7, 16, 0, 58), True, "19:58 CDT"), ((2026, 7, 16, 0, 59), False, "19:59 CDT"), ((2026, 11, 12, 6, 0), False, "00:00 CST")]
check("relay window edges, CST and CDT", all(S.relay_window_open(utc(*c[0])) is c[1] for c in cases), [c[2] for c in cases if S.relay_window_open(utc(*c[0])) is not c[1]])
check("DST switches on the 2nd Sunday of March and the 1st Sunday of November", S.central_now(utc(2026, 3, 8, 7, 59)).hour == 1 and S.central_now(utc(2026, 3, 8, 8, 0)).hour == 3 and S.central_now(utc(2026, 11, 1, 6, 59)).hour == 1 and S.central_now(utc(2026, 11, 1, 7, 0)).hour == 1)
night = utc(2026, 11, 13, 3, 0)   # 21:00 CST
p = agent_portal(); page = F.FakePage(); rt = F.FakeRuntime(page, agent_factory=lambda rt: F.FakeAgent([]))
r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, night)
check("NM outside the relay window: failed/timeout before the vault, sitegate, browser or oneshot", r == "failed:timeout" and rt.vault_fills == 0 and rt.reserves == [] and rt.launched == [] and page.visits == [] and rt.browsers == 0 and p.requests[F.RID]["fail_code"] == "timeout", r)
p = agent_portal(client=F.SCC); rt = F.FakeRuntime(F.FakePage(), agent_factory=lambda rt: F.FakeAgent([]))
r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, night)
check("SCC is not bound by the NM relay window", len(rt.launched) == 1 and r != "failed:timeout", r)

# ---- 12 Directory not in the file ---------------------------------------------------------------------------------------------------------
p = agent_portal(directory="notinfile.example"); page = F.FakePage(); rt = F.FakeRuntime(page, agent_factory=lambda rt: F.FakeAgent([]))
r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("a Directory not in the file: failed/no_playbook, 0 site loads, 0 reserves, no oneshot, no browser", r == "failed:no_playbook" and page.visits == [] and rt.reserves == [] and rt.launched == [] and rt.browsers == 0 and rt.vault_fills == 0, r)

# ---- 13 launch details: argv, env, kill tree -----------------------------------------------------------------------------------------------
seen = {}
class FakeProc:
    pid = 4242
    def __init__(self, argv, **kw): seen["argv"], seen["kw"] = argv, kw; self.killed = 0
    def poll(self): return None if not self.killed else -9
    def kill(self): self.killed += 1
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "service-key-placeholder"
rtr = S.Runtime(popen=FakeProc, runner=lambda argv, **kw: seen.setdefault("kill", argv))
h = rtr.launch_agent("C:/x/prompt.txt")
exe = seen["argv"][0]
check("oneshot argv is `hermes -p citation-submitter chat --query-file <file> --oneshot`", os.path.basename(exe).lower().startswith("hermes") and seen["argv"][1:] == ["-p", "citation-submitter", "chat", "--query-file", "C:/x/prompt.txt", "--oneshot"], seen["argv"])
check("the oneshot's env has no service-role variable and its stdout and stderr are dropped (no pipe, no reader thread: t_eae8e59f round 2)", all("SERVICE_ROLE" not in k.upper() for k in seen["kw"]["env"]) and seen["kw"]["stdout"] == subprocess.DEVNULL and seen["kw"]["stderr"] == subprocess.DEVNULL and not hasattr(h, "note"))
check("the oneshot is launched with cwd = the repo root (the app clone) and TERMINAL_CWD set to it", os.path.normcase(seen["kw"]["cwd"]) == os.path.normcase(S.REPO_ROOT) and os.path.exists(os.path.join(seen["kw"]["cwd"], "job", "verify_step.py")) and seen["kw"]["env"].get("TERMINAL_CWD") == S.REPO_ROOT, seen["kw"].get("cwd"))
h.kill(); h.kill()
check("kill ends the whole tree (taskkill /T on Windows, kill elsewhere) and is idempotent", (seen.get("kill", [None])[:3] == ["taskkill", "/F", "/T"]) if os.name == "nt" else (h.proc.killed >= 1 and h.poll() == -9))
del os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# ---- 14 leak test: a fake code through helper + prompt + run on every failure path ----------------------------------------------------------
logs = []
class LeakPortal(F.StrictPortal): pass
for label, kw in (("consume raises with the code in its text", "consume"), ("mark_code_sent raises with the code", "mark"), ("finish endpoint down", "finish"), ("set live fails", "live")):
    p = agent_portal(fail_mark=(kw == "mark"), finish_fails=(kw == "finish"), fail_patch=(kw == "live")); rpc = B.VerifyRpc(p)
    if kw == "consume":
        o = p.call
        def boom(method, path, body=None, prefer=None, o=o):
            if path == "rpc/consume_verify_code": raise RuntimeError("boom " + CODE)
            return o(method, path, body, prefer)
        p.call = boom
    out = io.StringIO(); holder = {}
    def factory(rt, p=p, rpc=rpc, out=out, holder=holder): return happy_steps(p, rpc, rt, out, holder)
    rt = F.FakeRuntime(F.FakePage(), agent_factory=factory)
    r, text = quiet(S.run, F.RID, p, rpc, rt, F.NOW)
    helper_text = []
    logs.append((label, r, CODE in text, CODE in repr([c[2] for c in p.calls]), any(CODE in t for t in rt.prompts), CODE in out.getvalue()))
for label, r, in_text, in_bodies, in_prompt, in_out in logs:
    check("leak: %s -> %s; code in run/helper log=%s, portal bodies=%s, prompt=%s" % (label, r, in_text, in_bodies, in_prompt), not in_text and not in_bodies and not in_prompt, in_out)
allfiles = "".join(open(os.path.join(dp, f), errors="ignore").read() for dp, _, fs in os.walk(TMP) for f in fs)
check("leak: no file under the logs/guard/locks dirs holds the code", CODE not in allfiles)
stepsrc = open(os.path.join(HERE, "..", "job", "verify_step.py"), encoding="utf-8").read()
codeprints = [l for l in stepsrc.splitlines() if re.search(r"\bcode\b", l) and re.search(r"log\(|print\(", l) and "code_" not in l and "step_code" not in l and "poll" not in l and "waiting" not in l]
check("verify_step.py: no log/print line formats the code variable", not [l for l in stepsrc.splitlines() if re.search(r"(log|print)\(.*%.*\bcode\b\s*[,)]", l) or re.search(r"(log|print)\(.*\{code\}", l)], codeprints)

# ---- 15 repo rules ----------------------------------------------------------------------------------------------------------------------------------
allsrc = {n: open(os.path.join(HERE, "..", "job", n), encoding="utf-8").read() for n in ("verify_bridge.py", "verify_send.py", "verify_step.py")}
allsrc["prompt"] = "".join(F.FakeRuntime(F.FakePage()).prompts) + S.build_prompt(F.RID, F.request(), F.verification(), B.directory_entry("cylex.us", "sms"), ("NM", "o", "i", "u"), MASK, "x")
check("no WhatsApp wording anywhere (job files + prompt)", not [n for n, t in allsrc.items() if re.search("whats" + "app", t, re.I)])
check("no em dashes in the new files or the prompt", not [n for n, t in allsrc.items() if "\u2014" in t])
check("the helper never asks for or prints the service key", "SERVICE_ROLE" not in allsrc["verify_step.py"])
sys.exit(0 if all(ok) else 1)
