"""recheck --any-state --write promotes a NAMED needs-human row to live on a match, and changes nothing else (t_dca17786).
No network, no browser, no vault, no prod env: fakes and temp files only. Run: python tests/recheck_promote_test.py (CI)."""
import os, sys, json, tempfile, copy, io, urllib.request, contextlib, types
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
os.environ["CE_ACTIVITIES_WRITE"] = "1"
os.environ["CE_DIRECTORIES_WRITE"] = "1"
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
import recheck as R, transitions as T, buildqueue as Q

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f" [{d}]" if d else ""), flush=True)

IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
PAD = " Lorem ipsum dolor sit amet." * 12
GOOD = "Home\nAlder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n(502) 555-0101\n%s\n" % PAD
NO_PHONE = "Home\nAlder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n%s\n" % PAD
WRONG_PHONE = "Home\nAlder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n(502) 555-0199\n%s\n" % PAD
URL = "https://nextdoor.example/pages/alder-care"
QP = os.path.join(tempfile.mkdtemp(), "queue.json")
def row(i, d, state, **kw): return dict({"id": i, "directory": d, "state": state, "mike_approval": None, "history": []}, **kw)
def fresh_rows(): return [row("create-nh", "nextdoor.example", "needs-human", listing_url=URL),
                          row("create-other-nh", "other.example", "needs-human", listing_url="https://other.example/x"),
                          row("create-sub", "sub.example", "submitted", listing_url="https://sub.example/y")]
def write_q(rows): json.dump({"canonical": CANON, "fix_queue": [], "create_rows": rows}, open(QP, "w"))
def queue(): return json.load(open(QP))
def rows_by_id(): return {r["id"]: r for r in queue()["create_rows"]}

class Sink:
    """Records every call: queue snapshot sink, Directory DB, activities, verification."""
    def __init__(s): s.calls = []
    owner = "owner-x"
    def call(s, method, path, body=None, prefer=None): s.calls.append((method, path, body)); return []
    def latest_snapshot(s, cid): return {"payload": {"directories": [], "totals": {}}}
    def upsert_snapshot(s, cid, day, payload): pass
SINK = Sink()
def real_record(*a, **k):
    return T.record_transition(*a, portal=SINK, directories=SINK, activities=SINK, activities_flag=True, verification=SINK, **k)
def plain_of(text, status=200): return lambda u: R.Page(status, u, text, html="<html>%s</html>" % text)

def run(mod, text, only=("create-nh",), status=200, **kw):
    SINK.calls.clear()
    q = queue()
    with contextlib.redirect_stdout(io.StringIO()):
        return mod.recheck(q, IDENT, plain=plain_of(text, status), chrome=None, record=real_record, db=SINK, queue_path=QP, today="2026-11-13", use_chrome=False, only=set(only), any_state=True, **kw)

# ---- 1 match: needs-human -> live through the one live writer ------------------------------------------------------------------------------------
write_q(fresh_rows()); others_before = {k: json.dumps(v, sort_keys=True) for k, v in rows_by_id().items() if k != "create-nh"}
res = run(R, GOOD, write=True)
nh = rows_by_id()["create-nh"]
check("1 verdict match, row report says needs-human -> live", res[0]["verdict"] == "match" and res[0]["before"] == "needs-human" and res[0]["after"] == "live", str(res[0]))
check("1 queue row is live with listing_url and a history entry needs-human -> live", nh["state"] == "live" and nh["listing_url"] == URL and nh["history"][-1]["from"] == "needs-human" and nh["history"][-1]["to"] == "live", str(nh))
pf = next((b[0] for m, p, b in SINK.calls if p.startswith("ce_directory_status") and b and b[0].get("queue_state") == "live"), None)
check("1 ce_directory_status upsert carries queue_state live + complete Proof (proof_url, nap, at, match True, build_action)", bool(pf) and not T.proof_problems(pf) and pf["proof_url"] == URL and pf["proof_nap_match"] is True, str(pf))
ver = [c for c in SINK.calls if c[0] == "PATCH" and c[1].startswith("citation_verification")]
check("1 citation_verification row marked live with verified_at", len(ver) == 1 and ver[0][2]["state"] == "live" and ver[0][2].get("verified_at"), str(ver))
act = [c for c in SINK.calls if c[0] == "POST" and c[1].startswith("deliverables")]
check("1 client activity written for the live move", len(act) == 1, str(act))
check("1 the other rows (needs-human + submitted) are byte-identical", {k: json.dumps(v, sort_keys=True) for k, v in rows_by_id().items() if k != "create-nh"} == others_before)

# ---- 2 second run writes 0 -----------------------------------------------------------------------------------------------------------------------
before_bytes = open(QP, "rb").read()
res2 = run(R, GOOD, write=True)
check("2 second run: the row is live now, named --any-state --write skips it unread and writes nothing (queue bytes and sink calls)", open(QP, "rb").read() == before_bytes and not SINK.calls and res2[0]["verdict"] is None and "needs-human rows only" in res2[0]["note"], str(res2[0]))

