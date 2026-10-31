"""Build rows: one SCC queue row per Directory Lis can work (kanban t_00821936). See plans/2026-10-25-buildrows.md.

Adds rows only. A Directory that already has a row (any list) is never touched: state, history and mike_approval stay as they are.
No Directory traffic, no portal call, no transitions.py call. New rows carry Mike's 2026-10-25 blanket approval, stamped verbatim.
Usage: python job/buildrows.py [--write]   (default is a dry run that prints counts; --write backs the queue up first)
"""
import copy, datetime, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buildqueue as Q
import permalink

APPROVED_AT = "2026-10-25T17:45:00+00:00"
SCOPE = "blanket-2026-10-25"
NOTE = ("Mike in Nate chat 2026-10-25: build new SCC listings across the Directory database, keep looping. "
        "Free listings only, canonical NAP verbatim. No spend, no phone/SMS/postcard verify, no client contact without Mike.")
KINDS = ("fix", "create")


def approval(row_id):
    return {"approved_by": "mike", "at": APPROVED_AT, "row_id": row_id, "scope": SCOPE, "note": NOTE}


def row_id(kind, domain):
    return "%s-%s" % (kind, domain.split(".")[0])


def existing_domains(queue):
    """Every Directory that already has a row, in fix_queue, create_rows or create_queue.rows."""
    cq = queue.get("create_queue")
    cq_rows = cq.get("rows") if isinstance(cq, dict) else (cq if isinstance(cq, list) else [])
    return {r.get("directory") for r in list(queue.get("fix_queue") or []) + list(queue.get("create_rows") or []) + list(cq_rows or []) if r.get("directory")}


def _hist(day, to, note, url=None):
    return [{"at": day, "from": "queued", "to": to, "evidence_url": url, "note": note}] if to != "queued" else []


def decide(d, st, ck):
    """-> (action, why, listing_url, diffs). action: none | fix | create | needs-human-paid | needs-human-route."""
    if d.get("build_route") == "none":
        return "needs-human-route", "no-route: Directory has no build route", None, None
    if d.get("cost") == "paid":
        return "needs-human-paid", "paid-tier: Directory charges for a listing; free listings only", None, None
    found = (ck or {}).get("result") == "found" if ck else (st or {}).get("last_result") == "found"
    if not found:
        return "create", "never checked" if not (ck or st) else "last check: %s" % ((ck or {}).get("result") or (st or {}).get("last_result") or "none"), None, None
    url = (ck or {}).get("url") or (st or {}).get("last_url")
    diffs = [x for x in ((ck or {}).get("diffs") or []) if x and x.get("field")]
    match = (ck or {}).get("match") if ck and "match" in ck else (st or {}).get("last_match")
    ok_url = bool(url) and permalink.is_permalink(d["domain"], url)[0]
    if diffs or match is False:
        return "fix", "found with NAP errors", (url if ok_url else None), diffs
    if match is True and ok_url:
        return "none", "found, NAP correct, permalink", url, None
    return "create", "found but no permalink or NAP not confirmed: search first, then claim", None, None


def make_row(d, action, why, url, diffs, day, canon):
    dom = d["domain"]
    base = {"directory": dom, "priority": d.get("priority"), "da": d.get("da"), "found_on": day, "cost": "free" if d.get("cost") != "paid" else "paid",
            "signup_url": d.get("signup_url"), "claim_url": d.get("claim_url"), "build_note": why}
    if action == "fix":
        x = (diffs or [{}])[0]
        rid = row_id("fix", dom)
        row = dict(base, id=rid, kind="fix", listing_url=url, wrong_field=x.get("field"), live_value=x.get("live"), right_value=x.get("canonical"),
                   fix_method="claim or edit on the listing page", claim_status="unknown", claim_evidence=None, evidence_url=url)
        state = "queued"
    elif action == "create":
        rid = row_id("create", dom)
        row = dict(base, id=rid, kind="create", search_first="Search the site for SCC by name + city first; a find is a claim, not a create.")
        state = "queued"
    else:
        rid = row_id("fix" if url else "create", dom)
        row = dict(base, id=rid, kind="create", cost="paid" if action == "needs-human-paid" else base["cost"])
        state = "needs-human"
    row["state"] = state
    row["mike_approval"] = approval(rid)
    row["history"] = [] if state == "queued" else [{"at": day, "from": "queued", "to": "needs-human", "evidence_url": None, "note": why}]
    return row


