"""verify_arm tests (t_282b646e). Fake armer / fake Twilio transport, fake agent, virtual clock. No network, no Twilio, no Chrome, no real code or number.
Covers: arm on a NM phone-call request (before the agent starts), no arm on sms / SCC, disarm on every terminal path, arm/disarm failure never fatal,
the Sync REST shapes, the sweeper, the window log, and mutations that drop the disarm / arm for sms.
Run: python tests/verify_arm_test.py   exit 1 on any failure."""
import contextlib, datetime, io, json, os, re, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ["CE_LOGS"] = os.path.join(TMP, "logs")
os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json")
os.environ["CE_VERIFY_LOCKS"] = os.path.join(TMP, "locks")
os.environ["CE_VERIFY_DIRECTORIES"] = os.path.join(HERE, "verify_directories_fixture.json")
os.environ["CE_NO_CARDS"] = "1"
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json"); os.environ["CE_RUNS"] = tempfile.mkdtemp()
os.environ["CE_VERIFY_WINDOWS"] = os.path.join(TMP, "windows.json")
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
import verify_fakes as F
import os as _fo; _fo.environ["CE_PORTAL_ENV"] = _fo.path.join(_fo.path.dirname(_fo.path.abspath(__file__)), "no-such-portal.env")  # t_2ddc7067: fail closed, never the prod portal
import verify_bridge as B
import verify_send as S
import verify_arm as AR
import verify_step as ST; F.default_evidence(ST)

CODE = "906417"   # fake
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


class FakeArmer:
    """Records calls in a shared event list (with the runtime's launch events) so ORDER is testable."""
    def __init__(self, events, arm_raises=False, disarm_raises=False, arm_result=True, disarm_result=True):
        self.events, self.arm_raises, self.disarm_raises, self.arm_result, self.disarm_result = events, arm_raises, disarm_raises, arm_result, disarm_result
    def arm(self, rid):
        self.events.append(("arm", rid))
        if self.arm_raises: raise RuntimeError("twilio down " + CODE)
        return self.arm_result
    def disarm(self, rid=None):
        self.events.append(("disarm", rid))
        if self.disarm_raises: raise RuntimeError("twilio down " + CODE)
        return self.disarm_result
    def armed_request(self): return None


class ArmRt(F.FakeRuntime):
    def __init__(self, page, events, armer=None, **kw):
        super().__init__(page, **kw)
        self.events, self.armer = events, armer
    def launch_agent(self, path, cdp=None):
        self.events.append(("launch", None)); return super().launch_agent(path, cdp)


def portal(channel="phone-call", client=F.NM):
    return F.StrictPortal(requests=[F.request(status="starting", channel=channel, client=client)], verifications=[F.verification(client=client, directory=AGENT_DIR)], queued_code=CODE)

def happy(p, rpc, out, holder):
    return lambda rt: F.FakeAgent([
        lambda: holder.__setitem__("sent", ST.step_sent(F.RID, MASK, p, rpc, F.NOW)),
        lambda: holder.__setitem__("code", ST.step_code(F.RID, p, rpc, out, rt.sleep, rt.now, wall=rt.wall)),
        lambda: holder.__setitem__("result", ST.step_result(F.RID, "accepted", p, rpc, F.NOW))])

_hc = S.helper_command
S.helper_command = lambda: '"C:/fixture/python" "C:/fixture/job/verify_step.py"'

def run_case(factory, channel="phone-call", client=F.NM, armer_kw=None, rt_cls=ArmRt, p=None, username=None):
    p = p or portal(channel, client); rpc = B.VerifyRpc(p); events = []
    armer = FakeArmer(events, **(armer_kw or {}))
    rt = rt_cls(F.FakePage(), events, armer=armer, agent_factory=factory(p, rpc), username=username) if rt_cls is ArmRt else rt_cls(F.FakePage(), events, armer=armer)
    r, text = quiet(S.run, F.RID, p, rpc, rt, F.NOW)
    return r, text, events, p, rt

# ---- 1 arm on a phone-call request, right before the agent starts; disarm after verified ----
holder = {}
r, text, ev, p, rt = run_case(lambda p, rpc: happy(p, rpc, io.StringIO(), holder))
check("phone-call: verified", r == "verified" and p.requests[F.RID]["status"] == "verified", r)
check("phone-call: armed once with the request id, before the agent launches", [e for e in ev if e[0] in ("arm", "launch")] == [("arm", F.RID), ("launch", None)], ev)
check("phone-call: disarmed exactly once, after the launch, with the request id", [e for e in ev if e[0] == "disarm"] == [("disarm", F.RID)] and ev.index(("disarm", F.RID)) > ev.index(("launch", None)), ev)
check("phone-call: the fake code never reaches the log", CODE not in text)

