"""Create-queue discovery tests (placeholder identity, no network). Run: python tests/create_test.py  (CI does this). Exit 1 on any failure.

  C1 absent only with a same-run positive control; no control = couldnt (golden 2)
  C2 walled / error / unrecognised results page = couldnt, never absent
  C3 a real claim = found (exists, so no create row)
  C4 create rows: only absent, state queued, mike_approval null, every required field present
  C5 non-production path: no portal import, no write verbs, no login/signup fetch
"""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
import tempfile as _tf; os.environ["CE_RUNS"] = _tf.mkdtemp(prefix="ce-runs-")  # run.py makes dirs on import; never the real runs folder
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import create_discovery as cd  # noqa: E402
from core import Result  # noqa: E402

ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

D = "acompio.us"
MARK = "Your search resulted in &nbsp;0 Results"
CTRL_TXT = "Search Results for Walmart in Exampleton Your search resulted in 1 Results Mcdonalds Hamburgers - Walmart 40000 Exampleton"
EMPTY = "Search Results for Alder Care Consulting in Exampleton Your search resulted in 0 Results. You can limit your search"
CLAIM = "Alder Care Consulting & Solutions 100 Example, Exampleton, KY 40000 (502) 555-0101 Search Results"
ctrl_ok = Result(200, "https://www.acompio.us/search.php?name=Walmart&place=Exampleton", CTRL_TXT, [{"href": "https://www.acompio.us/Control-1.html", "card": "Mcdonalds Hamburgers - Walmart", "text": "Mcdonalds Hamburgers - Walmart", "aria": ""}])
def R(t, s=200): return Result(s, "https://x/s", t, [])

d = cd.decide(D, [R(EMPTY)], ctrl_ok)
check("C1 absent with control", d["state"] == "absent" and d["control_url"] == "https://www.acompio.us/Control-1.html", str(d))
d = cd.decide(D, [R(EMPTY)], R("Search Results for Walmart Your search resulted in 0 Results"))
check("C1 no control -> couldnt", d["state"] == "couldnt" and "control" in d["why"], str(d))
d = cd.decide(D, [R(EMPTY)], None)
check("C1 control fetch missing -> couldnt", d["state"] == "couldnt")
bad = cd.decide(D, [R(EMPTY)], R(CTRL_TXT))  # control text present but no linked listing URL
check("C1 control without a listing URL -> couldnt", bad["state"] == "couldnt", str(bad))

check("C2 403 -> couldnt", cd.decide(D, [R("Just a moment...", 403)], ctrl_ok)["state"] == "couldnt")
check("C2 error (status None) -> couldnt", cd.decide(D, [Result(None, "u", "", [], "ConnectError")], ctrl_ok)["state"] == "couldnt")
check("C2 unrecognised page (no results marker) -> couldnt", cd.decide(D, [R("Welcome to our home page " * 40)], ctrl_ok)["state"] == "couldnt")
check("C2 one query walled, other clean-empty -> couldnt (not every query ran)", cd.decide(D, [R(EMPTY), R("denied", 403)], ctrl_ok)["state"] == "couldnt")

d = cd.decide(D, [R(CLAIM)], ctrl_ok)
check("C3 claim -> found", d["state"] == "found" and not cd.create_row(D, d, "2026-10-19"), str(d))

d = cd.decide(D, [R(EMPTY), R(EMPTY)], ctrl_ok)
row = cd.create_row(D, d, "2026-10-19")
need = {"directory", "state", "mike_approval", "proof_of_absence", "signup_url", "cost", "login_needed"}
check("C4 row fields", row and need <= set(row), str(sorted(set(row or {}))))
check("C4 queued + mike_approval null", row["state"] == "queued" and row["mike_approval"] is None)
check("C4 proof carries method + control URL", row["proof_of_absence"]["control_url"] == "https://www.acompio.us/Control-1.html" and row["proof_of_absence"]["method"])
check("C4 couldnt makes no row", cd.create_row(D, cd.decide(D, [R(EMPTY)], None), "2026-10-19") is None)
check("C4 every configured Directory has signup url + cost + login", all(v["signup_url"] and v["cost_class"] in ("free", "paid", "unknown") and v["cost"] and v["login_needed"] for v in cd.CREATE_DIRS.values()))
check("C4 exactly 10 Directories", len(cd.CREATE_DIRS) == 10, str(len(cd.CREATE_DIRS)))