def build_rows(queue, dirs, status, checks, day):
    """-> (new_queue, report). queue is not mutated. dirs: ce_directories rows; status: SCC ce_directory_status rows; checks: latest-run SCC checks."""
    q = copy.deepcopy(queue)
    have = existing_domains(q)
    sm = {s["directory"]: s for s in status or []}
    cm = {}
    for c in checks or []:
        cur = cm.get(c["directory"])
        if not cur or (c.get("result") == "found" and cur.get("result") != "found"):
            cm[c["directory"]] = c
    canon = q.get("canonical")
    added, rep = [], {"existing": 0, "none": 0, "fix": 0, "create": 0, "needs-human": 0, "ineligible": 0}
    taken = {r.get("id") for k in ("fix_queue", "create_rows") for r in q.get(k) or []} | {r.get("id") for r in (q.get("create_queue") or {}).get("rows", [])}
    for d in dirs:
        dom = d["domain"]
        if dom in have:
            rep["existing"] += 1; continue
        if d.get("build_eligible") is False:   # catalog-only Directory (db/008): no queue row at all, not even needs-human
            rep["ineligible"] += 1; continue
        action, why, url, diffs = decide(d, sm.get(dom), cm.get(dom))
        if action == "none":
            rep["none"] += 1; continue
        row = make_row(d, action, why, url, diffs, day, canon)
        if row["id"] in taken:
            raise Q.QueueError("row id %s would collide" % row["id"])
        taken.add(row["id"]); added.append(row)
        rep["needs-human" if row["state"] == "needs-human" else row["kind"]] += 1
    cq = q.get("create_queue")
    if not isinstance(cq, dict):
        cq = {} if cq is None else {"legacy": cq}
    cq.setdefault("rows", []); cq.setdefault("last_seen", {})
    for r in added:
        (q.setdefault("fix_queue", []) if r["kind"] == "fix" else cq["rows"]).append(r)
    q["create_queue"] = cq
    # build_order: every row id (new and old) by Directory priority, then DA high to low, then domain. Row lists keep their own order.
    pm = {d["domain"]: d for d in dirs}
    allrows = list(q.get("fix_queue") or []) + list(q.get("create_rows") or []) + list(cq["rows"])
    def key(r):
        d = pm.get(r.get("directory"), {})
        return (d.get("priority") if d.get("priority") is not None else 99, -(d.get("da") or 0), r.get("directory") or "")
    new_order = [r["id"] for r in sorted(allrows, key=key)]
    if added:  # only a run that adds rows touches the order, so a second run is a no-op
        q["build_order"] = new_order
    rep["added"] = len(added)
    rep["total_rows"] = len(allrows)
    return q, rep


def counts(queue):
    out = {}
    cq = queue.get("create_queue")
    rows = list(queue.get("fix_queue") or []) + list(queue.get("create_rows") or []) + list((cq or {}).get("rows") or [] if isinstance(cq, dict) else [])
    for r in rows:
        k = (r.get("kind") or ("fix" if str(r.get("id", "")).startswith("fix-") else "create"), r.get("state"))
        out[k] = out.get(k, 0) + 1
    return rows, out


def backup(path, day):
    bak = "%s.bak-%s-buildrows" % (path, day.replace("-", ""))
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    return bak


def apply_file(path, dirs, status, checks, day, write=True):
    """Idempotent file step. Returns (report, bak). Writes (atomic) only when something changes; backs up first."""
    with open(path, encoding="utf-8") as f:
        q = json.load(f)
    new, rep = build_rows(q, dirs, status, checks, day)
    if new == q:
        return rep, None
    if not write:
        return rep, None
    bak = backup(path, day)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(new, f, indent=1)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp): os.unlink(tmp)
        raise
    return rep, bak


def load_db_inputs(db):
    dirs = db.call("GET", "ce_directories?select=domain,name,priority,da,cost,build_route,signup_url,claim_url,build_eligible&order=priority.asc,da.desc.nullslast", None, "return=representation") or []
    status = db.call("GET", "ce_directory_status?biz=eq.SCC&select=directory,last_result,last_url,last_match,claim_status,queue_state", None, "return=representation") or []
    runs = db.call("GET", "ce_runs?select=id&order=started_at.desc&limit=1", None, "return=representation") or []
    checks = []
    if runs:
        checks = db.call("GET", "ce_checks?biz=eq.SCC&run_id=eq.%s&select=directory,result,url,match,diffs" % runs[0]["id"], None, "return=representation") or []
    return dirs, status, checks


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    import directories as D
    db = D.DirDB()
    dirs, status, checks = load_db_inputs(db)
    day = datetime.date.today().isoformat()
    rep, bak = apply_file(Q.QUEUE_PATH, dirs, status, checks, day, write="--write" in argv)
    with open(Q.QUEUE_PATH, encoding="utf-8") as f:
        _, c = counts(json.load(f))
    print(json.dumps({"report": rep, "backup": bak, "by_kind_state": {"%s/%s" % k: v for k, v in sorted(c.items())}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
