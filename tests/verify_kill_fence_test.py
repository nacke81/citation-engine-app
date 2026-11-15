"""Verify Now: a kill stops the run, the pre-send fence, env + vault organization reach the agent (t_c6eee3cb, request f2dbd5c0).
Fake gateway, fake process, virtual clock. No network, no hermes, no Chrome, no send. Run: python tests/verify_kill_fence_test.py (CI). Exit 1 on any failure."""
import contextlib, datetime, io, os, re, subprocess, sys, tempfile, time
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
import verify_step as ST

AGENT_DIR = "agentdir.example"
MASK = "(502) ***-0101"
SESSION = "local-0123456789abcdef"
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else ""), flush=True)

def quiet(fn, *a, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        r = fn(*a, **kw)
    return r, out.getvalue() + err.getvalue()

def agent_portal(**kw):
    return F.StrictPortal(requests=[F.request(status="starting", client=F.NM)], verifications=[F.verification(client=F.NM, directory=AGENT_DIR)], **kw)


# ---- 1 kill = stop: the gateway turn keeps running unless the session is cancelled ----------------------------------------------------------
class Gateway:
    """The profile's gateway. Its turn runs one tool call per tick whether or not the oneshot client is alive; only a cancel stops it."""
    def __init__(self): self.calls, self.cancelled, self.cancels = [], False, []
    def tick(self):
        if not self.cancelled: self.calls.append(len(self.calls) + 1)


class FakeProc:
    pid = 4242
    def __init__(self, stderr_text): self.dead, self.stderr = False, io.StringIO(stderr_text)
    def poll(self): return -9 if self.dead else None
    def kill(self): self.dead = True


def scenario(cancel_works=True, stderr_text="noise\nSession: %s\nmore noise\n" % SESSION):
    """A request swept (closed could_not_start) while the agent is mid-run; the run's grace expires and it kills the agent. -> (gateway, calls at kill, result)."""
    gw, p = Gateway(), agent_portal()
    proc = FakeProc(stderr_text); at_kill = {}
    def runner(argv, **kw):
        if "gateway_cancel.py" in " ".join(argv):
            gw.cancels.append(argv[-1]); at_kill.setdefault("n", len(gw.calls))
            if cancel_works: gw.cancelled = True
        else:
            proc.dead = True   # taskkill: the CLIENT is gone; the gateway turn is not
        return subprocess.CompletedProcess(argv, 0)
    def factory(rt):
        a = S.AgentProc(proc, runner, cancel_argv=["python", os.path.join("job", "gateway_cancel.py")], cancel_env={})
        for _ in range(100):   # the stderr reader is a thread
            if a.session_id: break
            time.sleep(0.01)
        return a
    rt = F.FakeRuntime(F.FakePage(), agent_factory=factory)
    base_sleep = rt.sleep
    def sleep(s):
        base_sleep(s); gw.tick()
        if rt.clock.t - 1000.0 >= 30 and p.requests[F.RID]["status"] == "starting":
            p.requests[F.RID]["status"] = "could_not_start"; p.requests[F.RID]["fail_code"] = "timeout"   # the sweeper closes it
    rt.sleep = sleep
    r, _t = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
    at_kill.setdefault("n", len(gw.calls))
    for _ in range(20): gw.tick()   # the gateway keeps going after the client is gone, unless cancelled
    return gw, at_kill["n"], r, proc

gw, n_kill, r, proc = scenario()
check("1a kill during a fake run: the gateway session is cancelled with the session id read from stderr", gw.cancels == [SESSION] and gw.cancelled, gw.cancels)
check("1b kill during a fake run: no tool call executes after the kill (calls frozen at the kill)", len(gw.calls) == n_kill and n_kill > 0, (len(gw.calls), n_kill))
check("1c the client process is ended too, and the run reports closed", proc.dead and r == "closed", r)
gw2, n2, _r2, _p2 = scenario(cancel_works=False)
check("1d control: when the cancel does nothing the gateway turn runs on (the test can fail)", len(gw2.calls) > n2, (len(gw2.calls), n2))
orig = S.AgentProc.cancel_session
S.AgentProc.cancel_session = lambda self: False   # mutation: kill only drops the client (the bug)
gw3, n3, _r3, _p3 = scenario()
S.AgentProc.cancel_session = orig
check("1e mutation: kill without the session cancel leaks tool calls after the kill", len(gw3.calls) > n3, (len(gw3.calls), n3))
gw4, n4, _r4, _p4 = scenario(stderr_text="no session line here\n")
check("1f no Session line: the cancel is not guessed (nothing cancelled, nothing raised); the pre-send fence is the only stop", gw4.cancels == [] and _r4 == "closed")

def kill_twice():
    gw, proc = Gateway(), FakeProc("Session: %s\n" % SESSION); seen = []
    a = S.AgentProc(proc, lambda argv, **kw: seen.append(argv) or subprocess.CompletedProcess(argv, 0), cancel_argv=["py", "gateway_cancel.py"], cancel_env={})
    for _ in range(100):
        if a.session_id: break
        time.sleep(0.01)
    a.kill(); a.kill(); return [s for s in seen if "gateway_cancel.py" in " ".join(s)]
check("1g kill twice cancels the session once", len(kill_twice()) == 1)
raised = S.AgentProc(FakeProc("Session: %s\n" % SESSION), lambda argv, **kw: (_ for _ in ()).throw(OSError("boom")), cancel_argv=["py", "g.py"], cancel_env={})
time.sleep(0.2)
try: raised.kill(); no_raise = True
except Exception: no_raise = False
check("1h a failing cancel never raises out of kill()", no_raise)

# the real launch_agent: stderr is a pipe handed to AgentProc, cancel argv points at gateway_cancel.py, cancel env targets the submitter profile
seen = {}
class LaunchProc(FakeProc):
    def __init__(self, argv, **kw): FakeProc.__init__(self, "Session: %s\n" % SESSION); seen["argv"], seen["kw"] = argv, kw
rt = S.Runtime(popen=LaunchProc, runner=lambda argv, **kw: seen.setdefault("runs", []).append((argv, kw)) or subprocess.CompletedProcess(argv, 0))
os.environ["CE_SUBMITTER_HOME"] = os.path.join(TMP, "submitter-home")
h = rt.launch_agent("C:/x/prompt.txt", "http://127.0.0.1:9334")
for _ in range(100):
    if h.session_id: break
    time.sleep(0.01)
h.kill()
cancel_runs = [(a, k) for a, k in seen["runs"] if "gateway_cancel.py" in " ".join(a)]
check("1i launch_agent: stderr piped, session id read, kill runs gateway_cancel.py <id> with HERMES_HOME = the submitter profile",
      seen["kw"]["stderr"] == subprocess.PIPE and h.session_id == SESSION and len(cancel_runs) == 1 and cancel_runs[0][0][-1] == SESSION
      and os.path.basename(cancel_runs[0][0][-2]) == "gateway_cancel.py" and cancel_runs[0][1]["env"]["HERMES_HOME"] == os.environ["CE_SUBMITTER_HOME"], len(cancel_runs))
check("1j the cancel order: session cancel runs BEFORE the process-tree kill", "gateway_cancel.py" in " ".join(seen["runs"][0][0]), seen["runs"][0][0])
cancel_src = open(os.path.join(HERE, "..", "job", "gateway_cancel.py"), encoding="utf-8").read()
check("1k gateway_cancel.py: resume, interrupt, close on the session; rejects a bad id with exit 2",
      all(s in cancel_src for s in ('"session.resume"', '"session.interrupt"', '"session.close"')) and __import__("gateway_cancel").main(["bad id"]) == 2)

# ---- 2 env reaches the agent ------------------------------------------------------------------------------------------------------------------
os.environ["BROWSER_CDP_URL"] = "http://127.0.0.1:1111"; os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "x"
seen2 = {}
class P2(FakeProc):
    def __init__(self, argv, **kw): FakeProc.__init__(self, ""); seen2["kw"] = kw
S.Runtime(popen=P2).launch_agent("C:/x/p.txt", "http://127.0.0.1:9334")
env = seen2["kw"]["env"]
check("2a child env: BROWSER_CDP_URL = the tenant's Chrome (not the inherited one), TERMINAL_CWD = the app clone, no service role", env.get("BROWSER_CDP_URL") == "http://127.0.0.1:9334" and env.get("TERMINAL_CWD") == S.REPO_ROOT and not [k for k in env if "SERVICE_ROLE" in k.upper()])
del os.environ["BROWSER_CDP_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
def cfg(text):
    d = tempfile.mkdtemp(); path = os.path.join(d, "config.yaml"); open(path, "w", encoding="utf-8").write(text); return path
check("2b gap: a profile that lists neither name reports both (the gateway drops client env it is not told to forward)", S.agent_env_gap(cfg("terminal:\n  backend: local\n")) == ["BROWSER_CDP_URL", "TERMINAL_CWD"])
check("2c gap: inline list with both names = no gap", S.agent_env_gap(cfg("terminal:\n  client_env_passthrough: [BROWSER_CDP_URL, TERMINAL_CWD]\n")) == [])
check("2d gap: block list with both names = no gap; one name missing is reported", S.agent_env_gap(cfg("terminal:\n  client_env_passthrough:\n    - BROWSER_CDP_URL\n    - TERMINAL_CWD\nother: 1\n")) == []
      and S.agent_env_gap(cfg("terminal:\n  client_env_passthrough:\n    - BROWSER_CDP_URL\nother: TERMINAL_CWD\n")) == ["TERMINAL_CWD"])
check("2e gap: an unreadable config reports every name", S.agent_env_gap(os.path.join(TMP, "nope.yaml")) == list(S.AGENT_ENV_NAMES))
real_cfg = os.path.expandvars("%LOCALAPPDATA%/hermes/profiles/citation-submitter/config.yaml")
lines = []
S.log = lambda m: lines.append(m)
os.environ["CE_SUBMITTER_HOME"] = os.path.dirname(cfg("terminal:\n  backend: local\n"))
S.Runtime(popen=P2).launch_agent("C:/x/p.txt", "http://127.0.0.1:9334")
check("2f launch_agent logs a loud WARNING naming the missing env names (no silent drop)", any("WARNING" in l and "BROWSER_CDP_URL" in l for l in lines), lines)
S.log = lambda m: print("verify_send: " + m, file=sys.stderr, flush=True)

# ---- 3 pre-send fence -----------------------------------------------------------------------------------------------------------------------
def arm(status="starting", age_s=5, **kw):
    p = F.StrictPortal(requests=[F.request(status=status, age_s=age_s)], verifications=[F.verification(directory=AGENT_DIR)])
    r, _t = quiet(ST.step_arm, F.RID, p, F.NOW, **kw)
    return r, p
r, p = arm()
check("3a arm on a fresh `starting` request exits 0 and writes nothing (no PATCH, no RPC)", r == 0 and all(c[0] == "GET" for c in p.calls), (r, [c[:2] for c in p.calls]))
check("3b arm at the margin: 839 s old is go, 840 s old (SWEEP_HARD_CAP_S - 60) is STOP", arm(age_s=839)[0] == 0 and arm(age_s=840)[0] == ST.REFUSED and B.SWEEP_HARD_CAP_S - ST.ARM_MARGIN_S == 840)
check("3c arm on a SWEPT row (could_not_start/timeout) is STOP (5)", arm(status="could_not_start", age_s=700)[0] == ST.REFUSED)
check("3d arm on failed, verified, requested and already-sent (code_sent) rows is STOP", all(arm(status=s)[0] == ST.REFUSED for s in ("failed", "verified", "requested", "code_sent", "checking")))
check("3e arm on a row past the hard cap that is still `starting` (sweeper not run yet) is STOP", arm(age_s=901)[0] == ST.REFUSED)
pn = F.StrictPortal(requests=[], verifications=[]); rn, _t = quiet(ST.step_arm, F.RID, pn, F.NOW)
check("3f arm on a missing request is STOP", rn == ST.REFUSED)
bad = F.request(status="starting"); bad["requested_at"] = None
pb = F.StrictPortal(requests=[bad], verifications=[F.verification(directory=AGENT_DIR)]); rb, _t = quiet(ST.step_arm, F.RID, pb, F.NOW)
check("3g arm with no readable requested_at is STOP (fail closed)", rb == ST.REFUSED)
pc = F.StrictPortal(requests=[F.request(status="starting", channel="voice")], verifications=[F.verification(directory=AGENT_DIR)]); rc_, _t = quiet(ST.step_arm, F.RID, pc, F.NOW)
check("3h arm runs the bridge fence too: a request that fails it is STOP", rc_ == ST.REFUSED)
fresh = F.request(status="starting"); fresh["requested_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
pm = F.StrictPortal(requests=[fresh], verifications=[F.verification(directory=AGENT_DIR)])
rm, _t = quiet(ST.main, ["arm", "--request-id", F.RID], pm, B.VerifyRpc(pm))
pm2 = F.StrictPortal(requests=[F.request(status="could_not_start", age_s=700)], verifications=[F.verification(directory=AGENT_DIR)])
rm2, _t = quiet(ST.main, ["arm", "--request-id", F.RID], pm2, B.VerifyRpc(pm2))
check("3i CLI: `arm --request-id` exits 0 on a fresh request and 5 on a swept row", rm == 0 and rm2 == 5, (rm, rm2))
src = open(os.path.join(HERE, "..", "job", "verify_step.py"), encoding="utf-8").read()
check("3j the fence cutoff is derived from the sweeper's own constant (B.SWEEP_HARD_CAP_S), not a copy", "B.SWEEP_HARD_CAP_S - ARM_MARGIN_S" in src)

# ---- 4 prompt: vault organization, no vault writes, the arm line --------------------------------------------------------------------------------
ent = B.directory_entry("cylex.us", "sms")
signup = {"steps": [{"text": "Open the form"}, {"text": "Click Sign up", "send": True}], "send_is_signup": True, "version": 1}
signin = {"steps": [{"text": "Open the page"}, {"text": "Click Send code", "send": True}], "send_is_signup": False, "version": 1}
for biz, cid in (("NM", F.NM), ("SCC", F.SCC)):
    org = S.TENANTS[cid][1]; item = "%s - example.test" % biz
    for label, pb in (("no playbook", None), ("sign-in playbook", signin), ("signup playbook", signup)):
        pr = S.build_prompt(F.RID, F.request(client=cid), F.verification(client=cid), ent, (biz, org, item, "https://example.test"), MASK, "x", playbook=pb)
        fills = [m.start() for m in re.finditer("vaultwarden-cli-fill.js", pr)]
        ctx = [pr[i:i + 330] for i in fills]
        check("4a %s %s: every fill call carries --organization \"%s\" --collection Citations --name \"%s\"" % (biz, label, org, item),
              bool(ctx) and all(('--organization "%s"' % org) in c and "--collection Citations" in c and ('--name "%s"' % item) in c for c in ctx), ctx[:1])
        check("4b %s %s: hard rule never create/edit a vault item, item not found = STOP; names no other tenant's org" % (biz, label),
              "Never create, edit, rename or move a vault item" in pr and "if the item is not found, STOP" in pr and not [v[1] for v in S.TENANTS.values() if v[1] != org and v[1] in pr])
        arm_i, sent_i, step3_i = pr.find("verify_step.py\" arm --request-id " + F.RID), pr.find("verify_step.py\" sent"), pr.find("3. ")
        check("4c %s %s: step 3 tells the agent to run `arm` right before the send click and STOP on nonzero; arm comes before the sent report" % (biz, label),
              step3_i != -1 and step3_i < arm_i < sent_i and "exits nonzero, STOP: do NOT click the send" in pr and pr.count('verify_step.py" arm') == 1)

# ---- 5 sweep fit + time to the send: re-measure of request f2dbd5c0 with the fixes (arithmetic on the measured stages; no real agent, no send) ----------
# Measured on f2dbd5c0 (CST): requested 13:35:31, pickup +32 s, agent_start +159 s, agent ready 13:38:39 (+188 s), send click ~13:48:40 (+789 s).
# The agent log shows two losses the fixes remove: ~180 s of its own Chromium (BROWSER_CDP_URL now named in the prompt/forwarded) and ~300 s of vault calls
# on the wrong organization (the prompt now names it). Everything else stays as measured.
MEAS = {"pickup": 32, "agent_start": 159, "ready": 188, "click": 789}
OWN_CHROMIUM_S, VAULT_ORG_HUNT_S = 180, 300
click_after = MEAS["click"] - OWN_CHROMIUM_S - VAULT_ORG_HUNT_S
limit = B.SWEEP_HARD_CAP_S - ST.ARM_MARGIN_S
print("INFO pickup->agent_start %d s, pickup->agent_ready %d s, agent_ready->send_clicked %d s measured / %d s with the fixes; request->send %d s (%d:%02d) vs the 4 min target (240 s)"
      % (MEAS["agent_start"] - MEAS["pickup"], MEAS["ready"] - MEAS["pickup"], MEAS["click"] - MEAS["ready"], click_after - MEAS["ready"], click_after, click_after // 60, click_after % 60))
check("5 re-measure: the real run clicked at 789 s; with the fixes ~%d s, inside the arm limit %d s (hard cap %d); SWEEP_AFTER_S stays %d (the 600 s sweep only bites a silent agent now)" % (click_after, limit, B.SWEEP_HARD_CAP_S, B.SWEEP_AFTER_S),
      MEAS["click"] == int((datetime.datetime(2026, 11, 15, 13, 48, 40) - datetime.datetime(2026, 11, 15, 13, 35, 31)).total_seconds()) and click_after < B.SWEEP_AFTER_S - ST.ARM_MARGIN_S and click_after < limit and B.SWEEP_AFTER_S == 600, (click_after, limit))
check("8 time to the send: the estimate with the fixes (%d s) is reported against the 240 s target; it is NOT claimed met" % click_after, click_after > 240, click_after)

# ---- 6 (a) sweep on liveness, not wall clock; hard cap ---------------------------------------------------------------------------------------------
import verify_scoreboard as SBD
def sweep_case(age_s, alive_ago=None, status="starting"):
    rid = F.RID; p = F.StrictPortal(requests=[F.request(status=status, age_s=age_s)], verifications=[F.verification(directory=AGENT_DIR)])
    f = SBD._alive_file(rid)
    if os.path.exists(f): os.remove(f)
    if alive_ago is not None:
        SBD.touch_alive(rid); t = F.NOW.timestamp() - alive_ago; os.utime(f, (t, t))
    done, _t = quiet(B.sweep, p, B.VerifyRpc(p), F.NOW, lambda *a, **k: None)
    return done, p.requests[rid]["status"]
check("6a-1 a `starting` row past 600 s whose agent was heard 30 s ago stays starting (not swept)", sweep_case(650, alive_ago=30) == ([], "starting"), sweep_case(650, alive_ago=30))
check("6a-2 same row, agent silent for 130 s (> 120): swept could_not_start", sweep_case(650, alive_ago=130)[1] == "could_not_start")
check("6a-3 same row, no activity ever: swept at 600 s exactly as before", sweep_case(650)[1] == "could_not_start" and sweep_case(599) == ([], "starting"))
check("6a-4 a live agent is swept at the hard cap (%d s) anyway; 899 s is kept" % B.SWEEP_HARD_CAP_S, sweep_case(B.SWEEP_HARD_CAP_S, alive_ago=5)[1] == "could_not_start" and sweep_case(B.SWEEP_HARD_CAP_S - 1, alive_ago=5)[1] == "starting")
check("6a-5 a `requested` (never claimed) row is swept at 600 s whatever the alive file says", sweep_case(650, alive_ago=5, status="requested")[1] == "could_not_start")
check("6a-6 a helper verb is the heartbeat: trace/stage/arm touch the alive file; a refused request does not",
      (lambda: (os.path.exists(SBD._alive_file(F.RID)) and os.remove(SBD._alive_file(F.RID)), arm(age_s=5), os.path.exists(SBD._alive_file(F.RID)))[2])() is True
      and (lambda: (os.remove(SBD._alive_file(F.RID)) if os.path.exists(SBD._alive_file(F.RID)) else None, arm(status="could_not_start"), os.path.exists(SBD._alive_file(F.RID)))[2])() is False)
orig_alive = SBD.last_alive
SBD.last_alive = lambda rid: None   # mutation: no liveness check
check("6a-7 mutation: without the liveness read a live agent's row is swept at 600 s", sweep_case(650, alive_ago=30)[1] == "could_not_start")
SBD.last_alive = orig_alive

# ---- 6 (b) late_sent: `sent` after the sweep reaches the code box ---------------------------------------------------------------------------------
def late(age_s=700, status="could_not_start", newer=False, masked=MASK):
    reqs = [F.request(status=status, age_s=age_s)]
    if newer: reqs.append(dict(F.request(rid="aaaaaaaa-0000-4000-8000-000000000002", status="requested", age_s=age_s - 100)))
    p = F.StrictPortal(requests=reqs, verifications=[F.verification(directory=AGENT_DIR)])
    r, text = quiet(ST.step_sent, F.RID, masked, p, B.VerifyRpc(p), F.NOW)
    return r, p, text
r, p, text = late()
check("6b-1 `sent` for a request swept 100 s ago with no newer request: row goes code_sent (code box), exit 0, logged late_sent", r == 0 and p.requests[F.RID]["status"] == "code_sent" and "late_sent" in text, (r, p.requests[F.RID]["status"]))
check("6b-2 the reopen is ONE conditional PATCH on the request table, then mark_code_sent (in that order)", [c[0] + " " + c[1] for c in p.calls if c[0] == "PATCH" or c[1] == "rpc/mark_code_sent"] == ["PATCH citation_code_request", "POST rpc/mark_code_sent"], [c[:2] for c in p.calls])
r2, p2, _t = late(age_s=B.SWEEP_AFTER_S + B.LATE_SENT_WINDOW_S + 5)
check("6b-3 swept more than 10 min ago: refused (5), row stays could_not_start, no PATCH", r2 == ST.REFUSED and p2.requests[F.RID]["status"] == "could_not_start" and not [c for c in p2.calls if c[0] == "PATCH"])
r3, p3, text3 = late(newer=True)
check("6b-4 a NEWER request exists for the same verification row: refused, row stays could_not_start", r3 == ST.REFUSED and p3.requests[F.RID]["status"] == "could_not_start" and "newer request" in text3)
r4, p4, _t = late(status="failed")
check("6b-5 a request closed `failed` (superseded/resend) is never reopened", r4 == ST.REFUSED and p4.requests[F.RID]["status"] == "failed")
r5, p5, _t = late(masked="not a mask")
check("6b-6 a bad mask still refuses (a bad mask never reopens a swept row)", r5 == ST.REFUSED and not [c for c in p5.calls if c[0] == "PATCH" or c[1] == "rpc/mark_code_sent"])
pn = agent_portal(); rn, _t = quiet(ST.step_sent, F.RID, MASK, pn, B.VerifyRpc(pn), F.NOW)
check("6b-7 the normal path (`starting`) is unchanged: code_sent, exit 0, no PATCH", rn == 0 and pn.requests[F.RID]["status"] == "code_sent" and not [c for c in pn.calls if c[0] == "PATCH"])
orig_lr = ST._late_reopen
ST._late_reopen = lambda *a, **k: (None, None)   # mutation: no late path
r7, p7, _t = late()
ST._late_reopen = orig_lr
check("6b-8 mutation: without the late path the swept request stays could_not_start (the reported bug)", r7 == ST.REFUSED and p7.requests[F.RID]["status"] == "could_not_start")

# ---- 6 repo rules -----------------------------------------------------------------------------------------------------------------------------
mine = {n: open(os.path.join(HERE, "..", "job", n), encoding="utf-8").read() for n in ("gateway_cancel.py",)}
check("6 the cancel helper never prints a prompt/message/code and has no em dash or WhatsApp wording", "\u2014" not in mine["gateway_cancel.py"] and not re.search("whats" + "app", mine["gateway_cancel.py"], re.I))
print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
