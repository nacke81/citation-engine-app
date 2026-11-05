"""Weekly progress chart data (kanban t_43e88fb7): ce_weekly_metrics writer and the one-time backfill.

Counting is NOT done here. Every number comes from site/metrics.js (the same builderStats / stats / checkedCount the home tiles use),
reached through job/metrics_cli.mjs, so Python cannot drift from the page. This module only reads rows, picks which runs are points, and writes.

  python job/weekly_metrics.py --backfill            dry run: prints week x metric with the source of every cell. Writes nothing.
  python job/weekly_metrics.py --backfill --write    inserts the rows (insert-or-ignore on (owner, biz, run_id): safe to repeat)

No Directory traffic of any kind: it reads the app's own database tables and the local queue file.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "metrics_cli.mjs")
BIZS = ("SCC", "NM")
KEYS = ("found", "notFound", "correct", "withErrors", "couldntCheck", "checked", "toBuild", "waiting", "needsPerson", "newLive", "claimed", "fixed")
TABLE = "ce_weekly_metrics"


def node_run(jobs, node="node"):
    p = subprocess.run([node, CLI], input=json.dumps(jobs), capture_output=True, text=True, encoding="utf-8", timeout=120)
    if p.returncode != 0:
        raise RuntimeError("metrics_cli failed: " + (p.stderr or "")[:300])
    return json.loads(p.stdout)


def run_day(run, checks):
    """The calendar day of a run: the checked_on the job stamped on its checks (local date), else the start date."""
    days = sorted({c.get("checked_on") for c in checks if c.get("checked_on")})
    return days[-1] if days else str(run.get("started_at") or "")[:10]


def classify_runs(runs, days):
    """Which ce_runs are weekly points. runs: rows with id/started_at/status; days: {run_id: 'YYYY-MM-DD'}.
    Week 0 = the first ok run (the baseline sweep). Every later ok run is the next week, EXCEPT a rerun on the same calendar day as the previous
    point (ad-hoc, adds no point). Failed runs are never points. Returns (points[{run_id, week, day}], skipped[{run_id, day, why}])."""
    pts, skipped = [], []
    for r in sorted(runs, key=lambda x: x["started_at"]):
        d = days.get(r["id"]) or str(r["started_at"])[:10]
        if r.get("status") != "ok":
            skipped.append({"run_id": r["id"], "day": d, "why": "run status " + str(r.get("status"))}); continue
        if pts and pts[-1]["day"] == d:
            skipped.append({"run_id": r["id"], "day": d, "why": "same-day rerun of week %d (ad-hoc)" % pts[-1]["week"]}); continue
        pts.append({"run_id": r["id"], "week": len(pts), "day": d})
    return pts, skipped


def _get(db, path):
    return db.call("GET", path, None, "return=representation") or []


def load_context(db):
    """Same tables the page reads: ce_runs, ce_checks, ce_directory_biz (status view), ce_directories."""
    runs = _get(db, "ce_runs?select=id,started_at,status&order=started_at.asc")
    checks = _get(db, "ce_checks?select=*&limit=5000")
    status = _get(db, "ce_directory_biz?select=*")
    dirs = _get(db, "ce_directories?select=*&order=priority")
    return runs, checks, status, dirs


def snapshot_run(db, run_id, day=None, node=node_run):
    """Weekly job: one row per business for this run, computed from what the page will read (ce_checks of the run, the status view, the Directory table).
    Idempotent on (owner, biz, run_id): a repeat writes nothing. Only the weekly job calls this (run.py --weekly); an ad-hoc run never does."""
    checks = _get(db, "ce_checks?select=*&run_id=eq.%s&limit=5000" % run_id)
    if not checks:
        raise RuntimeError("no ce_checks for run " + run_id)
    status = _get(db, "ce_directory_biz?select=*")
    dirs = _get(db, "ce_directories?select=*&order=priority")
    day = day or run_day({}, checks)
    out = {}
    for biz in BIZS:
        have = _get(db, "%s?select=id&biz=eq.%s&run_id=eq.%s" % (TABLE, biz, run_id))
        if have:
            out[biz] = "exists"; continue
        mx = _get(db, "%s?select=week_index&biz=eq.%s&order=week_index.desc&limit=1" % (TABLE, biz))
        if mx:
            week = mx[0]["week_index"] + 1
        else:   # no history table rows yet: position among the classified weekly runs
            runs = _get(db, "ce_runs?select=id,started_at,status&order=started_at.asc")
            allc = _get(db, "ce_checks?select=run_id,checked_on&limit=5000")
            days = {r["id"]: run_day(r, [c for c in allc if c["run_id"] == r["id"]]) for r in runs}
            pts, _ = classify_runs(runs, days)
            week = next((p["week"] for p in pts if p["run_id"] == run_id), len(pts))
        res = node([{"mode": "snapshot", "checks": [c for c in checks if c["biz"] == biz], "status": [s for s in status if s.get("biz") == biz], "dirs": dirs}])[0]
        row = {"owner": db.owner, "biz": biz, "run_id": run_id, "week_index": week, "captured_on": day, "metrics": res["metrics"], "sources": {k: "snapshot" for k in KEYS}}
        db.call("POST", TABLE + "?on_conflict=owner,biz,run_id", [row], "resolution=ignore-duplicates,return=minimal")
        out[biz] = week
    return out


def queue_rows_for(queue, biz):
    if biz != "SCC" or not queue:
        return []
    import directories as D
    return [{"directory": r["directory"], "state": r.get("state"), "kind": r.get("kind"), "history": r.get("history") or []} for r in D._queue_rows(queue) if r.get("directory")]


def backfill_plan(runs, checks, status, dirs, queue, node=node_run):
    """Rebuilt weekly rows for every point of every business. Nothing is written here."""
    by_run = {}
    for c in checks:
        by_run.setdefault(c["run_id"], []).append(c)
    days = {r["id"]: run_day(r, by_run.get(r["id"], [])) for r in runs}
    pts, skipped = classify_runs(runs, days)
    jobs, meta = [], []
    for p in pts:
        for biz in BIZS:
            jobs.append({"mode": "rebuild", "checks": [c for c in by_run.get(p["run_id"], []) if c["biz"] == biz], "queueRows": queue_rows_for(queue, biz),
                         "status": [s for s in status if s.get("biz") == biz], "dirs": dirs, "runDay": p["day"]})
            meta.append((p, biz))
    res = node(jobs) if jobs else []
    rows = [{"biz": biz, "run_id": p["run_id"], "week_index": p["week"], "captured_on": p["day"], "metrics": r["metrics"], "sources": r["sources"], "ranges": r.get("ranges")}
            for (p, biz), r in zip(meta, res)]
    return rows, skipped


def format_table(rows, skipped):
    """Week x metric with the source of every cell. v = value, [src] = ce_checks (C) / queue history (Q) / gap (GAP, with the possible range)."""
    tag = {"ce_checks": "C", "queue history": "Q", "gap": "GAP"}
    out = []
    for biz in BIZS:
        out.append("== %s ==" % biz)
        mine = sorted([r for r in rows if r["biz"] == biz], key=lambda r: r["week_index"])
        out.append("%-24s" % "metric" + "".join("%-16s" % ("Wk %d %s" % (r["week_index"], r["captured_on"][5:])) for r in mine))
        for k in KEYS:
            cells = []
            for r in mine:
                v, s = r["metrics"].get(k), r["sources"].get(k)
                rg = (r.get("ranges") or {}).get(k)
                cells.append(("%s [%s]" % (v, tag.get(s, s))) if v is not None else "gap [%s-%s]" % tuple(rg) if rg else "gap")
            out.append("%-24s" % k + "".join("%-16s" % c for c in cells))
    out.append("runs not used as points: " + (json.dumps(skipped) if skipped else "none"))
    return "\n".join(out)


def write_rows(db, rows):
    for r in rows:
        body = {"owner": db.owner, "biz": r["biz"], "run_id": r["run_id"], "week_index": r["week_index"], "captured_on": r["captured_on"], "metrics": r["metrics"], "sources": r["sources"]}
        db.call("POST", TABLE + "?on_conflict=owner,biz,run_id", [body], "resolution=ignore-duplicates,return=minimal")
    return len(rows)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--backfill" not in argv:
        print(__doc__); return 2
    sys.path.insert(0, HERE)
    import directories as D, buildqueue
    db = D.DirDB()
    runs, checks, status, dirs = load_context(db)
    try:
        queue = json.load(open(buildqueue.QUEUE_PATH, encoding="utf-8"))
    except Exception:
        queue = None
    rows, skipped = backfill_plan(runs, checks, status, dirs, queue)
    print(format_table(rows, skipped))
    if "--write" not in argv:
        print("dry run: nothing written"); return 0
    print("wrote", write_rows(db, rows), "rows (insert-or-ignore)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
