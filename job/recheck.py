"""Recheck job for rows that wait on a Directory (t_64c4d511). Read-only toward Directories: public GETs only (plain first, the build Chrome on CDP 9333
when the plain page is walled or has no readable listing). No login, no signup, no submit.

For every queue row in submitted / pending-verify / found (and live, report only, with --include-live) that carries a listing permalink:
  fetch the public page -> read the listing's own block -> compare name / street / phone to q["canonical"].
  all three match  -> Proof on ce_directory_status, then live through transitions.record_transition (with the permalink)
  a field differs  -> same-state note naming the field and the value shown (no state change)
  a field is absent-> same-state note naming the gap
  page unreadable  -> nothing written
  no permalink     -> nothing written (bbb.org is the exception: its profile URL is looked up by name + city and stored with a same-state note)
A note identical to the row's last history note is not written again, so a weekly run does not pile up duplicates.

  python job/recheck.py [--queue PATH] [--write] [--include-live] [--row ID ...] [--no-chrome]
Without --write nothing is written (dry run); the report still shows before -> after and any mismatch.
"""
import json, os, re, sys, urllib.request, urllib.error
from urllib.parse import quote, urljoin

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buildqueue as Q
import fixlist as F
import listing as L

WAITING = ("submitted", "pending-verify", "found")
CDP_URL = "http://127.0.0.1:9333"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
WALL_RE = re.compile(r"(?i)just a moment|quick security check|performing a quick|verify you are (a )?human|attention required|access denied|"
                     r"checking your browser|are you a robot|press (&|and) hold|error 1020|request blocked|security verification")
PLUS_PHONE_RE = re.compile(r"(?<![\w+])\+\d[\d\s().\-]{5,18}\d")
MASKED_PHONE_RE = re.compile(r"\*{2,}|reveal phone|show phone|click to (call|view)", re.I)   # a hidden phone is not a wrong phone


class Page:
    def __init__(self, status, url, text, links=None, err=None):
        self.status, self.url, self.text, self.links, self.err = status, url, text or "", links or [], err


# ---- fetching (every edge injectable) -----------------------------------------------------------------------------
def walled(page):
    return page.status in (None, 0, 401, 403, 429) or (page.status or 0) >= 500 or bool(WALL_RE.search(page.text[:4000])) or len(page.text.strip()) < 200


def plain_fetch(url):
    """One public GET. Never raises."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "replace"); status, final = r.status, r.geturl()
    except urllib.error.HTTPError as e:
        return Page(e.code, url, "", err="HTTP %s" % e.code)
    except Exception as e:
        return Page(0, url, "", err=type(e).__name__)
    import claim
    text = claim.html_to_text(html)
    links = []
    for m in re.finditer(r'(?is)<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html):
        ctx = claim.html_to_text(html[max(0, m.start() - 400):m.end() + 200])
        links.append({"href": urljoin(final, m.group(1)), "text": " ".join(claim.html_to_text(m.group(2)).split())[:80], "card": ctx[-400:], "aria": ""})
    return Page(status, final, text, links)


def chrome_fetch(url, cdp=CDP_URL, wait_s=30):
    """Read the rendered page in the build Chrome. Opens and closes one tab; reads only. Walls are waited on (a Turnstile that clears itself), never solved."""
    import core
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    try:
        b = p.chromium.connect_over_cdp(cdp)
        pg = b.contexts[0].new_page()
        try:
            r = pg.goto(url, timeout=40000, wait_until="domcontentloaded"); status = r.status if r else None
            text = ""
            for _ in range(max(1, wait_s // 2)):
                pg.wait_for_timeout(2000)
                try: text = pg.inner_text("body", timeout=8000)
                except Exception: text = ""
                if not WALL_RE.search(text[:4000]) and len(text.strip()) > 200: break
            try: links = pg.evaluate(core.LINKS_JS)
            except Exception: links = []
            return Page(status, pg.url, text, links)
        finally:
            try: pg.close()
            except Exception: pass
    except Exception as e:
        return Page(0, url, "", err=type(e).__name__)
    finally:
        try: p.stop()
        except Exception: pass


def get_page(url, plain=None, chrome=None, canonical=None):
    """Plain GET first. The build Chrome only when the plain page is walled or shows no readable listing block for the canonical name."""
    page = (plain or plain_fetch)(url)
    if not walled(page) and (canonical is None or read_block(page.text, canonical)):
        return page, "plain"
    if chrome is None:
        return page, "plain"
    cp = chrome(url)
    return (cp if not walled(cp) or walled(page) else page), "chrome"


# ---- NAP reading ----------------------------------------------------------------------------------------------------
def _digits(s): return re.sub(r"\D", "", s or "")


def read_block(text, canonical):
    """The listing's own lines: from the first short line carrying the canonical name to the next stop marker. [] when no such line."""
    lines = [l.strip() for l in (text or "").replace("\r", "").split("\n") if l.strip()]
    want = F._norm_name(canonical["name"])
    for i, l in enumerate(lines):
        if len(l) > 120: continue
        l2 = re.sub(r"^\d+\.\s*", "", l)
        if want in F._norm_name(l2) or (len(l2) <= 90 and L._name_hit(l2, canonical["name"])):
            out = [l2]
            for l3 in lines[i + 1:]:
                if F.STOP_RE.match(l3): break
                out.append(l3)
                if len(out) > 120: break
            return out
    return []


