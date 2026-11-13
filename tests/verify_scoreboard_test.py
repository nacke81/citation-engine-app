"""Verify Now scoreboard tests (t_e49457af). Virtual wall clock, strict portal fake, fake oneshot. No network, no Chrome, no hermes, no real code.
Run: python tests/verify_scoreboard_test.py              (CI) exit 1 on any failure
     python tests/verify_scoreboard_test.py --mutations  (CI) one mutation per timestamp in a copy of job/: the suite must FAIL on each one
     python tests/verify_scoreboard_test.py --sample     prints one sample scoreboard row from a dry run
"""
import contextlib, datetime, io, json, os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))


# ---- mutation runner (runs the whole suite against a patched copy of job/) -------------------------------------------------------------
def count(text, needle): return text.count(needle)


MUTATIONS = [  # (label, file, needle, replacement); every needle is a distinct call site of a new timestamp
    ("requested_at (bridge pickup)", "verify_bridge.py", 'SB.stamp(rid, "requested_at"', 'SB.stamp(rid, "zz_requested_at"'),
    ("bridge_pickup_at", "verify_bridge.py", 'SB.stamp(rid, "bridge_pickup_at"', 'SB.stamp(rid, "zz_bridge_pickup_at"'),
    ("agent_start_at (agent launch)", "verify_send.py", 'agent = rt.launch_agent(rt.write_prompt(request_id, prompt))\n        SB.stamp(request_id, "agent_start_at")', 'agent = rt.launch_agent(rt.write_prompt(request_id, prompt))\n        SB.stamp(request_id, "zz")'),
    ("agent_start_at (script browser)", "verify_send.py", 'SB.stamp(request_id, "agent_start_at")   # script', 'SB.stamp(request_id, "zz")   # script'),
    ("signed_in_at (script)", "verify_send.py", 'SB.stamp(request_id, "signed_in_at")', 'SB.stamp(request_id, "zz")'),
    ("signed_in_at (agent stage call)", "verify_step.py", 'STAGE_NAMES = {"signed_in": "signed_in_at"}', 'STAGE_NAMES = {"signed_in": "zz"}'),
    ("send_clicked_at (script)", "verify_send.py", 'SB.stamp(request_id, "send_clicked_at")', 'SB.stamp(request_id, "zz")'),
    ("send_clicked_at (agent sent)", "verify_step.py", 'SB.stamp(request_id, "send_clicked_at", now_dt)', 'SB.stamp(request_id, "zz", now_dt)'),
    ("code_sent_at (script)", "verify_send.py", 'SB.stamp(request_id, "code_sent_at")', 'SB.stamp(request_id, "zz")'),
    ("code_sent_at (agent sent)", "verify_step.py", 'SB.stamp(request_id, "code_sent_at", now_dt)', 'SB.stamp(request_id, "zz", now_dt)'),
    ("code_submitted_at (script)", "verify_send.py", 'SB.stamp(request_id, "code_submitted_at")', 'SB.stamp(request_id, "zz")'),
    ("code_submitted_at (agent code)", "verify_step.py", 'SB.stamp(request_id, "code_submitted_at", wall())', 'SB.stamp(request_id, "zz", wall())'),
    ("code_entered_at (script)", "verify_send.py", 'SB.stamp(request_id, "code_entered_at")', 'SB.stamp(request_id, "zz")'),
    ("code_entered_at (agent result)", "verify_step.py", 'SB.stamp(request_id, "code_entered_at", now_dt)', 'SB.stamp(request_id, "zz", now_dt)'),
    ("verified_at", "verify_scoreboard.py", 'row["verified_at"] = _at(at) if str(outcome) == "verified" else None', 'row["verified_at"] = None'),
    ("finalize hook in VerifyRpc.finish", "verify_bridge.py", "        SB.finalize(request_id, status", "        (lambda *a: None)(request_id, status"),
    ("summary click-to-send median", "verify_scoreboard.py", '"click_to_send": _d(row, "requested_at", "code_sent_at")', '"click_to_send": _d(row, "requested_at", "send_clicked_at")'),
    ("summary code-to-verified median", "verify_scoreboard.py", '"code_to_verified": _d(row, "code_submitted_at", "verified_at")', '"code_to_verified": _d(row, "code_entered_at", "verified_at")'),
]


