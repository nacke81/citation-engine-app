"""t_d9ed56f5: an existing listing recorded live posts ONE client row "Your <Directory> listing is confirmed live".
Run: python tests/existing_activity_test.py (CI). No network: urlopen is poisoned, the portal is a fake that records calls.
Mutations at the end prove the title test, the NAP gate and the one-writer rule can fail."""
import os; os.environ["CE_DIRECTORIES_WRITE"] = "0"   # never write the prod Directory DB
import sys, json, re, tempfile, urllib.request, io, contextlib, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
os.environ["CE_PORTAL_ENV"] = os.path.join(HERE, "no-such-portal.env")   # fail closed, never the prod portal
sys.path.insert(0, os.path.join(ROOT, "job"))
import transitions as T
import portal as P

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (("  [%s]" % d) if d else ""), flush=True)

SCC = P.ALLOWED["SCC"]; DAY = "2026-11-17"
class Portal:
    def __init__(self, fail=False): self.calls, self.fail, self.rows = [], fail, {}
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        if self.fail: raise P.PortalWriteError("boom")
        for r in body or []: self.rows[(r["client_id"], r["source_ref"])] = r   # on_conflict client_id,source_ref: an upsert
class DB:
    owner = "o1"
    def __init__(self): self.calls = []
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path))
        if method == "GET" and path.startswith("ce_directories?"): return [{"domain": "x"}]
        return []
QUEUE = {"fix_queue": [], "create_queue": {"rows": []}}
def fresh():
    d = tempfile.mkdtemp(prefix="ce-exact-"); p = os.path.join(d, "scc-fix-create-queue.json"); json.dump(QUEUE, open(p, "w")); return p
OK = dict(proof_url="https://maps.apple.com/place?auid=1", proof_nap="Senior Care Consulting | 1 Main St | 502-555-0101", proof_at="2026-11-17T12:00:00Z")
def rec(p, portal, domain="maps.apple.com", **kw): return T.record_existing("SCC", domain, queue_path=p, today=DAY, db=DB(), activities=portal, **dict(OK, **kw))
def qbytes(p): return open(p, "rb").read()

# --- real path: one row, right fields, through the one writer
p = fresh(); pt = Portal(); out = rec(p, pt)
check("A1 exactly one POST to deliverables on the real path", len(pt.calls) == 1 and pt.calls[0][0] == "POST" and pt.calls[0][1] == P.DELIVERABLES_PATH and len(pt.calls[0][2]) == 1, pt.calls)
r = pt.calls[0][2][0]
check("A2 title is 'Your <Directory> listing is confirmed live'", r["title"] == "Your maps.apple.com listing is confirmed live", r["title"])
check("A3 source_ref citation-existing:<row id>:live", r["source_ref"] == "citation-existing:scc-existing-maps-apple-com:live", r["source_ref"])
check("A4 fields: citation, SEO & Local SEO, SCC client, in_scope, units 1, evidence = proof url", (r["deliverable_type"], r["channel_label"], r["client_id"], r["in_scope"], r["units"], r["evidence_url"]) == ("citation", "SEO & Local SEO", SCC, True, 1, OK["proof_url"]), r)
check("A5 approved_at set and source citation_engine (the #139 helper)", r["approved_at"] and r["source"] == "citation_engine", r)
check("A6 date_completed is the confirmed (proof) date, not today", r["date_completed"] == "2026-11-17", r["date_completed"])
check("A7 title never says added/built/submitted", not re.search(r"(?i)\b(added|built|submitted)\b", r["title"]))
check("A8 result reports the write", out["activities_written"] is True and out["errors"] == [], out)

# --- idempotency: re-running on the same row writes no second row
pt2 = Portal(); T.post_existing_activity("SCC", "scc-existing-maps-apple-com", queue_path=p, activities=pt2)
T.post_existing_activity("SCC", "scc-existing-maps-apple-com", queue_path=p, activities=pt2)
pt2.rows.update(pt.rows)
check("B1 same source_ref twice -> one row in the feed", len(pt2.rows) == 1 and all(c[2][0]["source_ref"] == r["source_ref"] for c in pt2.calls))
try: rec(p, Portal()); again = False
except T.TransitionRefused: again = True
check("B2 record_existing on the same directory again is refused (no second row, no write)", again)

# --- dry run: no write, shows the request
p3 = fresh(); b3 = qbytes(p3); pt3 = Portal(); db3 = DB()
dr = T.record_existing("SCC", "maps.apple.com", queue_path=p3, today=DAY, db=db3, activities=pt3, dry_run=True, **OK)
check("D1 dry run: no portal call, no DB call, queue bytes unchanged", not pt3.calls and not db3.calls and qbytes(p3) == b3)
check("D2 dry run shows the request it would send", dr["activities_request"]["method"] == "POST" and dr["activities_request"]["path"] == P.DELIVERABLES_PATH and dr["activities_request"]["body"][0]["title"] == "Your maps.apple.com listing is confirmed live", dr.get("activities_request"))
dd = T.post_existing_activity("SCC", "scc-existing-maps-apple-com", queue_path=p, activities=Portal(), dry_run=True)
check("D3 backfill dry run shows the request and writes nothing", dd["activities_request"]["body"][0]["source_ref"] == r["source_ref"] and dd["activities_written"] is False)

