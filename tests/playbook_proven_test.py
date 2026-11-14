"""Proven write-back (t_eae8e59f): after an accepted code the BRIDGE writes the verify playbook from the sanitized trace. Offline: fake DB, fake runtime, no network.
Run: python tests/playbook_proven_test.py (CI). Exit 1 on any failure. Mutations at the end remove one guard and require the unsafe thing to HAPPEN."""
import contextlib, io, json, os, re, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ["CE_LOGS"] = os.path.join(TMP, "logs"); os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json"); os.environ["CE_VERIFY_LOCKS"] = os.path.join(TMP, "locks")
os.environ["CE_VERIFY_DIRECTORIES"] = os.path.join(HERE, "verify_directories_fixture.json"); os.environ["CE_NO_CARDS"] = "1"
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json"); os.environ["CE_RUNS"] = tempfile.mkdtemp()
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
import verify_fakes as F
import verify_bridge as B
import verify_send as S
import verify_step as ST
import playbook as PB
import playbook_proven as PP

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


class FakeDB:
    def __init__(self, dirs=(AGENT_DIR,)): self.dirs, self.rows, self.calls = set(dirs), {}, []
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path))
        m = re.search(r"domain=eq\.([^&]+)", path)
        if method == "GET" and path.startswith("ce_directories?"): return [{"domain": m.group(1)}] if m.group(1) in self.dirs else []
        if method == "GET" and path.startswith("ce_directory_playbooks?"):
            t = re.search(r"task=eq\.([^&]+)", path).group(1); r = self.rows.get((m.group(1), t)); return [dict(r)] if r else []
        if method == "POST" and path.startswith("ce_directory_playbooks?on_conflict=domain,task"):
            for r in body: self.rows[(r["domain"], r["task"])] = dict(r)
            return None
        if method == "PATCH" and path.startswith("ce_directory_playbooks?"):
            t = re.search(r"task=eq\.([^&]+)", path).group(1); self.rows[(m.group(1), t)].update(body); return None
        raise AssertionError("unexpected call %s %s" % (method, path))
    def writes(self): return [c for c in self.calls if c[0] in ("POST", "PATCH")]


RID = F.RID
def trace_dir(): return os.path.join(TMP, "traces-%d" % len(os.listdir(TMP)))
def put_trace(d, steps, rid=RID, domain=AGENT_DIR, channel="sms"):
    os.makedirs(os.path.join(d, "promote"), exist_ok=True)
    p = os.path.join(d, "promote", "%s__%s__%s.json" % (domain, channel, rid))
    json.dump({"request_id": rid, "domain": domain, "channel": channel, "steps": steps}, open(p, "w"))
    return p
GOOD = [{"action": "goto", "url": "https://agentdir.example/login"}, {"action": "click", "selector": "#verify"}, {"action": "fill", "selector": "input[name=phone]"}]
OLD = [{"text": "Open the profile", "url": "https://agentdir.example/p"}, {"text": "Click Verify"}, {"text": "Click Send", "send": True}, {"text": "Enter the code"}]

# ---- 1 the writer ---------------------------------------------------------------------------------------------------------------------
def marked_db(last_proven=None, signup=False):   # t_8b8c2650: every stored verify playbook has exactly one marked send step
    db = FakeDB(); db.rows[(AGENT_DIR, "verify")] = {"domain": AGENT_DIR, "task": "verify", "steps": PB.validate_steps(OLD), "send_is_signup": signup, "source": "seed", "last_proven_at": last_proven, "version": 3}
    return db
d = trace_dir(); put_trace(d, GOOD); db = FakeDB()
r = PP.write_proven(db, RID, AGENT_DIR, d)
check("1 accepted + trace but NO stored playbook: nothing is written (a trace cannot name the send step)", r == "no_trace" and not db.writes() and not db.rows, r)
for sg in (False, True):
    db = marked_db(signup=sg); put_trace(d, GOOD, rid="r2"); r2 = PP.write_proven(db, "r2", AGENT_DIR, d)
    srow = db.rows[(AGENT_DIR, "verify")]
    check("1 a proven run on a stored playbook (send_is_signup %s) keeps its marked steps and flag (a trace cannot name the send step), and only touches proof" % sg,
          r2 == "touched" and srow["version"] == 3 and srow["send_is_signup"] is sg and len(srow["steps"]) == 4 and sum(1 for s in srow["steps"] if s.get("send")) == 1 and srow["last_proven_at"], (r2, srow))