def compare(text, canonical):
    """-> {"verdict": match|mismatch|gap|unreadable, "wrong": [(field, shown)], "gaps": [field], "nap": "name | street | phone"}. Pure."""
    block = read_block(text, canonical)
    if not block:
        return {"verdict": "unreadable", "wrong": [], "gaps": [], "nap": None}
    wrong, gaps = [], []
    want_phone = _digits(canonical["phone"])[-10:]
    shown = F.phones_in(block)
    if shown:
        bad = [p for p in shown if p != want_phone]
        if bad: wrong.append(("phone", F.fmt_phone(bad[0])))
        elif want_phone not in shown: gaps.append("phone")
    else:
        masked = any(MASKED_PHONE_RE.search(l) for l in block if len(l) <= 200)
        plus = None if masked else next((m.group(0).strip() for l in block for m in [PLUS_PHONE_RE.search(l)] if m and len(l) <= 200), None)
        if plus: wrong.append(("phone", plus))
        else: gaps.append("phone")
    cstreet = F.parse_street(canonical["address"].split(",")[0])
    got = F.street_in(block)
    if got and cstreet:
        czip = re.search(r"\b(\d{5})\b", canonical["address"])
        street_txt_norm = " ".join(F._tok(got[0]))
        want_norm = " ".join(F._tok(canonical["address"].split(",")[0]))
        same = F.street_equal(got[1], cstreet) or street_txt_norm.startswith(want_norm)   # street and city on one line
        if not same or (got[2] and czip and got[2] != czip.group(1)):
            wrong.append(("address", got[0] if (got[2] or "") in got[0] else got[0] + ((" " + got[2]) if got[2] else "")))
    elif not got:
        gaps.append("address")
    street_txt = got[0] if got else None
    nap = " | ".join(x for x in (canonical["name"], street_txt, F.fmt_phone(shown[0]) if shown else None) if x)
    verdict = "mismatch" if wrong else "gap" if gaps else "match"
    return {"verdict": verdict, "wrong": wrong, "gaps": gaps, "nap": nap}


def note_for(cmp_):
    parts = ["%s shows %s" % (f, v) for f, v in cmp_["wrong"]] + ["%s not shown on the public page (hidden or missing)" % f for f in cmp_["gaps"]]
    return "weekly recheck: " + "; ".join(parts)


# ---- queue ------------------------------------------------------------------------------------------------------------
def _permalink(row):
    d = row.get("directory")
    for k in ("evidence_url", "listing_url"):   # evidence first; fix-bing keeps its Bing Maps permalink in listing_url, bingplaces.com is not a listing
        u = row.get(k)
        if u and L.is_permalink(d, u): return u
    return None


def _bbb_search_url(ident, biz="SCC"):
    x = ident["BIZ"][biz]
    return "https://www.bbb.org/search?find_text=%s&find_loc=%s" % (quote(x["name"]), quote("%s, %s" % (x["city"], x["st"])))


def resolve_bbb(page, ident, biz="SCC"):
    """Profile URL from a bbb.org search page: a /profile/ link whose card names the business. None when absent."""
    x = ident["BIZ"][biz]
    url, kind = L.resolve("bbb.org", page.url, page.links, x["name"], x.get("phones") or ())
    return url if (url and kind == "listing" and "/profile/" in url) else None


def candidates(q, include_live=False, only=None):
    import transitions as T
    out = []
    states = WAITING + (("live",) if include_live else ())
    for _key, kind, rows in T._row_lists(q):
        for r in rows:
            if r.get("state") in states and r.get("directory") and (not only or r["id"] in only):
                out.append((kind, r))
    return out


def _last_note(row):
    h = row.get("history") or []
    return (h[-1].get("note") if h and isinstance(h[-1], dict) else None)


