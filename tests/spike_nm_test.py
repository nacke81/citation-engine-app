"""CE v3 Spike golden checks (kanban t_62f64298). Run: python tests/spike_nm_test.py (CI). No network, no browser, no portal, no prod DB.

  S1 branch count gate: the NM-only branch names appear in at most 15 lines in the 5 known job files and nowhere else (planted-branch negative control)
  S2 fence: submit_row refuses a paid row or a needs_code row with no matching approval; paid stays refused even with one; one negative control passes
  S3 proof writer is business-agnostic: record_proof / db_proof_by_directory / mirror take the business (NM posts biz NM, SCC default unchanged,
     no cross-business copy), with a source mutation that a hard-coded SCC fails
  S4 comparator: a canonical that lists its street only if required (data) accepts city + state, refuses a wrong zip, a retired street, an old phone,
     another city; a canonical without that key still needs a street
The names of the two NM-only branch helpers are built from pieces here so this file adds no hit to the repo-wide grep the Frame counts.
"""
import os; os.environ["CE_DIRECTORIES_WRITE"] = "0"   # t_be2150cd: never write the prod Directory DB (tests/no_prod_directory_sink_test.py)
import inspect, json, re, sys, tempfile, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_RECORD_TRANSITIONS", None)
sys.path.insert(0, os.path.join(ROOT, "job"))
import os as _fo; _fo.environ["CE_PORTAL_ENV"] = _fo.path.join(HERE, "no-such-portal.env")  # t_2ddc7067: fail closed, never the prod portal
import buildqueue as Q
import transitions as T
import recheck as R

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)
def raises(fn, exc):
    try: fn()
    except exc: return True
    except Exception: return False
    return False

# ---- S1 branch count gate -------------------------------------------------------------------------------------------------------------------
NAMES = re.compile("is_" + "nm_row|NM_ROW" + "_PREFIX")
BASELINE = {"job/build_runner.py": 2, "job/buildqueue.py": 8, "job/nm_transitions.py": 2, "job/recheck.py": 1, "job/release.py": 2}   # main at 8af12eb: 15 hits, 5 files
SKIP = {".git", "node_modules", "vendor", "__pycache__"}

def hits(root):
    out = {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP]
        for f in files:
            if not f.endswith((".py", ".js", ".mjs", ".cjs", ".md", ".yml", ".yaml", ".json", ".sql", ".cmd", ".txt")): continue
            p = os.path.join(d, f)
            try: n = sum(1 for l in open(p, encoding="utf-8", errors="replace") if NAMES.search(l))
            except OSError: continue
            if n: out[os.path.relpath(p, root).replace(os.sep, "/")] = n
    return out

def gate(h):
    """True when no file is outside the baseline and none has more hits than the baseline, and the total is at most 15."""
    return sum(h.values()) <= 15 and all(f in BASELINE and n <= BASELINE[f] for f, n in h.items())

h = hits(ROOT)
check("S1 NM-branch names: at most 15 lines, only in the 5 known job files, none above its main count", gate(h), json.dumps(h, sort_keys=True))
plant = tempfile.mkdtemp()
os.makedirs(os.path.join(plant, "job")); open(os.path.join(plant, "job", "new_side_path.py"), "w").write("if Q." + "is_nm" + "_row(row): pass\n")
check("S1 negative control: a new NM branch in a new file is counted and the gate refuses it", gate(hits(plant)) is False and hits(plant) == {"job/new_side_path.py": 1}, str(hits(plant)))
open(os.path.join(plant, "job", "buildqueue.py"), "w").write("\n".join("x = Q." + "is_nm" + "_row(r)" for _ in range(9)) + "\n")
check("S1 negative control: a 9th hit in a known file (8 on main) is refused", gate({"job/buildqueue.py": 9}) is False and gate({"job/buildqueue.py": 8}) is True)

# ---- S2 fence -------------------------------------------------------------------------------------------------------------------------------
def login(item): return {"u": "x", "p": "y"}   # a placeholder getter; the fence must refuse before it matters
def fence_row(rid="r-fence", **kw):
    r = {"id": rid, "directory": "dir.example", "state": "queued", "cost": "free", "needs_code": False, "vaultwarden_item": "item", "mike_approval": None, "right_value": "v", "wrong_field": "f"}
    r.update(kw); return r
GO = lambda rid: {"approved_by": "mike", "at": "2026-11-24T20:00:00-06:00", "row_id": rid}

