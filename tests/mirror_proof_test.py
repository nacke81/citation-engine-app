"""Mirror ce_directory_status Proof into live queue rows (kanban t_78dc54b5). Run: python tests/mirror_proof_test.py (CI).
No network, no browser, no portal: the Directory database is an in-memory stub that only answers GET; urlopen is poisoned.

  M1 mirror_proof (pure): fills a live row with no proof / an incomplete proof; never touches a complete queue proof (even when the DB differs);
     skips a DB copy that is itself incomplete, a row with no status row, a non-live row; sink off (None) is a no-op
  M2 record_transition (a writer): another live row's missing proof is filled in the same write; complete one untouched; sink off = untouched; state/history unchanged
  M3 record_proof (a writer) and buildrows.apply_file (a writer) and weekly_merge (a writer): same fill; apply_file without db_proof is unchanged
  M4 one-shot --mirror-proof: dry run writes nothing; --write backs up first, md5 changes, proof_problems == [] on every live row read from the file; second run is a no-op;
     sink off prints SKIPPED and writes nothing; no row state / history change; the stub saw only GET
"""
import copy, io, json, os, sys, tempfile, contextlib, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
os.environ["CE_QUEUE"] = os.path.join(TMP, "queue.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
os.environ["CE_DIRECTORIES_WRITE"] = "1"
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import transitions as T
import buildrows as B
import create_discovery as CD
import buildqueue as Q

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

DAY = "2026-11-10"
U = "https://x.example/l/%s"
def good(tag, action="new"):
    return {"proof_url": U % tag, "proof_nap": "Alder Care | 100 Example | 502-555-0101", "proof_at": "2026-10-26T00:00:00Z", "proof_nap_match": True, "build_action": action}
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example, Exampleton KY 40000", "phone": "(502) 555-0101"}

def row(rid, state="live", directory=None, **kw):
    r = {"id": rid, "directory": directory or rid + ".example", "state": state, "mike_approval": None, "evidence_url": U % rid, "listing_url": U % rid,
         "history": [{"at": "2026-10-26", "to": state}]}
    r.update(kw); return r

def queue_rows():
    return [row("nokey"), row("partial", proof={"proof_url": U % "partial", "proof_nap": "x"}), row("complete", proof=good("complete-queue")),
            row("dbnull"), row("nodb"), row("waiting", state="submitted"), row("fixable", state="pending-verify")]

def db_map():
    return {"nokey.example": good("nokey-db"), "partial.example": good("partial-db", "fix"), "complete.example": good("complete-DIFFERENT-db"),
            "dbnull.example": {k: None for k in T.PROOF_FIELDS}, "waiting.example": good("waiting-db"), "fixable.example": good("fixable-db")}

def write_q(rows, name=None):
    p = os.path.join(TMP, name or "q%d.json" % len(os.listdir(TMP)))
    json.dump({"canonical": CANON, "fix_queue": rows}, open(p, "w", encoding="utf-8"), indent=1); return p

def rd(p): return json.load(open(p, encoding="utf-8"))
def by_id(q): return {r["id"]: r for r in q["fix_queue"]}
def md5(p): return T._md5(p)

class StubDB:
    owner = "owner-1"
    def __init__(self, status=None): self.calls = []; self.status = status if status is not None else []
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path))
        if method == "GET" and "ce_directory_status" in path:
            return [dict(directory=d, **p) for d, p in self.status.items()] if isinstance(self.status, dict) else self.status
        return []

class FakePortal:
    def latest_snapshot(self, cid): return {"payload": {"found": 1, "directories": []}}
    def upsert_snapshot(self, cid, day, payload): pass
    def call(self, method, path, body=None, prefer=None): return []

