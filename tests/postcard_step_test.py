"""Postcard step tests (no network, fake portal, fake Directory). Run: python tests/postcard_step_test.py  (CI). Exit 1 on any failure.
The headline test: the code never reaches stdout, stderr, any file the step writes, or any portal write body."""
import os, sys, io, json, contextlib, tempfile, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp()   # importing run.py makes a run dir; never the real runs folder
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import portal as P
import postcard_step as PS

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % d) if d else ""), flush=True)

SCC = P.ALLOWED["SCC"]
NOW = datetime.datetime(2026, 10, 27, 12, 0, tzinfo=datetime.timezone.utc)
CODE = "ZQ7K4M9X"
V1, V2, V3 = ("11111111-1111-1111-1111-11111111111%d" % i for i in (1, 2, 3))


def ago(h): return (NOW - datetime.timedelta(hours=h)).isoformat()


class FakePortal:
    def __init__(self, rows, codes):
        self.rows, self.codes, self.writes, self.calls = rows, dict(codes), [], []
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        if method == "GET": return list(self.rows)
        if path == "rpc/consume_postcard_code": return self.codes.pop(body["p_verification_id"], None)
        self.writes.append((method, path, body)); return None


def rows(*specs): return [{"id": v, "client_id": SCC, "directory": d, "code_received_at": ago(h)} for v, d, h in specs]


def go(portal, enterers, **kw):
    out, err = io.StringIO(), io.StringIO()
    lines = []
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        res = PS.run(portal=portal, enterers=enterers, now=NOW, log=lambda s: (lines.append(s), print(s)), **kw)
    return res, out.getvalue() + err.getvalue()


def every_byte(portal, res, text):
    """Everything this step produced or sent anywhere, as one string."""
    return text + json.dumps(res) + json.dumps(portal.writes) + json.dumps(portal.calls[:1])


# 1 accepted: consume once, enter once, one verified attempt, row state untouched
seen = []
def accept(d, code): seen.append((d, code)); return "accepted"
p = FakePortal(rows((V1, "a.example", 5)), {V1: CODE})
res, text = go(p, {"a.example": accept})
check("accepted: the Directory got the code once", seen == [("a.example", CODE)])
check("accepted: outcome accepted", res[0]["outcome"] == "accepted")
w = p.writes
check("accepted: exactly one attempt row, outcome verified, fixed note", len(w) == 1 and w[0][1] == "citation_verification_attempt" and w[0][2][0]["outcome"] == "verified" and w[0][2][0]["note"] == PS.NOTES["verified"])
check("accepted: row state is not changed by this step (no PATCH to citation_verification)", not any(x[0] == "PATCH" for x in w))
check("CODE NEVER LEAKS (accepted): not in stdout, stderr, result, or any write", CODE not in every_byte(p, res, text))
check("the code is gone from the portal after consume", V1 not in p.codes)

# 2 rejected: failed attempt, no leak
p = FakePortal(rows((V1, "a.example", 5)), {V1: CODE})
res, text = go(p, {"a.example": lambda d, c: "rejected"})
check("rejected: failed attempt recorded", res[0]["outcome"] == "rejected" and p.writes[0][2][0]["outcome"] == "failed")
check("CODE NEVER LEAKS (rejected)", CODE not in every_byte(p, res, text))

# 3 the Directory step blows up with the code in the message: only the fact survives
def boom(d, c): raise RuntimeError("form said bad code " + c)
p = FakePortal(rows((V1, "a.example", 5)), {V1: CODE})
res, text = go(p, {"a.example": boom})
check("exception: outcome error, retry attempt recorded", res[0]["outcome"] == "error" and p.writes[0][2][0]["outcome"] == "retry")
check("CODE NEVER LEAKS (exception text carried it)", CODE not in every_byte(p, res, text))

# 4 no entry registered: consume NOT called, code left in the portal
p = FakePortal(rows((V1, "nowhere.example", 5)), {V1: CODE})
res, text = go(p, {"a.example": accept})
check("no entry for the Directory: skipped", res[0]["outcome"] == "skipped-no-entry")
check("no entry: consume was NOT called and the code is still waiting", not any(c[1] == "rpc/consume_postcard_code" for c in p.calls) and p.codes == {V1: CODE})

# 5 dry run: nothing consumed, nothing entered, nothing written
seen.clear()
p = FakePortal(rows((V1, "a.example", 5)), {V1: CODE})
res, text = go(p, {"a.example": accept}, dry=True)
check("dry: would-consume only; no consume, no enter, no write", res[0]["outcome"] == "would-consume" and not seen and not p.writes and p.codes == {V1: CODE} and not any(c[1].startswith("rpc") for c in p.calls))

# 6 already purged: no-code, no attempt, no retry loop
p = FakePortal(rows((V1, "a.example", 5)), {})
res, text = go(p, {"a.example": accept})
check("purged code: no-code, nothing entered, nothing recorded", res[0]["outcome"] == "no-code" and not p.writes)

# 7 age warning at 48h
p = FakePortal(rows((V1, "nowhere.example", 50), (V2, "nowhere.example", 3)), {})
res, text = go(p, {})
check("waiting 50h warns; 3h does not", text.count("POSTCARD WARNING") == 1 and V1 in text.split("POSTCARD WARNING")[1].split("\n")[0])

# 8 consume failure: error outcome, message holds no code
class Down(FakePortal):
    def call(self, method, path, body=None, prefer=None):
        if path.startswith("rpc"): raise RuntimeError("down " + CODE)
        return super().call(method, path, body, prefer)
p = Down(rows((V1, "a.example", 5)), {})
res, text = go(p, {"a.example": accept})
check("consume failure: error, no write", res[0]["outcome"] == "error" and not p.writes)

# 9 query shape: SCC only, postcard, waiting, code received
p = FakePortal([], {}); go(p, {})
q = p.calls[0][1]
check("query asks for postcard + requires_verification + code_received_at set + SCC only", all(s in q for s in ("verification_type=eq.postcard", "state=eq.requires_verification", "code_received_at=not.is.null", "client_id=eq." + SCC)))

# 10 cadence: the scheduler file runs this step, and the interval constants cover the 72h window
cmd = open(os.path.join(HERE, "..", "job", "postcards.cmd"), encoding="utf-8").read()
check("postcards.cmd runs postcard_step.py", "postcard_step.py" in cmd and "every 12 hours" in cmd.lower())
check("warn threshold sits inside the 72h expiry", PS.WARN_AFTER_HOURS < PS.EXPIRY_HOURS == 72)

# 11 static: the module never writes a file
src = open(os.path.join(HERE, "..", "job", "postcard_step.py"), encoding="utf-8").read()
check("postcard_step has no file writes and no logging module", "open(" not in src and "import logging" not in src and "json.dump(" not in src)

# 12 run.py hook is non-fatal and prints ids/outcomes only
import run as R
buf = io.StringIO(); eb = io.StringIO()
with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(eb):
    good = R.postcard_step(run=lambda: [{"id": V1, "outcome": "accepted", "directory": "a.example", "age_hours": 1.0}])
    bad = R.postcard_step(run=lambda: (_ for _ in ()).throw(RuntimeError(CODE)))
check("run.py hook: ok path prints POSTCARD OK, failure is non-fatal and names the type only", good is True and bad is False and "POSTCARD OK" in buf.getvalue() and "RuntimeError" in eb.getvalue() and CODE not in buf.getvalue() + eb.getvalue())

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
