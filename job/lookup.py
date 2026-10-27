"""Public-search lookup for rows with no permalink (t_89f4aebf, batch 20 problem 4).

  python job/lookup.py [--queue PATH] [--row ID ...] [--set-url]

For each named (or every no-permalink waiting) row it searches the Directory's OWN public search by name + city, SIGNED OUT (recheck.SignedOutReader: its own
throwaway Chrome, never CDP 9333, never the build profile), opens each same-host permalink-shaped result and reports the first whose NAP reads `match`
(recheck.read_listing: the one read path). Per row: FOUND <url> | NOT FOUND | SEARCH WALLED. --set-url writes listing_url through transitions.record_transition
as a same-state note refresh (no state change, never live; the batch does the recheck --write). Reads only otherwise: no form is submitted, no login.
"""
import os, re, sys
from urllib.parse import quote, urlparse
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import recheck as R

# directory -> search URL builder (name, "City, ST") and the shape of a record page on that host. Shapes were read on the live sites 2026-10-27.
REFERER = {"businessyab.com": "https://www.businessyab.com/"}   # the search 403s ("Please back to home page") without it


SEARCH = {
    "loc8nearme.com": dict(url=lambda n, loc: "https://www.loc8nearme.com/search/?query=%s&place=%s&sort_by=rating" % (quote(n), quote(loc)),
                           permalink=r"^/[a-z\-.]+/[a-z\-.]+/[a-z0-9\-.]+/\d+/?$"),
    "businessyab.com": dict(url=lambda n, loc: "https://www.businessyab.com/explore/?page=1&where=%s&what=%s" % (quote(loc + ", United States"), quote(n)),
                            permalink=r"^/explore/united_states/.+(\.html|/[a-z0-9_\-]+)$"),
    "bbb.org": dict(url=lambda n, loc: "https://www.bbb.org/search?find_text=%s&find_loc=%s" % (quote(n), quote(loc)), permalink=r"^/us/[a-z]{2}/[^/]+/profile/"),
    "dnb.com": dict(url=None, permalink=None, why="dnb has no public name + city search without login (the lookup flow is on my.dnb.com)"),
    "discoverourtown.com": dict(url=None, permalink=None, why="discoverourtown has no search box; its city guide pages (/KY.html) list no business search"),
}


def search_url(directory, ident, biz="SCC"):
    cfg = SEARCH.get(directory)
    if not cfg or not cfg.get("url"): return None
    x = ident["BIZ"][biz]
    return cfg["url"](x.get("short") or x["name"], "%s, %s" % (x["city"], x["st"]))   # the short name: directories index "Senior Care Consulting", not the legal suffix


def candidate_links(directory, page):
    """Same-host links on the search page that look like a record page. Deduped, page order, capped."""
    pat = re.compile(SEARCH[directory]["permalink"], re.I)
    host = lambda u: (urlparse(u).netloc or "").lower().replace("www.", "")
    out = []
    for l in getattr(page, "links", None) or []:
        h = (l.get("href") or "").split("#")[0]
        p = urlparse(h)
        if host(h) != directory or not pat.search(p.path) or h in out: continue
        out.append(h)
    return out[:8]


def lookup(directory, ident, canonical, plain=None, chrome=None, biz="SCC"):
    """-> {"status": found|not-found|walled|no-search|unreadable, "url", "search", "checked": n}. Never raises."""
    res = {"directory": directory, "status": None, "url": None, "search": None, "checked": 0, "note": None}
    cfg = SEARCH.get(directory)
    if not cfg or not cfg.get("url"):
        res["status"], res["note"] = "no-search", (cfg or {}).get("why", "no public search known for this Directory"); return res
    su = search_url(directory, ident, biz); res["search"] = su
    try:
        # these result pages are filled by JS: the plain GET is an empty shell, so the rendered signed-out read comes first (plain only when no Chrome)
        sp, how = ((chrome(su, REFERER[directory]) if directory in REFERER else chrome(su)), "chrome") if chrome else R.get_page(su, plain, None)
        if R.walled(sp): res["status"] = "walled"; return res
        if sp.err or (sp.status or 0) >= 400: res["status"], res["note"] = "walled" if (sp.status or 0) in (401, 403, 429) else "unreadable", "status %s %s" % (sp.status, sp.err or ""); return res
        res["note"] = R.search_log(su, sp, how, False)
        # an own-name card: the same card test recheck uses (listing.resolve), then every shaped link is opened and must NAP-match
        links = candidate_links(directory, sp)
        for u in links:
            res["checked"] += 1
            page, how2, cmp_ = R.read_listing(u, plain, chrome, canonical)
            if cmp_["verdict"] == "match":
                res["status"], res["url"] = "found", R.final_url(u, page); return res
        res["status"] = "not-found"
    except Exception as e:
        res["status"], res["note"] = "unreadable", type(e).__name__ + ": " + str(e)[:100]
    return res


def set_listing_url(rid, url, directory, queue_path=None, record=None, today=None):
    """Only path that writes: transitions.record_transition, same state, listing_url. Refuses a row already live."""
    import transitions as T, buildqueue as Q
    q = T._read(queue_path or Q.QUEUE_PATH); row = T._find(q, rid)
    if row["state"] not in R.WAITING: raise T.TransitionRefused("lookup --set-url only touches waiting rows (row %s is %s)" % (rid, row["state"]))
    note = "lookup: found the listing URL by the Directory's public name + city search (signed out); NAP checked, state unchanged"
    return (record or T.record_transition)("SCC", rid, row["state"], None, note, queue_path=queue_path, today=today, listing_url=url)


def main(argv=None):
    import argparse, json
    a = argparse.ArgumentParser(description="Find the listing permalink of no-permalink rows via the Directory's public search (signed out, read-only)")
    a.add_argument("--queue", default=None)
    a.add_argument("--row", action="append", default=None)
    a.add_argument("--set-url", action="store_true", help="record a found URL as listing_url (same state; never live)")
    n = a.parse_args(argv)
    import buildqueue as Q
    from cfg import IDENT
    path = n.queue or Q.QUEUE_PATH
    with open(path, encoding="utf-8") as f: q = json.load(f)
    canonical = q.get("canonical")
    import transitions as T
    rows = [r for _k, _kind, rs in T._row_lists(q) for r in rs if r.get("directory") in SEARCH and (not n.row or r["id"] in n.row) and (n.row or (r.get("state") in R.WAITING and not R._permalink(r)))]
    reader = R.SignedOutReader(); reader.canonical = canonical
    rc = 0
    try:
        for r in rows:
            res = lookup(r["directory"], IDENT, canonical, chrome=reader)
            line = {"found": "FOUND %s", "not-found": "NOT FOUND (%s)", "walled": "SEARCH WALLED (%s)", "no-search": "NO PUBLIC SEARCH (%s)", "unreadable": "UNREADABLE (%s)"}[res["status"]]
            print("%-24s | %-18s | %s | search: %s | checked %d" % (r["id"], r["directory"], line % ((res["url"] if res["status"] == "found" else (res["note"] or "")[:90]),), res["search"] or "-", res["checked"]))
            if res["status"] == "found" and n.set_url:
                try: set_listing_url(r["id"], res["url"], r["directory"], queue_path=n.queue); print("  listing_url set (state %s unchanged)" % r["state"])
                except Exception as e: print("  REFUSED: %s" % e); rc = 1
    finally:
        reader.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
