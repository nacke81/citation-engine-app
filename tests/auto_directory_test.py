"""A domain new to the Catalog gets a minimal ce_directories row, so the status / playbook FKs stop answering 409 (t_9a722352).
Offline: a fake PostgREST that enforces the same FKs as the real tables (db/002, db/017). Run: python tests/auto_directory_test.py (CI). Exit 1 on any failure.
Mutations at the end disable the fix and require the real failure (HTTP 409) to HAPPEN."""
import contextlib, io, json, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
TMP = tempfile.mkdtemp()
os.environ["CE_LOGS"] = os.path.join(TMP, "logs"); os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json")
os.environ["CE_VERIFY_DIRECTORIES"] = os.path.join(HERE, "verify_directories_fixture.json")
os.environ["CE_VERIFY_DIRECTORIES_LOCAL"] = os.path.join(TMP, "outside", "v.local.json")
os.environ["CE_NO_CARDS"] = "1"; os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_DIRECTORIES_WRITE"] = "0"   # the default sink is off; every test hands its fake DB in
import directories as D, playbook as PB, transitions as T

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else ""), flush=True)

class Conflict(Exception): code = 409

class FakeDB:
    """ce_directories(domain pk), ce_directory_status.directory -> ce_directories, ce_directory_playbooks.domain -> ce_directories (409 on a missing parent)."""
    owner = "00000000-0000-0000-0000-000000000001"
    def __init__(self, dirs=("mapquest.com",)):
        self.dirs = {d: {"domain": d, "name": d, "priority": 1} for d in dirs}; self.status = []; self.pbs = []; self.calls = []
    def call(self, method, path, body=None, prefer="return=minimal"):
        self.calls.append((method, path, body, prefer))
        base = path.split("?")[0]
        if method == "GET" and base == "ce_directories":
            dom = path.split("domain=eq.")[1].split("&")[0] if "domain=eq." in path else None
            return [self.dirs[dom]] if dom in self.dirs else []
        if method == "POST" and base == "ce_directories":
            for r in body:
                if r["domain"] in self.dirs and "ignore-duplicates" in prefer: continue
                if r["domain"] in self.dirs: raise Conflict("duplicate key")
                self.dirs[r["domain"]] = r
            return None
        if method == "POST" and base == "ce_directory_status":
            for r in body:
                if r["directory"] not in self.dirs: raise Conflict("ce_directory_status_directory_fkey")
                self.status.append(r)
            return None
        if method == "POST" and base == "ce_directory_playbooks":
            for r in body:
                if r["domain"] not in self.dirs: raise Conflict("ce_directory_playbooks_domain_fkey")
                self.pbs.append(r)
            return None
        if method == "GET" and base == "ce_directory_playbooks": return []
        return None

def raises(fn, exc=Exception):
    try: fn(); return None
    except exc as e: return e

STEPS = [{"text": "Open the sign-in page", "url": "https://www.designrush.com/login"}]
ROW = {"id": "nm-create-alignable", "directory": "alignable.com"}

# ---- 1 sink: a park on a domain not in ce_directories ----------------------------------------------------------------------------
db = FakeDB()
r = D.sync_transition("NM", ROW, "needs-human", "phone verify", "2026-11-13", kind="create", db=db, reason_code="phone_verify", old_state="queued")
row = db.dirs.get("alignable.com")
check("1 NM park on a new domain: status written, no 409", r["status_written"] and len(db.status) == 1 and db.status[0]["directory"] == "alignable.com")
check("1 the minimal row is exactly the rule: name, priority 4, general, source auto, last_verified null", row == {"domain": "alignable.com", "name": "Alignable", "priority": 4, "category": "general", "source": "auto", "last_verified": None}, row)
db2 = FakeDB()
D.sync_transition("SCC", {"id": "x", "directory": "mapquest.com"}, "needs-human", "n", "2026-11-13", db=db2, reason_code="phone_verify", old_state="queued")
check("1 a Catalog domain is NOT touched: no ce_directories POST at all", not [c for c in db2.calls if c[0] == "POST" and c[1].startswith("ce_directories")] and db2.dirs["mapquest.com"]["priority"] == 1)
D.sync_transition("SCC", {"id": "x", "directory": "new-agency.io"}, "queued", None, "2026-11-13", db=db2)
check("1 SCC gets the same rule (any tenant); a hyphenated domain is named by rule", db2.dirs["new-agency.io"]["name"] == "New Agency")
d3 = FakeDB()
check("1 a second ensure is a no-op (False) and the row is never overwritten", D.ensure_directory(d3, "zz.example") is True and D.ensure_directory(d3, "zz.example") is False and len([c for c in d3.calls if c[0] == "POST"]) == 1)
e = raises(lambda: D.ensure_directory(FakeDB(), "not a domain"), D.DirectoriesError)
check("1 a bad domain is refused with a clear message, nothing posted", e and "not a bare domain" in str(e))

