"""Weekly Proof writer tests. Run: python tests/proof_test.py (CI). No network: db, portal and activities are in-memory fakes; urlopen is poisoned."""
import os, sys, copy, json, tempfile, shutil, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import portal as P
import transitions as T
import proof as PR

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

TMP = tempfile.mkdtemp()
SRC = os.path.join(HERE, "fixtures", "test_queue.json")
SCC = P.ALLOWED["SCC"]
DAY = "2026-11-02"
LISTING = "https://a.example/listing/1"

class FakeDB:
    owner = "owner-1"
    def __init__(self): self.calls = []; self.status = {}
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        if method == "POST" and path.startswith("ce_directory_status"):
            for r in body: self.status.setdefault((r["biz"], r["directory"]), {}).update(r)
class FakePortal:
    def __init__(self): self.calls = []; self.snap = {"found": 1, "directories": [{"name": "a.example", "domain": "a.example", "state": "submitted", "url": None, "urlKind": "search"}]}
    def latest_snapshot(self, cid): return {"payload": copy.deepcopy(self.snap)}
    def upsert_snapshot(self, cid, day, payload): self.calls.append(("snap", day))
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))

def fresh(state="submitted", kind_key="fix_queue", **extra):
    p = os.path.join(TMP, "q.json"); shutil.copy(SRC, p)
    q = json.load(open(p)); r = q["fix_queue"][0]; r["state"] = state; r.update(extra)
    if kind_key == "create_rows": q["create_rows"] = [q["fix_queue"].pop(0)]
    json.dump(q, open(p, "w")); return p, r["id"]

def chk(result="found", url=LISTING, match=True, diffs=None, claim=None, biz="SCC", d="a.example"):
    c = dict(biz=biz, directory=d, result=result, url=url if result == "found" else None, nap_shown="Alder Care | 1 Main St | 502-555-0101" if result == "found" else None,
             name_match=True if result == "found" else None, street_match=match, phone_match=match, match=match if result == "found" else None, diffs=diffs or [], note=None)
    if claim: c["_claim"] = {"claim_status": claim}
    return c

def run(path, checks):
    db, fp = FakeDB(), FakePortal()
    def record(*a, **k): return T.record_transition(*a, portal=fp, activities=fp, verification=fp, directories=db, **k)
    res = PR.proof_step(checks, DAY, queue_path=path, db=db, record=record)
    return res, db, fp

def counts_as_result(s):
    """Mirror of the page rule (PR #14): live + http(s) proof_url + proof_nap + proof_at + proof_nap_match true + build_action."""
    return (s.get("queue_state") == "live" and str(s.get("proof_url", "")).startswith(("http://", "https://")) and bool(s.get("proof_nap"))
            and bool(s.get("proof_at")) and s.get("proof_nap_match") is True and s.get("build_action") in ("new", "claim", "fix"))

def qstate(path, key="fix_queue"): return json.load(open(path))[key][0]["state"]

# G1 submitted + matching re-check -> live, counts as a result, Activities fired
p, rid = fresh("submitted")
res, db, fp = run(p, [chk()])
s = db.status.get(("SCC", "a.example"), {})
check("G1 row moved", [m["row"] for m in res["moved"]] == [rid] and not res["errors"], res)
check("G1 queue state live", qstate(p) == "live")
check("G1 Proof written", s.get("proof_url") == LISTING and s.get("proof_nap_match") is True and s.get("proof_at") and s.get("proof_nap") and s.get("build_action") == "fix", s)
check("G1 status row is live (transitions.py)", s.get("queue_state") == "live")
check("G1 counts as a result", counts_as_result(s))
acts = [c for c in fp.calls if c[0] == "POST" and "deliverables" in c[1]]
check("G1 client-voiced Activities row", len(acts) == 1 and acts[0][2][0]["title"] == "Your a.example listing is live", acts)
check("G1 proof written before the transition", [c[1].split("?")[0] for c in db.calls if c[0] == "POST"][0] == "ce_directory_status" and db.calls[0][2][0].get("proof_nap_match") is True)

# G2 submitted + mismatch -> stays waiting, match=false, no result, no transition
for label, c in (("phone mismatch", chk(match=False)), ("diffs present", chk(diffs=[{"field": "phone"}]))):
    p, rid = fresh("submitted")
    res, db, fp = run(p, [c]); s = db.status.get(("SCC", "a.example"), {})
    check("G2 %s stays submitted" % label, qstate(p) == "submitted" and not res["moved"] and res["mismatched"] == ["a.example"])
    check("G2 %s proof_nap_match=false, not a result" % label, s.get("proof_nap_match") is False and not counts_as_result(s) and "queue_state" not in s, s)
    check("G2 %s no Activities, no transition" % label, not fp.calls)

