"""SCC fix/create queue: portal overlay + gated one-row submit (DRY RUN ONLY).

This module makes no outbound calls of any kind. A live Directory adapter does not exist.
submit_row refuses unless the row carries a Mike approval recorded for that exact row id, and unless the login can be read from
Vaultwarden at run time (injected getter; missing or failing -> refuse). SCC only.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
# The real queue holds the client's identity, so it lives outside the repo (like the identity file). Tests point CE_QUEUE at a placeholder fixture.
QUEUE_PATH = os.environ.get("CE_QUEUE") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/queue/scc-fix-create-queue.json")
LISTING_STATES = ("live", "pending-verify", "submitted")
PORTAL_STATES = ("submitted", "pending-verify", "needs-human", "live", "rejected")
# found = SCC is already listed and the claim is not done. Internal only: the client sees needs-human, like queued.
QUEUE_TO_PORTAL = {"queued": "needs-human", "found": "needs-human"}
for _s in PORTAL_STATES:
    QUEUE_TO_PORTAL[_s] = _s


class QueueError(Exception):
    pass


class SubmitRefused(QueueError):
    pass


def parse_rows(q):
    rows = list(q.get("fix_queue", [])) + list(q.get("create_rows", []))
    ids = [r.get("id") for r in rows]
    if len(set(ids)) != len(ids) or not all(ids):
        raise QueueError("queue row ids missing or duplicated")
    for r in rows:
        if r.get("state") not in QUEUE_TO_PORTAL:
            raise QueueError("row %s has invalid state %r" % (r["id"], r.get("state")))
        if not r.get("directory"):
            raise QueueError("row %s has no directory" % r["id"])
    return rows


def load_rows(path=None):
    with open(path or QUEUE_PATH, encoding="utf-8") as f:
        return parse_rows(json.load(f))


def overlay_directories(payload, rows, day):
    """Return a copy of an SCC payload with queue state shown on each queued Directory. Counts are not changed."""
    out = dict(payload)
    out["directories"] = [dict(d) for d in payload["directories"]]
    by = {d["domain"]: d for d in out["directories"]}
    for r in rows:
        st = QUEUE_TO_PORTAL[r["state"]]
        d = by.get(r["directory"])
        if d is None:  # a create row: not in the checked 25
            d = {"name": r["directory"], "domain": r["directory"], "authority": None, "napConsistent": None, "url": None, "issues": [],
                 "status": "undiscovered", "httpStatus": None, "method": None}
            out["directories"].append(d)
            by[r["directory"]] = d
        d["state"], d["stateDate"] = st, day
        if st != "live" and d.get("urlKind") != "listing":
            d["url"] = None  # a resolved listing permalink is kept; anything else is cleared
        if str(r.get("id", "")).startswith("create-") and st in LISTING_STATES and d.get("urlKind") != "listing":
            import listing  # a create row carries its evidence URL; shown only when it is a listing permalink (never search / signup / success)
            ev = r.get("evidence_url")
            if ev and listing.is_permalink(r["directory"], ev):
                d["url"], d["urlKind"] = ev, "listing"
    return out


def approval_ok(row):
    a = row.get("mike_approval")
    return isinstance(a, dict) and a.get("approved_by") == "mike" and bool(a.get("at")) and a.get("row_id") == row.get("id")


def submit_row(row, get_login, free_only=True, record=None):
    """DRY RUN of one submit. Returns the intended transition; never contacts a Directory."""
    if not approval_ok(row):
        raise SubmitRefused("no Mike approval recorded for row %s" % row.get("id"))
    if row.get("state") != "queued":
        raise SubmitRefused("row %s is not queued" % row.get("id"))
    if free_only and not str(row.get("cost", "")).startswith("free"):
        raise SubmitRefused("paid rows are out of scope")
    item = row.get("vaultwarden_item")
    if not item:
        raise SubmitRefused("login missing for row %s" % row.get("id"))
    try:
        cred = get_login(item)
    except Exception:
        raise SubmitRefused("Vaultwarden read failed for row %s" % row.get("id")) from None
    if not cred:
        raise SubmitRefused("Vaultwarden item missing for row %s" % row.get("id"))
    res = {"id": row["id"], "dry_run": True, "directory": row["directory"], "field": row["wrong_field"], "to": row["right_value"], "next_state": "submitted"}
    # Success path: record the submitted state (queue + Local SEO + gated Activities). submit_row is still a dry run (no Directory adapter
    # exists), so recording is opt-in via CE_RECORD_TRANSITIONS=1 or an injected record(); once a live adapter lands, flip the default.
    if record is None and os.environ.get("CE_RECORD_TRANSITIONS") == "1":
        import transitions
        record = transitions.record_transition
    if record:
        res["recorded"] = record("SCC", row["id"], "submitted", row.get("listing_url"), "submitted via build queue")
    return res
