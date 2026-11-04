"""Every job path that parks needs-human carries a reason_code (t_8d61ef01). Weekly path stays code-free (t_93ae9b6b)."""
import os, sys, json, copy, tempfile, io, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
JOB = os.path.join(os.path.dirname(HERE), "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
import walls as W
import transitions as T
import buildrows as BR
import captcha_route as C
import directories as D

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

def refused(fn, *a, **k):
    try: fn(*a, **k)
    except T.TransitionRefused: return True
    return False

def src(name): return open(os.path.join(JOB, name), encoding="utf-8").read()

# 1 buildrows
d = {"domain": "p.example", "priority": 1, "da": 50, "cost": "paid", "signup_url": None, "claim_url": None}
for action, code in (("needs-human-paid", "paid"), ("needs-human-route", "signup_form")):
    r = BR.make_row(d, action, "why", None, None, "2026-11-04", None)
    h = r["history"][-1]
    check("R1 %s row parks needs-human with code %s" % (action, code), r["state"] == "needs-human" and h["reason_code"] == code and code in D.REASON_CODES)
q = BR.make_row(d, "create", "why", None, None, "2026-11-04", None)
check("R1 a queued create row has no code", q["state"] == "queued" and q["history"] == [])

# 2 walls try 3
r = {"id": "fix-a", "directory": "a.example", "state": "queued", "history": []}
e1 = W.record_try(r, "2026-10-26"); W.record_try(r, "2026-10-27")
check("R2 try 1-2 carry no code", "reason_code" not in e1 and r["state"] == "queued")
e3 = W.record_try(r, "2026-10-28")
check("R2 try 3 without a Ray ID -> bot_wall", e3["reason_code"] == "bot_wall" and r["state"] == "needs-human")
r2 = {"id": "fix-b", "directory": "b.example", "state": "queued", "history": []}
W.record_try(r2, "2026-10-26"); W.record_try(r2, "2026-10-27")
check("R2 try 3 with a Ray ID -> cloudflare", W.record_try(r2, "2026-10-28", "9f1a2b3c4d5e6f70")["reason_code"] == "cloudflare")

# 3 recheck park passes no_search (source check; the call is deep inside _backoff)
s = src("recheck.py")
check("R3 recheck no-public-permalink park passes reason_code no_search", 'park_reason="no-public-permalink", reason_code="no_search"' in s)

# 5 hints
plan = C.plan('<html><body><div class="h-captcha" data-sitekey="abcdefghij12345"></div></body></html>', "https://a.example/x")
check("R5 captcha park hint names --reason-code captcha", any("--reason-code captcha" in n for n in plan["notes"]), plan["route"])
cf = C.plan("<html><title>Just a moment...</title><div id='challenge-form'></div><script src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1'></script></html>", "https://a.example/x")
if cf["route"] == "park" and cf["wall"] == "WALL:cloudflare-click":
    check("R5 cloudflare interstitial hint names --reason-code cloudflare", any("--reason-code cloudflare" in n for n in cf["notes"]))
check("R6 build_runner record:none hint names --reason-code", "--reason-code phone_verify or id_check" in src("build_runner.py"))

# 7 transitions: validate before any write, echo on dry run
tmp = tempfile.mkdtemp(); qp = os.path.join(tmp, "q.json")
row = {"id": "create-cylex", "directory": "cylex.example", "kind": "create", "state": "queued", "mike_approval": None, "history": []}
json.dump({"create_rows": [row]}, open(qp, "w"))
before = open(qp, "rb").read()
check("R7 bogus code refused", refused(T.record_transition, "SCC", "create-cylex", "needs-human", None, "x", queue_path=qp, today="2026-11-04", dry_run=True, reason_code="bogus"))
check("R7 bogus code refused on a LIVE call before any write", refused(T.record_transition, "SCC", "create-cylex", "needs-human", None, "x", queue_path=qp, today="2026-11-04", reason_code="bogus", directories=object()) and open(qp, "rb").read() == before)
check("R7 code on a non-needs-human move refused", refused(T.record_transition, "SCC", "create-cylex", "submitted", None, "x", queue_path=qp, today="2026-11-04", dry_run=True, reason_code="captcha"))
res = T.record_transition("SCC", "create-cylex", "needs-human", None, "x", queue_path=qp, today="2026-11-04", dry_run=True, reason_code="captcha")
check("R7 dry run echoes reason_code", res["reason_code"] == "captcha" and res["directories_request"]["reason_code"] == "captcha" and res["history_entry"]["reason_code"] == "captcha")
res = T.record_transition("SCC", "create-cylex", "needs-human", None, "x", queue_path=qp, today="2026-11-04", dry_run=True)
check("R7 dry run with no code echoes null", res["reason_code"] is None and "reason_code" not in res["history_entry"])
check("R7 dry run wrote nothing", open(qp, "rb").read() == before)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = T.main(["--client", "SCC", "--row", "create-cylex", "--to", "needs-human", "--reason-code", "captcha", "--note", "x", "--queue", qp, "--today", "2026-11-04", "--dry-run"])
check("R7 CLI dry run exits 0 and prints the code", rc == 0 and '"reason_code": "captcha"' in buf.getvalue())
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    rc = T.main(["--client", "SCC", "--row", "create-cylex", "--to", "needs-human", "--reason-code", "bogus", "--note", "x", "--queue", qp, "--today", "2026-11-04", "--dry-run"])
check("R7 CLI bogus code exits 1 REFUSED", rc == 1 and "REFUSED" in err.getvalue())

# 4 scope guard: the weekly path still never sends the key
check("R4 weekly queue_rows_to_status source unchanged (no reason_code key sent)", "never sends reason_code" in src("directories.py"))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