# note: stored in source, never as a step
d = trace_dir(); put_trace(d, GOOD); db = marked_db()
PP.write_proven(db, RID, AGENT_DIR, d, note="step 3 needs the phone tab first")
row = db.rows[(AGENT_DIR, "verify")]
check("1 PLAYBOOK-NOTE lands in source as a note, steps unchanged", "note: step 3 needs the phone tab first" in row["source"] and len(row["steps"]) == 4 and not any("phone tab" in s["text"] for s in row["steps"]), row["source"])
d = trace_dir(); put_trace(d, GOOD); db = marked_db()
PP.write_proven(db, RID, AGENT_DIR, d, note="the code was 90641" + "7")
check("1 a note with a 6+ digit run is dropped (the proof still lands)", "note:" not in db.rows[(AGENT_DIR, "verify")]["source"] and len(db.rows) == 1 and db.rows[(AGENT_DIR, "verify")]["last_proven_at"])

# code-like trace
d = trace_dir(); put_trace(d, GOOD + [{"action": "fill", "selector": "input#code-906417"}]); db = FakeDB()
r = PP.write_proven(db, RID, AGENT_DIR, d)
check("1 a trace with a code-like value is refused and nothing is written", r == "refused" and not db.writes(), r)
d = trace_dir(); put_trace(d, [{"action": "goto", "url": "https://agentdir.example/x?code=1"}, {"action": "type", "selector": "x"}]); db = FakeDB()
check("1 an unknown action is refused", PP.write_proven(db, RID, AGENT_DIR, d) == "refused" and not db.writes())
d = trace_dir(); put_trace(d, GOOD, rid="other"); db = FakeDB()
check("1 a trace for a different request id is not used", PP.write_proven(db, RID, AGENT_DIR, d) in ("no_trace", "touched") and not db.rows)
d = trace_dir(); p = put_trace(d, GOOD); db = FakeDB(); tr = json.load(open(p)); tr["domain"] = "elsewhere.example"; json.dump(tr, open(p, "w"))
check("1 a trace whose domain differs is refused", PP.write_proven(db, RID, AGENT_DIR, d) == "refused" and not db.writes())

# empty / shorter
def seeded(last_proven="2026-11-01T00:00:00Z", stale=True):
    db = FakeDB(); db.rows[(AGENT_DIR, "verify")] = {"domain": AGENT_DIR, "task": "verify", "steps": PB.validate_steps(OLD), "send_is_signup": False, "source": "seed", "last_proven_at": last_proven, "version": 3, "stale": stale}
    return db
d = trace_dir(); db = seeded()
r = PP.write_proven(db, RID, AGENT_DIR, d)
row = db.rows[(AGENT_DIR, "verify")]
check("1 no trace + existing playbook: steps kept, only last_proven_at moves (no version bump)", r == "touched" and len(row["steps"]) == 4 and row["version"] == 3 and row["last_proven_at"] != "2026-11-01T00:00:00Z" and row["stale"] is False, (r, row))
d = trace_dir(); put_trace(d, [{"action": "goto", "url": "https://agentdir.example/login"}]); db = seeded()
r = PP.write_proven(db, RID, AGENT_DIR, d)
row = db.rows[(AGENT_DIR, "verify")]
check("1 a shorter trace than the proven playbook keeps the old steps", r == "touched" and len(row["steps"]) == 4 and row["version"] == 3 and row["last_proven_at"] != "2026-11-01T00:00:00Z", (r, row))
d = trace_dir(); put_trace(d, GOOD); db = seeded(last_proven=None)
r = PP.write_proven(db, RID, AGENT_DIR, d)
check("1 a trace over an UNPROVEN stored playbook does not replace it either (t_8b8c2650: it cannot name the send step); proof is touched", r == "touched" and len(db.rows[(AGENT_DIR, "verify")]["steps"]) == 4 and db.rows[(AGENT_DIR, "verify")]["version"] == 3 and db.rows[(AGENT_DIR, "verify")]["last_proven_at"])
d = trace_dir(); db = FakeDB()
check("1 no trace and no playbook: nothing is written", PP.write_proven(db, RID, AGENT_DIR, d) == "no_trace" and not db.writes())