check("S2 paid row, no approval: refused", raises(lambda: Q.submit_row(fence_row(cost="paid"), login, record=None), Q.SubmitRefused))
check("S2 needs_code true, no approval: refused", raises(lambda: Q.submit_row(fence_row(needs_code=True), login, record=None), Q.SubmitRefused))
check("S2 needs_code true, approval for a DIFFERENT row: refused", raises(lambda: Q.submit_row(fence_row(needs_code=True, mike_approval=GO("other-row")), login, record=None), Q.SubmitRefused))
check("S2 paid row WITH a matching approval: still refused (paid is out of scope)", raises(lambda: Q.submit_row(fence_row(cost="paid", mike_approval=GO("r-fence")), login, record=None), Q.SubmitRefused))
check("S2 approval by someone else: refused", raises(lambda: Q.submit_row(fence_row(mike_approval=dict(GO("r-fence"), approved_by="agent")), login, record=None), Q.SubmitRefused))
calls = []
res = Q.submit_row(fence_row(mike_approval=GO("r-fence")), login, record=lambda *a, **k: calls.append(a) or {})
check("S2 negative control: free row, no code, matching approval passes the fence (dry run, one transition planned)", res["dry_run"] is True and res["next_state"] == "submitted" and len(calls) == 1 and calls[0][0] == "SCC", str(res))
res = Q.submit_row(fence_row(needs_code=True, mike_approval=GO("r-fence")), login, record=lambda *a, **k: {})
check("S2 needs_code true WITH Mike's per-row go is the one allowed path", res["id"] == "r-fence")

# ---- S3 proof writer is business-agnostic ----------------------------------------------------------------------------------------------------
GOOD = {"proof_url": "https://dir.example/biz/1", "proof_nap": "Birch Media | Testville, TN 37099 | (615) 555-0100", "proof_at": "2026-11-24T20:00:00Z", "proof_nap_match": True, "build_action": "new"}

class FakeDB:
    owner = "owner-1"
    def __init__(self, status_rows=None): self.calls, self.status_rows = [], status_rows or []
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("ce_directory_status"):
            m = re.search(r"biz=eq\.(\w+)", path)
            return [r for r in self.status_rows if r["biz"] == m.group(1)]
        if method == "GET": return [{"domain": "dir.example"}]
        return None

def make_q(rows, name="q.json"):
    d = tempfile.mkdtemp(); p = os.path.join(d, name)
    json.dump({"canonical": {"name": "Birch Media", "address": "Testville, TN 37099", "phone": "(615) 555-0100"}, "fix_queue": rows}, open(p, "w")); return p
def qrow(rid="x-1", state="live", directory="dir.example", **kw):
    r = {"id": rid, "directory": directory, "state": state, "history": []}; r.update(kw); return r
def status_posts(db): return [c[2][0] for c in db.calls if c[0] == "POST" and "ce_directory_status" in c[1]]

db = FakeDB(); p = make_q([qrow()])
T.record_proof("x-1", GOOD, queue_path=p, today="2026-11-24", db=db, client="NM")
st = status_posts(db)
check("S3 record_proof(client=NM) posts ONE status row with biz NM, queue_state live, row id and the 5 proof fields", len(st) == 1 and st[0]["biz"] == "NM" and st[0]["queue_state"] == "live" and st[0]["queue_row_id"] == "x-1" and all(st[0][k] == GOOD[k] for k in T.PROOF_FIELDS), str(st))
db = FakeDB(); p = make_q([qrow()])
T.record_proof("x-1", GOOD, queue_path=p, today="2026-11-24", db=db)
check("S3 record_proof default is unchanged: biz SCC", [s["biz"] for s in status_posts(db)] == ["SCC"])
check("S3 record_proof refuses a row that is not live, for NM too, before any DB call", raises(lambda: T.record_proof("x-1", GOOD, queue_path=make_q([qrow(state="submitted")]), db=(lambda d: d)(FakeDB()), client="NM"), T.TransitionRefused))
db = FakeDB(); p = make_q([qrow()])
check("S3 record_proof refuses an incomplete proof, for NM too; the queue and the DB stay untouched", raises(lambda: T.record_proof("x-1", dict(GOOD, proof_nap_match=False), queue_path=p, db=db, client="NM"), T.TransitionRefused) and not db.calls and "proof" not in json.load(open(p))["fix_queue"][0])
db = FakeDB(); T.db_proof_by_directory(db, client="NM"); T.db_proof_by_directory(db)
check("S3 db_proof_by_directory reads the business it is asked for (NM, then the SCC default)", "biz=eq.NM" in db.calls[0][1] and "biz=eq.SCC" in db.calls[1][1], str([c[1][:60] for c in db.calls]))
# no cross-business copy: a live NM row with no proof, and a complete SCC proof for the SAME domain in the status table
scc_row = dict({"biz": "SCC", "directory": "dir.example"}, **GOOD)
db = FakeDB([scc_row]); q = {"fix_queue": [qrow()]}
filled = T.mirror_proof_quiet(q, db, "NM")
check("S3 an SCC proof for the same domain is NOT copied into an NM row (the bug found on the real NM queue)", filled == [] and "proof" not in q["fix_queue"][0], str(filled))
q = {"fix_queue": [qrow()]}
filled = T.mirror_proof_quiet(q, FakeDB([scc_row]), "SCC")
check("S3 positive control: the same call for SCC does fill the SCC row", filled == ["x-1"] and q["fix_queue"][0]["proof"]["proof_url"] == GOOD["proof_url"], str(filled))
db = FakeDB(); p = make_q([qrow()])
src = inspect.getsource(T.record_proof)
def hardcoded(s): return bool(re.search(r"_status_row\(db, \"SCC\"", s))
check("S3 source: record_proof does not hard-code SCC in the status row", not hardcoded(src))
check("S3 mutation: put the hard-coded SCC back and the check above fails", hardcoded(src.replace("_status_row(db, client,", "_status_row(db, \"SCC\",")))