import copy, json, tempfile
base_q = {"fix_queue": [{"id": "fix-x", "state": "queued", "mike_approval": None}], "create_queue": {"status": "NOT RUN", "unproven_domains": ["a.com"]}}
dec1 = {D: d}; rows1 = [row]
q1 = cd.merge_create_queue(copy.deepcopy(base_q), dec1, rows1, "2026-10-19")
check("M1 merge adds the row under create_queue.rows, fix_queue untouched, other keys kept", [r["id"] for r in q1["create_queue"]["rows"]] == ["create-acompio"] and q1["fix_queue"] == base_q["fix_queue"] and q1["create_queue"]["unproven_domains"] == ["a.com"])
q2 = cd.merge_create_queue(copy.deepcopy(q1), dec1, rows1, "2026-10-19")
check("M2 second merge, no change: identical file", json.dumps(q1, sort_keys=True) == json.dumps(q2, sort_keys=True))
q3 = copy.deepcopy(q1); q3["create_queue"]["rows"][0]["mike_approval"] = {"approved_by": "mike", "at": "2026-10-20", "row_id": "create-acompio"}; q3["create_queue"]["rows"][0]["state"] = "submitted"
q3 = cd.merge_create_queue(q3, dec1, [dict(row, state="queued", mike_approval=None, cost="changed")], "2026-10-26")
r3 = q3["create_queue"]["rows"]
check("M3 existing mike_approval, state and fields kept; no duplicate row", len(r3) == 1 and r3[0]["mike_approval"]["approved_by"] == "mike" and r3[0]["state"] == "submitted" and r3[0]["cost"] == row["cost"])
q4 = cd.merge_create_queue(copy.deepcopy(q1), {D: dict(state="found", why="now listed")}, [], "2026-11-02")
r4 = q4["create_queue"]["rows"]
check("M4 later found/couldnt keeps the queued row and adds last_seen_state", len(r4) == 1 and r4[0]["state"] == "queued" and r4[0]["last_seen_state"]["state"] == "found")
q5 = cd.merge_create_queue(copy.deepcopy(q1), {D: dict(state="couldnt", why="walled")}, [], "2026-11-02")
check("M4 couldnt also keeps the row", len(q5["create_queue"]["rows"]) == 1 and q5["create_queue"]["rows"][0]["last_seen_state"]["state"] == "couldnt")
check("M5 every row has checked_on", all(v.get("checked_on") for v in cd.CREATE_DIRS.values()) and row["checked_on"])

class FakeF:  # offline fetcher: acompio zero results + Walmart control, everything else a plain page
    def fetch(self, url, label=""):
        if "acompio" in url and "Walmart" in url: return ctrl_ok
        if "acompio" in url: return R(EMPTY)
        return Result(403, url, "denied", [])
tmpq = os.path.join(tempfile.mkdtemp(), "q.json"); json.dump(copy.deepcopy(base_q), open(tmpq, "w"))
cd.weekly_merge(tmpq, FakeF(), "2026-10-19"); a = open(tmpq).read(); cd.weekly_merge(tmpq, FakeF(), "2026-10-19"); b = open(tmpq).read()
check("M6 weekly_merge on a file twice: byte-identical, 1 row", a == b and len(json.loads(b)["create_queue"]["rows"]) == 1)
import run as RUN, io, contextlib  # noqa: E402
# M7 forces a failure on purpose (1/0). create_queue_step prints "CREATE QUEUE FAILED: division by zero" to stderr; under the agent runner that line read as a real
# failure while the exit code was 0 (t_64c4d511). Capture it, assert it, and never let it reach the real stderr.
_err = io.StringIO()
with contextlib.redirect_stderr(_err):
    _m7 = RUN.create_queue_step(merge=lambda p: 1 / 0, path="x")
check("M7 run.create_queue_step failure is non-fatal", _m7 is False)
check("M7 the deliberate failure is reported on stderr (captured, not printed)", "CREATE QUEUE FAILED: division by zero" in _err.getvalue())
check("M7 run.create_queue_step ok", RUN.create_queue_step(merge=lambda p: ({D: {"state": "absent"}}, [row]), path="x") is True)

src = open(os.path.join(HERE, "..", "job", "create_discovery.py"), encoding="utf-8").read()
check("C5 no portal import", not re.search(r"(?m)^\s*(import|from)\s+portal\b", src))
check("C5 no write verbs", not re.search(r"\.(post|put|patch|delete)\(|method\s*=\s*[\"'](POST|PUT|PATCH|DELETE)", src, re.I))
check("C5 only search URLs fetched (no login/signup/add path in search builders)",
      not any(re.search(r"(?i)login|sign_?up|register|add[_-]?business|create-listing", u) for k in cd.CREATE_DIRS for u in cd.search_urls(k, "Alder Care Consulting")))
check("C5 SCC is the only business", cd.BIZ_KEY == "SCC")

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if ok and all(ok) else 1)   # no checks run (empty list) is a failure too