# ---- 2 through the real run (S.run with a fake oneshot) ----------------------------------------------------------------------------
CODE = "906417"
def agent_portal(**kw):
    return F.StrictPortal(requests=[F.request(status="starting", channel="sms", client=F.NM)], verifications=[F.verification(client=F.NM, directory=AGENT_DIR)], queued_code=CODE, **kw)

class WBRt(F.FakeRuntime):
    def __init__(self, *a, db=None, tdir=None, note=None, **kw):
        super().__init__(*a, **kw); self.db, self.tdir, self.wb_calls = db, tdir, 0
    def write_back(self, request_id, domain, note=None):
        self.wb_calls += 1
        return PP.write_proven(self.db, request_id, domain, self.tdir, note)

NoteAgent = F.FakeAgent

def run_once(outcome, trace_steps=GOOD, note="ok", db=None, tdir=None):
    p = agent_portal(); rpc = B.VerifyRpc(p); out = io.StringIO(); db = db or marked_db(); tdir = tdir or trace_dir()
    if trace_steps is not None: put_trace(tdir, trace_steps)
    def factory(rt):
        ag = NoteAgent([lambda: ST.step_sent(RID, MASK, p, rpc, F.NOW),
                        lambda: ST.step_code(RID, p, rpc, out, rt.sleep, rt.now, wall=rt.wall),
                        lambda: ST.step_note(RID, note, p),
                        lambda: ST.step_result(RID, outcome, p, rpc, F.NOW)])
        return ag
    rt = WBRt(F.FakePage(), agent_factory=factory, db=db, tdir=tdir)
    r, text = quiet(S.run, RID, p, rpc, rt, F.NOW)
    return r, rt, db, p, text

r, rt, db, p, text = run_once("accepted", note="step 2 was renamed")
row = db.rows.get((AGENT_DIR, "verify"))
check("2 accepted run: the bridge proved the stored verify playbook once (steps kept, a trace cannot name the send), with the note", r == "verified" and rt.wb_calls == 1 and row and len(row["steps"]) == 4 and row["version"] == 3 and row["last_proven_at"] and "note: step 2 was renamed" in row["source"], (r, row))
check("2 the agent never held the DB: no DB call came from the helper (writes happen after the oneshot is gone)", rt.agent.kills >= 1 and len(db.writes()) == 1)
check("2 no code in the written row or the run log", CODE not in repr(db.rows) and CODE not in text)
r, rt, db, p, text = run_once("rejected")
check("2 rejected run: failed/code_rejected, NO playbook write, write_back never called", r in ("closed", "failed:code_rejected") and p.requests[RID]["status"] == "failed" and rt.wb_calls == 0 and not db.writes() and not db.rows[(AGENT_DIR, "verify")]["last_proven_at"], (r, rt.wb_calls))
def no_result_run():
    p = agent_portal(); rpc = B.VerifyRpc(p); db = FakeDB(); tdir = trace_dir(); put_trace(tdir, GOOD)
    rt = WBRt(F.FakeRuntime and F.FakePage(), agent_factory=lambda rt: F.FakeAgent([lambda: ST.step_sent(RID, MASK, p, rpc, F.NOW)]), db=db, tdir=tdir)
    r, _ = quiet(S.run, RID, p, rpc, rt, F.NOW); return r, rt, db
r, rt, db = no_result_run()
check("2 agent sent but never reported a result (failed/other): NO playbook write", r == "failed:other" and rt.wb_calls == 0 and not db.writes(), r)
p = agent_portal(); rpc = B.VerifyRpc(p); db = FakeDB(); tdir = trace_dir(); put_trace(tdir, GOOD)
def sup_steps(rt):
    def close(): p.requests[RID]["status"] = "failed"; p.requests[RID]["fail_code"] = "other"   # the sweeper / portal closed it
    return F.FakeAgent([lambda: ST.step_sent(RID, MASK, p, rpc, F.NOW), close, lambda: ST.step_result(RID, "accepted", p, rpc, F.NOW)])
rt = WBRt(F.FakePage(), agent_factory=sup_steps, db=db, tdir=tdir)
r, _ = quiet(S.run, RID, p, rpc, rt, F.NOW)
check("2 superseded / closed by the portal mid-run: NO playbook write", rt.wb_calls == 0 and not db.writes(), r)
class BoomWB(WBRt):
    def write_back(self, *a, **k): raise OSError("db down " + CODE)
