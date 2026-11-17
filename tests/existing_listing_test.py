"""build_action `existing` (kanban t_dc4ffd67): proof for a listing NM did not build. Run: python tests/existing_listing_test.py (CI).
No network, no browser: DirDB is an in-memory fake that enforces the ce_directory_status.build_action check (as db/019 widens it);
urlopen is poisoned, so no Directory call and no portal seed can happen."""
import os, sys, json, re, tempfile, shutil, urllib.request, io, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import transitions as T
import proof as PR
import recheck as R
import buildqueue as Q

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

DAY = "2026-11-17"
DB_ALLOWED = ("new", "claim", "fix", "existing")   # db/019 predicate; the mutation check drops "existing" from T.BUILD_ACTIONS and from here

class FakeDB:
    owner = "owner-1"
    def __init__(self, status=None, allowed=DB_ALLOWED):
        self.status = dict(status or {}); self.calls = []; self.allowed = allowed; self.directories = {"n49.com", "maps.apple.com"}
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("ce_directories?"): return [{"domain": "x"}] if re.search(r"eq\.([^&]+)", path).group(1) in self.directories else []
        if method == "GET" and path.startswith("ce_directory_status?"):
            d = re.search(r"directory=eq\.([^&]+)", path)
            if d: return [self.status[d.group(1)]] if d.group(1) in self.status else []
            return []
        if method == "POST" and path.startswith("ce_directory_status"):
            for r in body:
                if r.get("build_action") is not None and r["build_action"] not in self.allowed: raise RuntimeError("23514 check constraint ce_directory_status_build_action_check")
                self.status.setdefault(r["directory"], {}).update(r)
            return None
        return None

QUEUE = {"fix_queue": [{"id": "fix-acme", "group": "A", "kind": "fix", "directory": "acme.com", "state": "queued", "history": []}], "create_queue": {"rows": []}}
def fresh(q=None):
    d = tempfile.mkdtemp(prefix="ce-existing-"); p = os.path.join(d, "scc-fix-create-queue.json")
    json.dump(q or QUEUE, open(p, "w")); return p

OK = dict(proof_url="https://n49.com/biz/123/senior-care-consulting", proof_nap="Senior Care Consulting | 1 Main St | 502-555-0101", proof_at="2026-11-17T12:00:00Z")
def rec(p, db, domain="n49.com", **kw):
    a = dict(OK); a.update(kw)
    return T.record_existing("SCC", domain, queue_path=p, today=DAY, db=db, **a)
def refused(p, db, domain="n49.com", match=None, **kw):
    before = open(p, "rb").read(); n = len(db.calls) if db else 0
    try:
        if match is not None: kw["proof_nap_match"] = match
        rec(p, db, domain, **kw)
    except T.TransitionRefused as e:
        return (open(p, "rb").read() == before and (db is None or not any(c[0] == "POST" for c in db.calls)), str(e))
    return (False, "not refused")

# --- allowed set
check("E1 existing is an allowed build_action", "existing" in T.BUILD_ACTIONS and set(T.BUILD_ACTIONS) == set(DB_ALLOWED))
check("E2 complete proof with build_action existing passes check_proof", T.proof_problems(dict(OK, proof_nap_match=True, build_action="existing")) == [])
check("E3 an unknown build_action is still refused", T.proof_problems(dict(OK, proof_nap_match=True, build_action="adopted")) == ["build_action"])

# --- happy path
p = fresh(); db = FakeDB()
out = rec(p, db)
q = json.load(open(p)); rows = [r for r in q["fix_queue"] if r["directory"] == "n49.com"]
check("H1 exactly one new row, state live, proof.build_action existing", len(rows) == 1 and rows[0]["state"] == "live" and rows[0]["proof"]["build_action"] == "existing" and rows[0]["proof"]["proof_nap_match"] is True, rows)
check("H2 history note is the specified text", rows[0]["history"][-1]["note"] == "pre-existing listing, proof recorded (--record-existing)" and rows[0]["history"][-1]["to"] == "live", rows[0]["history"])
check("H3 other rows untouched, queue still parses", q["fix_queue"][0] == QUEUE["fix_queue"][0] and len(Q.all_rows(q)) == 2)
st = db.status.get("n49.com", {})
check("H4 ce_directory_status: live + full proof + existing + kind fix", st.get("queue_state") == "live" and st.get("build_action") == "existing" and st.get("queue_kind") == "fix" and st.get("queue_row_id") == rows[0]["id"] and not T.proof_problems({k: st.get(k) for k in T.PROOF_FIELDS}), st)
posts = [i for i, c in enumerate(db.calls) if c[0] == "POST"]
check("H5 status written (POST) and the queue was written after it (backup exists)", bool(posts) and out["directories_written"] is True and any(f.startswith("scc-fix-create-queue.json.bak") for f in os.listdir(os.path.dirname(p))), out)
check("H6 a live row with this proof passes the audit", T.live_rows_missing_proof(q, {"n49.com": {k: st.get(k) for k in T.PROOF_FIELDS}}) == [])
check("H7 subdomain of the domain is accepted (www.n49.com)", rec(fresh(), FakeDB(), proof_url="https://www.n49.com/biz/9")["row"]["proof"]["build_action"] == "existing")

