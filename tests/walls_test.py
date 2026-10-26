"""Hard-block retry cap (t_fccbb7ef): 1 try/day, 3 tries, then STOPPED until Mike resets."""
import os, sys, json, copy, tempfile, io, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
JOB = os.path.join(os.path.dirname(HERE), "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
import walls as W
import transitions as T
import build_runner as B
import recheck as R
from build_core import Site

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

def refused(fn, *a, **k):
    try: fn(*a, **k)
    except (W.WallRefused, T.TransitionRefused): return True
    return False

def row(rid="fix-a", state="queued", d="a.example"):
    return {"id": rid, "directory": d, "listing_url": "https://a.example/x", "state": state, "mike_approval": None, "history": []}

# W1 same-day refusal
r = row()
e1 = W.record_try(r, "2026-10-26", "9f1a2b3c4d5e6f70")
check("W1 try 1 recorded as {wall, try, at, ray_id}", e1["wall"] == "hard-block" and e1["try"] == 1 and e1["at"] == "2026-10-26" and e1["ray_id"] == "9f1a2b3c4d5e6f70" and r["history"][-1] is e1)
check("W1 try 1 note names the try and leaves the state alone", e1["note"] == "WALL:hard-block try 1/3" and r["state"] == "queued")
before = copy.deepcopy(r)
check("W1 second try the same calendar day is refused", refused(W.record_try, r, "2026-10-26"))
check("W1 refusal changes nothing", r == before)
check("W1 gate says SKIP the same day", (W.gate({"fix_queue": [r]}, "a.example", "2026-10-26") or "").startswith("SKIP a.example"))
check("W1 gate is clear the next day", W.gate({"fix_queue": [r]}, "a.example", "2026-10-27") is None)

# W2 the stop on try 3 and the 4th-try refusal
W.record_try(r, "2026-10-27")
check("W2 try 2 does not stop the row", not W.is_stopped(r) and r["state"] == "queued")
e3 = W.record_try(r, "2026-10-28", "aaaaaaaaaaaaaaaa")
check("W2 failed try 3 sets the stop note exactly", e3["note"] == "WALL:hard-block STOPPED, waiting on Mike" == W.STOP_NOTE)
check("W2 failed try 3 parks the row needs-human, stopped", r["state"] == "needs-human" and W.is_stopped(r) and r["history"][-1]["note"] == W.STOP_NOTE)
b4 = copy.deepcopy(r)
check("W2 4th try ever is refused (a later day)", refused(W.record_try, r, "2026-11-30"))
check("W2 4th try refusal changes nothing", r == b4)
check("W2 gate skips a stopped row on any later day", "STOPPED" in (W.gate({"create_rows": [r]}, "a.example", "2027-01-01") or ""))
check("W2 gate ignores other Directories", W.gate({"create_rows": [r]}, "b.example", "2027-01-01") is None)

# W3 transitions refuse to move a stopped row; the build path skips it
tmp = tempfile.mkdtemp(); qp = os.path.join(tmp, "q.json")
json.dump({"fix_queue": [r, row("fix-b", d="b.example")]}, open(qp, "w"))
check("W3 transitions refuses submitted on a stopped row", refused(T.record_transition, "SCC", "fix-a", "submitted", queue_path=qp, today="2026-11-01", dry_run=True))
check("W3 transitions refuses live on a stopped row", refused(T.record_transition, "SCC", "fix-a", "live", "https://a.example/l", queue_path=qp, today="2026-11-01", dry_run=True))
ok_other = T.record_transition("SCC", "fix-b", "submitted", queue_path=qp, today="2026-11-01", dry_run=True)
check("W3 an unstopped row still moves", ok_other["to"] == "submitted")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cands = R.candidates({"fix_queue": [dict(r, state="submitted"), dict(row("fix-b", "submitted", "b.example"))]})
check("W3 recheck skips a stopped row with a log line", [c[1]["id"] for c in cands] == ["fix-b"] and "SKIP a.example" in buf.getvalue())

# W4 runner checks before touching a Directory
site = Site("A", "a.example", [])
check("W4 build_runner.wall_gate skips a stopped Directory", "STOPPED" in (B.wall_gate(site, qp, "2026-11-01") or ""))
check("W4 build_runner.wall_gate lets a clean Directory through", B.wall_gate(Site("B", "b.example", []), qp, "2026-11-01") is None)
check("W4 no queue file means no known wall", B.wall_gate(site, os.path.join(tmp, "none.json"), "2026-11-01") is None)
def boom(*a, **k): raise AssertionError("Chrome touched")
old = (B.connect, B.load_site); B.connect = boom; B.load_site = lambda n, d=None: site
os.environ["CE_QUEUE"] = qp
import buildqueue as Q
Q.QUEUE_PATH = qp
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = B.main(["a.example", "--dry-run"])
B.connect, B.load_site = old
check("W4 main() on a stopped Directory logs the skip, exits 0, never connects to Chrome", rc == 0 and "SKIP a.example" in buf.getvalue())
fmt = B.format_result({"site": "a", "mode": "live", "steps": [{"name": "s", "kind": "submit", "status": "failed", "detail": "Sorry, you have been blocked Ray ID: 9F1A2B3C4D5E6F70"}], "stopped_before": None, "ok": False})
check("W4 a hard-block failure prints the record-try command with the Ray ID", "walls.py --record-try" in fmt and "9f1a2b3c4d5e6f70" in fmt)
check("W4 Ray ID parsed from page text", W.parse_ray_id("<span>Cloudflare Ray ID: <strong>8a1b2c3d4e5f6a7b</strong>") == "8a1b2c3d4e5f6a7b")

# W5 reset: only the explicit CLI call clears it
rc = W.main(["--reset-wall", "fix-a", "--queue", qp, "--today", "2026-11-02"])
after = json.load(open(qp))["fix_queue"][0]
check("W5 --reset-wall clears the stop", rc == 0 and not W.is_stopped(after) and W.tries(after) == [])
check("W5 reset is logged in history", after["history"][-1].get("reset") is True and len(after["history"]) == 4)
check("W5 reset leaves state for Mike to move (no silent re-queue)", after["state"] == "needs-human")
check("W5 after reset the gate is clear and a fresh try 1 is allowed", W.gate({"fix_queue": [after]}, "a.example", "2026-11-02") is None and W.record_try(after, "2026-11-02")["try"] == 1)
check("W5 reset on a row with no wall history is refused", refused(W.reset_wall, row()))
buf = io.StringIO()
with contextlib.redirect_stderr(buf): rc = W.main(["--reset-wall", "nope", "--queue", qp])
check("W5 reset of an unknown row is refused, exit 1", rc == 1 and "REFUSED" in buf.getvalue())
src = open(os.path.join(JOB, "walls.py"), encoding="utf-8").read()
check("W5 nothing but the CLI resets: no other job module calls reset_wall", not any("reset_wall" in open(os.path.join(JOB, f), encoding="utf-8").read() for f in os.listdir(JOB) if f.endswith(".py") and f != "walls.py"))

# W6 CLI record-try writes the queue and enforces the same rules
json.dump({"fix_queue": [row()]}, open(qp, "w"))
with contextlib.redirect_stdout(io.StringIO()):
    rcs = [W.main(["--record-try", "fix-a", "--queue", qp, "--today", d, "--ray-id", "abc123abc123abc1"]) for d in ("2026-10-26", "2026-10-26", "2026-10-27", "2026-10-28")]
with contextlib.redirect_stderr(io.StringIO()):
    rc4 = W.main(["--record-try", "fix-a", "--queue", qp, "--today", "2026-10-29"])
fin = json.load(open(qp))["fix_queue"][0]
check("W6 CLI: try, same-day refused, try 2, try 3 -> exits 0,1,0,0", rcs == [0, 1, 0, 0], str(rcs))
check("W6 CLI: 4th refused (exit 1); file shows stopped needs-human with the stop note", rc4 == 1 and fin["state"] == "needs-human" and fin["history"][-1]["note"] == W.STOP_NOTE and [h["try"] for h in W.tries(fin)] == [1, 2, 3])

print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