p = agent_portal(); rpc = B.VerifyRpc(p); out = io.StringIO()
def fac(rt):
    return F.FakeAgent([lambda: ST.step_sent(RID, MASK, p, rpc, F.NOW), lambda: ST.step_code(RID, p, rpc, out, rt.sleep, rt.now, wall=rt.wall), lambda: ST.step_result(RID, "accepted", p, rpc, F.NOW)])
rt = BoomWB(F.FakePage(), agent_factory=fac, db=FakeDB(), tdir=trace_dir())
r, text = quiet(S.run, RID, p, rpc, rt, F.NOW)
check("2 a write-back failure never changes the result and its text is not logged", r == "verified" and "db down" not in text and CODE not in text, r)
r, rt, db, p, text = run_once("accepted", trace_steps=GOOD + [{"action": "fill", "selector": "input#c-906417"}])
check("2 accepted run whose trace holds a code-like value: run still verified, steps untouched, no code in the row", r == "verified" and "906417" not in repr(db.rows) and len(db.rows[(AGENT_DIR, "verify")]["steps"]) == 4, (r, db.rows))
check("2 the real Runtime has the bridge-side write_back (agent has no DB access)", hasattr(S.Runtime, "write_back") and "SERVICE_ROLE" not in S.AgentProc.__init__.__doc__ if S.AgentProc.__init__.__doc__ else hasattr(S.Runtime, "write_back"))

# ---- 2b the note helper: `verify_step.py note` (stage file), validator, states, prompt, stdout --------------------------------------------
import verify_scoreboard as SB
def stage_note(rid):
    f = SB._stage_file(rid)
    return json.load(open(f, encoding="utf-8")).get("playbook_note") if os.path.exists(f) else None
def note_portal(status):
    return F.StrictPortal(requests=[F.request(status=status, channel="sms", client=F.NM)], verifications=[F.verification(client=F.NM, directory=AGENT_DIR)], queued_code=CODE)
def note_rc(text, status="starting", rid=RID):
    p = note_portal(status); lg = io.StringIO()
    with contextlib.redirect_stderr(lg), contextlib.redirect_stdout(io.StringIO()): rc = ST.step_note(rid, text, p)
    return rc, lg.getvalue()
for fn in os.listdir(os.path.join(os.environ["CE_LOGS"], "verify-stages")) if os.path.isdir(os.path.join(os.environ["CE_LOGS"], "verify-stages")) else []:
    os.remove(os.path.join(os.environ["CE_LOGS"], "verify-stages", fn))
rc, lg = note_rc("step 3 needs the phone tab first")
check("2b note in `starting`: stored in the request's stage file", rc == ST.OK and stage_note(RID) == "step 3 needs the phone tab first", (rc, stage_note(RID)))
for st in ("code_sent", "checking"):
    rc, _ = note_rc("the signup button moved to the footer", status=st)
    check("2b note allowed in %s" % st, rc == ST.OK and stage_note(RID) == "the signup button moved to the footer")
rc, _ = note_rc("later note wins"); check("2b the last note wins", stage_note(RID) == "later note wins")
before = stage_note(RID)
for label, txt in (("a 6+ digit run", "the code was 90641" + "7"), ("an email", "login a.b@example.com failed"), ("a phone number", "call (502) 555-0101 first"),
                   ("a code assignment", "code: abcd"), ("over 400 chars", "x" * 401), ("empty", "   ")):
    rc, lg = note_rc(txt)
    check("2b note refused: %s (exit 5, nothing stored, text not logged)" % label, rc == ST.REFUSED and stage_note(RID) == before and (not txt.strip() or txt.strip() not in lg), (rc, lg[-80:]))
check("2b exactly 400 chars is allowed", note_rc("y" * 400)[0] == ST.OK and len(stage_note(RID)) == 400)
for st in ("requested", "verified", "failed"):
    rc, _ = note_rc("too late or too early", status=st)
    check("2b note refused in state %s" % st, rc == ST.REFUSED and stage_note(RID) == "y" * 400, rc)
