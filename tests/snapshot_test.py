"""Full snapshot overlay + same-state notes (t_64c4d511). Run: python tests/snapshot_test.py (CI). No network: portal is an in-memory fake."""
import os, sys, copy, json, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import portal as P
import transitions as T
import snapshot as P_SN

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

TMP = tempfile.mkdtemp()
SCC = P.ALLOWED["SCC"]
DAY = "2026-10-26"
BASE = {"found": 2, "directories": [
    {"name": "a.example", "domain": "a.example", "state": "needs-human", "url": None},
    {"name": "b.example", "domain": "b.example", "state": "needs-human", "url": None},
    {"name": "c.example", "domain": "c.example", "state": "needs-human", "url": None}]}

class FakePortal:
    def __init__(self): self.snaps, self.calls = {SCC: copy.deepcopy(BASE)}, []
    def latest_snapshot(self, cid): return {"payload": copy.deepcopy(self.snaps[cid])}
    def upsert_snapshot(self, cid, day, payload): self.snaps[cid] = copy.deepcopy(payload); self.calls.append(("snap", day))
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))

def queue():
    p = os.path.join(TMP, "q.json"); shutil.copy(os.path.join(HERE, "fixtures", "test_queue.json"), p); return p

def st(fp, dom): return next(d for d in fp.snaps[SCC]["directories"] if d["domain"] == dom)["state"]

# S1 two rows transition in turn; between them the snapshot is replaced by a fresh weekly scan (no overlay). Both stay in the payload.
p, fp = queue(), FakePortal()
T.record_transition("SCC", "fix-a", "submitted", None, "n", queue_path=p, today="2026-10-25", portal=fp, activities_flag=False)
fp.snaps[SCC] = copy.deepcopy(BASE)   # weekly scan rewrote the snapshot without queue state
T.record_transition("SCC", "fix-b", "submitted", None, "n", queue_path=p, today=DAY, portal=fp, activities_flag=False)
T.record_transition("SCC", "fix-b", "pending-verify", None, "n", queue_path=p, today=DAY, portal=fp, activities_flag=False)
check("S1 first row survives the second transition", st(fp, "a.example") == "submitted", st(fp, "a.example"))
check("S1 second row in the payload", st(fp, "b.example") == "pending-verify")
check("S1 untouched row unchanged (a needs-human row with no listing shows blocked)", st(fp, "c.example") == "blocked")
a = next(d for d in fp.snaps[SCC]["directories"] if d["domain"] == "a.example")
check("S1 first row keeps its own date, not today's", a.get("stateDate") == "2026-10-25", str(a.get("stateDate")))
check("S1 summary recounted from the rows", fp.snaps[SCC]["summary"] == P_SN.summary_from_rows(fp.snaps[SCC]["directories"]))

# S2 a needs-human / queued row never overlays as a listing state beyond its portal mapping; rejected rows are not re-overlaid
p, fp = queue(), FakePortal()
T.record_transition("SCC", "fix-a", "rejected", None, "n", queue_path=p, today=DAY, portal=fp, activities_flag=False)
T.record_transition("SCC", "fix-b", "submitted", None, "n", queue_path=p, today=DAY, portal=fp, activities_flag=False)
check("S2 rejected row is not pulled back into the overlay by a later transition", st(fp, "a.example") == "rejected")

# S3 live row keeps its permalink after another row moves
p, fp = queue(), FakePortal()
T.record_transition("SCC", "fix-a", "submitted", None, "n", queue_path=p, today=DAY, portal=fp, activities_flag=False)
T.record_transition("SCC", "fix-a", "live", "https://a.example/listing/1", "n", queue_path=p, today=DAY, portal=fp, activities_flag=False,
                    proof={"proof_url": "https://a.example/listing/1", "proof_nap": "NAP", "proof_at": "2026-10-20T00:00:00Z", "proof_nap_match": True, "build_action": "fix"})   # t_d660babc
T.record_transition("SCC", "fix-b", "submitted", None, "n", queue_path=p, today=DAY, portal=fp, activities_flag=False)
check("S3 live row still live after a later transition", st(fp, "a.example") == "live")

# S4 same-state note on submitted / pending-verify: accepted with a note, refused without, writes no Activities row
for s in ("submitted", "pending-verify"):
    p, fp = queue(), FakePortal()
    q = json.load(open(p)); q["fix_queue"][0]["state"] = s; json.dump(q, open(p, "w"))
    try: T.record_transition("SCC", "fix-a", s, None, None, queue_path=p, today=DAY, portal=fp); noted = False
    except T.TransitionRefused: noted = True
    check("S4 %s -> %s without a note refused" % (s, s), noted)
    r = T.record_transition("SCC", "fix-a", s, None, "phone shows 111", queue_path=p, today=DAY, portal=fp)
    row = json.load(open(p))["fix_queue"][0]
    check("S4 %s -> %s with a note: state kept, history note added" % (s, s), row["state"] == s and row["history"][-1]["note"] == "phone shows 111")
    check("S4 same-state note writes no Activities row", r["activity_record"] is None and not any("deliverables" in str(c[1]) for c in fp.calls))

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