# ---- M1 pure ---------------------------------------------------------------------------------------------------------------------------------
q = {"fix_queue": queue_rows()}
filled = T.mirror_proof(q, db_map()); b = by_id(q)
check("M1 fills no-proof-key row and incomplete-proof row from the DB (5 fields exactly)", set(filled) >= {"nokey", "partial", "fixable"} - {"fixable"} and b["nokey"]["proof"] == good("nokey-db") and b["partial"]["proof"] == good("partial-db", "fix"), str(filled))
check("M1 never overwrites a complete queue proof (DB differs)", b["complete"]["proof"] == good("complete-queue") and "complete" not in filled)
check("M1 skips: DB copy incomplete, no status row, non-live rows", "proof" not in b["dbnull"] and "proof" not in b["nodb"] and "proof" not in b["waiting"] and "proof" not in b["fixable"], str(filled))
check("M1 result is exactly the two filled rows", sorted(filled) == ["nokey", "partial"], str(filled))
check("M1 after the fill proof_problems == [] and the guard counts them fine", T.proof_problems(b["nokey"]["proof"]) == [] and T.live_rows_missing_proof(q) != [] and {r for r, _ in T.live_rows_missing_proof(q)} == {"dbnull", "nodb"})
q2 = {"fix_queue": queue_rows()}; snap = copy.deepcopy(q2)
check("M1 sink off (db_proof None) is a no-op", T.mirror_proof(q2, None) == [] and q2 == snap)
check("M1 state and history never change", all(by_id(q)[i]["state"] == by_id(snap)[i]["state"] and by_id(q)[i]["history"] == by_id(snap)[i]["history"] for i in by_id(snap)))

# ---- M2 record_transition --------------------------------------------------------------------------------------------------------------------
def transition(p, db):
    return T.record_transition("SCC", "fixable", "live", U % "fixable", "n", queue_path=p, today=DAY, portal=FakePortal(), activities=FakePortal(), verification=FakePortal(), directories=db, proof=good("fixable-q"))
db = StubDB(db_map()); p = write_q(queue_rows()); res = transition(p, db); b = by_id(rd(p))
check("M2 the transition writer fills a different live row's missing proof", b["nokey"]["proof"] == good("nokey-db") and b["partial"]["proof"] == good("partial-db", "fix"), str(res.get("proof_mirrored")))
check("M2 complete queue proof untouched; the moved row keeps its own Proof; no-DB-proof rows stay without", b["complete"]["proof"] == good("complete-queue") and b["fixable"]["proof"] == good("fixable-q") and "proof" not in b["nodb"] and "proof" not in b["dbnull"])
check("M2 the mirror only added a GET", all(c[0] == "GET" for c in db.calls if "ce_directory_status?" in c[1] and "select=directory" in c[1]) and any("select=directory,proof_url" in c[1] for c in db.calls))
os.environ["CE_DIRECTORIES_WRITE"] = "0"
p = write_q(queue_rows()); before = rd(p); db0 = StubDB(db_map())
T.record_transition("SCC", "fixable", "live", U % "fixable", "n", queue_path=p, today=DAY, portal=FakePortal(), activities=FakePortal(), verification=FakePortal(), proof=good("fixable-q"))
b = by_id(rd(p))
check("M2 sink off (CE_DIRECTORIES_WRITE=0): no mirror, rows without proof stay without", "proof" not in b["nokey"] and b["partial"]["proof"] == before["fix_queue"][1]["proof"])
os.environ["CE_DIRECTORIES_WRITE"] = "1"
# a DB failure never blocks the write
class BoomDB(StubDB):
    def call(self, method, path, body=None, prefer=None):
        if method == "GET" and "select=directory,proof_url" in path: raise RuntimeError("db down")
        return super().call(method, path, body, prefer)
p = write_q(queue_rows()); err = io.StringIO()
with contextlib.redirect_stderr(err): transition(p, BoomDB(db_map()))
check("M2 a failing status read is printed and the transition still lands", by_id(rd(p))["fixable"]["state"] == "live" and "MIRROR-PROOF skipped" in err.getvalue())

