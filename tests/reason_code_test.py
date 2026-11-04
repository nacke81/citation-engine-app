"""t_93ae9b6b: the worker that parks a row writes reason_code. Additive: no code given -> the column is never sent."""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "job"))
import directories as D

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

class DB:
    owner = "o1"
    def __init__(s): s.calls = []
    def call(s, method, path, body=None, prefer=None): s.calls.append((method, path, body)); return None
def posted(db): return [c[2][0] for c in db.calls if c[0] == "POST" and "ce_directory_status" in c[1]]
ROW = {"id": "create-x", "directory": "x.example"}

d1 = DB(); D.sync_transition("SCC", ROW, "needs-human", "paid-tier, Mike decides", "2026-11-04", kind="create", db=d1, reason_code="paid")
check("R1 needs-human with a code writes reason_code in the same upsert as the queue state", posted(d1)[0].get("reason_code") == "paid" and posted(d1)[0]["queue_state"] == "needs-human")
d2 = DB(); D.sync_transition("SCC", ROW, "needs-human", "note", "2026-11-04", kind="create", db=d2)
check("R2 stays needs-human with no code given -> key not sent (stored code kept); no old_state known -> also not sent", "reason_code" not in posted(d2)[0])
d2b = DB(); D.sync_transition("SCC", ROW, "needs-human", "note", "2026-11-04", kind="create", db=d2b, old_state="needs-human")
check("R2b needs-human -> needs-human, no code: key not sent", "reason_code" not in posted(d2b)[0])
d2c = DB(); D.sync_transition("SCC", ROW, "needs-human", "note", "2026-11-04", kind="create", db=d2c, old_state="needs-human", reason_code="nap")
check("R2c needs-human -> needs-human with a code: code replaces the stored one", posted(d2c)[0]["reason_code"] == "nap")
d2d = DB(); D.sync_transition("SCC", ROW, "needs-human", "note", "2026-11-04", kind="create", db=d2d, old_state="queued")
check("R2d queued -> needs-human with no code: sends null", "reason_code" in posted(d2d)[0] and posted(d2d)[0]["reason_code"] is None)
def refuses(**k):
    try: D.sync_transition("SCC", ROW, k.pop("state", "needs-human"), "n", "2026-11-04", kind="create", db=DB(), **k)
    except D.DirectoriesError: return True
    return False
check("R3 an unknown code is refused", refuses(reason_code="made_up"))
check("R4 a code on any other move is refused", refuses(state="live", reason_code="paid") and refuses(state="queued", reason_code="paid"))
d5 = DB(); D.sync_transition("SCC", ROW, "live", None, "2026-11-04", kind="create", db=d5)
check("R5 a move to live sends reason_code null (clears any stored code)", "reason_code" in posted(d5)[0] and posted(d5)[0]["reason_code"] is None)

# R11 walk one row: captcha park -> queued -> park with no code. A fake that merges upserts the way PostgREST does.
class MergeDB(DB):
    def __init__(s): DB.__init__(s); s.row = {}
    def call(s, method, path, body=None, prefer=None):
        if method == "POST" and "ce_directory_status" in path: s.row.update(body[0])
        return None
mdb = MergeDB()
D.sync_transition("SCC", ROW, "needs-human", "captcha", "2026-11-01", kind="create", db=mdb, old_state="queued", reason_code="captcha")
c1 = mdb.row.get("reason_code")
D.sync_transition("SCC", ROW, "queued", None, "2026-11-02", kind="create", db=mdb, old_state="needs-human")
c2 = mdb.row.get("reason_code")
D.sync_transition("SCC", ROW, "needs-human", "other wall", "2026-11-03", kind="create", db=mdb, old_state="queued")
c3 = mdb.row.get("reason_code")
check("R11 captcha park -> queued -> park with no code ends with null", (c1, c2, c3) == ("captcha", None, None), str((c1, c2, c3)))

# R12 weekly queue rows: the weekly re-assert is not a move, so no row, in any state, ever carries reason_code
q = {"fix_queue": [{"id": "f1", "directory": "a.example", "state": "needs-human", "history": [{"at": "2026-10-20", "note": "x"}]},
                   {"id": "f2", "directory": "b.example", "state": "queued", "history": []},
                   {"id": "f3", "directory": "c.example", "state": "live", "history": []},
                   {"id": "f4", "directory": "d.example", "state": "rejected", "history": []},
                   {"id": "f5", "directory": "e.example", "state": "submitted", "history": []}]}
