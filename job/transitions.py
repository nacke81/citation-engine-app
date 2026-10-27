"""Citation state transitions: one call records a state change in the SCC queue file, the SCC Local SEO portal snapshot, and (gated) Activities.

record_transition(client, row_id, new_state, evidence_url, note) accepts only:
  queued -> found, queued|found|needs-human -> created-unlisted (internal; live|needs-human|rejected from it), queued|found|needs-human -> submitted|pending-verify, found|submitted|pending-verify|needs-human -> live,
  any -> rejected, any -> needs-human. found (SCC already listed, claim not done) is internal: no client activity.
  found -> found and needs-human -> needs-human are accepted only with a note (note refresh on a parked row).
Everything else is refused before anything is written. mike_approval is never read for writing and never changed.

Sinks (all injectable so tests and the dry run make no network call):
  queue     the SCC queue JSON (atomic replace; state, evidence_url, dated history entry)
  portal    footprint_snapshot via portal.Portal (same-day snapshot, one directory row overlaid; counts unchanged)
  activities  one client-voiced deliverables row for submitted, pending-verify, live and rejected (never needs-human: an internal blocker
            is not client news). ON by default (Mike, 2026-10-21). Rows land with approved_at null and the portal hides them until Mike
            approves (migration 20261020000002); the engine never sets approved_at. Opt out with CE_ACTIVITIES_WRITE=0 (tests, dry runs).
  verification  needs-human with verify_type phone-call|sms|postcard upserts one citation_verification row (idempotent per client+directory)
            for the client's Your Turn page and the batch trigger. A later live transition marks that row live with verified_at.
            Email verifications never use this path.
"""
import copy, datetime, json, os, re, sys, tempfile
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buildqueue as Q
import portal as P
import directories as D
import walls as W

STATES = ("queued", "found", "claimed-unverified", "created-unlisted") + Q.PORTAL_STATES  # queued, found, claimed-unverified, created-unlisted, submitted, pending-verify, needs-human, live, rejected
ALLOWED_FROM = {
    "found": {"queued"},  # internal: SCC already listed, claim not done; no client activity
    "claimed-unverified": {"queued", "found", "needs-human"},  # internal: listed + claimed, but edits are ID-gated (dnb, t_d13bd638); no client activity
    "created-unlisted": {"queued", "found", "needs-human"},  # internal: the listing EXISTS on the Directory but is not public yet, or is public without full NAP (t_f707b644); In flight, no client activity
    "submitted": {"queued", "found", "needs-human"},
    "pending-verify": {"submitted", "found", "needs-human"},
    "live": {"found", "claimed-unverified", "created-unlisted", "submitted", "pending-verify", "needs-human"},  # needs-human: a row parked for phone/sms/postcard verification goes live once verified
}
ANY_FROM = {"rejected", "needs-human"}
ACTIVITY_SOURCE = "citation_engine"
FLAG = "CE_ACTIVITIES_WRITE"
ACTIVITY_STATES = ("submitted", "pending-verify", "live", "rejected")  # needs-human is internal, never client news
VERIFY_TYPES = ("phone-call", "sms", "postcard", "id-check", "client-email")
# client-email (t_d2f75685, Nate 2026-10-27): the Directory wants the owner to attest the email "belongs directly to the business and is not a proxy or
# agency-controlled address" (showmelocal ACTIVATE). listings@ is ours, so we NEVER attest it. The client's own address is needed: a client gate in the portal.
CLIENT_EMAIL_NOTE = "parked for client verification (client-email): needs the client's own email address; we never attest listings@ as the business's own address"
POSTCARD_DEADLINE_DAYS = 30
VERIFY_UPSERT_PATH = "citation_verification?on_conflict=client_id,directory"


class TransitionRefused(Exception):
    pass


NOTE_ONLY_STATES = ("found", "claimed-unverified", "created-unlisted", "needs-human", "submitted", "pending-verify")  # a same-state move is a note refresh on a waiting row (the weekly recheck names a wrong field); needs a note