def run_mutations():
    bad = 0
    for label, fn, needle, repl in MUTATIONS:
        tmp = tempfile.mkdtemp()
        try:
            for d in ("job", "tests", "config"):
                shutil.copytree(os.path.join(ROOT, d), os.path.join(tmp, d), ignore=shutil.ignore_patterns("__pycache__", "playbooks"))
            f = os.path.join(tmp, "job", fn)
            s = open(f, encoding="utf-8", newline="").read().replace("\r\n", "\n")
            if s.count(needle) != 1:
                print("MUTATION ERROR %s: needle found %d times" % (label, s.count(needle))); bad += 1; continue
            open(f, "w", encoding="utf-8", newline="").write(s.replace(needle, repl))
            r = subprocess.run([sys.executable, os.path.join(tmp, "tests", "verify_scoreboard_test.py")], capture_output=True, text=True, timeout=300)
            killed = r.returncode != 0
            print(("KILLED   " if killed else "SURVIVED ") + label); bad += 0 if killed else 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("mutations: %d, survived or broken: %d" % (len(MUTATIONS), bad))
    return 1 if bad else 0


if "--mutations" in sys.argv:
    sys.exit(run_mutations())

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
import verify_scoreboard as SB

CODE = "906417"
AGENT_DIR = "agentdir.example"
MASK = "(502) ***-0101"
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print((("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else "")), flush=True)

def quiet(fn, *a, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        r = fn(*a, **kw)
    return r, out.getvalue() + err.getvalue()

T = {"s": 0}
SB.now = lambda: F.NOW + datetime.timedelta(seconds=T["s"])   # the scoreboard's wall clock, driven by the test
at = lambda s: None if s is None else F.iso(F.NOW + datetime.timedelta(seconds=s))
board = lambda: SB.load(SB.path())
fresh = lambda: [shutil.rmtree(os.path.join(TMP, "logs"), ignore_errors=True), T.update(s=0)]

def agent_portal(directory=AGENT_DIR, claimed=30, **kw):
    r = F.request(status="starting", age_s=0)
    r["claimed_at"] = at(claimed)
    return F.StrictPortal(requests=[r], verifications=[F.verification(directory=directory)], queued_code=CODE, **kw)

# ---- 1 stamp / finalize basics -----------------------------------------------------------------------------------------------------
fresh()
SB.stamp("rid-1", "requested_at", F.NOW); T["s"] = 50; SB.stamp("rid-1", "requested_at", F.NOW + datetime.timedelta(seconds=99))
SB.stamp("rid-1", None, tenant="NM", domain="x.example", channel="sms", send_mode="agent", code="906417", evil="y")
check("stamp: first write wins per stage", json.load(open(SB._stage_file("rid-1")))["requested_at"] == at(0))
check("stamp: unknown stage and unknown meta keys are dropped (no place for a code)", "906417" not in open(SB._stage_file("rid-1")).read() and "evil" not in open(SB._stage_file("rid-1")).read() and SB.stamp("rid-1", "bogus_at") is False)
check("stamp: a send_mode outside agent/script is dropped", SB.stamp("rid-1", None, send_mode="manual") and json.load(open(SB._stage_file("rid-1")))["send_mode"] == "agent")
check("stamp: a bad request id never touches the disk", SB.stamp("../x", "requested_at") is False)
T["s"] = 400
check("finalize: writes one row", SB.finalize("rid-1", "verified") is True and len(board()) == 1)
check("finalize: a second call writes nothing (one row per request)", SB.finalize("rid-1", "verified") is False and len(board()) == 1)
row = board()[0]
check("row: has exactly the card's fields", set(row) == set(SB.FIELDS), sorted(set(row) ^ set(SB.FIELDS)))
check("row: verified_at only on a verified outcome", row["verified_at"] == at(400) and row["outcome"] == "verified")
SB.stamp("rid-2", "requested_at", F.NOW); SB.finalize("rid-2", "failed:timeout")
check("row: a failed outcome has no verified_at", board()[1]["verified_at"] is None and board()[1]["outcome"] == "failed:timeout")
check("finalize with no stage file writes nothing", SB.finalize("rid-9", "verified") is False)
check("append-only: the file keeps earlier rows when later ones land", [r["request_id"] for r in board()] == ["rid-1", "rid-2"])

# ---- 2 agent path end to end: bridge pickup -> send run -> helper calls -> verified ---------------------------------------------------
fresh()
p = agent_portal(); rpc = B.VerifyRpc(p); out = io.StringIO(); holder = {}
class NoSpawn:
    def __init__(self, *a, **k): pass
req = p.requests[F.RID]
res = {"refused": [], "deferred": [], "started": []}
T["s"] = 30
quiet(B.dispatch, dict(req), p, rpc, res, set(), lambda *a, **k: NoSpawn())
def adv(s): T["s"] = s
def agent_steps(rt):
    def signed(): adv(90); holder["stage"] = ST.step_stage(F.RID, "signed_in", p)
    def traced():
        adv(100)
        holder["t1"] = ST.step_trace(F.RID, "goto", "https://agentdir.example/login?token=abc#frag", "", p)
        holder["t2"] = ST.step_trace(F.RID, "click", "https://agentdir.example/login", "#send-code", p)
    def sent(): adv(110); holder["sent"] = ST.step_sent(F.RID, MASK, p, rpc, SB.now())
    def code(): adv(200); holder["code"] = ST.step_code(F.RID, p, rpc, out, rt.sleep, rt.now, wall=SB.now)
    def result(): adv(230); holder["result"] = ST.step_result(F.RID, "accepted", p, rpc, SB.now()); adv(235)
    return F.FakeAgent([signed, traced, sent, code, result])
adv(50)
rt = F.FakeRuntime(F.FakePage(), agent_factory=agent_steps)
r, text = quiet(S.run, F.RID, p, rpc, rt, F.NOW)
check("agent run verified through the helper", r == "verified" and p.requests[F.RID]["status"] == "verified" and all(v == 0 for v in holder.values()), (r, holder))
rows = board()
check("agent run: exactly one scoreboard row", len(rows) == 1, len(rows))
row = rows[0] if rows else {}
want = {"request_id": F.RID, "tenant": "NM", "domain": AGENT_DIR, "channel": "sms", "send_mode": "agent", "outcome": "verified",
        "requested_at": at(0), "bridge_pickup_at": at(30), "agent_start_at": at(50), "signed_in_at": at(90), "send_clicked_at": at(110),
        "code_sent_at": at(110), "code_submitted_at": at(200), "code_entered_at": at(230)}
for k, v in want.items():
    check("agent row: %s" % k, row.get(k) == v, (row.get(k), v))
check("agent row: verified_at is the finish time", row.get("verified_at") == at(230) or row.get("verified_at") == at(235), row.get("verified_at"))
check("agent row: the code is nowhere in the scoreboard or stage files", CODE not in open(SB.path()).read() and not os.listdir(os.path.join(TMP, "logs", "verify-stages")))
d = SB.durations(row)
check("agent row: click-to-send and code-to-verified derive from the stamps", d["click_to_send"] == 110 and d["code_to_verified"] in (35, 30) and d["pickup_start"] == 50, d)
check("agent row: the sweeper finishing the closed request later writes no second row", quiet(rpc.finish, F.RID, "failed", "timeout")[0] is None and len(board()) == 1)

# ---- 3 script path (Cylex fake page): every stage is stamped, in order -------------------------------------------------------------------
fresh()
clk = F.Clock(); SB.now = lambda: F.NOW + datetime.timedelta(seconds=clk.t - 1000)
p = F.StrictPortal(requests=[F.request(status="starting", age_s=0)], verifications=[F.verification()], queued_code=CODE)
p.code_after_polls = 2
rt = F.FakeRuntime(F.FakePage(accepted=CODE), clock=clk)
r, _ = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
rows = board(); row = rows[0] if rows else {}
check("script run verified and wrote one row", r == "verified" and len(rows) == 1, (r, len(rows)))
check("script row: mode script, tenant NM, domain cylex.us, channel sms", (row.get("send_mode"), row.get("tenant"), row.get("domain"), row.get("channel")) == ("script", "NM", "cylex.us", "sms"), row)
for k in ("agent_start_at", "signed_in_at", "send_clicked_at", "code_sent_at", "code_submitted_at", "code_entered_at", "verified_at"):
    check("script row: %s stamped" % k, bool(row.get(k)))
check("script row: the 20 s of code polling shows between code_sent and code_submitted", SB._d(row, "code_sent_at", "code_submitted_at") == 20, SB._d(row, "code_sent_at", "code_submitted_at"))
SB.now = lambda: F.NOW + datetime.timedelta(seconds=T["s"])

# ---- 4 every close path lands a row (sweeper, fence refusal) -----------------------------------------------------------------------------
fresh()
r0 = F.request(status="requested", age_s=900)
p = F.StrictPortal(requests=[r0], verifications=[F.verification(directory=AGENT_DIR)], queued_code=CODE)
rpc = B.VerifyRpc(p)
SB.stamp(F.RID, "requested_at", F.NOW)
quiet(B.sweep, p, rpc, F.NOW + datetime.timedelta(seconds=1000), None)
rows = board()
check("sweeper close writes a failed row with the outcome and no verified_at", len(rows) == 1 and rows[0]["outcome"] == "could_not_start:timeout" and rows[0]["verified_at"] is None, rows)
fresh()
p = F.StrictPortal(requests=[F.request(status="starting", age_s=0)], verifications=[F.verification(directory="notinfile.example")])
res = {"refused": [], "deferred": [], "started": []}
quiet(B.dispatch, dict(p.requests[F.RID]), p, B.VerifyRpc(p), res, set(), lambda *a, **k: NoSpawn())
check("a fence refusal ends the request without a row (nothing was stamped before the fence)", res["refused"] and len(board()) == 0)

# ---- 5 step trace + promotion -----------------------------------------------------------------------------------------------------------
fresh()
p = agent_portal(); rpc = B.VerifyRpc(p)
tf = ST._trace_file(F.RID)
check("trace: URL query and fragment are stripped, no value is stored", ST.step_trace(F.RID, "goto", "https://agentdir.example/login?code=906417#x", "", p) == 0
      and json.loads(open(tf).readline())["url"] == "https://agentdir.example/login" and "906417" not in open(tf).read())
check("trace: a selector with a 6-digit run is refused", ST.step_trace(F.RID, "fill", "https://agentdir.example/login", "#code-906417", p) == ST.BAD_ARGS)
check("trace: a non-http URL is refused", ST.step_trace(F.RID, "goto", "file:///c:/x", "", p) == ST.BAD_ARGS and ST.step_trace(F.RID, "goto", "javascript:alert(1)", "", p) == ST.BAD_ARGS)
check("trace: an unknown action is refused", ST.step_trace(F.RID, "eval", "https://agentdir.example/", "x", p) == ST.BAD_ARGS)
check("trace: no --value option exists on the CLI", quiet(ST.main, ["trace", "--request-id", F.RID, "--action", "fill", "--url", "https://a.example/", "--selector", "#e", "--value", "x"], p, rpc)[0] == ST.BAD_ARGS)
ST.step_trace(F.RID, "fill", "https://agentdir.example/login", "input[name=email]", p)
ST.step_trace(F.RID, "click", "https://agentdir.example/login", "button[type=submit]", p)
check("trace: three steps recorded in order", [json.loads(l)["n"] for l in open(tf)] == [1, 2, 3])
ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
pd = os.path.join(TMP, "logs", "verify-traces", "promote")
files = os.listdir(pd) if os.path.isdir(pd) else []
check("promotion: a clean agent send saves <domain>__<channel>__<request>.json", files == ["%s__sms__%s.json" % (AGENT_DIR, F.RID)], files)
saved = json.load(open(os.path.join(pd, files[0]))) if files else {}
check("promotion: the file carries domain, channel, signin_url and the 3 steps (url + selector), and no code", saved.get("domain") == AGENT_DIR and saved.get("channel") == "sms" and len(saved.get("steps", [])) == 3
      and saved["steps"][1]["selector"] == "input[name=email]" and CODE not in json.dumps(saved), saved.get("steps"))
check("trace: after the send the request is not `starting`, so a late trace is refused", ST.step_trace(F.RID, "click", "https://agentdir.example/x", "#a", p) == ST.REFUSED)
fresh()
p = agent_portal(directory="cylex.us"); rpc = B.VerifyRpc(p)
ST.step_trace(F.RID, "goto", "https://www.cylex.us.com/signin/", "", p); ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
check("promotion: a script-mode directory is not promoted (already a script)", not os.path.isdir(pd) or not os.listdir(pd))
fresh()
p = agent_portal(); rpc = B.VerifyRpc(p); ST.step_sent(F.RID, MASK, p, rpc, F.NOW)
check("promotion: an agent send with no trace saves nothing", not os.path.isdir(pd) or not os.listdir(pd))
p = agent_portal(client=None) if False else agent_portal(); p.requests[F.RID]["client_id"] = "not-a-client"
check("stage and trace: the fence still refuses a non-allow-listed client", ST.step_stage(F.RID, "signed_in", p) == ST.REFUSED and ST.step_trace(F.RID, "goto", "https://a.example/", "", p) == ST.REFUSED)
check("stage: only signed_in is a stage name", ST.step_stage(F.RID, "verified", agent_portal()) == ST.BAD_ARGS)

# ---- 6 the fence and the send limits are untouched (the scoreboard adds no send path) ------------------------------------------------------
src = open(os.path.join(ROOT, "job", "verify_scoreboard.py"), encoding="utf-8").read()
check("scoreboard module imports no portal, subprocess or network module", not re.search(r"^\s*(import|from)\s+(portal|subprocess|urllib\.request|requests|socket)", src, re.M))
SB.stamp("boom", "requested_at"); os.environ["CE_LOGS"] = os.path.join(TMP, "a-file-not-a-dir")
open(os.environ["CE_LOGS"], "w").write("x")
check("a write failure (logs path is a file) never raises into the send", SB.stamp("rid-z", "requested_at") is False and SB.finalize("rid-z", "verified") is False)
os.environ["CE_LOGS"] = os.path.join(TMP, "logs")

# ---- 7 summary ----------------------------------------------------------------------------------------------------------------------------
fresh()
def mk(rid, tenant, dom, mode, req, pick, start, signin, click, code_sent, sub, entered, ver, outcome="verified"):
    return {"request_id": rid, "tenant": tenant, "domain": dom, "channel": "sms", "requested_at": at(req), "bridge_pickup_at": at(pick), "agent_start_at": at(start),
            "signed_in_at": at(signin), "send_clicked_at": at(click), "code_sent_at": at(code_sent), "code_submitted_at": at(sub), "code_entered_at": at(entered),
            "verified_at": at(ver) if ver is not None else None, "outcome": outcome, "send_mode": mode}
os.makedirs(os.path.join(TMP, "logs"))
rowsin = [mk("11111111-aaaa", "NM", "cylex.us", "agent", 0, 40, 70, 150, 200, 210, 300, 330, 340),
          mk("22222222-bbbb", "NM", "cylex.us", "script", 0, 20, 30, 60, 90, 95, 150, 170, 180),
          mk("33333333-cccc", "SCC", "yelp.com", "agent", 0, 55, 65, 100, 100, 120, None, None, None, "failed:code_expired")]
with open(SB.path(), "w") as h:
    for rr in rowsin: h.write(json.dumps(rr) + "\n")
    h.write("not json\n")
lines = []
m = SB.summary(SB.load(), out=lines.append)
text = "\n".join(lines)
check("summary: one table line per run (+ header), a bad line is skipped", len([l for l in lines if re.match(r"^[0-9a-f]{8} ", l)]) == 3 and lines[0].startswith("request"), lines[:5])
check("summary: median click-to-send over the runs that sent (210, 95, 120 -> 120)", m["click_to_send"] == 120 and "median click-to-send (requested -> code_sent): 120 s" in text, text)
check("summary: median code-to-verified (40, 30; the failed run has none -> 35)", m["code_to_verified"] == 35 and "median code-to-verified (code_submitted -> verified): 35 s" in text, text)
check("summary: pickup+start median 65 s is under the 90 s flag", m["pickup_start"] == 65 and "over 90" not in text)
lines2 = []
SB.summary([mk("44444444-dddd", "NM", "cylex.us", "agent", 0, 70, 130, 170, 190, 190, 250, 260, 270)], out=lines2.append)
check("summary: pickup+start over 90 s is flagged", any("over 90" in l for l in lines2), lines2[-1])
lines3 = []
SB.summary([], out=lines3.append)
check("summary: an empty file prints dashes, not a crash", any("click-to-send" in l and "-" in l for l in lines3))
r, text = quiet(SB.main, ["--summary", "--file", SB.path()])
check("CLI --summary reads the file and exits 0", r == 0 and "runs: 3" in text)
check("CLI refuses to run without --summary", quiet(SB.main, [])[0] if False else subprocess.run([sys.executable, os.path.join(ROOT, "job", "verify_scoreboard.py")], capture_output=True).returncode != 0)

# ---- sample row (dry run) -----------------------------------------------------------------------------------------------------------------
if "--sample" in sys.argv:
    fresh(); clk = F.Clock(); SB.now = lambda: F.NOW + datetime.timedelta(seconds=clk.t - 1000)
    r0 = F.request(status="starting", age_s=40); r0["claimed_at"] = at(-10)   # clicked 40 s ago, the bridge claimed it 30 s later
    p = F.StrictPortal(requests=[r0], verifications=[F.verification()], queued_code=CODE); p.code_after_polls = 3
    quiet(B.dispatch, dict(p.requests[F.RID]), p, B.VerifyRpc(p), {"refused": [], "deferred": [], "started": []}, set(), lambda *a, **k: NoSpawn())
    quiet(S.run, F.RID, p, B.VerifyRpc(p), F.FakeRuntime(F.FakePage(accepted=CODE), clock=clk), F.NOW)
    print("SAMPLE ROW:", open(SB.path()).read().strip())
    SB.summary(SB.load())

print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