# ---- S4 comparator: street optional is DATA on the canonical -------------------------------------------------------------------------------
CANON_OPT = {"name": "Birch Media", "address": "Testville, TN 37099 on every listing; street 200 Sample Ave only where the form requires it", "phone": "(615) 555-0100",
             "street_if_required": "200 Sample Ave", "retire_phones": ["(615) 555-0112"], "retire_streets": ["900 Old Road, Oldtown TN 37001"]}
CANON_SCC = {"name": "Birch Media", "address": "200 Sample Ave, Testville TN 37099", "phone": "(615) 555-0100"}
def page(*lines): return "Home\n" + "\n".join(lines) + "\n"
def verdict(text, canon=CANON_OPT): return R.compare(text, canon)

c = verdict(page("Birch Media", "Testville, TN 37099", "(615) 555-0100"))
check("S4 city + state + zip + phone, no street: match, quoted as shown", c["verdict"] == "match" and "Testville, TN 37099" in c["nap"], str(c))
c = verdict(page("Birch Media", "Testville, TN", "(615) 555-0100"))
check("S4 city + state (no zip shown) + phone: match, the quote does not invent a zip", c["verdict"] == "match" and c["nap"].endswith("Testville, TN | (615) 555-0100"), str(c))
c = verdict(page("Birch Media", "200 Sample Ave", "Testville, TN 37099", "(615) 555-0100"))
check("S4 the listed optional street + locality: match", c["verdict"] == "match", str(c))
check("S4 wrong zip: mismatch", verdict(page("Birch Media", "Testville, TN 37011", "(615) 555-0100"))["verdict"] == "mismatch")
check("S4 another city: mismatch", verdict(page("Birch Media", "Oldtown, TN 37001", "(615) 555-0100"))["verdict"] == "mismatch")
check("S4 retired street next to the right phone and city: mismatch", verdict(page("Birch Media", "900 Old Road", "Testville, TN 37099", "(615) 555-0100"))["verdict"] == "mismatch")
check("S4 a different street that is not the optional street: mismatch", verdict(page("Birch Media", "123 Main Street", "Testville, TN 37099", "(615) 555-0100"))["verdict"] == "mismatch")
check("S4 old phone: mismatch", verdict(page("Birch Media", "Testville, TN 37099", "(615) 555-0112"))["verdict"] == "mismatch")
check("S4 no locality at all: nap-incomplete (never match)", verdict(page("Birch Media", "(615) 555-0100"))["verdict"] == "nap-incomplete")
check("S4 no phone: nap-incomplete", verdict(page("Birch Media", "Testville, TN 37099"))["verdict"] == "nap-incomplete")
check("S4 control: a canonical WITHOUT street_if_required still needs the street (city-only page is not a match)", verdict(page("Birch Media", "Testville, TN 37099", "(615) 555-0100"), CANON_SCC)["verdict"] == "nap-incomplete")
check("S4 control: the same canonical with its street shown is a match as before", verdict(page("Birch Media", "200 Sample Ave", "Testville, TN 37099", "(615) 555-0100"), CANON_SCC)["verdict"] == "match")

print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