# ---- 2 create-row (NM) ----------------------------------------------------------------------------------------------------------------
q = os.path.join(TMP, "nm-fix-queue.json"); json.dump({"business": "NM fixture", "fix_queue": []}, open(q, "w"))
dbc = FakeDB()
res = T.create_row("NM", "designrush.com", "create", queue_path=q, today="2026-11-13", directories=dbc)
check("2 create-row on a new domain: Directory row added, queue row written", res["directory_row_added"] is True and "designrush.com" in dbc.dirs and len(json.load(open(q))["fix_queue"]) == 1)
dry = FakeDB(); before = open(q).read()
rd = T.create_row("NM", "sortlist.com", "create", queue_path=q, today="2026-11-13", dry_run=True, directories=dry)
check("2 dry run reports it would add, writes nothing (no POST, queue unchanged)", rd["directory_row_added"] is True and not dry.dirs.get("sortlist.com") and not [c for c in dry.calls if c[0] == "POST"] and open(q).read() == before)
class Down(FakeDB):
    def call(self, method, path, body=None, prefer="return=minimal"):
        if method == "POST": raise Conflict("sink down")
        return super().call(method, path, body, prefer)
before = open(q).read()
msg = raises(lambda: T.create_row("NM", "clutch.co", "create", queue_path=q, today="2026-11-13", directories=Down()), T.TransitionRefused)
check("2 when the Directory row cannot be added: clear refusal and the queue is untouched", msg and "not in ce_directories" in str(msg) and "nothing written" in str(msg) and open(q).read() == before, msg)
check("2 the tenant lock still refuses an SCC queue for NM (unchanged)", "tenant lock" in str(raises(lambda: T.create_row("NM", "x.com", "create", queue_path=os.path.join(TMP, "scc.json"), directories=FakeDB()), T.TransitionRefused) or ""))

# ---- 3 playbook set ------------------------------------------------------------------------------------------------------------------
dbp = FakeDB()
pr = PB.set_playbook(dbp, "designrush.com", "verify", STEPS)
check("3 playbook set on a domain not in ce_directories: Directory row added, playbook stored, no 409", "designrush.com" in dbp.dirs and dbp.dirs["designrush.com"]["source"] == "auto" and len(dbp.pbs) == 1 and pr["version"] == 1)
dbq = FakeDB()
PB.set_playbook(dbq, "sortlist.com", "verify", STEPS, dry_run=True)
check("3 playbook --dry-run adds nothing to either table", not dbq.dirs.get("sortlist.com") and not dbq.pbs and not [c for c in dbq.calls if c[0] == "POST"])
bd = FakeDB(); e3 = raises(lambda: PB.set_playbook(bd, "bad domain", "verify", STEPS), PB.PlaybookError)
check("3 playbook on a bad domain: refused with PlaybookError, nothing posted", e3 is not None and not [c for c in bd.calls if c[0] == "POST"], str(e3))
buf = io.StringIO(); f = os.path.join(TMP, "pb.json"); json.dump({"steps": STEPS}, open(f, "w"))
dbm = FakeDB()
rc = PB.main(["set", "--domain", "sortlist.com", "--task", "verify", "--file", f], db=dbm, out=buf.write)
check("3 the CLI path (playbook.py set) works end to end for a new domain", rc == 0 and "written" in buf.getvalue() and "sortlist.com" in dbm.dirs)

# ---- mutations: the fix off -> the real 409 happens ------------------------------------------------------------------------------------
real = D.ensure_directory
D.ensure_directory = lambda *a, **k: False
m1 = raises(lambda: D.sync_transition("NM", ROW, "needs-human", "n", "2026-11-13", db=FakeDB(), reason_code="phone_verify", old_state="queued"), Conflict)
m2 = raises(lambda: PB.set_playbook(FakeDB(), "designrush.com", "verify", STEPS), Conflict)
D.ensure_directory = real
check("M1 mutation (ensure off): the park hits the FK 409 (the old bug)", isinstance(m1, Conflict))
check("M2 mutation (ensure off): the playbook set hits the FK 409", isinstance(m2, Conflict))
print("%d checks, %d failed" % (len(ok), ok.count(False)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if False in ok else 0)