def recheck(q, ident, *, plain=None, chrome=None, record=None, db=None, queue_path=None, today=None, write=False, include_live=False, only=None, use_chrome=True):
    """-> list of per-row results {row, directory, url, before, after, verdict, fields, note, error}. Never raises per row."""
    import datetime
    day = today or datetime.date.today().isoformat()
    canonical = q.get("canonical")
    if not canonical or not all(canonical.get(k) for k in ("name", "address", "phone")):
        raise Q.QueueError("queue has no canonical name/address/phone")
    ident_phone = _digits(ident["BIZ"]["SCC"]["phones"][0])[-10:]
    if _digits(canonical["phone"])[-10:] != ident_phone:
        raise Q.QueueError("queue canonical phone differs from the approved identity; refusing to recheck")
    if record is None:
        import transitions; record = transitions.record_transition
    chrome = (chrome or chrome_fetch) if use_chrome else None
    results = []
    for kind, row in candidates(q, include_live, only):
        d, rid, before = row["directory"], row["id"], row["state"]
        res = {"row": rid, "directory": d, "url": None, "before": before, "after": before, "verdict": None, "fields": [], "note": None, "error": None}
        results.append(res)
        try:
            url = _permalink(row)
            if url is None and d == "bbb.org":
                sp, _how = get_page(_bbb_search_url(ident), plain, chrome)
                url = resolve_bbb(sp, ident)
                if url:
                    note = "weekly recheck: found the BBB profile URL"
                    if write: record("SCC", rid, before, url, note, queue_path=queue_path, today=day) if before in ("submitted", "pending-verify", "found") else None
                    res["note"] = note
            if url is None:
                res["verdict"] = "no-permalink"; continue
            res["url"] = url
            page, how = get_page(url, plain, chrome, canonical)
            cmp_ = compare(page.text, canonical)
            res["verdict"] = cmp_["verdict"]; res["fields"] = cmp_["wrong"] or cmp_["gaps"]; res["via"] = how
            if cmp_["verdict"] == "unreadable":
                res["error"] = "page not readable (%s)" % (page.err or page.status); continue
            if cmp_["verdict"] == "match":
                if before == "live": continue   # already live: report only
                res["note"] = "weekly recheck: listing live, NAP matches canonical"
                if write:
                    _proof_then_live(row, kind, url, cmp_["nap"], day, db, record, queue_path, res["note"])
                res["after"] = "live"
            elif before != "live":
                note = note_for(cmp_); res["note"] = note
                if write and note != _last_note(row):
                    record("SCC", rid, before, None, note, queue_path=queue_path, today=day)
        except Exception as e:
            res["error"] = (str(e)[:200] or type(e).__name__)
    return results


def _proof_then_live(row, kind, url, nap, day, db, record, queue_path, note):
    """Proof first (a live row without Proof never counts); if the transition then fails the row stays waiting and the next run retries."""
    import datetime, directories as D, proof as PR
    db = db or D.DirDB()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action = PR.build_action(kind, row, row.get("claim_status"))
    D._upsert_status(db, [D._status_row(db, "SCC", row["directory"], day, proof_url=url, proof_nap=nap, proof_at=stamp, proof_nap_match=True, build_action=action)])
    out = record("SCC", row["id"], "live", url, note, queue_path=queue_path, today=day)
    if out.get("errors"): raise RuntimeError("; ".join(out["errors"])[:200])


def recheck_file(path=None, ident=None, **kw):
    path = path or Q.QUEUE_PATH
    with open(path, encoding="utf-8") as f: q = json.load(f)
    if ident is None:
        from cfg import IDENT as ident
    return recheck(q, ident, queue_path=path, **kw)


def format_report(results):
    lines = []
    for r in results:
        f = "; ".join("%s=%s" % (a, b) if isinstance(a, str) and b else str(a) for a, b in [(x if isinstance(x, tuple) else (x, "")) for x in r["fields"]])
        lines.append("%-26s %-14s -> %-14s %-12s %s%s" % (r["row"], r["before"], r["after"], r["verdict"], f, ("  ERR " + r["error"]) if r["error"] else ""))
    return "\n".join(lines)


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Recheck waiting queue rows against their public listing page")
    a.add_argument("--queue", default=None)
    a.add_argument("--write", action="store_true", help="record transitions and notes (default: dry run, nothing written)")
    a.add_argument("--include-live", action="store_true", help="also read live rows (report only)")
    a.add_argument("--row", action="append", default=None)
    a.add_argument("--no-chrome", action="store_true")
    a.add_argument("--today", default=None)
    n = a.parse_args(argv)
    res = recheck_file(n.queue, write=n.write, include_live=n.include_live, only=set(n.row) if n.row else None, use_chrome=not n.no_chrome, today=n.today)
    print(format_report(res))
    print("%d rows read; %d to live; mode=%s" % (len(res), sum(1 for r in res if r["after"] == "live" and r["before"] != "live"), "WRITE" if n.write else "dry run"))
    return 1 if any(r["error"] and r["verdict"] != "unreadable" for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
