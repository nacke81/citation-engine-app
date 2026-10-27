"""Directory database writer: keeps ce_directories / ce_directory_status current from the weekly run and from transitions.py.

No hand-kept copy: the weekly run calls sync_run(), record_transition() calls sync_transition(). Both go through one injectable `db` object with
call(method, path, body=None, prefer=None) (the real one is DirDB, the same Supabase secret key the weekly job already uses). Tests pass a fake.
Never any Directory traffic. The tables hold no client NAP: only the listing URL, the check result, claim status and queue state.

ce_directories.agent_access rules (reference facts, kept by whoever saw the wall last):
  * a weekly search that was walled sets agent_access=blocked (source 'weekly') only when the Directory is not already blocked;
  * a later clean weekly check clears it only when the blocker came from the weekly run (a hand-seen signup wall is never cleared by a search);
  * a needs-human transition sets agent_access=blocked with the transition note as the blocker (source 'transition').
"""
import json, os, urllib.request

ENV_FILE = os.path.expandvars("%LOCALAPPDATA%/hermes/.env")
BIZS = ("SCC", "NM")
WRITE_FLAG = "CE_DIRECTORIES_WRITE"   # set to 0 to switch the sink off (tests)
QUEUE_STATES = ("queued", "found", "claimed-unverified", "created-unlisted", "submitted", "pending-verify", "needs-human", "live", "rejected")


class DirectoriesError(Exception):
    pass


def enabled():
    return os.environ.get(WRITE_FLAG) != "0"


class DirDB:
    """PostgREST client with the weekly job's secret key. Env is read lazily so importing this module has no side effects."""
    def __init__(self, env=None):
        if env is None:
            env = {}
            for l in open(ENV_FILE, encoding="utf-8"):
                if "=" in l and not l.lstrip().startswith("#"):
                    k, v = l.rstrip("\n").split("=", 1); env[k.strip()] = v.strip().strip('"')
        self.url, self.key, self.owner = env["PEOPLE_CRM_SUPABASE_URL"], env["PEOPLE_CRM_SECRET_KEY"], env["BROKER_WATCH_OWNER_ID"]

    def call(self, method, path, body=None, prefer="return=minimal"):
        req = urllib.request.Request(self.url + "/rest/v1/" + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"apikey": self.key, "Authorization": "Bearer " + self.key, "Content-Type": "application/json", "Prefer": prefer})
        with urllib.request.urlopen(req, timeout=30) as r:
            t = r.read(); return json.loads(t) if t else None


def _owner(db):
    o = getattr(db, "owner", None)
    if not o: raise DirectoriesError("db has no owner id")
    return o


def _upsert_status(db, rows):
    if rows:
        db.call("POST", "ce_directory_status?on_conflict=owner,biz,directory", rows, "resolution=merge-duplicates,return=minimal")


def _status_row(db, biz, directory, day, **cols):
    return dict({"owner": _owner(db), "biz": biz, "directory": directory, "updated_at": day + "T00:00:00Z"}, **cols)


def check_rows(db, checks, day):
    """ce_directory_status rows from build() checks. Keys are uniform (PostgREST batch upsert). Local '_claim' rides here and nowhere else."""
    out = []
    for c in checks:
        if c.get("biz") not in BIZS: continue
        cl = c.get("_claim") or {}
        found = c.get("result") == "found"
        ev = cl.get("claim_evidence") or {}
        out.append(_status_row(db, c["biz"], c["directory"], day, last_result=c["result"], last_checked_on=day, last_url=c.get("url") if found else None,
                               last_match=c.get("match") if found else None, last_note=c.get("note") or None,
                               claim_status=(cl.get("claim_status") or "unknown") if found else None,
                               claim_evidence_text=ev.get("text") if found else None))
    return out


def queue_rows_to_status(db, queue, day):
    """Status rows from the SCC queue file contents: fix_queue, create_rows and create_queue.rows. Queue state, row id, blocker note."""
    out = []
    for kind, rows in (("fix", queue.get("fix_queue") or []), ("create", queue.get("create_rows") or []),
                       ("create", (queue.get("create_queue") or {}).get("rows") or [] if isinstance(queue.get("create_queue"), dict) else [])):
        for r in rows:
            if r.get("state") not in QUEUE_STATES or not r.get("directory"): continue
            hist = r.get("history") or []
            last = hist[-1] if hist else {}
            note = last.get("note") if r["state"] == "needs-human" else None
            out.append(_status_row(db, "SCC", r["directory"], day, queue_state=r["state"], queue_row_id=r.get("id"), queue_kind=kind,
                                   queue_note=note, queue_state_at=last.get("at") or r.get("found_on") or day))
    return out