# G3 couldn't check writes nothing
for r in ("couldnt_check", "absent", "unsearchable"):
    p, rid = fresh("submitted"); before = open(p, "rb").read()
    res, db, fp = run(p, [chk(result=r)])
    check("G3 %s writes nothing" % r, not db.calls and not fp.calls and open(p, "rb").read() == before and res["untouched"] == ["a.example"])
p, rid = fresh("submitted"); before = open(p, "rb").read()
res, db, fp = run(p, [chk(url="https://a.example/search?q=alder")])
check("G3 found with no permalink writes nothing", not db.calls and not fp.calls and open(p, "rb").read() == before)

# other waiting states move; non-waiting rows and NM are ignored
for st in ("pending-verify", "needs-human"):
    p, rid = fresh(st); res, db, fp = run(p, [chk()])
    check("%s + match -> live" % st, qstate(p) == "live" and len(res["moved"]) == 1)
for st in ("queued", "live", "rejected"):
    p, rid = fresh(st); before = open(p, "rb").read(); res, db, fp = run(p, [chk()])
    check("%s row ignored" % st, not db.calls and not fp.calls and open(p, "rb").read() == before)
p, rid = fresh("submitted"); res, db, fp = run(p, [chk(biz="NM")])
check("NM check ignored", not db.calls and qstate(p) == "submitted")

# no carried-over Proof: a stale full Proof is cleared by a later mismatch; a later could-not-check does not touch it either way
p, rid = fresh("submitted")
res, db, fp = run(p, [chk(match=False)])
body = [c[2][0] for c in db.calls if c[0] == "POST"][0]
check("mismatch clears older Proof", all(body[k] is None for k in ("proof_url", "proof_nap", "proof_at", "build_action")) and body["proof_nap_match"] is False, body)

# build_action
p, rid = fresh("submitted", "create_rows"); res, db, fp = run(p, [chk()])
check("create row -> new", res["moved"] and res["moved"][0]["build_action"] == "new", res)
p, rid = fresh("submitted", wrong_field=None); res, db, fp = run(p, [chk(claim="claimed")])
check("claimed listing, nothing to fix -> claim", res["moved"] and res["moved"][0]["build_action"] == "claim", res)
p, rid = fresh("submitted"); res, db, fp = run(p, [chk(claim="claimed")])
check("fix row with wrong field -> fix", res["moved"] and res["moved"][0]["build_action"] == "fix", res)

# transition failure leaves the row waiting and reports it
p, rid = fresh("submitted"); db = FakeDB()
def boom(*a, **k): raise T.TransitionRefused("no")
res = PR.proof_step([chk()], DAY, queue_path=p, db=db, record=boom)
check("transition failure: waiting, error reported, not moved", qstate(p) == "submitted" and res["errors"] and not res["moved"])

# R2-1 a match with no NAP text shown writes nothing (no live row without proof_nap)
for label, nap in (("None", None), ("blank", "   ")):
    p, rid = fresh("submitted"); before = open(p, "rb").read(); c = chk(); c["nap_shown"] = nap
    res, db, fp = run(p, [c])
    check("R2-1 nap_shown %s writes nothing, stays submitted" % label, not db.calls and not fp.calls and open(p, "rb").read() == before and not res["moved"] and res["untouched"] == ["a.example"], res)

# R2-2 a failed run (guards / Chrome check) never writes Proof or moves rows
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import io, contextlib
import run as RUN
calls = []
orig = RUN.proof_step_run
RUN.proof_step_run = lambda *a, **k: calls.append(a) or True
buf = io.StringIO()
with contextlib.redirect_stdout(buf): r_bad = RUN.proof_step_if_ok(False, [chk()], DAY)
check("R2-2 failed run: proof step skipped, loud", r_bad is None and not calls and "PROOF SKIPPED: run failed guards" in buf.getvalue())
RUN.proof_step_if_ok(True, [chk()], DAY)
check("R2-2 passing run: proof step runs", len(calls) == 1)
RUN.proof_step_run = orig
rsrc = open(os.path.join(HERE, "..", "job", "run.py"), encoding="utf-8").read()
check("R2-2 main() calls the gated wrapper only", "proof_step_if_ok(ok_run," in rsrc and "proof_step_run(checks, datetime" not in rsrc)

# nit: two waiting rows on one Directory both move
p, rid = fresh("submitted"); q = json.load(open(p)); r2 = copy.deepcopy(q["fix_queue"][0]); r2["id"] = rid + "-b"; q["fix_queue"].append(r2); json.dump(q, open(p, "w"))
res, db, fp = run(p, [chk()])
check("two waiting rows on one Directory both move", len(res["moved"]) == 2 and all(r["state"] == "live" for r in json.load(open(p))["fix_queue"] if r["id"] in (rid, rid + "-b")), res)

# source rules: no Directory traffic in the module
src = open(os.path.join(HERE, "..", "job", "proof.py"), encoding="utf-8").read()
check("proof.py has no network or browser code", not any(w in src for w in ("urlopen", "requests", "fetcher", "owned_chrome", "submit_row")))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
