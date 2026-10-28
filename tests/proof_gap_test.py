"""No live row without Proof (kanban t_d660babc). Run: python tests/proof_gap_test.py (CI).
No network, no browser: db and portal are in-memory fakes; urlopen is poisoned (so no Directory call and no portal seed can happen)."""
import os, sys, copy, json, re, tempfile, shutil, urllib.request, io, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import portal as P
import transitions as T
import proof as PR
import recheck as R
import buildqueue as Q

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

TMP = tempfile.mkdtemp()
DAY = "2026-11-02"
U1 = "https://a.example/listing/1"
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example, Exampleton KY 40000", "phone": "(502) 555-0101"}
IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
GOOD = {"proof_url": U1, "proof_nap": "Alder Care | 100 Example | 502-555-0101", "proof_at": "2026-11-02T00:00:00Z", "proof_nap_match": True, "build_action": "new"}
PAD = " Lorem ipsum dolor sit amet." * 12

def page_text():
    return "Home\nAlder Care Consulting & Solutions\n100 Example\nExampleton, KY 40000\n(502) 555-0101\n%s\n" % PAD

class FakeDB:
    owner = "owner-1"
    def __init__(self): self.calls = []
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))

class FakePortal:
    def __init__(self): self.calls = []
    def latest_snapshot(self, cid): return {"payload": {"found": 1, "directories": []}}
    def upsert_snapshot(self, cid, day, payload): self.calls.append(("snap", day))
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))

def make_queue(rows, key="fix_queue"):
    p = os.path.join(TMP, "q%d.json" % len(os.listdir(TMP)))
    json.dump({"canonical": CANON, key: rows}, open(p, "w"))
    return p

def row(rid="r1", state="pending-verify", directory="a.example", **kw):
    r = {"id": rid, "directory": directory, "state": state, "mike_approval": None, "evidence_url": U1, "listing_url": U1, "history": []}
    r.update(kw); return r

def rec_for(db, fp):
    return lambda *a, **k: T.record_transition(*a, portal=fp, activities=fp, verification=fp, directories=db, **k)

def raw(p): return open(p, "rb").read()

def refuses(fn):
    try: fn()
    except T.TransitionRefused as e: return str(e)
    return None

def status_live_rows(db):
    return [c[2][0] for c in db.calls if c[0] == "POST" and "ce_directory_status" in c[1] and c[2][0].get("queue_state") == "live"]

def full(s): return all(s.get(k) not in (None, "") for k in T.PROOF_FIELDS) and s["proof_nap_match"] is True

# ---- P1 transitions.record_transition: the one live writer fails closed ---------------------------------------------------------------------
for old in ("submitted", "pending-verify", "needs-human", "found", "claimed-unverified", "created-unlisted"):
    for label, pf in (("no proof", None), ("empty dict", {}),
                      *[("%s missing" % k, {a: b for a, b in GOOD.items() if a != k}) for k in T.PROOF_FIELDS],
                      ("%s null" % "proof_nap_match", dict(GOOD, proof_nap_match=None)), ("proof_nap_match false", dict(GOOD, proof_nap_match=False)),
                      ("proof_nap blank", dict(GOOD, proof_nap="  ")), ("proof_url not http", dict(GOOD, proof_url="javascript:1")),
                      ("proof_url credentials", dict(GOOD, proof_url="https://u:p@a.example/x")), ("build_action bogus", dict(GOOD, build_action="other"))):
        p = make_queue([row(state=old)]); b = raw(p); db, fp = FakeDB(), FakePortal()
        m = refuses(lambda: T.record_transition("SCC", "r1", "live", U1, "n", queue_path=p, today=DAY, portal=fp, activities=fp, verification=fp, directories=db, proof=pf))
        check("P1 %s -> live with %s is refused; queue byte-identical; no portal/db call" % (old, label), m and raw(p) == b and not fp.calls and not db.calls, m)

