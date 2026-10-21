"""Citation state transitions: one call records a state change in the SCC queue file, the SCC Local SEO portal snapshot, and (gated) Activities.

record_transition(client, row_id, new_state, evidence_url, note) accepts only:
  queued -> submitted, submitted -> pending-verify, submitted|pending-verify -> live, any -> rejected, any -> needs-human.
Everything else is refused before anything is written. mike_approval is never read for writing and never changed.

Sinks (all injectable so tests and the dry run make no network call):
  queue     the SCC queue JSON (atomic replace; state, evidence_url, dated history entry)
  portal    footprint_snapshot via portal.Portal (same-day snapshot, one directory row overlaid; counts unchanged)
  activities  one client-voiced deliverables row per transition. The deliverables table has NO draft or pending-approval state
            (read from the portal repo migrations on 2026-10-20), so a written row is client-visible at once. The write is therefore OFF
            unless CE_ACTIVITIES_WRITE=1 (or activities_enabled=True) is set by a person who owns the Mike gate.
"""
import copy, datetime, json, os, re, sys, tempfile
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buildqueue as Q
import portal as P
import directories as D

STATES = ("queued",) + Q.PORTAL_STATES  # queued, submitted, pending-verify, needs-human, live, rejected
ALLOWED_FROM = {
    "submitted": {"queued"},
    "pending-verify": {"submitted"},
    "live": {"submitted", "pending-verify"},
}
ANY_FROM = {"rejected", "needs-human"}
ACTIVITY_SOURCE = "citation_engine"
FLAG = "CE_ACTIVITIES_WRITE"


class TransitionRefused(Exception):
    pass


def check_transition(old, new):
    if new not in STATES or new == "queued":
        raise TransitionRefused("unknown or unsupported target state %r" % (new,))
    if old not in STATES:
        raise TransitionRefused("row has unknown current state %r" % (old,))
    if new in ANY_FROM:
        if old == new:
            raise TransitionRefused("row is already %s" % new)
        return
    if old not in ALLOWED_FROM[new]:
        raise TransitionRefused("transition %s -> %s is not allowed" % (old, new))


def check_evidence(url, new):
    if url in (None, ""):
        if new == "live":
            raise TransitionRefused("live needs an evidence url")
        return None
    s = urlsplit(url)
    if s.scheme not in ("http", "https") or not s.netloc or "@" in s.netloc:
        raise TransitionRefused("evidence url must be plain http(s) with no credentials")
    return url


def activity_title(new, directory):
    """Client-voiced, no terminal period, domain only (no NAP)."""
    t = {
        "submitted": "Submitted your business listing to %s",
        "pending-verify": "Your %s listing is awaiting verification",
        "live": "Your %s listing is live",
        "rejected": "%s did not accept your listing, we are following up",
        "needs-human": "Your %s listing needs a manual step from our team",
    }[new]
    return t % directory


def activities_enabled(explicit=None):
    return bool(explicit) if explicit is not None else os.environ.get(FLAG) == "1"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_atomic(path, data):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp): os.unlink(tmp)
        raise


def _row_lists(q):
    """(key, kind, list) for every list that holds queue rows. The weekly create discovery writes create rows under
    create_queue.rows (a dict); create_rows is the older flat list. Lists are returned live so callers can replace rows in place."""
    out = [("fix_queue", "fix", q.get("fix_queue") or []), ("create_rows", "create", q.get("create_rows") or [])]
    cq = q.get("create_queue")
    if isinstance(cq, dict):
        out.append(("create_queue", "create", cq.get("rows") or []))
    elif isinstance(cq, list):
        out.append(("create_queue", "create", cq))
    return out


def _find(q, row_id):
    for _key, _kind, rows in _row_lists(q):
        for r in rows:
            if r.get("id") == row_id:
                return r
    raise TransitionRefused("no queue row with id %r" % (row_id,))


def _kind_of(q, row_id):
    for _key, kind, rows in _row_lists(q):
        if any(r.get("id") == row_id for r in rows):
            return kind
    return "fix"


def portal_payload_for(base, row, day):
    """Overlay ONE row's state on a snapshot payload (counts unchanged). base None (dry run) gives just the row patch."""
    if base is None:
        base = {"directories": []}
    return Q.overlay_directories(base, [row], day)


def build_activity_record(client_id, row, new, evidence_url, day):
    return {"client_id": client_id, "deliverable_type": "citation", "title": activity_title(new, row["directory"]),
            "date_completed": day, "in_scope": True, "units": 1, "evidence_url": evidence_url,
            "source": ACTIVITY_SOURCE, "source_ref": "citation-transition:%s:%s" % (row["id"], new)}