wk = {r["directory"]: r for r in D.queue_rows_to_status(MergeDB(), q, "2026-11-08")}
check("R12 weekly: no row in any state sends the reason_code key", len(wk) == 5 and all("reason_code" not in r for r in wk.values()), str(sorted(wk)))
class StoreDB(DB):
    def __init__(s, store): DB.__init__(s); s.owner = "o1"; s.store = store
    def call(s, method, path, body=None, prefer=None):
        if method == "POST" and "ce_directory_status" in path:
            for r in body: s.store.setdefault(r["directory"], {}).update(r)
        return None
store = {"a.example": {"reason_code": "paid"}, "b.example": {"reason_code": "captcha"}, "c.example": {"reason_code": "captcha"},
         "d.example": {"reason_code": "id_check"}, "e.example": {"reason_code": "contact_name"}}
D.sync_run([], "2026-11-08", queue=q, db=StoreDB(store))
check("R13 weekly sync_run: needs-human, rejected and submitted rows keep their stored codes", (store["a.example"]["reason_code"], store["d.example"]["reason_code"], store["e.example"]["reason_code"]) == ("paid", "id_check", "contact_name"), str(store))
check("R13b weekly sync_run does not touch codes on queued/live rows (only sync_transition clears)", (store["b.example"]["reason_code"], store["c.example"]["reason_code"]) == ("captcha", "captcha"))
check("R13c weekly sync_run still writes the queue state", all(store[k]["queue_state"] == v for k, v in {"a.example": "needs-human", "b.example": "queued", "c.example": "live", "d.example": "rejected", "e.example": "submitted"}.items()))

# R14 real prod shape: the 4 coded non-needs-human rows (yellowbook, facebook, localstack rejected; bbb.org submitted)
q4 = {"fix_queue": [{"id": "p1", "directory": "yellowbook.com", "state": "rejected", "history": []},
                    {"id": "p2", "directory": "facebook.com", "state": "rejected", "history": []},
                    {"id": "p3", "directory": "localstack.com", "state": "rejected", "history": []},
                    {"id": "p4", "directory": "bbb.org", "state": "submitted", "history": []}]}
want = {"yellowbook.com": "no_search", "facebook.com": "id_check", "localstack.com": "bad_catalog", "bbb.org": "contact_name"}
store4 = {k: {"reason_code": v} for k, v in want.items()}
D.sync_run([], "2026-11-08", queue=q4, db=StoreDB(store4))
check("R14 real 4-row shape: codes unchanged after a weekly sync_run", {k: v["reason_code"] for k, v in store4.items()} == want, str(store4))

js = open(os.path.join(ROOT, "site", "reasons.js"), encoding="utf-8").read()
js_codes = set(re.findall(r"^  (\w+): \{ label:", js, re.M))
derived_only = {"blocked_unknown", "no_result", "unsearchable", "other"}   # read from ce_checks / fallback, never stored
check("R6 every stored code is a code the page knows", set(D.REASON_CODES) <= js_codes, str(set(D.REASON_CODES) - js_codes))
check("R7 every page code is either stored or derived-only (the two lists cannot drift)", js_codes - set(D.REASON_CODES) == derived_only, str(js_codes - set(D.REASON_CODES)))

sql = open(os.path.join(ROOT, "db", "011_reason_code.sql"), encoding="utf-8").read()
body = re.sub(r"(?m)^--.*$", "", sql)
check("R8 migration 011 is additive: one nullable column + the view, no drop/delete/update/insert", "add column if not exists reason_code text;" in body and not re.search(r"(?i)\b(drop|delete|update|insert|truncate)\b", body))
check("R9 the view the page reads keeps every earlier column and appends reason_code last", all(c in body for c in ("s.build_action", "s.proof_url", "s.proof_nap_match", "s.queue_note")) and body.rstrip().split("from public.ce_directories")[0].rstrip().endswith("s.reason_code"))
check("R10 the weekly job source never writes reason_code (the check path is untouched)", "reason_code" not in open(os.path.join(ROOT, "job", "run.py"), encoding="utf-8").read())

print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