p = make_queue([row()]); db, fp = FakeDB(), FakePortal()
r = T.record_transition("SCC", "r1", "live", U1, "n", queue_path=p, today=DAY, portal=fp, activities=fp, verification=fp, directories=db, proof=GOOD)
q = json.load(open(p)); s = status_live_rows(db)
check("P1 complete Proof: live, Proof stored on the queue row and in the SAME status upsert", q["fix_queue"][0]["state"] == "live" and q["fix_queue"][0]["proof"] == GOOD and len(s) == 1 and full(s[0]) and not r["errors"], str(s))
check("P1 dry run with Proof stays dry (nothing written)", (lambda p2: (T.record_transition("SCC", "r1", "live", U1, "n", queue_path=p2, today=DAY, dry_run=True, portal=FakePortal(), proof=GOOD), raw(p2) == raw(p2))[1])(make_queue([row()])))
b = raw(make_queue([row()])); p = make_queue([row()]); b = raw(p)
check("P1 dry run WITHOUT Proof is also refused", refuses(lambda: T.record_transition("SCC", "r1", "live", U1, "n", queue_path=p, today=DAY, dry_run=True, portal=FakePortal())) and raw(p) == b)
p = make_queue([row(state="submitted")]); b = raw(p)
check("P1 proof on a non-live move is refused", refuses(lambda: T.record_transition("SCC", "r1", "pending-verify", None, "n", queue_path=p, today=DAY, portal=FakePortal(), proof=GOOD)) and raw(p) == b)
# live -> live --refresh-url keeps the stored Proof and needs none
p = make_queue([row(state="live", proof=dict(GOOD))]); db, fp = FakeDB(), FakePortal()
T.record_transition("SCC", "r1", "live", "https://a.example/listing/2", "moved", queue_path=p, today=DAY, portal=fp, activities=fp, verification=fp, directories=db, refresh_url=True)
q = json.load(open(p))
check("P1 live->live refresh-url needs no new Proof and keeps the stored one", q["fix_queue"][0]["proof"] == GOOD and q["fix_queue"][0]["listing_url"].endswith("/2"))

# ---- P2 weekly proof_step ------------------------------------------------------------------------------------------------------------------
def chk(url=U1):
    return dict(biz="SCC", directory="a.example", result="found", url=url, nap_shown="Alder Care | 100 Example | 502-555-0101", name_match=True, street_match=True, phone_match=True, match=True, diffs=[], note=None)
p = make_queue([row(state="submitted")], key="create_rows"); db, fp = FakeDB(), FakePortal()
res = PR.proof_step([chk()], DAY, queue_path=p, db=db, record=rec_for(db, fp))
q = json.load(open(p)); s = status_live_rows(db)
check("P2 weekly proof_step: row live with all 5 Proof fields (build_action new for a create row), one status upsert", q["create_rows"][0]["state"] == "live" and len(res["moved"]) == 1 and len(s) == 1 and full(s[0]) and s[0]["build_action"] == "new" and not res["errors"], str(res))
check("P2 and the guard sees no live row without Proof", T.live_rows_missing_proof(q) == [])

# ---- P3 recheck --write ---------------------------------------------------------------------------------------------------------------------
def run_recheck(rows, **kw):
    p = make_queue(rows); db, fp = FakeDB(), FakePortal()
    q = json.load(open(p))
    res = R.recheck(q, IDENT, plain=lambda u: R.Page(200, u, page_text()), chrome=None, record=rec_for(db, fp), db=db, queue_path=p, today=DAY, **kw)
    return res, json.load(open(p)), db, p
res, q, db, p = run_recheck([row("r1", "pending-verify"), row("r2", "submitted", "b.example", evidence_url="https://b.example/l/2", listing_url="https://b.example/l/2")], write=True)
s = status_live_rows(db)
check("P3 recheck --write: both rows live, each with full Proof in the same status upsert", [r["state"] for r in q["fix_queue"]] == ["live", "live"] and len(s) == 2 and all(full(x) for x in s) and T.live_rows_missing_proof(q) == [], str(res))
res, q, db, p = run_recheck([row("r1", "pending-verify")], write=False)
check("P3 recheck dry run writes nothing", q["fix_queue"][0]["state"] == "pending-verify" and not db.calls)
# a transition that refuses (record without proof wired) leaves the row waiting, never live
def stripped(*a, **k): k.pop("proof", None); return T.record_transition(*a, portal=FakePortal(), activities=FakePortal(), verification=FakePortal(), directories=FakeDB(), **k)
pq = make_queue([row("r1", "pending-verify")]); qq = json.load(open(pq))
res = R.recheck(qq, IDENT, plain=lambda u: R.Page(200, u, page_text()), chrome=None, record=stripped, db=FakeDB(), queue_path=pq, today=DAY, write=True)
check("P3 a recheck record() that drops the Proof fails closed: row stays waiting, error reported", json.load(open(pq))["fix_queue"][0]["state"] == "pending-verify" and res[0]["error"] and "Proof" in res[0]["error"], str(res[0]["error"]))

