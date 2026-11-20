"""NM queue state writer (kanban t_00a75d04 r2). The ONE writer for NM queue HISTORY from a build run (no portal). A park (needs-human + --verify-type: Your turn row + Verify Now allowlist) goes through `transitions.py --client NM` (t_cb7bad04), never here, so nothing writes twice.

  python job/nm_transitions.py --row nm-fix-bbb --to skipped --note "ruling: why" [--clear-recheck]   (t_5ddb67a4: `skipped` is terminal, NM only, from needs-human / pending-verify / queued; clears recheck_due; no batch tool reads it again.)
  --clear-recheck drops the old recheck_due on a park with no new date (explicit flag, never implicit); refused with --recheck-due.
  python job/nm_transitions.py --row nm-fix-bbb --to submitted --note "submitted via build queue" [--evidence URL] [--listing-url URL] [--queue PATH] [--dry-run]

Same state matrix as transitions.check_transition (queued -> submitted, submitted -> pending-verify/live, ... ), a history entry with a note on every move,
a per-write .bak-nm-<YYYYMMDD-HHMMSS>[-n] backup of the file (plus the daily .bak-nm-<day> if absent) and an atomic write. It writes the NM queue file ONLY: no portal, no Activities, no Local SEO,
no Directory database, never the SCC queue. Refused before any write: a queue file that is not nm-fix-queue.json, a row id that is not an `nm-` row or does
not exist, a client other than NM, a missing note, a move the matrix refuses. `approval` and `mike_approval` are never touched.
buildqueue.submit_row(live=True) calls record_transition("NM", ...) here by default for an NM row.
"""
import argparse, copy, datetime, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buildqueue as Q
import transitions as T

NM_QUEUE_NAME = "nm-fix-queue.json"
DEFAULT_NM_QUEUE = os.environ.get("CE_NM_QUEUE") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/queue/" + NM_QUEUE_NAME)


SKIP_FROM = ("needs-human", "pending-verify", "queued")   # NM "pending" = pending-verify, NM "new" = queued


class NMTransitionRefused(T.TransitionRefused):
    pass


def record_transition(client, row_id, new_state, evidence_url=None, note=None, *, queue_path=None, today=None, dry_run=False,
                      listing_url=None, listing_id=None, recheck_due=None, reason=None, refresh_url=False, clear_recheck=False,
                      side_effects=False, portal=None, activities=None, verification=None, activities_flag=None, **unsupported):
    """Same call shape as transitions.record_transition for the arguments a build records. Returns {"dry_run", "row_id", "from", "to", "history_entry", "backup"}."""
    if client != "NM":
        raise NMTransitionRefused("this writer is NM only, got %r (SCC rows go through transitions.py)" % (client,))
    if unsupported:
        raise NMTransitionRefused("not supported on NM rows: %s" % ", ".join(sorted(unsupported)))
    path = queue_path or DEFAULT_NM_QUEUE
    if os.path.basename(path) != NM_QUEUE_NAME:
        raise NMTransitionRefused("only %s can be written, got %s" % (NM_QUEUE_NAME, os.path.basename(path)))
    if not Q.is_nm_row({"id": row_id}):
        raise NMTransitionRefused("%s is not an NM row (ids start %s)" % (row_id, Q.NM_ROW_PREFIX))
    if not (note or "").strip():
        raise NMTransitionRefused("a history note is required")
    day = today or datetime.date.today().isoformat()
    q = T._read(path)
    Q.parse_rows(q)
    row = T._find(q, row_id)
    old = row["state"]
    if clear_recheck and recheck_due:
        raise NMTransitionRefused("--clear-recheck and --recheck-due together: pick one")
    if new_state == Q.SKIPPED:   # t_5ddb67a4: terminal, NM only. T.STATES stays closed, so the SCC writer still refuses it; a skipped row has no way out (old not in STATES)
        if old not in SKIP_FROM:
            raise NMTransitionRefused("transition %s -> skipped is not allowed (from %s only)" % (old, ", ".join(SKIP_FROM)))
        if reason or refresh_url:
            raise NMTransitionRefused("--reason / --refresh-url do not apply to skipped")
        if recheck_due:
            raise NMTransitionRefused("a skipped row has no recheck date")
    else:
        T.check_transition(old, new_state, note, reason, refresh_url)
    evidence_url = T.check_evidence(evidence_url, new_state)
    listing_url = T.check_evidence(listing_url, "submitted") if listing_url else None
    guard = (copy.deepcopy(row.get("approval")), copy.deepcopy(row.get("mike_approval")))
    new_row = row   # rows are mutated in place inside q, so the whole file is written back
    new_row["state"] = new_state
    if evidence_url: new_row["evidence_url"] = evidence_url
    if listing_url: new_row["listing_url"] = listing_url
    if listing_id: new_row["listing_id"] = str(listing_id)
    if old != new_state or clear_recheck or new_state == Q.SKIPPED: new_row.pop("recheck_due", None)   # --clear-recheck: a dateless park drops the old date
    if recheck_due:
        import re
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(recheck_due)): raise NMTransitionRefused("recheck_due must be YYYY-MM-DD")
        new_row["recheck_due"] = str(recheck_due)
    entry = {"at": day, "from": old, "to": new_state, "evidence_url": evidence_url, "note": note.strip()}
    if recheck_due: entry["recheck_due"] = str(recheck_due)
    new_row["history"] = list(new_row.get("history") or []) + [entry]
    assert (new_row.get("approval"), new_row.get("mike_approval")) == guard   # never touched
    out = {"dry_run": bool(dry_run), "row_id": row_id, "from": old, "to": new_state, "history_entry": entry, "backup": None}
    if dry_run:
        return out
    out["backup"] = backup_before_write(path, day)
    T._write_atomic(path, q)
    prune_backups(path, keep_path=out["backup"])
    out["errors"] = []
    if side_effects or portal or activities or verification:   # t_2211682c: the portal half (Activities row, Your turn row closed on live). Opt-in so a bare call in a test never reaches a portal; the CLI and the build path turn it on.
        fx = T.queue_move_effects("NM", new_row, new_state, evidence_url, day, portal=portal, activities=activities, verification=verification, activities_flag=activities_flag)
        out.update(fx)
    return out