# ---- 2 sms never arms; SCC phone-call never arms (the line is the NM tenant's) ----
holder = {}
r, text, ev, p, rt = run_case(lambda p, rpc: happy(p, rpc, io.StringIO(), holder), channel="sms")
check("sms: verified and NOTHING armed or disarmed", r == "verified" and [e for e in ev if e[0] in ("arm", "disarm")] == [], (r, ev))
holder = {}
r, text, ev, p, rt = run_case(lambda p, rpc: happy(p, rpc, io.StringIO(), holder), client=F.SCC)
check("SCC phone-call: never arms the NM line", [e for e in ev if e[0] in ("arm", "disarm")] == [], (r, ev))

# ---- 3 disarm on every terminal path ----
def only_launch(): return lambda p, rpc: (lambda rt: F.FakeAgent([], hang=True))
r, text, ev, p, rt = run_case(only_launch())
check("failed (agent never sends, killed at the cap): disarmed once", r == "failed:send_failed" and [e for e in ev if e[0] == "disarm"] == [("disarm", F.RID)] and rt.agent.kills >= 1, (r, ev))
class BoomRt(ArmRt):
    def launch_agent(self, path, cdp=None): self.events.append(("launch", None)); raise OSError("hermes missing")
p = portal(); events = []; rt = BoomRt(F.FakePage(), events, armer=FakeArmer(events))
r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("agent cannot start: armed then disarmed, request failed", r == "failed:send_failed" and [e[0] for e in events] == ["arm", "launch", "disarm"], (r, events))
p = portal(); rpc = B.VerifyRpc(p); events = []
def close_it(): p.requests[F.RID]["status"] = "failed"; p.requests[F.RID]["fail_code"] = "other"
rt = ArmRt(F.FakePage(), events, armer=FakeArmer(events), agent_factory=lambda rt: F.FakeAgent([lambda: None, close_it, lambda: None, lambda: None]))
r, text = quiet(S.run, F.RID, p, rpc, rt, F.NOW)
check("closed by the portal/helper (client asked again): disarmed once", [e for e in events if e[0] == "disarm"] == [("disarm", F.RID)], (r, events))
p = portal(); rpc = B.VerifyRpc(p); events = []
rt = ArmRt(F.FakePage(), events, armer=FakeArmer(events), username="someone.else@example.com", agent_factory=lambda rt: F.FakeAgent([], hang=True))
r, text = quiet(S.run, F.RID, p, rpc, rt, F.NOW)
check("killed by the vault identity check: disarmed once", r == "failed:signin_failed" and [e for e in events if e[0] == "disarm"] == [("disarm", F.RID)] and rt.agent.kills >= 1, (r, events))
class CrashRt(ArmRt):
    def write_prompt(self, rid, text): raise RuntimeError("disk full")
p = portal(); events = []; rt = CrashRt(F.FakePage(), events, armer=FakeArmer(events))
r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("a crash before the arm leaves nothing to disarm", [e[0] for e in events if e[0] in ("arm", "disarm")] == [], (r, events))
class StatusBoomRt(ArmRt):
    def vault_lookup(self, t): return True
p = portal(); rpc = B.VerifyRpc(p); events = []
class RaisingAgent(F.FakeAgent):
    def poll(self): raise RuntimeError("unexpected")
rt = ArmRt(F.FakePage(), events, armer=FakeArmer(events), agent_factory=lambda rt: RaisingAgent())
try: quiet(S.run, F.RID, p, rpc, rt, F.NOW); raised = False
except Exception: raised = True
check("an unexpected exception out of the send loop: disarmed (finally) even though it propagates", raised and [e for e in events if e[0] == "disarm"] == [("disarm", F.RID)], events)
# superseded / claim lost: the script path. sms-only fixture Directory has the script path (cylex) but only for sms, so phone-call there is a fence refusal: nothing armed.
p = F.StrictPortal(requests=[F.request(status="starting", channel="phone-call")], verifications=[F.verification(directory="cylex.us")]); events = []
rt = ArmRt(F.FakePage(), events, armer=FakeArmer(events))
r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("fence refusal (no phone-call playbook for the Directory): never armed", [e for e in events if e[0] in ("arm", "disarm")] == [], (r, events))

