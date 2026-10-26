"""Hard-block retry cap (t_fccbb7ef). "Sorry, you have been blocked" (Cloudflare 403 + Ray ID): 1 try per calendar day, 3 tries, then STOPPED
until Mike resets it with `python job/walls.py --reset-wall <row>`.

A try is a history entry {wall: "hard-block", try: N, at: date, ray_id, note}. Tries are counted since the last reset entry.
  check_try(row, today)   raises WallRefused for a stopped row, a 2nd try on the same day, or a 4th try
  record_try(...)         check_try, then append the entry; try 3 also sets state needs-human + note STOP_NOTE
  gate(q, directory, day) refusal text (or None) that runners check BEFORE touching a Directory
  reset_wall(...)         the only thing that clears the stop (CLI only)
"""
import datetime, json, os, re, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WALL = "hard-block"
MAX_TRIES = 3
STOP_NOTE = "WALL:hard-block STOPPED, waiting on Mike"
BLOCK_RX = re.compile(r"(?i)you have been blocked")
RAY_RX = re.compile(r"(?i)ray id:?\s*(?:</?\w+>|\s)*([0-9a-f]{12,20})")


class WallRefused(Exception):
    pass


def _hist(row):
    return [h for h in (row.get("history") or []) if isinstance(h, dict) and h.get("wall") == WALL]


def tries(row):
    """Hard-block try entries since the last reset."""
    out = []
    for h in _hist(row):
        if h.get("reset"): out = []
        elif h.get("try"): out.append(h)
    return out


def is_stopped(row):
    return len(tries(row)) >= MAX_TRIES


def check_try(row, today):
    t = tries(row)
    if len(t) >= MAX_TRIES:
        raise WallRefused("%s is STOPPED after %d hard-block tries; only Mike's --reset-wall clears it" % (row.get("id"), MAX_TRIES))
    if t and t[-1].get("at") == today:
        raise WallRefused("%s already had hard-block try %d today (%s); one try per day" % (row.get("id"), t[-1]["try"], today))
    return len(t) + 1


def parse_ray_id(text):
    m = RAY_RX.search(text or "")
    return m.group(1).lower() if m else None


def is_block_text(text):
    return bool(BLOCK_RX.search(text or ""))


def record_try(row, today=None, ray_id=None):
    """Mutates row (history, and state/note on try 3). Returns the entry. Refusals raise before anything changes."""
    day = today or datetime.date.today().isoformat()
    n = check_try(row, day)
    old = row.get("state")
    entry = {"wall": WALL, "try": n, "at": day, "ray_id": ray_id, "from": old, "to": old, "evidence_url": None,
             "note": "WALL:hard-block try %d/%d" % (n, MAX_TRIES)}
    if n >= MAX_TRIES:
        entry["to"] = "needs-human"; entry["note"] = STOP_NOTE; row["state"] = "needs-human"
    row["history"] = list(row.get("history") or []) + [entry]
    return entry


def reset_wall(row, today=None):
    day = today or datetime.date.today().isoformat()
    if not _hist(row):
        raise WallRefused("%s has no hard-block history to reset" % row.get("id"))
    entry = {"wall": WALL, "reset": True, "at": day, "from": row.get("state"), "to": row.get("state"), "evidence_url": None,
             "note": "WALL:hard-block reset by Mike"}
    row["history"] = list(row.get("history") or []) + [entry]
    return entry


def _rows(q):
    import transitions as T
    return [r for _k, _kind, rows in T._row_lists(q) for r in rows]


def gate(q, directory, today=None):
    """None = fine to touch the Directory. Otherwise the log line for the skip. Covers every queue row for that Directory."""
    day = today or datetime.date.today().isoformat()
    for r in _rows(q):
        if r.get("directory") != directory: continue
        try: check_try(r, day)
        except WallRefused as e: return "SKIP %s: %s" % (directory, e)
    return None


def _read(path):
    with open(path, encoding="utf-8") as f: return json.load(f)


def _write_atomic(path, data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2); f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp): os.unlink(tmp)
        raise


def _find(q, row_id):
    for r in _rows(q):
        if r.get("id") == row_id: return r
    raise WallRefused("no queue row with id %r" % (row_id,))


def record_try_in_queue(path, row_id, today=None, ray_id=None):
    q = _read(path); e = record_try(_find(q, row_id), today, ray_id); _write_atomic(path, q); return e


def reset_in_queue(path, row_id, today=None):
    q = _read(path); e = reset_wall(_find(q, row_id), today); _write_atomic(path, q); return e


def main(argv=None):
    import argparse, buildqueue as Q
    a = argparse.ArgumentParser(description="Hard-block retry cap: record a try, or (Mike only) reset a stopped row")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--record-try", metavar="ROW", help="a hard block just answered this row: log try N/3")
    g.add_argument("--reset-wall", metavar="ROW", help="Mike only: clear the STOPPED state and the try count")
    a.add_argument("--ray-id", default=None)
    a.add_argument("--queue", default=None)
    a.add_argument("--today", default=None)
    n = a.parse_args(argv)
    path = n.queue or Q.QUEUE_PATH
    try:
        e = reset_in_queue(path, n.reset_wall, n.today) if n.reset_wall else record_try_in_queue(path, n.record_try, n.today, n.ray_id)
    except WallRefused as ex:
        print("REFUSED: %s" % ex, file=sys.stderr); return 1
    print(json.dumps(e, indent=2)); return 0


if __name__ == "__main__":
    sys.exit(main())