REASON_MIN = 10


def check_transition(old, new, note=None, reason=None):
    if new == "queued":   # t_d2f75685: the ONE way back. A rejected listing may be re-created, with a written reason; never a silent reset.
        if old != "rejected":
            raise TransitionRefused("only a rejected row can go back to queued (row is %s)" % (old,))
        if len((reason or "").strip()) < REASON_MIN:
            raise TransitionRefused("rejected -> queued needs --reason (at least %d characters: why a re-create can succeed this time)" % REASON_MIN)
        return
    if reason:
        raise TransitionRefused("--reason only applies to rejected -> queued")
    if new not in STATES:
        raise TransitionRefused("unknown or unsupported target state %r" % (new,))
    if old not in STATES:
        raise TransitionRefused("row has unknown current state %r" % (old,))
    if old == new and new in NOTE_ONLY_STATES and note:
        return
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
    }[new]
    return t % directory


def activities_enabled(explicit=None):
    """Default ON. CE_ACTIVITIES_WRITE=0 (or activities_flag=False) turns it off."""
    return bool(explicit) if explicit is not None else os.environ.get(FLAG) != "0"


def verification_note(verify_type):
    if verify_type == "client-email": return CLIENT_EMAIL_NOTE
    return "parked for client verification (%s)" % verify_type


def check_verify_type(verify_type, new):
    if verify_type in (None, ""):
        return None
    if verify_type not in VERIFY_TYPES:
        raise TransitionRefused("verify type must be one of %s, got %r (a mailbox-link email verification never uses this path; client-email is the client's own address)" % ("/".join(VERIFY_TYPES), verify_type))
    if new != "needs-human":
        raise TransitionRefused("verify type only applies to a needs-human transition")
    return verify_type


ID_CHECK_BAD = re.compile(r"\b(password|passcode)\b", re.I)


def check_id_check_fields(verify_type, steps, directory_url):
    """Mirror the portal DB checks so a bad id-check row is refused here, not by a failed write. steps/directory_url apply to id-check only."""
    if verify_type != "id-check":
        if steps or directory_url: raise TransitionRefused("steps and directory_url only apply to an id-check verification")
        return None, None
    steps = [str(x).strip() for x in (steps or []) if str(x).strip()]
    if not steps: raise TransitionRefused("id-check needs at least one plain-language step for the client")
    if len(steps) > 12 or len("\n".join(steps)) > 3000: raise TransitionRefused("id-check steps: 12 steps and 3000 characters at most")
    if ID_CHECK_BAD.search("\n".join(steps)): raise TransitionRefused("id-check steps must not mention a password or passcode (the client sees them)")
    if directory_url and not re.match(r"^https://\S+$", directory_url): raise TransitionRefused("directory_url must be an https URL with no spaces")
    return steps, (directory_url or None)


def build_verification_record(client_id, directory, verify_type, day, deadline_days=POSTCARD_DEADLINE_DAYS, steps=None, directory_url=None):
    """One citation_verification row. parked_at is left to the table default and never resent, so a re-park does not restart the 14-day clock."""
    r = {"client_id": client_id, "directory": directory, "verification_type": verify_type, "state": "requires_verification"}
    if verify_type == "postcard":
        r["deadline"] = (datetime.date.fromisoformat(day) + datetime.timedelta(days=deadline_days)).isoformat()
    if verify_type == "id-check":
        # Plain instructions the client sees. Never a credential: the portal DB also refuses password/passcode text.
        if steps: r["steps"] = list(steps)
        if directory_url: r["directory_url"] = directory_url
    return r


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