# ---- 3 every other verdict leaves the parked row exactly as it was -------------------------------------------------------------------------------
CASES = [("nap-incomplete", NO_PHONE, 200), ("mismatch", WRONG_PHONE, 200), ("unreadable", "", 500), ("wall", "Attention Required! Cloudflare. Just a moment... Checking your browser", 403)]
def no_demote(mod, label_prefix, strict_verdicts=True):
    all_ok = True
    for name, text, status in CASES:
        write_q(fresh_rows()); b = open(QP, "rb").read()
        res = run(mod, text, write=True)
        same = open(QP, "rb").read() == b and not SINK.calls
        all_ok = all_ok and same
        check("%s %s on a needs-human row: queue byte-identical, no sink call, still needs-human (verdict %s)" % (label_prefix, name, res[0]["verdict"]), same and res[0]["after"] == "needs-human", str((res[0]["verdict"], res[0]["note"], res[0]["error"])))
    return all_ok
no_demote(R, "3")
write_q(fresh_rows()); res = run(R, WRONG_PHONE, write=True)
check("3 the mismatch verdict is still printed (field named in the report)", res[0]["verdict"] == "mismatch" and "phone" in R.format_report(res), R.format_report(res))

# ---- 4 only named needs-human rows are written; a named non-needs-human row is not read -----------------------------------------------------------
write_q(fresh_rows()); b = open(QP, "rb").read()
res = run(R, GOOD, only=("create-sub",), write=True)
check("4 a named SUBMITTED row under --any-state --write is not read and not promoted", open(QP, "rb").read() == b and not SINK.calls and res[0]["verdict"] is None and res[0]["after"] == "submitted", str(res[0]))
write_q(fresh_rows()); res = run(R, GOOD, only=("create-nh", "create-other-nh"), write=True)
rb = rows_by_id()
check("4 two named needs-human rows both promote; the unnamed submitted row is untouched", rb["create-nh"]["state"] == rb["create-other-nh"]["state"] == "live" and rb["create-sub"]["state"] == "submitted" and not rb["create-sub"]["history"], str([r["state"] for r in rb.values()]))
write_q(fresh_rows()); b = open(QP, "rb").read(); res = run(R, GOOD, only=("create-nh",), write=False)
check("4 --any-state without --write is still a dry run (match reported, queue bytes unchanged)", res[0]["verdict"] == "match" and res[0]["after"] == "live" and open(QP, "rb").read() == b and not SINK.calls)

# ---- 5 refusals ----------------------------------------------------------------------------------------------------------------------------------
write_q(fresh_rows()); b = open(QP, "rb").read()
for kw, why in (({"backoff_only": True}, "backoff-only"), ({"proof_live": True}, "proof-live")):
    try: run(R, GOOD, write=True, **kw); e = None
    except Q.QueueError as ex: e = str(ex)
    check("5 --any-state --write + %s is refused" % why, bool(e) and why.replace("-", "_") in e.replace("-", "_"), str(e))
try: run(R, GOOD, only=(), write=True); e = None
except Q.QueueError as ex: e = str(ex)
check("5 --any-state --write without --row is refused (function)", bool(e) and "--row" in e, str(e))
errb = io.StringIO()
with contextlib.redirect_stderr(errb):
    rcs = [R.main(["--queue", QP, "--any-state", "--write"]), R.main(["--queue", QP, "--any-state", "--write", "--backoff-only", "--row", "create-nh"]),
           R.main(["--queue", QP, "--any-state", "--write", "--proof-live", "--include-live", "--row", "create-nh"]), R.main(["--queue", QP, "--any-state"])]
check("5 CLI: --any-state without --row, with --backoff-only, with --proof-live: exit 1, REFUSED, nothing written", rcs == [1, 1, 1, 1] and errb.getvalue().count("REFUSED") == 4 and open(QP, "rb").read() == b, str(rcs))

# ---- 6 mutations: each guard removed must fail its test -----------------------------------------------------------------------------------------
src = open(os.path.join(JOB, "recheck.py"), encoding="utf-8", newline="").read()
def mutant(old, new):
    assert src.count(old) == 1, old
    m = types.ModuleType("recheck_mut"); m.__file__ = os.path.join(JOB, "recheck.py")
    exec(compile(src.replace(old, new), m.__file__, "exec"), m.__dict__)
    return m
with contextlib.redirect_stdout(io.StringIO()):
    M1 = mutant('            elif parked:', '            elif False:')   # the no-demote / no-note branch removed: a non-match verdict writes a note onto the parked row
    M2 = mutant('if any_state and write and not parked:', 'if False:')    # the needs-human guard removed: a named non-parked row is read and promoted
def silent(f, *a):   # the mutant's own inner checks are expected to fail: run them quietly and keep them out of the tally
    n = len(ok)
    with contextlib.redirect_stdout(io.StringIO()): r = f(*a)
    del ok[n:]
    return r
check("6 MUTATION: dropping the non-match branch makes the no-demote test fail (a note lands on the parked row)", not silent(no_demote, M1, "m1"))
write_q(fresh_rows()); b = open(QP, "rb").read(); res = run(M2, GOOD, only=("create-sub",), write=True)
check("6 MUTATION: dropping the needs-human guard makes the named-submitted-row test fail (it goes live)", open(QP, "rb").read() != b and rows_by_id()["create-sub"]["state"] == "live", str(res[0]["after"]))
write_q(fresh_rows()); res = run(R, GOOD, write=True)
check("6 control: the unmutated code passes both after the mutants ran", rows_by_id()["create-nh"]["state"] == "live")

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