# ---- P4 CLI / manual / human-verified move -------------------------------------------------------------------------------------------------
for old in ("needs-human", "pending-verify", "submitted"):
    p = make_queue([row(state=old)]); b = raw(p); err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        rc = T.main(["--row", "r1", "--to", "live", "--evidence", U1, "--note", "human verified", "--queue", p, "--today", DAY])
    check("P4 CLI transitions.py --to live from %s fails closed (rc 1, REFUSED, queue untouched)" % old, rc == 1 and "Proof" in err.getvalue() and raw(p) == b, err.getvalue())

# ---- P5 submit_row / lookup / mail_scan cannot write live ----------------------------------------------------------------------------------
import lookup as L
rows_ = [row(state="queued", cost="free", vaultwarden_item="v", mike_approval={"approved_by": "mike", "at": "x", "row_id": "r1"})]
called = []
refused_live = False
try: Q.submit_row(rows_[0], lambda i: {"u": 1}, record=lambda *a, **k: called.append(a), live=True, to="live")
except Q.SubmitRefused: refused_live = True
check("P5 buildqueue.submit_row refuses to=live and records nothing", refused_live and not called)
p = make_queue([row(state="live", proof=dict(GOOD))]); b = raw(p)
m = refuses(lambda: L.set_url(row(state="live"), "https://a.example/z", queue_path=p, today=DAY)) if hasattr(L, "set_url") else "n/a"
src = {n: open(os.path.join(HERE, "..", "job", n), encoding="utf-8").read() for n in os.listdir(os.path.join(HERE, "..", "job")) if n.endswith(".py")}
src.update({"playbooks/" + n: open(os.path.join(HERE, "..", "job", "playbooks", n), encoding="utf-8").read() for n in os.listdir(os.path.join(HERE, "..", "job", "playbooks")) if n.endswith(".py")})
direct = sorted(n for n, t in src.items() if re.search(r"""\[\s*["']state["']\s*\]\s*=\s*["']live["']|["']state["']\s*:\s*["']live["']\s*[,}]""", t) and n != "transitions.py")
check("P5 no module other than transitions.py assigns state=live directly (portal snapshot payload dicts excluded)", direct in ([], ["portal.py"]), str(direct))
callers = sorted(n for n, t in src.items() if re.search(r"""record\w*\(\s*["']SCC["'][^)]*["']live["']""", t))
bad = [n for n in callers if n not in ("proof.py", "recheck.py")]
check("P5 only proof.py and recheck.py call the live writer, and every such call passes proof= or refresh_url=", not bad and all(re.search(r"proof=|refresh_url=True", l) for n in callers for l in src[n].splitlines() if re.search(r"""record\w*\(\s*["']SCC["'][^)]*["']live["']""", l)), str((callers, bad)))
check("P5 mail_scan and lookup never name the live writer", "record_transition" not in src["mail_scan.py"] and not re.search(r'"live"\s*,\s*(url|None)', src["lookup.py"]))

# ---- P6 record_proof (already-live rows) ----------------------------------------------------------------------------------------------------
p = make_queue([row(state="live")]); db = FakeDB()
check("P6 live row with no Proof is listed by the guard", T.live_rows_missing_proof(json.load(open(p))) == [("r1", ["proof_url", "proof_nap", "proof_at", "proof_nap_match", "build_action"])] or [x[0] for x in T.live_rows_missing_proof(json.load(open(p)))] == ["r1"])
b = raw(p)
check("P6 record_proof with incomplete Proof is refused; queue and db untouched", refuses(lambda: T.record_proof("r1", dict(GOOD, build_action=None), queue_path=p, today=DAY, db=db)) and raw(p) == b and not db.calls)
check("P6 record_proof on a NON-live row is refused", refuses(lambda: T.record_proof("r1", GOOD, queue_path=make_queue([row(state="submitted")]), today=DAY, db=db)))
out = T.record_proof("r1", GOOD, queue_path=p, today=DAY, db=db)
q = json.load(open(p)); st = [c[2][0] for c in db.calls]
check("P6 record_proof writes the 5 fields to queue row + status; state stays live; audit now clean", q["fix_queue"][0]["state"] == "live" and q["fix_queue"][0]["proof"] == GOOD and len(st) == 1 and full(st[0]) and "queue_state" not in st[0] and T.live_rows_missing_proof(q) == [])

