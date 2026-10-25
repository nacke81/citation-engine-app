"""Fill signup_url / claim_url on queue rows from the batch-1 playbooks (t_568f1ee6). Only those two fields, only when empty.
state, history, approval and every other field are untouched. Backup (.bak-<date>-signup-urls) before any write; atomic write; idempotent.
  python job/signup_urls.py [--queue PATH] [--dry-run]"""
import os, sys, json, shutil, tempfile, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# row id -> (field, url). Source: Obsidian playbooks/build/<directory>.md, batch 1.
URLS = {
    "create-bbb":       ("signup_url", "https://www.bbb.org/get-listed/form"),
    "fix-merchantcircle": ("claim_url", "https://www.merchantcircle.com/signup?business=senior-care-consulting-solutions-madisonville-ky&claiming=True"),
    "create-ezlocal":   ("signup_url", "https://ezlocal.com/free-business-listing/"),
    "create-brownbook": ("signup_url", "https://www.brownbook.net/add-business"),
}


def _rows(q):
    for k in ("fix_queue", "create_rows"):
        for r in q.get(k) or []: yield r
    cq = q.get("create_queue")
    if isinstance(cq, dict):
        for r in cq.get("rows") or []: yield r


def fill(q):
    """Mutates q. Returns [(row_id, field)] actually set. An existing non-empty value is never overwritten."""
    done = []
    for r in _rows(q):
        if r.get("id") in URLS:
            f, u = URLS[r["id"]]
            if not r.get(f): r[f] = u; done.append((r["id"], f))
    return done


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(); a.add_argument("--queue", default=None); a.add_argument("--dry-run", action="store_true")
    n = a.parse_args(argv)
    import buildqueue as Q
    path = n.queue or Q.QUEUE_PATH
    q = json.load(open(path, encoding="utf-8"))
    done = fill(q)
    print("set:", done)
    if not done or n.dry_run: return 0
    bak = "%s.bak-%s-signup-urls" % (path, datetime.date.today().isoformat())
    shutil.copy2(path, bak); print("backup:", bak)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(q, f, indent=2); f.write("\n")
    os.replace(tmp, path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
