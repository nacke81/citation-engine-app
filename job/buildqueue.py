"""SCC fix/create queue: portal overlay + gated one-row submit (DRY RUN ONLY).

This module makes no outbound calls of any kind. A live Directory adapter does not exist.
submit_row refuses unless the row carries a Mike approval recorded for that exact row id, and unless the login can be read from
Vaultwarden at run time (injected getter; missing or failing -> refuse). SCC only.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
# The real queue holds the client's identity, so it lives outside the repo (like the identity file). Tests point CE_QUEUE at a placeholder fixture.
QUEUE_PATH = os.environ.get("CE_QUEUE") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/queue/scc-fix-create-queue.json")
LISTING_STATES = ("live", "pending-verify", "submitted", "created-unlisted")
PORTAL_STATES = ("submitted", "pending-verify", "needs-human", "live", "rejected")
# found = SCC is already listed and the claim is not done. Internal only: the client sees needs-human, like queued.
# claimed-unverified = found and claimed (free account linked) but edits are ID-gated (D&B). Internal like found; the client sees needs-human.
# created-unlisted = the listing exists but is not public yet / lacks full NAP (t_f707b644). The portal already has `submitted` (In flight), so it maps there: no portal enum change.
QUEUE_TO_PORTAL = {"queued": "needs-human", "found": "needs-human", "claimed-unverified": "needs-human", "created-unlisted": "submitted"}
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


def all_rows(q):
    """Every queue row in every list: fix_queue, create_rows AND create_queue.rows (t_3ac43137: `--row create-acompio` lives in create_queue.rows,
    which parse_rows does not read). Validates the same way parse_rows does."""
    cq = q.get("create_queue")
    cq_rows = cq.get("rows") if isinstance(cq, dict) else (cq if isinstance(cq, list) else [])
    return parse_rows(dict(q, create_rows=list(q.get("create_rows") or []) + list(cq_rows or [])))


def load_all_rows(path=None):
    with open(path or QUEUE_PATH, encoding="utf-8") as f:
        return all_rows(json.load(f))


def overlay_directories(payload, rows, day):
    """Return a copy of an SCC payload with queue state shown on each queued Directory, needs-human split into nap-fix / blocked, and `summary` recounted from the rows."""
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
        if st == "needs-human":   # t_f6267312: the snapshot never shows the overloaded state: nap-fix (listing exists) or blocked (no listing yet)
            import snapshot as SN
            st = SN.classify_needs_human(r, d)
        d["state"], d["stateDate"] = st, day
        if st != "live" and d.get("urlKind") != "listing":
            d["url"] = None  # a resolved listing permalink is kept; anything else is cleared
        if str(r.get("id", "")).startswith("create-") and st in LISTING_STATES and d.get("urlKind") != "listing":
            import listing  # a create row carries its evidence URL; shown only when it is a listing permalink (never search / signup / success)
            ev = r.get("evidence_url")
            if ev and listing.is_permalink(r["directory"], ev):
                d["url"], d["urlKind"] = ev, "listing"
        if st == "live" and r.get("nap_check"):
            import snapshot as SN
            SN.apply_nap_check(d, r["nap_check"])   # the stored read of the listing page, written by recheck
    import snapshot as SN
    return SN.finalize(out)   # summary recounted from the rows on every write


# t_03a74bae: no account, no vault item. The Directory tells us only by mail to listings@, so mail_scan.py is the ONLY status path: no owner read is ever planned.
MAIL_ONLY = ("discoverourtown.com", "loc8nearme.com")


def is_mail_only(directory_or_row):
    """True for a mail-only Directory (domain, or a queue row naming one, or a row carrying `status_path: mail-only`)."""
    if isinstance(directory_or_row, dict):
        return directory_or_row.get("status_path") == "mail-only" or is_mail_only(directory_or_row.get("directory"))
    h = (directory_or_row or "").lower()
    return any(h == d or h.endswith("." + d) for d in MAIL_ONLY)


def status_path(row):
    """'mail-only' | 'public+owner'. Batch tools plan an owner read only for rows that are not mail-only."""
    return "mail-only" if is_mail_only(row) else "public+owner"


def owner_read_rows(rows):
    """The rows a batch may plan an owner read (login + dashboard) for. Mail-only rows are never in it."""
    return [r for r in rows if not is_mail_only(r)]


def not_due(row, today=None):
    """recheck_due (YYYY-MM-DD) on a row = retry later (t_6b1e01ff foursquare edit review; t_d2f75685 citylocalpro 24h sender limit).
    Returns the due date while it is still in the future, else None. Batch tools skip such a row; a row NAMED by id on the command line is still worked."""
    due = (row or {}).get("recheck_due")
    import datetime
    day = today or datetime.date.today().isoformat()
    return str(due) if due and str(due) > str(day) else None


def approval_ok(row):
    a = row.get("mike_approval")
    return isinstance(a, dict) and a.get("approved_by") == "mike" and bool(a.get("at")) and a.get("row_id") == row.get("id")


LIVE_FROM = ("queued", "found", "needs-human")   # states the transition matrix lets move to submitted


def submit_row(row, get_login, free_only=True, record=None, live=False, to="submitted", captured_url=None, captured_id=None, recheck_due=None):
    """One submit. live=False (default) is a DRY RUN: returns the intended transition, never records unless CE_RECORD_TRANSITIONS=1 or record= is given.
    live=True is build_runner --live after the Directory build succeeded (t_df278575): the same refusals apply, a queued/found/needs-human row may move,
    and the `submitted` transition is recorded by default (no env flag). Refusals raise before anything is recorded. This function itself never contacts a Directory."""
    if not approval_ok(row):
        raise SubmitRefused("no Mike approval recorded for row %s" % row.get("id"))
    if to not in ("submitted", "created-unlisted"): raise SubmitRefused("a build records submitted or created-unlisted, not %r" % (to,))
    if row.get("state") != "queued" and not (live and row.get("state") in LIVE_FROM):
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
    res = {"id": row["id"], "dry_run": not live, "directory": row["directory"], "field": row.get("wrong_field"), "to": row.get("right_value"), "next_state": to}
    # Success path: record the submitted state (queue + Local SEO + gated Activities). submit_row is still a dry run (no Directory adapter
    # exists), so recording is opt-in via CE_RECORD_TRANSITIONS=1 or an injected record(); once a live adapter lands, flip the default.
    if record is None and (live or os.environ.get("CE_RECORD_TRANSITIONS") == "1"):
        import transitions
        record = transitions.record_transition
    if record:
        note = "submitted via build queue" if to == "submitted" else "created via build queue; not public yet or NAP incomplete"
        extra = {}
        if captured_url: extra["listing_url"] = captured_url   # t_3ac43137: the confirmation / owner-view / permalink URL the Directory showed at submit
        if captured_id: extra["listing_id"] = captured_id
        if recheck_due: extra["recheck_due"] = recheck_due
        res["recorded"] = record("SCC", row["id"], to, row.get("listing_url"), note, **extra)
    return res