# --- NAP mismatch posts nothing
pn = fresh(); ptn = Portal()
try: rec(pn, ptn, proof_nap_match=False); raised = False
except T.TransitionRefused: raised = True
check("N1 proof_nap_match false: refused, queue unchanged, 0 portal calls", raised and not ptn.calls and qbytes(pn) == json.dumps(QUEUE).encode())
row = dict(id="x", directory="a.com", state="live", evidence_url="https://a.com/1", proof=dict(OK, proof_nap_match=False, build_action="existing"))
check("N2 builder returns None for a false/missing/truthy-string NAP match", all(T.build_existing_activity(SCC, dict(row, proof=dict(row["proof"], proof_nap_match=v))) is None for v in (False, None, "true", 1)))
check("N3 builder returns None for a non-existing build_action or a non-live row", T.build_existing_activity(SCC, dict(row, proof=dict(OK, proof_nap_match=True, build_action="new"))) is None and T.build_existing_activity(SCC, dict(row, state="queued", proof=dict(OK, proof_nap_match=True, build_action="existing"))) is None)

# --- failure in the feed never undoes the queue; flag off posts nothing
pf = fresh(); out = rec(pf, Portal(fail=True))
check("F1 feed failure is reported, the queue row is still written", out["activities_written"] is False and out["errors"] and json.load(open(pf))["fix_queue"][0]["state"] == "live", out["errors"])
os.environ["CE_ACTIVITIES_WRITE"] = "0"; pq = fresh(); ptq = Portal(); rec(pq, ptq)
check("F2 CE_ACTIVITIES_WRITE=0 posts nothing", not ptq.calls); os.environ.pop("CE_ACTIVITIES_WRITE")
pr = fresh(); ptr = Portal()
try: T.record_existing("NM", "maps.apple.com", queue_path=pr, today=DAY, db=DB(), activities=ptr, **OK)
except T.TransitionRefused: pass
check("F3 NM client: refused, nothing posted", not ptr.calls)

# --- CLI backfill path
with contextlib.redirect_stdout(io.StringIO()) as buf:
    rc = T.main(["--existing-activity", "--client", "SCC", "--row", "scc-existing-maps-apple-com", "--queue", p, "--dry-run"])
check("C1 CLI --existing-activity --dry-run exits 0 and prints the confirmed-live request", rc == 0 and "confirmed live" in buf.getvalue())

# --- t_9f3a9323: --record-existing CLI exit code when the client-row post fails
def _cli_record(p, writer):
    real, realp, realenv = P.write_deliverables, P.Portal, P.load_portal_env
    P.write_deliverables, P.Portal, P.load_portal_env = writer, (lambda *a, **k: Portal()), (lambda *a, **k: ("u", "k"))
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            rc = T.main(["--record-existing", "--client", "SCC", "--domain", "maps.apple.com", "--proof-url", OK["proof_url"], "--proof-nap", OK["proof_nap"], "--proof-at", OK["proof_at"], "--queue", p, "--today", DAY])
        return rc, err.getvalue()
    finally: P.write_deliverables, P.Portal, P.load_portal_env = real, realp, realenv
def _raise(*a, **k): raise P.PortalWriteError("boom")
pr1 = fresh(); rc1, err1 = _cli_record(pr1, _raise)
check("R1 failed client-row post: CLI rc 1, queue row still written, retry command printed", rc1 == 1 and json.load(open(pr1))["fix_queue"][0]["state"] == "live" and "--existing-activity --client SCC --row scc-existing-maps-apple-com" in err1, "rc=%s err=%s" % (rc1, err1))
pr2 = fresh(); rc2, _e = _cli_record(pr2, P.write_deliverables)
check("R2 clean post: CLI rc 0", rc2 == 0, rc2)

# --- one writer: the module names no deliverables path of its own
src = open(os.path.join(ROOT, "job", "transitions.py"), encoding="utf-8").read()
check("W1 transitions.py has no literal deliverables path and calls write_deliverables", "deliverables?" not in src and "P.write_deliverables(" in src)

# --- mutations: each must be caught by the checks above
def run_mutant(name, old, new, probe):
    code = src.replace(old, new); assert code != src, name
    d = tempfile.mkdtemp(prefix="ce-mut-"); mp = os.path.join(d, "transitions.py"); open(mp, "w", encoding="utf-8").write(code)
    env = dict(os.environ, CE_MUT_PATH=d)
    t = open(__file__, encoding="utf-8").read().replace('sys.path.insert(0, os.path.join(ROOT, "job"))', 'sys.path.insert(0, os.path.join(ROOT, "job")); sys.path.insert(0, os.environ["CE_MUT_PATH"])')
    tp = os.path.join(d, "t.py"); open(tp, "w", encoding="utf-8").write(t.replace("HERE = os.path.dirname(os.path.abspath(__file__))", "HERE = %r" % HERE))
    res = subprocess.run([sys.executable, tp], capture_output=True, text=True, env=env, timeout=120)
    return probe in res.stdout and res.returncode != 0

if not os.environ.get("CE_MUT_PATH"):
    check("M1 mutant: title says 'added' -> the title check FAILS", run_mutant("title", 'EXISTING_TITLE = "Your %s listing is confirmed live"', 'EXISTING_TITLE = "Your %s listing was added"', "FAIL A2"))
    check("M2 mutant: NAP gate dropped -> the NAP test FAILS", run_mutant("nap", 'or pf.get("proof_nap_match") is not True', "", "FAIL N2"))
    check("M3 mutant: row posted around P.write_deliverables -> A1 and W1 FAIL", run_mutant("helper", "P.write_deliverables(act, [rec], now=rec[\"approved_at\"])", "act.call(\"POST\", \"deliverables\", [rec])", "FAIL A1"))
    check("M5 mutant: --record-existing returns 0 on a failed post -> R1 FAILS", run_mutant("rc", 'file=sys.stderr); return 1\n        return 0\n    if n.create_row', 'file=sys.stderr); return 0\n        return 0\n    if n.create_row', "FAIL R1"))
    check("M4 mutant: source_ref drops :live -> A3 FAILS", run_mutant("ref", '"citation-existing:%s:live"', '"citation-existing:%s"', "FAIL A3"))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