def record_transition(client, row_id, new_state, evidence_url=None, note=None, *, queue_path=None, today=None, portal=None,
                      dry_run=False, activities=None, activities_flag=None, directories=None):
    """Returns a dict describing what was (or, in dry_run, would be) written. Refusals raise TransitionRefused before any write.
    portal: object with latest_snapshot(client_id)/upsert_snapshot(...) (default: real Portal from the prod env pointer).
    activities: object with call(method, path, body, prefer) (default: the same Portal).
    directories: object with .owner and call(method, path, body, prefer) for the Directory database (default: DirDB from the weekly job env;
    CE_DIRECTORIES_WRITE=0 turns the sink off)."""
    if client != "SCC":
        raise TransitionRefused("queue transitions are SCC only, got %r" % (client,))
    client_id = P.client_for(client)
    path = queue_path or Q.QUEUE_PATH
    day = today or datetime.date.today().isoformat()
    q = _read(path)
    Q.parse_rows(q)
    row = _find(q, row_id)
    old = row["state"]
    check_transition(old, new_state)
    evidence_url = check_evidence(evidence_url, new_state)

    approval_before = copy.deepcopy(row.get("mike_approval"))
    new_row = copy.deepcopy(row)
    new_row["state"] = new_state
    if evidence_url: new_row["evidence_url"] = evidence_url
    entry = {"at": day, "from": old, "to": new_state, "evidence_url": evidence_url, "note": note or None}
    new_row.setdefault("history", [])
    new_row["history"] = list(new_row["history"]) + [entry]
    assert new_row.get("mike_approval") == approval_before  # never touched

    out = {"dry_run": bool(dry_run), "row_id": row_id, "from": old, "to": new_state, "history_entry": entry, "errors": []}
    rec = build_activity_record(client_id, new_row, new_state, evidence_url, day)
    out["activity_record"] = rec
    out["activities_written"] = False
    use_act = activities_enabled(activities_flag)
    out["activities_flag_on"] = use_act

    if dry_run:
        pp = portal_payload_for(None, new_row, day)
        out["queue_row_after"] = {k: new_row[k] for k in ("id", "directory", "state", "evidence_url", "history") if k in new_row}
        out["portal_request"] = {"method": "POST", "path": "footprint_snapshot?on_conflict=client_id,source,captured_day",
                                 "row": {"client_id": client_id, "source": P.SOURCE, "captured_day": day,
                                         "payload": "latest snapshot payload, directories patched with:",
                                         "directory_patch": pp["directories"]}}
        out["activities_request"] = ({"method": "POST", "path": "deliverables?on_conflict=client_id,source_ref", "body": [rec]} if use_act
                                     else "skipped: %s is not 1 (the deliverables table has no draft state)" % FLAG)
        return out

    # 1 queue file (source of truth). Replace the row in place, preserving the rest of the file.
    kind = _kind_of(q, row_id)
    for _key, _kind, rows in _row_lists(q):
        for i, r in enumerate(rows):
            if r.get("id") == row_id: rows[i] = new_row
    _write_atomic(path, q)
    out["queue_written"] = path

    # 2 portal snapshot
    try:
        portal = portal or P.Portal(*P.load_portal_env())
        latest = portal.latest_snapshot(client_id)
        base = latest["payload"] if latest else None
        if base is None: raise P.PortalWriteError("no existing SCC snapshot to overlay; run the weekly scan first")
        portal.upsert_snapshot(client_id, day, portal_payload_for(base, new_row, day))
        out["portal_written"] = True
    except Exception as e:
        out["portal_written"] = False
        out["errors"].append("portal: %s" % e)

    # 3 activities (gated)
    if use_act:
        try:
            act = activities or portal or P.Portal(*P.load_portal_env())
            act.call("POST", "deliverables?on_conflict=client_id,source_ref", [rec], prefer="resolution=merge-duplicates,return=minimal")
            out["activities_written"] = True
        except Exception as e:
            out["errors"].append("activities: %s" % e)

    # 4 Directory database (ce_directory_status + needs-human blocker on ce_directories). Never blocks the queue write above.
    out["directories_written"] = False
    if directories is not None or D.enabled():
        try:
            out["directories"] = D.sync_transition(client, new_row, new_state, note, day, kind=kind, db=directories)
            out["directories_written"] = True
        except Exception as e:
            out["errors"].append("directories: %s" % e)
    return out


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Record a citation state transition (queue + Local SEO + gated Activities)")
    a.add_argument("--client", default="SCC")
    a.add_argument("--row", required=True)
    a.add_argument("--to", required=True, dest="new_state")
    a.add_argument("--evidence", default=None)
    a.add_argument("--note", default=None)
    a.add_argument("--queue", default=None)
    a.add_argument("--dry-run", action="store_true", help="no queue write, no network; print the payloads")
    a.add_argument("--today", default=None)
    n = a.parse_args(argv)
    try:
        res = record_transition(n.client, n.row, n.new_state, n.evidence, n.note, queue_path=n.queue, today=n.today, dry_run=n.dry_run)
    except (TransitionRefused, Q.QueueError, P.PortalWriteError) as e:
        print("REFUSED: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2))
    return 2 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