def full_portal_payload(base, q, new_row, day):
    """Snapshot overlay from ALL live / pending-verify / submitted queue rows (each at its own last history date), then the moved row.
    A single transition therefore never drops another row's state from the snapshot (t_bb08988c needed an ad hoc rewrite for this)."""
    if base is None:
        base = {"directories": []}
    payload = base
    for _key, _kind, rows in _row_lists(q):
        for r in rows:
            if r.get("id") == new_row.get("id") or r.get("state") not in Q.LISTING_STATES:
                continue
            hist = r.get("history") or []
            at = (hist[-1].get("at") if hist and isinstance(hist[-1], dict) else None) or day
            payload = Q.overlay_directories(payload, [r], at)
    return Q.overlay_directories(payload, [new_row], day)


def build_activity_record(client_id, row, new, evidence_url, day):
    return {"client_id": client_id, "deliverable_type": "citation", "title": activity_title(new, row["directory"]),
            "date_completed": day, "in_scope": True, "units": 1, "evidence_url": evidence_url,
            "source": ACTIVITY_SOURCE, "source_ref": "citation-transition:%s:%s" % (row["id"], new)}


def record_transition(client, row_id, new_state, evidence_url=None, note=None, *, queue_path=None, today=None, portal=None,
                      dry_run=False, activities=None, activities_flag=None, directories=None, verify_type=None, verification=None,
                      verify_deadline_days=POSTCARD_DEADLINE_DAYS, steps=None, directory_url=None, listing_url=None, listing_id=None, recheck_due=None, reason=None):
    """Returns a dict describing what was (or, in dry_run, would be) written. Refusals raise TransitionRefused before any write.
    portal: object with latest_snapshot(client_id)/upsert_snapshot(...) (default: real Portal from the prod env pointer).
    activities: object with call(method, path, body, prefer) (default: the same Portal).
    verify_type: phone-call|sms|postcard with new_state needs-human; upserts a citation_verification row via `verification` (default: the Portal).
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
    if W.is_stopped(row) and new_state != "needs-human":
        raise TransitionRefused("row %s is STOPPED by the hard-block cap; only Mike's --reset-wall (job/walls.py) clears it" % row_id)
    check_transition(old, new_state, note, reason)
    requeue = new_state == "queued"
    if requeue: note = "re-create after rejection: %s" % reason.strip()   # t_d2f75685: logged, never a silent reset (the history entry also carries requeue + reason)
    evidence_url = check_evidence(evidence_url, new_state)
    verify_type = check_verify_type(verify_type, new_state)
    steps, directory_url = check_id_check_fields(verify_type, steps, directory_url)
    if verify_type: note = verification_note(verify_type)

    approval_before = copy.deepcopy(row.get("mike_approval"))
    new_row = copy.deepcopy(row)
    new_row["state"] = new_state
    if evidence_url: new_row["evidence_url"] = evidence_url
    if old != new_state: new_row.pop("recheck_due", None)   # t_d2f75685: a retry-later marker belongs to the state it was set in
    listing_url = check_evidence(listing_url, "submitted") if listing_url else None   # t_3ac43137: the URL the Directory showed at submit (permalink, owner view or confirmation); plain http(s) only
    if listing_url: new_row["listing_url"] = listing_url
    if recheck_due:   # t_6b1e01ff: the earliest day recheck reads this row (foursquare: 2 days after the edit is sent)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(recheck_due)): raise TransitionRefused("recheck_due must be YYYY-MM-DD")
        new_row["recheck_due"] = str(recheck_due)
    if listing_id and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{2,40}", str(listing_id)): new_row["listing_id"] = str(listing_id)
    entry = {"at": day, "from": old, "to": new_state, "evidence_url": evidence_url, "note": note or None}
    if verify_type: entry["verify_type"] = verify_type  # history carries the type, not only the note text (t_568f1ee6)
    if requeue: entry["requeue"] = True; entry["reason"] = reason.strip()
    if recheck_due: entry["recheck_due"] = str(recheck_due)
    new_row.setdefault("history", [])
    new_row["history"] = list(new_row["history"]) + [entry]
    assert new_row.get("mike_approval") == approval_before  # never touched

    out = {"dry_run": bool(dry_run), "row_id": row_id, "from": old, "to": new_state, "history_entry": entry, "errors": []}
    same_state = old == new_state  # note refresh: no client news, no Activities row
    rec = build_activity_record(client_id, new_row, new_state, evidence_url, day) if new_state in ACTIVITY_STATES and not same_state else None
    out["activity_record"] = rec
    out["activities_written"] = False
    use_act = activities_enabled(activities_flag) and new_state in ACTIVITY_STATES and not same_state
    out["activities_flag_on"] = use_act
    ver_rec = build_verification_record(client_id, row["directory"], verify_type, day, verify_deadline_days, steps=steps, directory_url=directory_url) if verify_type else None
    out["verification_record"] = ver_rec
    out["verification_written"] = False
    ver_patch_path = "citation_verification?client_id=eq.%s&directory=eq.%s&state=eq.requires_verification" % (client_id, row["directory"])

    if dry_run:
        pp = portal_payload_for(None, new_row, day)
        out["queue_row_after"] = {k: new_row[k] for k in ("id", "directory", "state", "evidence_url", "history") if k in new_row}
        out["portal_request"] = {"method": "POST", "path": "footprint_snapshot?on_conflict=client_id,source,captured_day",
                                 "row": {"client_id": client_id, "source": P.SOURCE, "captured_day": day,
                                         "payload": "latest snapshot payload, directories patched with:",
                                         "directory_patch": pp["directories"]}}
        out["activities_request"] = ({"method": "POST", "path": "deliverables?on_conflict=client_id,source_ref", "body": [rec]} if use_act
                                     else "skipped: %s=0 or state %s is not client news" % (FLAG, new_state))
        out["verification_request"] = (
            {"method": "POST", "path": VERIFY_UPSERT_PATH, "body": [ver_rec]} if ver_rec else
            {"method": "PATCH", "path": ver_patch_path, "body": {"state": "live", "verified_at": "<now>"}} if new_state == "live"
            else "skipped: no verification step")
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
        portal.upsert_snapshot(client_id, day, full_portal_payload(base, q, new_row, day))
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

    # 3b verification queue (phone/sms/postcard). Never blocks the queue write above.
    if ver_rec or new_state == "live":
        try:
            ver = verification or portal or P.Portal(*P.load_portal_env())
            if ver_rec:
                ver.call("POST", VERIFY_UPSERT_PATH, [ver_rec], prefer="resolution=ignore-duplicates,return=minimal")  # existing row untouched: no deadline restart, a live row is not flipped back
            else:
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                ver.call("PATCH", ver_patch_path, {"state": "live", "verified_at": now, "updated_at": now}, prefer="return=minimal")
            out["verification_written"] = True
        except Exception as e:
            out["errors"].append("verification: %s" % e)

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
    a.add_argument("--verify-type", default=None, choices=VERIFY_TYPES, help="needs-human only: stopped at a phone call, SMS or postcard; writes the portal verification queue")
    a.add_argument("--step", action="append", default=None, help="id-check only: one plain instruction for the client (repeat per step)")
    a.add_argument("--directory-url", default=None, help="id-check only: the https page where the owner does the check")
    a.add_argument("--queue", default=None)
    a.add_argument("--dry-run", action="store_true", help="no queue write, no network; print the payloads")
    a.add_argument("--today", default=None)
    a.add_argument("--reason", default=None, help="rejected -> queued only: why a re-create can succeed this time (10+ characters; logged in the row history)")
    a.add_argument("--recheck-due", default=None, help="YYYY-MM-DD: batch tools skip this row until that day (retry later, e.g. a Directory sender limit)")
    n = a.parse_args(argv)
    try:
        res = record_transition(n.client, n.row, n.new_state, n.evidence, n.note, queue_path=n.queue, today=n.today, dry_run=n.dry_run, verify_type=n.verify_type, steps=n.step, directory_url=n.directory_url, reason=n.reason, recheck_due=n.recheck_due)
    except (TransitionRefused, Q.QueueError, P.PortalWriteError) as e:
        print("REFUSED: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2))
    return 2 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