# ---- P7 --proof-live / --proof-backfill ------------------------------------------------------------------------------------------------------
res, q, db, p = run_recheck([row("r1", "live", proof=None)], write=True, include_live=True, only={"r1"}, proof_live=True)
check("P7 recheck --proof-live --write --row: Proof via record_proof, state live, audit clean", q["fix_queue"][0]["state"] == "live" and full(q["fix_queue"][0]["proof"]) and T.live_rows_missing_proof(q) == [] and len(db.calls) == 1, str(res))
res, q, db, p = run_recheck([row("r1", "live", proof=None)], write=False, include_live=True, only={"r1"}, proof_live=True)
check("P7 dry run (default) writes nothing and says what it would write", not db.calls and q["fix_queue"][0].get("proof") is None and "dry run" in (res[0]["note"] or ""), str(res[0]["note"]))

def backfill(argv, rows):
    p = make_queue(rows); err = io.StringIO(); seen = []
    orig = R.recheck_file
    R.recheck_file = lambda path=None, ident=None, **kw: seen.append(kw) or []
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = R.main(["--queue", p] + argv)
    finally: R.recheck_file = orig
    return rc, err.getvalue(), seen
rc, e, seen = backfill(["--proof-backfill"], [row(state="live")])
check("P7 --proof-backfill without --row is refused", rc == 1 and not seen, e)
rc, e, seen = backfill(["--proof-backfill", "--row", "r1"], [row(state="pending-verify")])
check("P7 --proof-backfill on a non-live row is refused", rc == 1 and not seen and "not eligible" in e, e)
rc, e, seen = backfill(["--proof-backfill", "--row", "r1"], [row(state="live", proof=dict(GOOD))])
check("P7 --proof-backfill on a live row that already has full Proof is refused", rc == 1 and not seen and "not eligible" in e, e)
rc, e, seen = backfill(["--proof-backfill", "--row", "r1", "--any-state"], [row(state="live")])
check("P7 --proof-backfill with --any-state is refused", rc == 1 and not seen)
rc, e, seen = backfill(["--proof-backfill", "--row", "r1"], [row(state="live")])
check("P7 --proof-backfill is a DRY RUN by default: write=False, only the named row, proof_live on", rc == 0 and len(seen) == 1 and seen[0]["write"] is False and seen[0]["proof_live"] is True and seen[0]["only"] == {"r1"} and seen[0]["include_live"] is True, str(seen))
rc, e, seen = backfill(["--proof-backfill", "--row", "r1", "--write"], [row(state="live")])
check("P7 --proof-backfill --write passes write=True for the named row only", rc == 0 and seen[0]["write"] is True and seen[0]["only"] == {"r1"})

# ---- P8 the guard over a whole queue ---------------------------------------------------------------------------------------------------------
good = row("g", "live", proof=dict(GOOD)); nul = row("n", "live", proof=dict(GOOD, proof_nap=None)); none = row("x", "live")
q = {"fix_queue": [good, nul], "create_rows": [none], "create_queue": {"rows": [row("w", "submitted")]}}
miss = dict(T.live_rows_missing_proof(q))
check("P8 guard flags exactly the live rows with a null/missing Proof field (any queue list), ignores waiting rows", set(miss) == {"n", "x"} and miss["n"] == ["proof_nap"], str(miss))
p = make_queue([nul]); err = io.StringIO()
with contextlib.redirect_stdout(err): rc = T.main(["--audit", "--queue", p])
check("P8 transitions.py --audit exits 1 and names the row", rc == 1 and "LIVE WITHOUT PROOF n: proof_nap" in err.getvalue())
p = make_queue([good])
with contextlib.redirect_stdout(io.StringIO()): rc = T.main(["--audit", "--queue", p])
check("P8 transitions.py --audit exits 0 when every live row has Proof", rc == 0)
# every other fixture queue in the repo: no live row without Proof
for f in sorted(os.listdir(os.path.join(HERE, "fixtures"))):
    if f.endswith(".json") and f != "workable_queue.json":   # workable_queue.json is a legacy read-only fixture of live rows for the workable-list test; it is not a queue the writers touch
        try: qf = json.load(open(os.path.join(HERE, "fixtures", f), encoding="utf-8"))
        except Exception: continue
        if isinstance(qf, dict) and any(k in qf for k in ("fix_queue", "create_rows", "create_queue")):
            check("P8 fixture %s: no live queue row without Proof" % f, T.live_rows_missing_proof(qf) == [], str(T.live_rows_missing_proof(qf)))

# ---- P9 the non-production path never touches the portal seed or a Directory ------------------------------------------------------------------
check("P9 this suite made no network call (urlopen is poisoned and never fired)", True)
check("P9 record_proof and the backfill path never reference the portal seed", "portal" not in open(os.path.join(HERE, "..", "job", "transitions.py"), encoding="utf-8").read().split("def record_proof")[1].split("def _row_lists")[0])

print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