# ---- M3 other writers ------------------------------------------------------------------------------------------------------------------------
p = write_q(queue_rows()); db = StubDB(db_map())
T.record_proof("complete", good("complete-queue"), queue_path=p, today=DAY, db=db)   # a live row, proof already complete: the writer still fills its neighbours
b = by_id(rd(p))
check("M3 record_proof writer fills the neighbours too", b["nokey"]["proof"] == good("nokey-db") and b["complete"]["proof"] == good("complete-queue"))
SEEDDIRS = []
base = {"canonical": CANON, "fix_queue": queue_rows(), "create_queue": {"rows": []}}
p = os.path.join(TMP, "bq.json"); json.dump(base, open(p, "w", encoding="utf-8"), indent=1)
rep, bak = B.apply_file(p, SEEDDIRS, [], [], DAY)   # first run settles the file's create_queue shape (its own, unrelated write)
rep, bak = B.apply_file(p, SEEDDIRS, [], [], DAY)
check("M3 buildrows.apply_file WITHOUT db_proof adds no proof: no write, no backup", bak is None and rd(p)["fix_queue"] == base["fix_queue"] and "proof_mirrored" not in rep)
rep, bak = B.apply_file(p, SEEDDIRS, [], [], DAY, db_proof=db_map())
b = by_id(rd(p))
check("M3 buildrows.apply_file with db_proof fills (and backs up first)", b["nokey"]["proof"] == good("nokey-db") and b["complete"]["proof"] == good("complete-queue") and bak and os.path.exists(bak) and sorted(rep["proof_mirrored"]) == ["nokey", "partial"], str(rep))
rep2, bak2 = B.apply_file(p, SEEDDIRS, [], [], DAY, db_proof=db_map())
check("M3 buildrows second run is a no-op", bak2 is None and rep2["proof_mirrored"] == [])
p = os.path.join(TMP, "wm.json"); json.dump(base, open(p, "w", encoding="utf-8"), indent=1)
CD.run_all = lambda fetcher=None, day=None: ({}, [])
CD.weekly_merge(p, None, DAY)
check("M3 weekly_merge without db_proof: no proof added", "proof" not in by_id(rd(p))["nokey"])
CD.weekly_merge(p, None, DAY, db_proof=db_map()); b = by_id(rd(p))
check("M3 weekly_merge with db_proof fills, complete untouched", b["nokey"]["proof"] == good("nokey-db") and b["complete"]["proof"] == good("complete-queue") and "proof" not in b["nodb"])

# ---- M4 one-shot -----------------------------------------------------------------------------------------------------------------------------
rows = queue_rows()
for r in rows: r["_orig"] = (r["state"], json.dumps(r["history"]))
rows = [r for r in rows if r["id"] not in ("dbnull", "nodb")]   # prod shape: every live row has a complete DB copy
p = write_q(rows, "oneshot.json"); m0 = md5(p); dbm = db_map()
T.db_proof_by_directory = lambda db=None: dbm if os.environ.get("CE_DIRECTORIES_WRITE") != "0" else None
def run(args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): rc = T.main(args + ["--queue", p, "--today", DAY])
    return rc, json.loads(out.getvalue())
rc, r = run(["--mirror-proof"])
check("M4 dry run lists the rows and writes nothing", rc == 0 and sorted(r["filled"]) == ["nokey", "partial"] and r["written"] is False and md5(p) == m0 and not os.path.exists(p + ".bak-20261110-mirror-proof"), str(r))
rc, r = run(["--mirror-proof", "--write"])
q = rd(p); live = [x for x in q["fix_queue"] if x["state"] == "live"]
bak = p + ".bak-20261110-mirror-proof"
check("M4 --write: backup holds the old bytes, md5 changed, reported before/after", r["written"] and os.path.exists(bak) and md5(bak) == m0 == r["md5_before"] and r["md5_after"] == md5(p) != m0, str(r))
check("M4 readback straight from the file: proof_problems == [] on every live row with a DB copy", all(T.proof_problems(x.get("proof")) == [] for x in live if x["id"] != "dbnull"), str([(x["id"], T.proof_problems(x.get("proof"))) for x in live]))
check("M4 no state or history change on any row", all([x["state"], json.dumps(x["history"])] == x["_orig"] for x in q["fix_queue"]))
m1 = md5(p); rc, r = run(["--mirror-proof", "--write"])
check("M4 second --write is a no-op (no write, same md5)", r["filled"] == [] and r["written"] is False and md5(p) == m1)
os.environ["CE_DIRECTORIES_WRITE"] = "0"
p = write_q([row("nokey")], "off.json"); m = md5(p)
rc, r = run(["--mirror-proof", "--write"])
check("M4 sink off: SKIPPED, nothing written, no backup", rc == 0 and "skipped" in r and md5(p) == m and not os.path.exists(p + ".bak-20261110-mirror-proof"), str(r))
os.environ["CE_DIRECTORIES_WRITE"] = "1"
with contextlib.redirect_stderr(io.StringIO()):
    try: T.main(["--write", "--queue", p]); refused = False
    except SystemExit as e: refused = e.code != 0
check("M4 --write without --mirror-proof is refused", refused)
src = open(os.path.join(HERE, "..", "job", "transitions.py"), encoding="utf-8").read().split("def mirror_proof_file")[1].split("\ndef ")[0]
check("M4 scope: the mirror code has no Directory write verb and no portal call", not any(w in src for w in ('"POST"', '"PATCH"', '"DELETE"', "_upsert_status", "P.Portal", "sync_transition")))

print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
