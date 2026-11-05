"""Weekly progress chart data (t_43e88fb7): snapshot writer idempotent, ad-hoc runs add no point, gaps stay gaps, no Directory traffic. Fake db; real node for the counts."""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); JOB = os.path.join(ROOT, "job")
sys.path.insert(0, JOB)
import tempfile
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
_T = tempfile.TemporaryDirectory(prefix="weekly-metrics-", dir=HERE)
os.environ["CE_RUNS"] = _T.name; os.environ["CE_ROWS"] = os.path.join(_T.name, "rows.jsonl")
import weekly_metrics as W

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

# ---- fixture: 4 runs. r0 = baseline (Fri), r0b = same-day rerun (ad-hoc), r1 = Sunday weekly, r2 = Sunday weekly, rf = failed.
RUNS = [{"id": "r0", "started_at": "2026-10-16T16:30:00Z", "status": "ok"}, {"id": "r0b", "started_at": "2026-10-16T19:44:00Z", "status": "ok"},
        {"id": "r1", "started_at": "2026-10-18T16:00:00Z", "status": "ok"}, {"id": "rf", "started_at": "2026-10-20T16:00:00Z", "status": "failed"},
        {"id": "r2", "started_at": "2026-10-25T16:00:00Z", "status": "ok"}]
DAY = {"r0": "2026-10-16", "r0b": "2026-10-16", "r1": "2026-10-18", "rf": "2026-10-20", "r2": "2026-10-25"}
def ck(run, biz, d, res, **x): return dict({"run_id": run, "biz": biz, "directory": d, "result": res, "checked_on": DAY[run], "diffs": []}, **x)
CHECKS = []
for r in DAY:
    CHECKS += [ck(r, "SCC", "a.example", "found"), ck(r, "SCC", "b.example", "absent"), ck(r, "SCC", "c.example", "couldnt_check"),
               ck(r, "NM", "a.example", "found"), ck(r, "NM", "b.example", "absent")]
DIRS = [{"domain": d + ".example", "name": d, "agent_access": "ok"} for d in "abc"]
STATUS = [{"biz": "SCC", "domain": "b.example", "queue_state": "submitted", "queue_kind": "create", "build_action": "new"}, {"biz": "SCC", "domain": "a.example", "claim_status": "claimed"}]
QUEUE = {"create_queue": {"rows": [{"id": "x", "directory": "b.example", "state": "submitted", "kind": "create", "history": [{"at": "2026-10-21", "from": "queued", "to": "submitted"}]}]}}

# ---- classifier
pts, skipped = W.classify_runs(RUNS, DAY)
check("C1 week 0 is the first ok run", pts[0] == {"run_id": "r0", "week": 0, "day": "2026-10-16"})
check("C2 same-day rerun adds no point (ad-hoc)", [p["run_id"] for p in pts] == ["r0", "r1", "r2"] and any(s["run_id"] == "r0b" for s in skipped))
check("C3 failed run is not a point", all(p["run_id"] != "rf" for p in pts) and any(s["run_id"] == "rf" for s in skipped))
check("C4 weeks are 0,1,2", [p["week"] for p in pts] == [0, 1, 2])

# ---- backfill rebuild (real node + site/metrics.js)
rows, sk = W.backfill_plan(RUNS, CHECKS, STATUS, DIRS, QUEUE)
check("B1 two businesses x three points", len(rows) == 6)
scc = {r["week_index"]: r for r in rows if r["biz"] == "SCC"}; nm = {r["week_index"]: r for r in rows if r["biz"] == "NM"}
check("B2 check metrics come from ce_checks", scc[2]["metrics"]["found"] == 1 and scc[2]["metrics"]["notFound"] == 1 and scc[2]["metrics"]["checked"] == 3 and scc[2]["sources"]["found"] == "ce_checks")
check("B3 queue row from history: submitted before the run day -> waiting 1", scc[2]["metrics"]["waiting"] == 1 and scc[2]["sources"]["waiting"] == "queue history")
check("B4 before the queue row existed: waiting is exactly 0, but To build is a gap (found row a.example may or may not have been claimed then)", scc[0]["metrics"]["waiting"] == 0 and scc[0]["metrics"]["toBuild"] is None and scc[0]["sources"]["toBuild"] == "gap")
check("B5 NM has no queue: To build cannot be known -> None (gap)", nm[1]["metrics"]["toBuild"] is None and nm[1]["sources"]["toBuild"] == "gap")
check("B6 gap is never a zero anywhere", all(v is None or isinstance(v, int) for r in rows for v in r["metrics"].values()) and all((r["metrics"][k] is None) == (r["sources"][k] == "gap") for r in rows for k in W.KEYS))
tbl = W.format_table(rows, sk)
check("B7 dry-run table has a source on every cell and lists the skipped run", "[C]" in tbl and "[Q]" in tbl and "gap [" in tbl and "r0b" in tbl)