def backup_before_write(path, day):
    """Per-write pre-write backup (t_9cc92bf1). Copies the queue as it is RIGHT NOW to `<path>.bak-nm-<YYYYMMDD-HHMMSS>[-n]`, created exclusively
    so an earlier backup is never reused or clobbered, and returns that path (always a file this call created). The daily
    `<path>.bak-nm-<day>` (other tools and tests look for it) is still kept: created if absent, never reported."""
    daily = "%s.bak-nm-%s" % (path, day)
    if not os.path.exists(daily):
        shutil.copyfile(path, daily)
    with open(path, "rb") as f:
        data = f.read()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    n = 0
    while True:
        backup = "%s.bak-nm-%s%s" % (path, stamp, "" if n == 0 else "-%d" % n)
        try:
            fh = open(backup, "xb")
        except FileExistsError:
            n += 1
            continue
        with fh:
            fh.write(data)
        return backup


NM_BACKUP_KEEP = 50   # t_13adf93c: per-write backups kept per queue file


def prune_backups(path, keep_path=None, keep=None):
    """Call AFTER a successful atomic write. Keeps the newest NM_BACKUP_KEEP per-write backups of `path` and deletes older ones.
    Only names matching exactly `<queue>.bak-nm-YYYYMMDD-HHMMSS[-n]` are candidates: never the daily `.bak-nm-<day>`, a `.bak-t_*` card
    backup or any other file. Never deletes `keep_path` (the backup this call reported). Any error goes to stderr and never fails the write."""
    keep = NM_BACKUP_KEEP if keep is None else keep
    try:
        d, base = os.path.split(path)
        pat = re.compile(r"^" + re.escape(base) + r"\.bak-nm-(\d{8})-(\d{6})(?:-(\d+))?$")
        found = []
        for name in os.listdir(d or "."):
            m = pat.match(name)
            if m: found.append(((m.group(1), m.group(2), int(m.group(3) or 0)), os.path.join(d, name)))
        found.sort()
        victims = found[:-keep] if keep > 0 else found
        for _k, f in victims:
            if keep_path and os.path.abspath(f) == os.path.abspath(keep_path): continue
            try: os.remove(f)
            except OSError as e: print("backup prune: could not remove %s: %s" % (f, e), file=sys.stderr)
    except Exception as e:
        print("backup prune failed (write kept): %s" % e, file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--row", required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--note", required=True)
    ap.add_argument("--evidence")
    ap.add_argument("--listing-url")
    ap.add_argument("--listing-id")
    ap.add_argument("--recheck-due")
    ap.add_argument("--clear-recheck", action="store_true", help="drop the row's old recheck_due (a park with no new date); refused with --recheck-due")
    ap.add_argument("--queue", default=DEFAULT_NM_QUEUE)
    ap.add_argument("--dry-run", action="store_true")
    n = ap.parse_args(argv)
    try:
        res = record_transition("NM", n.row, n.to, n.evidence, n.note, queue_path=n.queue, dry_run=n.dry_run,
                                listing_url=n.listing_url, listing_id=n.listing_id, recheck_due=n.recheck_due, clear_recheck=n.clear_recheck, side_effects=not n.dry_run)
    except (T.TransitionRefused, Q.QueueError) as e:
        print("REFUSED: %s" % e); return 2
    print(json.dumps(res, indent=2))
    for e in res.get("errors") or []: print("FAILED STEP: %s (the queue row IS written; fix the portal and re-run the portal step)" % e, file=sys.stderr)   # t_2211682c: fail loud
    return 3 if res.get("errors") else 0


if __name__ == "__main__":
    sys.exit(main())