def create_discovery_rows(db, queue, day):
    """Last create-discovery verdict per Directory (SCC): absent/found/couldnt_check. Only fills last_result for Directories outside the weekly 25."""
    cq = queue.get("create_queue")
    ls = cq.get("last_seen") if isinstance(cq, dict) else None
    m = {"absent": "absent", "found": "found", "couldnt": "couldnt_check"}
    out = []
    for d, v in (ls or {}).items():
        if v.get("state") in m:
            out.append(_status_row(db, "SCC", d, day, last_result=m[v["state"]], last_checked_on=v.get("on") or day, last_note=(v.get("why") or "")[:200] or None))
    return out


def _access_updates(db, checks, day):
    """agent_access PATCHes from this run's checks (see module docstring)."""
    try:
        cur = {r["domain"]: r for r in (db.call("GET", "ce_directories?select=domain,agent_access,agent_blocker_source", None, "return=representation") or [])}
    except Exception:
        cur = {}
    by = {}
    for c in checks:
        if c.get("biz") in BIZS: by.setdefault(c["directory"], []).append(c)
    n = 0
    for d, cs in by.items():
        walled = any(c["result"] == "couldnt_check" and c.get("note") == "blocked" for c in cs)
        clean = all(c["result"] in ("found", "absent") for c in cs)
        row = cur.get(d, {})
        if walled and row.get("agent_access") != "blocked":
            db.call("PATCH", "ce_directories?domain=eq.%s" % d, {"agent_access": "blocked", "agent_blocker": "Search was walled in the weekly run.",
                    "agent_blocker_seen_on": day, "agent_blocker_source": "weekly", "last_verified": day, "updated_at": day + "T00:00:00Z"}); n += 1
        elif clean and row.get("agent_access") == "blocked" and row.get("agent_blocker_source") == "weekly":
            db.call("PATCH", "ce_directories?domain=eq.%s" % d, {"agent_access": "ok", "agent_blocker": None, "agent_blocker_seen_on": None,
                    "agent_blocker_source": None, "last_verified": day, "updated_at": day + "T00:00:00Z"}); n += 1
        elif clean and row.get("agent_access") == "unknown":
            db.call("PATCH", "ce_directories?domain=eq.%s" % d, {"agent_access": "ok", "agent_blocker_source": "weekly", "last_verified": day,
                    "updated_at": day + "T00:00:00Z"}); n += 1
    return n


def sync_run(checks, day, queue=None, db=None):
    """Weekly run: upsert check results + claim_status for SCC and NM, the SCC queue state, and the create-discovery verdicts."""
    db = db or DirDB()
    rows = {}
    for r in check_rows(db, checks, day): rows[(r["biz"], r["directory"])] = r
    n_checks = len(rows)
    if queue:
        for r in create_discovery_rows(db, queue, day):
            rows.setdefault((r["biz"], r["directory"]), r)
    # one batch per key shape: PostgREST needs identical keys across a batch
    shapes = {}
    for r in rows.values(): shapes.setdefault(tuple(sorted(r)), []).append(r)
    qrows = queue_rows_to_status(db, queue, day) if queue else []
    for k in shapes: _upsert_status(db, shapes[k])
    for r in qrows: _upsert_status(db, [r])
    n_access = _access_updates(db, checks, day)
    return {"checks": n_checks, "create_discovery": len(rows) - n_checks, "queue_rows": len(qrows), "access_updates": n_access}


def sync_transition(client, row, new_state, note, day, kind="fix", db=None):
    """One queue transition: queue state on the status row; needs-human also marks the Directory agent-blocked with the note as the blocker."""
    if new_state not in QUEUE_STATES: raise DirectoriesError("unknown state %r" % (new_state,))
    db = db or DirDB()
    _upsert_status(db, [_status_row(db, client, row["directory"], day, queue_state=new_state, queue_row_id=row.get("id"), queue_kind=kind,
                                    queue_note=(note or None) if new_state == "needs-human" else None, queue_state_at=day)])
    out = {"status_written": True, "agent_blocked": False}
    if new_state == "needs-human":
        db.call("PATCH", "ce_directories?domain=eq.%s" % row["directory"],
                {"agent_access": "blocked", "agent_blocker": note or "Agent could not continue; needs a human step.", "agent_blocker_seen_on": day,
                 "agent_blocker_source": "transition", "last_verified": day, "updated_at": day + "T00:00:00Z"})
        out["agent_blocked"] = True
    return out