# ---- fake PostgREST: just enough to prove idempotency and ordering
class Fake:
    owner = "o1"
    def __init__(self, preload=None):
        self.t = {"ce_checks": CHECKS, "ce_runs": RUNS, "ce_directory_biz": STATUS, "ce_directories": DIRS, "ce_weekly_metrics": list(preload or [])}; self.posts = []; self.all = []
    def call(self, method, path, body=None, prefer=None):
        self.all.append((method, path)); table, _, q = path.partition("?"); qs = dict(p.split("=", 1) for p in q.split("&") if "=" in p)
        if method == "GET":
            rs = self.t[table]
            for k, v in qs.items():
                if v.startswith("eq."): rs = [r for r in rs if str(r.get(k)) == v[3:]]
            if qs.get("order") == "week_index.desc": rs = sorted(rs, key=lambda r: -r["week_index"])[:1]
            return rs
        if method == "POST":
            self.posts.append((path, body, prefer))
            for r in body:
                dup = any(x["biz"] == r["biz"] and x["run_id"] == r["run_id"] for x in self.t[table])
                if not dup: self.t[table].append(r)
            return None
        raise AssertionError("unexpected " + method)

wsrc0 = open(os.path.join(JOB, "weekly_metrics.py"), encoding="utf-8").read()
db = Fake()
r1 = W.snapshot_run(db, "r1", "2026-10-18")
check("S1 one row per business written", len(db.t["ce_weekly_metrics"]) == 2 and set(r1) == {"SCC", "NM"})
check("S2 first run with no table rows gets its classified week (r1 = week 1, not 0)", {r["week_index"] for r in db.t["ce_weekly_metrics"]} == {1})
before = len(db.posts); r1b = W.snapshot_run(db, "r1", "2026-10-18")
check("S3 idempotent: second call writes nothing", len(db.t["ce_weekly_metrics"]) == 2 and len(db.posts) == before and r1b == {"SCC": "exists", "NM": "exists"})
check("S4 insert is ignore-duplicates on (owner,biz,run_id)", all("on_conflict=owner,biz,run_id" in p and "ignore-duplicates" in pf for p, b, pf in db.posts))
W.snapshot_run(db, "r2", "2026-10-25")
check("S5 next weekly run is max+1", sorted(r["week_index"] for r in db.t["ce_weekly_metrics"] if r["biz"] == "SCC") == [1, 2])
m = next(r for r in db.t["ce_weekly_metrics"] if r["biz"] == "SCC" and r["run_id"] == "r2")["metrics"]
check("S6 snapshot has the 12 tile keys, all ints (none is a gap going forward)", set(m) == set(W.KEYS) and all(isinstance(v, int) for v in m.values()))
node_m = W.node_run([{"mode": "snapshot", "checks": [c for c in CHECKS if c["run_id"] == "r2" and c["biz"] == "SCC"], "status": [s for s in STATUS if s["biz"] == "SCC"], "dirs": DIRS}])[0]["metrics"]
check("S7 snapshot equals the page's weeklyMetrics for the same rows", m == node_m)
check("S8 submitted row is waiting; claimed found row and the unchecked row are not To build", m["waiting"] == 1 and m["toBuild"] == 0, str(m))

# ---- round 3: the live path uses the SAME week rule as the backfill
def mk(extra_runs, extra_days, preload):
    for r in extra_runs:
        RUNS.append(r); DAY[r["id"]] = extra_days[r["id"]]
        CHECKS.extend([ck(r["id"], "SCC", "a.example", "found"), ck(r["id"], "NM", "a.example", "found")])
    return Fake(preload)