# ---- 4 arm / disarm failures are never fatal ----
holder = {}
r, text, ev, p, rt = run_case(lambda p, rpc: happy(p, rpc, io.StringIO(), holder), armer_kw={"arm_raises": True})
check("arm raises: the send still runs to verified; the failed arm is still disarmed (Twilio may have applied it)", r == "verified" and ("disarm", F.RID) in ev, (r, ev))
check("arm failure logs the type only, not the message", "arm failed: RuntimeError" in text and CODE not in text, text[-200:])
holder = {}
r, text, ev, p, rt = run_case(lambda p, rpc: happy(p, rpc, io.StringIO(), holder), armer_kw={"disarm_raises": True})
check("disarm raises: the outcome is still verified, logged, not fatal", r == "verified" and "disarm failed: RuntimeError" in text and CODE not in text, (r, text[-200:]))
holder = {}
r, text, ev, p, rt = run_case(lambda p, rpc: happy(p, rpc, io.StringIO(), holder), armer_kw={"disarm_result": False})
check("disarm returns False: still verified", r == "verified", r)
p = portal(); rpc = B.VerifyRpc(p); events = []
rt = F.FakeRuntime(F.FakePage(), agent_factory=happy(p, rpc, io.StringIO(), {}))
r, text = quiet(S.run, F.RID, p, rpc, rt, F.NOW)
check("a runtime with no armer (every older fake) runs a phone-call request to verified and never arms", r == "verified" and not hasattr(rt, "armer"), r)

# ---- 5 real SyncArm through a fake transport ----
class Twilio:
    def __init__(self, post_first=200, post_doc=200, delete=204): self.calls, self.post_first, self.post_doc, self.delete = [], post_first, post_doc, delete
    def __call__(self, method, url, form):
        self.calls.append((method, url, dict(form) if form else None))
        if method == "POST" and url.endswith("/Documents"): return self.post_first, b""
        if method == "POST": return self.post_doc, b""
        if method == "DELETE": return self.delete, b""
        raise AssertionError("unexpected " + method)