# status before queue: a failing status write leaves the queue file unchanged
p2 = fresh(); before = open(p2, "rb").read()
try: rec(p2, FakeDB(allowed=("new", "claim", "fix")))   # the DB check without db/019
except Exception as e: failed = str(e)
else: failed = None
check("H8 DB refuses (check not widened): queue file byte-identical, no row", failed is not None and open(p2, "rb").read() == before, failed)

# --- dry run
p3 = fresh(); b3 = open(p3, "rb").read(); d3 = FakeDB()
dr = T.record_existing("SCC", "n49.com", queue_path=p3, today=DAY, db=d3, dry_run=True, **OK)
check("D1 dry run writes nothing (queue bytes, no DB call, no backup)", open(p3, "rb").read() == b3 and not d3.calls and len(os.listdir(os.path.dirname(p3))) == 1)
check("D2 dry run prints the row and the status body", dr["dry_run"] is True and dr["row"]["state"] == "live" and dr["status_body"]["build_action"] == "existing" and dr["status_body"]["queue_state"] == "live", dr)

# --- refusals
r, why = refused(fresh(), FakeDB(), domain="acme.com", proof_url="https://acme.com/l/1"); check("R1 a queue row for that directory exists -> refused, points to --proof-live", r and "--proof-live" in why, why)
r, why = refused(fresh(), FakeDB(status={"n49.com": {"queue_state": "found"}})); check("R2 a status row with a queue state exists -> refused", r and "already" in why, why)
r, why = refused(fresh(), FakeDB(), proof_url="https://evil-n49.com/x"); check("R3 host not the domain (lookalike) -> refused", r and "host" in why, why)
r, why = refused(fresh(), FakeDB(), proof_url="https://n49.com.evil.com/x"); check("R4 host with the domain as a prefix label -> refused", r and "host" in why, why)
r, why = refused(fresh(), FakeDB(), proof_url="https://maps.apple.com/p/1"); check("R5 another domain's URL -> refused", r and "host" in why, why)
r, why = refused(fresh(), FakeDB(), proof_url="https://user@n49.com/x"); check("R6 userinfo in the URL -> refused", r, why)
for k in ("proof_url", "proof_nap", "proof_at"):
    r, why = refused(fresh(), FakeDB(), **{k: ""}); check("R7 empty %s -> refused" % k, r and k in why, why)
    r, why = refused(fresh(), FakeDB(), **{k: None}); check("R7 missing %s -> refused" % k, r and k in why, why)
r, why = refused(fresh(), FakeDB(), match=False); check("R8 proof_nap_match false -> refused", r and "proof_nap_match" in why, why)
r, why = refused(fresh(), FakeDB(), match="true"); check("R9 proof_nap_match not literally true -> refused", r, why)
try: T.record_existing("NM", "n49.com", queue_path=fresh(), today=DAY, db=FakeDB(), **OK); nm = False
except T.TransitionRefused: nm = True
check("R10 NM client refused (SCC only)", nm)
r, why = refused(fresh(), FakeDB(), domain="not a domain"); check("R11 bad domain refused", r, why)

# --- CLI
p4 = fresh()
with contextlib.redirect_stdout(io.StringIO()) as buf:
    rc = T.main(["--record-existing", "--client", "SCC", "--domain", "maps.apple.com", "--proof-url", "https://maps.apple.com/place?auid=1", "--proof-nap", "SCC | 1 Main St | 502-555-0101", "--proof-at", "2026-11-17T12:00:00Z", "--queue", p4, "--dry-run", "--today", DAY])
check("C1 CLI dry run exits 0 and prints the row", rc == 0 and "maps.apple.com" in buf.getvalue() and "existing" in buf.getvalue())
with contextlib.redirect_stderr(io.StringIO()) as err:
    rc = T.main(["--record-existing", "--client", "SCC", "--domain", "maps.apple.com", "--queue", p4, "--dry-run"])
check("C2 CLI with a proof flag missing is refused (exit 1)", rc == 1 and "proof_url" in err.getvalue(), err.getvalue())

# --- recheck / proof keep existing
row = rows[0]
check("K1 build_action keeps existing for a row whose proof says existing (fix kind)", PR.build_action("fix", row, "unknown") == "existing")
check("K2 ...also when the claim status says claimed", PR.build_action("fix", row, "claimed") == "existing")
check("K3 other rows unchanged: create->new, fix->fix, claimed->claim", PR.build_action("create", {}, None) == "new" and PR.build_action("fix", {"proof": {"build_action": "fix"}}, None) == "fix" and PR.build_action("fix", {}, "claimed") == "claim")
pr = fresh(); pdb = FakeDB()
rec(pr, pdb); cur = [r for r in json.load(open(pr))["fix_queue"] if r["directory"] == "n49.com"][0]
R._proof_only(cur, "fix", "https://www.n49.com/biz/123", "Senior Care Consulting | 1 Main St | 502-555-0101", DAY, pdb, pr)
after = [r for r in json.load(open(pr))["fix_queue"] if r["directory"] == "n49.com"][0]
check("K4 recheck --proof-live re-proof keeps existing in the queue row and the status row", after["proof"]["build_action"] == "existing" and pdb.status["n49.com"]["build_action"] == "existing" and after["proof"]["proof_url"].startswith("https://www.n49.com"), after["proof"])

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