pre = [{"biz": b, "run_id": "r2", "week_index": 3, "captured_on": "2026-11-01"} for b in W.BIZS]
db3 = mk([{"id": "w_fail", "started_at": "2026-11-08T16:00:00Z", "status": "failed"}, {"id": "w_ok", "started_at": "2026-11-08T17:00:00Z", "status": "ok"},
          {"id": "w_ok2", "started_at": "2026-11-08T18:00:00Z", "status": "ok"}], {"w_fail": "2026-11-08", "w_ok": "2026-11-08", "w_ok2": "2026-11-08"}, pre)
n0 = len(db3.t["ce_weekly_metrics"])
rf_ = W.snapshot_run(db3, "w_fail", "2026-11-08")
check("R1 failed weekly run gives no row, does not raise", len(db3.t["ce_weekly_metrics"]) == n0 and all(str(v).startswith("skipped") for v in rf_.values()), str(rf_))
rok = W.snapshot_run(db3, "w_ok", "2026-11-08")
check("R2 ok rerun the same day after a FAILED run becomes the next week (N+1)", sorted({r["week_index"] for r in db3.t["ce_weekly_metrics"] if r["run_id"] == "w_ok"}) == [4], str(rok))
n1 = len(db3.t["ce_weekly_metrics"])
rdup = W.snapshot_run(db3, "w_ok2", "2026-11-08")
check("R3 same-day ok rerun after an ok point gives no row", len(db3.t["ce_weekly_metrics"]) == n1 and all(str(v).startswith("skipped") for v in rdup.values()), str(rdup))
check("R4 one week rule: classify_runs and snapshot_run both call skip_reason", bool(W.skip_reason("failed", "d", None)) and bool(W.skip_reason("ok", "d", {"day": "d", "week": 1})) and W.skip_reason("ok", "d", {"day": "e", "week": 1}) is None
      and "skip_reason(" in wsrc0.split("def classify_runs")[1].split("def _get")[0] and "skip_reason(" in wsrc0.split("def snapshot_run")[1].split("def queue_rows_for")[0])

# ---- ad hoc runs add no point: only run.py --weekly writes a snapshot; weekly.cmd passes it
src = open(os.path.join(JOB, "run.py"), encoding="utf-8").read()
calls = [l for l in src.splitlines() if "weekly_metrics_step(" in l and "def " not in l]
check("A1 run.py main calls the snapshot only under --weekly", len(calls) == 1 and '"--weekly" in sys.argv' in calls[0])
check("A2 weekly.cmd passes --weekly", re.search(r"run\.py\"? --weekly", open(os.path.join(JOB, "weekly.cmd"), encoding="utf-8").read()) is not None)
check("A3 only run.py writes ce_runs (no other writer to count as a weekly point)", sum(1 for f in os.listdir(JOB) if f.endswith(".py") and re.search(r'"POST",\s*"ce_runs"', open(os.path.join(JOB, f), encoding="utf-8").read())) == 1)
import run as R   # noqa: E402  (after the source checks: importing creates the runs dir, tests set none here)
fail_db = type("B", (Fake,), {"call": lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("down"))})()
check("A4 snapshot failure is non-fatal", R.weekly_metrics_step("r1", "2026-10-18", db=fail_db) is False)

# ---- no Directory traffic
wsrc = open(os.path.join(JOB, "weekly_metrics.py"), encoding="utf-8").read()
check("N1 weekly_metrics.py has no fetch / discovery / recheck / browser code", not re.search(r"discover|recheck|fetcher|selenium|playwright|chrome|urlopen|requests\.", wsrc, re.I))
check("N2 only the app's own tables are touched", set(re.findall(r'"(ce_[a-z_]+)', wsrc)) <= {"ce_runs", "ce_checks", "ce_directory_biz", "ce_directories", "ce_weekly_metrics"})
check("N3 backfill dry run writes nothing (no POST path without --write)", "--write" in wsrc and wsrc.index("dry run: nothing written") < wsrc.index("write_rows(db, rows)", wsrc.index("dry run: nothing written")))
check("N4 migration file creates the table with the unique key", "unique (owner, biz, run_id)" in open(os.path.join(ROOT, "db", "012_weekly_metrics.sql"), encoding="utf-8").read() and "ce_weekly_metrics" in open(os.path.join(ROOT, "db", "schema.sql"), encoding="utf-8").read())

print("ALL PASS" if all(ok) else "FAILURES", sum(ok), "/", len(ok))
sys.exit(0 if all(ok) else 1)
