"""Nate's release of NM queue rows (kanban t_00a75d04). No Mike gate on NM citations (plan 11/10); Nate's card is the go.

  python job/release.py --release nm-fix-bbb nm-fix-n49 --card t_76ce8d3c [--queue PATH] [--dry-run]

Stamps `approval: {by: "nate", card, at, row_id}` on the named rows of the NM queue file (nm-fix-queue.json) and nothing else: state, history and
mike_approval are never touched. buildqueue.submit_row accepts that stamp on NM rows only (buildqueue.nate_approval_ok).
Refused before any write: a queue file that is not nm-fix-queue.json, a row id that is not an `nm-` row or does not exist, a card id that is not t_<id>,
a row that already carries a DIFFERENT card's release (re-releasing the same card is a no-op). The file is backed up as <name>.bak-<card> (first write
only) and written atomically. This command contacts no Directory, no portal and no network.
"""
import argparse, datetime, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buildqueue as Q
import transitions as T

NM_QUEUE_NAME = "nm-fix-queue.json"
DEFAULT_NM_QUEUE = os.environ.get("CE_NM_QUEUE") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/queue/" + NM_QUEUE_NAME)


class ReleaseRefused(Exception):
    pass


def release(path, ids, card, now=None, write=True):
    """-> {"released": [ids stamped], "unchanged": [ids already stamped by this card], "backup": path|None}. Raises ReleaseRefused before any write."""
    if os.path.basename(path) != NM_QUEUE_NAME:
        raise ReleaseRefused("release only works on %s, got %s" % (NM_QUEUE_NAME, os.path.basename(path)))
    if not (isinstance(card, str) and card.startswith("t_") and len(card) > 2 and card.replace("_", "").isalnum()):
        raise ReleaseRefused("--card must be a Kanban card id like t_76ce8d3c, got %r" % (card,))
    ids = list(dict.fromkeys(ids or []))
    if not ids:
        raise ReleaseRefused("name at least one row id")
    q = T._read(path)
    rows = {r.get("id"): r for r in Q.all_rows(q)}
    for rid in ids:
        if not Q.is_nm_row({"id": rid}):
            raise ReleaseRefused("%s is not an NM row (ids start %s)" % (rid, Q.NM_ROW_PREFIX))
        if rid not in rows:
            raise ReleaseRefused("no such row %s in %s" % (rid, NM_QUEUE_NAME))
        old = rows[rid].get("approval")
        if isinstance(old, dict) and old.get("card") not in (None, card):
            raise ReleaseRefused("row %s is already released by %s; not overwritten" % (rid, old.get("card")))
    at = (now or datetime.datetime.now().astimezone()).isoformat(timespec="seconds")
    released, unchanged = [], []
    for rid in ids:
        r = rows[rid]
        old = r.get("approval")
        if isinstance(old, dict) and old.get("card") == card and old.get("by") == "nate" and old.get("row_id") == rid:
            unchanged.append(rid); continue
        r["approval"] = {"by": "nate", "card": card, "at": at, "row_id": rid}
        released.append(rid)
    backup = None
    if write and released:
        backup = path + ".bak-" + card
        if not os.path.exists(backup):
            shutil.copyfile(path, backup)
        T._write_atomic(path, q)
    return {"released": released, "unchanged": unchanged, "backup": backup, "dry_run": not write}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", nargs="+", required=True, metavar="ROW_ID")
    ap.add_argument("--card", required=True, help="the Kanban card that is Nate's go, e.g. t_76ce8d3c")
    ap.add_argument("--queue", default=DEFAULT_NM_QUEUE)
    ap.add_argument("--dry-run", action="store_true", help="show what would be stamped; write nothing")
    n = ap.parse_args(argv)
    try:
        res = release(n.queue, n.release, n.card, write=not n.dry_run)
    except (ReleaseRefused, Q.QueueError) as e:
        print("REFUSED: %s" % e); return 2
    print(json.dumps(res, indent=2)); return 0


if __name__ == "__main__":
    sys.exit(main())