check("2b bad request id exits 2 through the CLI", ST.main(["note", "--request-id", "nope", "--text", "x"]) == ST.BAD_ARGS)
check("2b the CLI parses `note --request-id R --text T`", ST.main(["note", "--request-id", RID]) == ST.BAD_ARGS)
# the note survives finalize on verified only, and is read once
SB.set_note(RID, "keep me"); SB.finalize(RID, "verified")
check("2b a verified finalize leaves only the note; take_note reads it once and cleans up", SB.take_note(RID) == "keep me" and SB.take_note(RID) is None and not os.path.exists(SB._stage_file(RID)))
SB.set_note(RID, "drop me"); SB.finalize(RID, "failed:code_rejected")
check("2b a rejected/failed finalize removes the note with the stage file", SB.take_note(RID) is None and not os.path.exists(SB._stage_file(RID)))
# prompt + launch
sp = S.build_prompt(RID, F.request(status="starting", channel="sms", client=F.NM), F.verification(client=F.NM, directory=AGENT_DIR), {"domain": AGENT_DIR, "signin_url": "https://agentdir.example/login"}, F.NM, MASK, "u@example.com")
check("2b prompt tells the agent to use `verify_step.py note` and never mentions PLAYBOOK-NOTE", "verify_step.py" in sp and " note --request-id %s --text" % RID in sp and "PLAYBOOK-NOTE" not in sp and "Never print the note" in sp)
src_send = open(os.path.join(HERE, "..", "job", "verify_send.py"), encoding="utf-8").read()
check("2b verify_send has no stdout reader (no NoteReader, no PIPE)", "NoteReader" not in src_send and "subprocess.PIPE" not in src_send and "stdout=subprocess.DEVNULL" in src_send)

# ---- 3 the unchanged guards still hold ------------------------------------------------------------------------------------------------

# ---- 4 mutations: remove ONE guard, the unsafe thing must then HAPPEN ---------------------------------------------------------------------
_v = PB.validate_steps
PB.validate_steps = lambda steps: steps   # MUTATION 1: no validation of trace steps
d = trace_dir(); put_trace(d, GOOD + [{"action": "fill", "selector": "input#c-906417"}]); mdb = marked_db()
try: m1 = PP.write_proven(mdb, RID, AGENT_DIR, d)
except Exception as e: m1 = repr(e)
PB.validate_steps = _v
check("4 no validation, stored playbook: the code-like trace still cannot reach the row (traces never replace a verify playbook's steps)", "906417" not in repr(mdb.rows) and m1 == "touched", m1)

_st = S._status
S._status = lambda portal, rid: "verified"   # MUTATION 2: the verified gate removed (every run looks accepted)
r, rt, db, p, text = run_once("rejected")
S._status = _st
check("4 MUTATION no status gate: a REJECTED run then DOES stamp the playbook proven", rt.wb_calls == 1 and bool(db.rows[(AGENT_DIR, "verify")]["last_proven_at"]), (r, rt.wb_calls))

src = open(os.path.join(HERE, "..", "job", "playbook_proven.py"), encoding="utf-8").read()
mut = src.replace("    if steps and not cur:", "    if False:").replace("    if steps and cur:", "    if False:")   # MUTATION 3: the 'a trace cannot name the send step' guard removed
check("4 mutation 3 source edit applies", mut != src and mut.count("if False:") == 2)
ns = {"__name__": "pp_mut", "__file__": os.path.join(HERE, "..", "job", "playbook_proven.py")}; exec(compile(mut, "pp_mut", "exec"), ns)
d = trace_dir(); put_trace(d, GOOD); mdb = marked_db()
try: ns["write_proven"](mdb, RID, AGENT_DIR, d); m3 = None
except PB.PlaybookError as e: m3 = str(e)
check("4 MUTATION no trace guard: the writer (second guard) still refuses an unmarked trace, and the stored 4-step playbook is untouched", m3 is not None and "exactly one" in m3 and len(mdb.rows[(AGENT_DIR, "verify")]["steps"]) == 4, m3)

# MUTATION 4: the note validator removed -> a note holding a 6-digit run IS stored in the stage file
_c = ST.clean_note_text
ST.clean_note_text = lambda t: t
rc, _ = note_rc("the code was 90641" + "7")
ST.clean_note_text = _c
check("4 MUTATION no note validator: a note with a 6-digit run IS then stored", rc == ST.OK and "906417" in (stage_note(RID) or ""), stage_note(RID))

sys.exit(0 if all(ok) else 1)