T0 = datetime.datetime(2026, 11, 19, 15, 0, 0, tzinfo=datetime.timezone.utc)
BASE = "https://sync.twilio.com/v1/Services/IS36a9f8f48c4dba0472d019ea83eac69e/Documents"
WF = os.path.join(TMP, "win-real.json")
tw = Twilio(); a = AR.SyncArm(transport=tw, now=lambda: T0, windows=WF)
res, text = quiet(a.arm, "req-1")
check("arm: POST /Documents with UniqueName=verify_armed, Data until = now+12 min, Ttl=900", res is True and tw.calls == [("POST", BASE, {"UniqueName": "verify_armed", "Data": '{"verify_armed_until": "2026-11-19T15:12:00Z"}', "Ttl": "900"})], tw.calls)
check("arm: the window log holds id and times only", AR.load_windows(WF) == [{"request_id": "req-1", "start": "2026-11-19T15:00:00Z", "until": "2026-11-19T15:12:00Z", "end": None}], AR.load_windows(WF))
tw = Twilio(post_first=409); a = AR.SyncArm(transport=tw, now=lambda: T0, windows=WF)
res, text = quiet(a.arm, "req-2")
check("arm on 409: second POST to /Documents/verify_armed with Data and Ttl (no UniqueName)", res is True and tw.calls[1] == ("POST", BASE + "/verify_armed", {"Data": '{"verify_armed_until": "2026-11-19T15:12:00Z"}', "Ttl": "900"}), tw.calls)
tw = Twilio(post_first=500); a = AR.SyncArm(transport=tw, now=lambda: T0, windows=os.path.join(TMP, "w500.json"))
res, text = quiet(a.arm, "req-3")
check("arm refused by Twilio (500): False, logged, no window recorded", res is False and AR.load_windows(os.path.join(TMP, "w500.json")) == [] and "HTTP 500" in text, text)
def boom(m, u, f): raise TimeoutError("slow")
a = AR.SyncArm(transport=boom, now=lambda: T0, windows=os.path.join(TMP, "wboom.json"))
res, text = quiet(a.arm, "req-4"); res2, text2 = quiet(a.disarm, "req-4")
check("transport error on arm and on disarm: False, never raises, type only", res is False and res2 is False and "TimeoutError" in text + text2)
tw = Twilio(); a = AR.SyncArm(transport=tw, now=lambda: T0 + datetime.timedelta(minutes=3), windows=WF)
res, text = quiet(a.disarm, "req-2")
check("disarm: DELETE /Documents/verify_armed", res is True and tw.calls == [("DELETE", BASE + "/verify_armed", None)], tw.calls)
ws = {w["request_id"]: w for w in AR.load_windows(WF)}
check("disarm closes only its own window", ws["req-2"]["end"] == "2026-11-19T15:03:00Z" and ws["req-1"]["end"] is None, ws)
tw = Twilio(delete=404); a = AR.SyncArm(transport=tw, now=lambda: T0, windows=os.path.join(TMP, "w404.json"))
check("disarm: 404 (already gone) is success", quiet(a.disarm, "x")[0] is True)
tw = Twilio(delete=500); wf3 = os.path.join(TMP, "w3.json"); a = AR.SyncArm(transport=tw, now=lambda: T0, windows=wf3); quiet(a.arm, "req-5")
res, text = quiet(a.disarm, "req-5")
check("disarm refused (500): False, logged; the window stays open to its `until` (what the line really does)", res is False and AR.load_windows(wf3)[0]["end"] is None and "HTTP 500" in text, text)
# another request holds the line: a stale disarm must not pull its arm
wf4 = os.path.join(TMP, "w4.json"); tw = Twilio(); clk = [T0]; a = AR.SyncArm(transport=tw, now=lambda: clk[0], windows=wf4)
quiet(a.arm, "req-A"); clk[0] = T0 + datetime.timedelta(minutes=1); quiet(a.arm, "req-B"); tw.calls.clear()
check("armed_request: the newest open window is B", a.armed_request() == "req-B", a.armed_request())
quiet(a.disarm, "req-A")
check("disarm for A while the NEWER window of B is open: no DELETE (B keeps the line)", [c for c in tw.calls if c[0] == "DELETE"] == [], tw.calls)
quiet(a.disarm, "req-B")
check("disarm for B (A is only an older stale window): DELETE goes out and B's window closes", [c[0] for c in tw.calls] == ["DELETE"] and {w["request_id"]: w["end"] for w in AR.load_windows(wf4)}["req-B"] is not None, tw.calls)
# credentials: read from the file, never printed
cp = os.path.join(TMP, "cred.json"); json.dump({"account_sid": "ACfakefake", "auth_token": "fake-token-value"}, open(cp, "w"))
seen = {}
import urllib.request
class Resp:
    status = 201
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return b"{}"
def fake_urlopen(req, timeout=None): seen["h"] = dict(req.header_items()); seen["m"] = req.get_method(); seen["u"] = req.full_url; seen["t"] = timeout; return Resp()
_old = urllib.request.urlopen; urllib.request.urlopen = fake_urlopen
os.environ.pop("CE_NO_TWILIO", None)
try:
    a = AR.SyncArm(cred_path=cp, now=lambda: T0, windows=os.path.join(TMP, "wc.json")); res, text = quiet(a.arm, "req-c")
finally:
    urllib.request.urlopen = _old; os.environ["CE_NO_TWILIO"] = "1"
check("real transport: Basic auth header from the creds file, 5 s timeout, nothing printed", res is True and seen["h"].get("Authorization", "").startswith("Basic ") and seen["t"] == 5 and "fake-token-value" not in text and "ACfakefake" not in text, (res, seen.get("t")))
a = AR.SyncArm(cred_path=cp, now=lambda: T0, windows=os.path.join(TMP, "wf.json"))
res, text = quiet(a.arm, "req-f")
check("the test fence: CE_NO_TWILIO refuses a real network call (RuntimeError type only in the log)", res is False and "RuntimeError" in text, text)

# ---- 6 sweeper disarms the swept request's own window ----
class SweepArmer:
    def __init__(self, armed): self.armed, self.disarmed = armed, []
    def armed_request(self): return self.armed
    def disarm(self, rid=None): self.disarmed.append(rid)
stuck = [F.request(status="starting", age_s=700, channel="phone-call")]
p = F.StrictPortal(requests=stuck, verifications=[F.verification(directory=AGENT_DIR)])
sa = SweepArmer(F.RID)
quiet(B.sweep, p, B.VerifyRpc(p), F.NOW, F.FakeCards(), sa)
check("sweep: a swept request that holds the arm window is disarmed", sa.disarmed == [F.RID], sa.disarmed)
p = F.StrictPortal(requests=[F.request(status="starting", age_s=700, channel="phone-call")], verifications=[F.verification(directory=AGENT_DIR)])
sa = SweepArmer("some-other-request")
quiet(B.sweep, p, B.VerifyRpc(p), F.NOW, F.FakeCards(), sa)
check("sweep: a swept request that does NOT hold the window leaves the arm alone", sa.disarmed == [], sa.disarmed)
class BadArmer(SweepArmer):
    def armed_request(self): raise RuntimeError("log unreadable")
