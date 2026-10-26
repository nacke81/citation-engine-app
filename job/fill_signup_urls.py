"""Fill signup_url / claim_url on the queue rows that still have none (t_64c4d511). Builds on signup_urls.py (batch 1: bbb, merchantcircle, ezlocal, brownbook).
Only those two fields, only when empty. state, history, approval and every other field are untouched. Backup (.bak-<date>-fill-signup-urls) before any write;
atomic write; idempotent. A URL must be plain https with no credentials. No network: the sources are the playbook files (Obsidian playbooks/build/<domain>.md,
copied here as data) and create_discovery.CREATE_DIRS (signup URLs re-read by GET on 2026-10-19).

  python job/fill_signup_urls.py [--queue PATH] [--dry-run]
"""
import datetime, json, os, shutil, sys, tempfile
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import signup_urls as S

# directory domain -> (field, url). Playbook files win over CREATE_DIRS. Entries are the signup/claim entry the playbook recorded, not a search page.
PLAYBOOK_URLS = {
    "bbb.org":            ("signup_url", "https://www.bbb.org/get-listed/form"),          # bbb.org.md: "Add It Now" href
    "ezlocal.com":        ("signup_url", "https://ezlocal.com/free-business-listing/"),   # ezlocal.com.md step 2
    "brownbook.net":      ("signup_url", "https://www.brownbook.net/add-business"),       # brownbook.net.md step 3
    "yelp.com":           ("signup_url", "https://biz.yelp.com/signup_business/new"),     # yelp.com.md
    "bizapedia.com":      ("signup_url", "https://www.bizapedia.com/company-add.aspx"),   # t_64c4d511: Add My Company form; claim of an existing page is /company-claim.aspx?companyid=<id from the Claim Profile button>
}
# merchantcircle: claim_url is built from the row's own listing_url slug (signup_urls.merchantcircle_claim), so no identity text lives in the repo.


def https_ok(u):
    s = urlsplit(u or "")
    return s.scheme == "https" and bool(s.netloc) and "@" not in s.netloc


def _create_dirs(db=None):
    """domain -> signup_url from create_discovery.CREATE_DIRS, then (if db is given) from ce_directories (our own database, GET only). The database wins only where CREATE_DIRS has none."""
    out = {}
    try:
        import create_discovery as CD
        out = {k: v.get("signup_url") for k, v in CD.CREATE_DIRS.items()}
    except Exception:
        pass
    if db is not None:
        for r in db.call("GET", "ce_directories?select=domain,signup_url&signup_url=not.is.null&limit=1000", None, "return=representation") or []:
            if r.get("signup_url") and not out.get(r["domain"]): out[r["domain"]] = r["signup_url"]
    return out


def plan_for(row, create_dirs):
    """-> (field, url) for a row, or None. Existing non-empty values are never replaced."""
    d = row.get("directory")
    if d == "merchantcircle.com":
        u = S.merchantcircle_claim(row.get("listing_url"))
        return ("claim_url", u) if u and not row.get("claim_url") and https_ok(u) else None
    if row.get("signup_url"):
        return None
    if d in PLAYBOOK_URLS:
        f, u = PLAYBOOK_URLS[d]
    elif create_dirs.get(d):
        f, u = "signup_url", create_dirs[d]
    else:
        return None
    return (f, u) if https_ok(u) and not row.get(f) else None


def fill(q, create_dirs=None):
    """Mutates q. Returns [(row_id, field, url)] set. A kind=fix row with a listing_url is claimed on the listing, so it gets no signup_url."""
    cd = _create_dirs() if create_dirs is None else create_dirs
    done = []
    for r in S._rows(q):
        if r.get("kind") == "fix" and r.get("directory") != "merchantcircle.com":
            continue
        p = plan_for(r, cd)
        if p:
            r[p[0]] = p[1]; done.append((r["id"], p[0], p[1]))
    return done


def write_atomic(path, q):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(q, f, indent=2); f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp): os.unlink(tmp)
        raise


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Fill empty signup_url / claim_url on queue rows from the playbooks")
    a.add_argument("--queue", default=None); a.add_argument("--dry-run", action="store_true")
    a.add_argument("--from-db", action="store_true", help="also read signup_url from ce_directories (GET only)")
    n = a.parse_args(argv)
    import buildqueue as Q
    path = n.queue or Q.QUEUE_PATH
    q = json.load(open(path, encoding="utf-8"))
    rows = list(S._rows(q))
    empty_before = sum(1 for r in rows if not r.get("signup_url") and not r.get("claim_url"))
    db = None
    if n.from_db:
        import directories as D; db = D.DirDB()
    done = fill(q, _create_dirs(db))
    empty_after = sum(1 for r in rows if not r.get("signup_url") and not r.get("claim_url"))
    print("rows %d; empty before %d; filled %d; empty after %d" % (len(rows), empty_before, len(done), empty_after))
    for rid, f, u in done: print("  %-28s %-10s %s" % (rid, f, u))
    if not done or n.dry_run: return 0
    bak = "%s.bak-%s-fill-signup-urls" % (path, datetime.date.today().isoformat())
    shutil.copy2(path, bak); print("backup:", bak)
    write_atomic(path, q)
    return 0


if __name__ == "__main__":
    sys.exit(main())
