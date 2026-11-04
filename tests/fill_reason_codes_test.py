"""Fill-only reason_code command (t_c3087efc). Fake db; no network."""
import os, sys, json, io, contextlib
HERE = os.path.dirname(os.path.abspath(__file__)); JOB = os.path.join(os.path.dirname(HERE), "job")
sys.path.insert(0, JOB)
import directories as D

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

class Fake:
    owner = "o1"
    def __init__(self, status): self.status = status; self.calls = []
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        return [{"directory": d, "reason_code": c} for d, c in self.status.items()] if method == "GET" else None

def nh(i, d, code, state="needs-human", to="needs-human"):
    h = [{"at": "2026-11-04", "from": "queued", "to": to, "note": "n"}]
    if code is not None: h[0]["reason_code"] = code
    return {"id": i, "directory": d, "state": state, "history": h}

Q = {"fix_queue": [nh("a", "a.example", "bot_wall"), nh("b", "b.example", "paid"), nh("c", "c.example", "bogus"), nh("d", "d.example", None),
                   nh("e", "e.example", "paid", state="live", to="live"), nh("f", "f.example", "paid"), nh("g", "nostatus.example", "paid")],
     "create_rows": [nh("h", "h.example", "signup_form")]}
STATUS = {"a.example": None, "b.example": "captcha", "c.example": None, "d.example": None, "e.example": None, "f.example": None, "h.example": None}

db = Fake(STATUS)
plan = D.fill_reason_code_plan(db, Q)
ids = {p["id"]: p for p in plan}
check("F1 picks a, f, h (null DB value, valid code)", set(ids) == {"a", "f", "h"} and ids["a"]["code"] == "bot_wall" and ids["h"]["code"] == "signup_form")
check("F2 non-null DB code (b) untouched", "b" not in ids)
check("F3 unknown code (c) skipped", "c" not in ids)
check("F4 no code on history (d) skipped", "d" not in ids)
check("F5 non-needs-human (e) skipped", "e" not in ids)
check("F6 no status row (g) skipped, never created", "g" not in ids)
check("F7 plan echoes current DB value", all(p["db_value"] is None for p in plan))

db = Fake(STATUS); r = D.fill_reason_codes(db, Q)
check("F8 dry run is default and writes nothing", r["write"] is False and len(r["rows"]) == 3 and all(c[0] == "GET" for c in db.calls))

db = Fake(STATUS); r = D.fill_reason_codes(db, Q, write=True)
pa = [c for c in db.calls if c[0] == "PATCH"]
check("F9 write PATCHes one per row", len(pa) == 3)
check("F10 body is exactly one column, never null", all(list(c[2]) == ["reason_code"] and c[2]["reason_code"] in D.REASON_CODES for c in pa))
check("F11 PATCH filtered to reason_code=is.null and needs-human", all("reason_code=is.null" in c[1] and "queue_state=eq.needs-human" in c[1] for c in pa))
check("F12 no POST/upsert anywhere", not any(c[0] == "POST" for c in db.calls))

qp = os.path.join(os.environ.get("TMPDIR") or HERE, "fill_rc_q.json"); json.dump(Q, open(qp, "w"))
D.DirDB = lambda *a, **k: Fake(STATUS)
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = D.main(["--fill-reason-codes", "--queue", qp])
check("F13 CLI default is dry run, prints id/code/db", rc == 0 and "DRY RUN" in buf.getvalue() and "id=a" in buf.getvalue() and "code=bot_wall" in buf.getvalue() and "db=None" in buf.getvalue())
os.remove(qp)

rows = D.queue_rows_to_status(Fake(STATUS), Q, "2026-11-05")
check("F14 weekly path still sends no reason_code key", rows and all("reason_code" not in x for x in rows))

print("%d/%d passed" % (sum(ok), len(ok))); sys.exit(0 if all(ok) else 1)