p = F.StrictPortal(requests=[F.request(status="starting", age_s=700, channel="phone-call")], verifications=[F.verification(directory=AGENT_DIR)])
done, text = quiet(B.sweep, p, B.VerifyRpc(p), F.NOW, F.FakeCards(), BadArmer(None))
check("sweep: an armer that raises never stops the sweep", done == [F.RID] and "sweep disarm failed" in text, (done, text[-120:]))
p = F.StrictPortal(requests=[F.request(status="starting", age_s=700, channel="phone-call")], verifications=[F.verification(directory=AGENT_DIR)])
done, _ = quiet(B.sweep, p, B.VerifyRpc(p), F.NOW, F.FakeCards())
check("sweep: no armer (default) is the old behaviour", done == [F.RID])

# ---- 7 source scans + mutations ----
src = open(os.path.join(HERE, "..", "job", "verify_send.py"), encoding="utf8").read()
check("verify_send never speaks HTTP to Twilio itself (only through verify_arm)", "sync.twilio.com" not in src and "api.twilio.com" not in src and "urllib" not in src)
arm_src = open(os.path.join(HERE, "..", "job", "verify_arm.py"), encoding="utf8").read()
check("verify_arm never imports the portal and never touches a Directory", not re.search(r"^\s*(import|from)\s+(portal|verify_send|verify_bridge)\b", arm_src, re.M))
check("verify_arm holds no phone number and no auth token literal", not re.search(r"\+?\d{3}\W?\d{3}\W?\d{4}", arm_src) and "auth_token\"] =" not in arm_src)

def mutant(old, new):
    assert old in src, old
    ns = {"__name__": "verify_send_mut", "__file__": os.path.join(HERE, "..", "job", "verify_send.py")}
    exec(compile(src.replace(old, new), "verify_send_mut", "exec"), ns)
    return ns
def runs_with(ns, channel):
    p = portal(channel); rpc = B.VerifyRpc(p); events = []
    rt = ArmRt(F.FakePage(), events, armer=FakeArmer(events), agent_factory=happy(p, rpc, io.StringIO(), {}))
    ns["helper_command"] = lambda: '"C:/fixture/python" "C:/fixture/job/verify_step.py"'
    quiet(ns["run"], F.RID, p, rpc, rt, F.NOW)
    return events
anchor = "finally: _disarm(rt, request_id)"
ns = mutant(anchor, "finally: pass")
ev = runs_with(ns, "phone-call")
check("MUTATION: the disarm dropped -> the line stays armed, and the disarm tests would catch it", ("arm", F.RID) in ev and not any(e[0] == "disarm" for e in ev), ev)
ns = mutant('req.get("channel") != "phone-call" or biz != "NM"', 'biz != "NM"')
ev = runs_with(ns, "sms")
check("MUTATION: arming for sms -> an arm event on an sms request, which the no-arm test would catch", any(e[0] == "arm" for e in ev), ev)
ns = mutant('or biz != "NM"', "")
p = portal("phone-call", F.SCC); rpc = B.VerifyRpc(p); events = []
rt = ArmRt(F.FakePage(), events, armer=FakeArmer(events), agent_factory=happy(p, rpc, io.StringIO(), {}))
ns["helper_command"] = lambda: '"C:/fixture/python" "C:/fixture/job/verify_step.py"'
quiet(ns["run"], F.RID, p, rpc, rt, F.NOW)
check("MUTATION: arming for any tenant -> SCC arms the NM line, which the SCC test would catch", any(e[0] == "arm" for e in events), events)
ns = mutant("_arm(rt, req, tenant[0], request_id)   #", "pass   #")
ev = runs_with(ns, "phone-call")
check("MUTATION: the arm dropped -> no arm event, which the phone-call test would catch", not any(e[0] == "arm" for e in ev), ev)

S.helper_command = _hc
print("verify_arm_test: %d checks, %d failed" % (len(ok), ok.count(False)))
sys.exit(0 if all(ok) else 1)
