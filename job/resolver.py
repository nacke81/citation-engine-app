"""Resolver: scripts the playbooks Edith (citation-auditor) proved by hand on 2026-10-22, so a found row follows the result to the real listing page.

Only proven Directories are in scope (INSCOPE). Everything else returns None and is left on today's path; the permalink gate marks it honestly.
Read only. Never logs in, never submits, never steps past a block. A blocked page is reported with its exact blocker and the cell stays couldnt_check.
Uses the fetcher the weekly job already owns (core.ChromeFetcher over owned_chrome). No new browser stack.

resolve_cell(fetcher, directory, biz, ident, search_box=None) -> dict(status 'found'|'miss'|'blocked', url, ev, text, note, log, blocker)
resolve_found_rows(rows, fetcher, ident, search_box=None) -> list of new 'chrome-resolver' rows (same shape discover.emit writes)

Search rules (Edith, in code):
  1. query ladder: ONE distinctive word first, then phone digits, then the short name, then the full name (word_ladder / QUERY_KINDS)
  2. a location field with autocomplete is PICKED (n49 uses discover.own_search_box, which picks the suggestion); every URL search carries City, ST
  3. pagination is the page's own Next anchor (next_page_link). This module never builds a page=N URL.
  4. listing vs search page: URL shape (permalink.is_permalink + listing.is_permalink) AND page tell (is_search_page)
Matched card must agree with the business (name token or phone digits) before it is followed: no match, no follow (card_agrees).
"""
import re
from urllib.parse import quote, quote_plus, urlparse

import core
import listing
import permalink

INSCOPE = ("yellowpages.com", "superpages.com", "dexknows.com", "google.com", "merchantcircle.com", "hotfrog.com", "n49.com", "yellowbot.com", "cybo.com")

# which query kinds each Directory takes, in ladder order. Proven limits: superpages phone search 500s, yellowbot errors on multi-word queries.
QUERY_KINDS = {
    "yellowpages.com": ("word", "phone", "short", "name"),
    "superpages.com": ("word", "short", "name"),
    "dexknows.com": ("word", "phone", "short", "name"),
    "hotfrog.com": ("word", "short", "name"),
    "merchantcircle.com": ("word", "short", "name"),
    "yellowbot.com": ("word",),
}
GENERIC = {"the", "and", "llc", "inc", "co", "company", "corp", "senior", "care", "consulting", "solutions", "services", "media", "group", "of", "for"}
MAX_FETCHES = 14      # per cell, a polite ceiling
MAX_PAGES = 2         # extra result pages followed through the page's own Next link
MAX_FOLLOW = 3        # cards followed per results page
SEARCH_TELL = re.compile(r"(?i)\bresults? for\b|showing \d+\s*-\s*\d+ of|\btop \d+ best\b|\b\d+ results? (found|for)\b|no results")
NEXT_TEXT = re.compile(r"(?i)^\s*(next|next page|next >|›|»|>)\s*$")


def in_scope(directory):
    return directory in INSCOPE


def _digits(s):
    return re.sub(r"\D", "", s or "")


def word_ladder(b, ident):
    """-> {'word','phone','short','name'} queries for this business. 'word' is the ONE distinctive word (identity RESOLVER_WORDS wins)."""
    x = ident["BIZ"][b]
    toks = [t for t in re.split(r"[^a-z0-9]+", x["name"].lower()) if t]
    cand = [t for t in toks if t not in GENERIC and len(t) > 2]
    word = (cand or sorted(toks, key=len, reverse=True) or [x["name"]])[0]
    return {"word": word, "phone": (x.get("phones") or [""])[0], "short": x.get("short") or x["name"], "name": x["name"]}


def word_for(d, b, ident):
    """Identity may pin a word per Directory: RESOLVER_WORDS = {biz: {directory or '*': word}} (e.g. superpages 'consltng' for SCC)."""
    pin = (ident.get("RESOLVER_WORDS") or {}).get(b) or {}
    return pin.get(d) or pin.get("*") or word_ladder(b, ident)["word"]


def plan(d, b, ident):
    """-> [(kind, url)] in ladder order. Pure."""
    x = ident["BIZ"][b]
    lad = word_ladder(b, ident); lad["word"] = word_for(d, b, ident)
    place_plus = quote_plus("%s, %s" % (x["city"], x["st"]))      # City%2C+ST
    place_pct = quote("%s, %s" % (x["city"], x["st"]), safe="")   # City%2C%20ST
    out = []
    if d == "google.com":
        return [("direct", "https://www.google.com/maps/search/" + quote_plus("%s %s %s" % (x["name"], x["city"], x["st"])))]
    if d == "cybo.com":
        return [("direct", "https://www.cybo.com/US-biz/" + x["slug"])]
    if d == "n49.com":
        return [("box", "https://www.n49.com/")]
    for kind in QUERY_KINDS[d]:
        q = lad[kind]
        if not q:
            continue
        if d in ("yellowpages.com", "superpages.com", "dexknows.com"):
            u = "https://www.%s/search?search_terms=%s&geo_location_terms=%s" % (d, quote_plus(q), place_plus)
        elif d == "hotfrog.com":
            u = "https://www.hotfrog.com/search/%s/%s" % (place_pct, quote(q, safe=""))
        elif d == "merchantcircle.com":
            u = "https://www.merchantcircle.com/search?q=%s&qn=%s" % (quote_plus(q), place_plus)
        elif d == "yellowbot.com":
            u = "https://www.yellowbot.com/search?q=%s&place=%s" % (quote_plus(q), place_plus)
        else:
            continue
        out.append((kind, u))
    return out


def is_search_page(text):
    """Page tell for a results page ('Results for', 'Showing 1-N of M', 'Top N Best')."""
    return bool(SEARCH_TELL.search((text or "")[:1500]))


def is_listing_page(d, url, text):
    """URL shape (gate + listing) AND no search tell."""
    return bool(url) and permalink.is_permalink(d, url)[0] and listing.is_permalink(d, url) and not is_search_page(text)


def card_agrees(l, b, ident):
    """The card agrees with the business by name token or phone digits."""
    x = ident["BIZ"][b]
    hay = " ".join([l.get("text") or "", l.get("aria") or ""])
    card = l.get("card") or ""
    if listing._name_hit(hay, x["name"]):
        return True
    if hay.strip():
        # the link names a business and it is not ours: a neighbour's phone or name in the surrounding card text does not make it ours
        return False
    phones = {m.group(1) + m.group(2) + m.group(3) for m in core.PHONE_RE.finditer(card)}
    if phones and phones <= set(x.get("phones") or []):
        return True      # an icon/empty link whose card shows only our phone digits
    return listing._name_hit(card, x["name"]) and len(listing._tok(card)) < 60


def cards_to_follow(d, page_url, links, b, ident):
    """Agreeing record links on a results page, same Directory host, listing shape, deduped, capped. Never a search/category link."""
    out = []
    for l in links or []:
        href = (l.get("href") or "").split("#")[0]
        if not href or d not in urlparse(href).netloc:
            continue
        if not (permalink.is_permalink(d, href)[0] and listing.is_permalink(d, href)):
            continue
        if not card_agrees(l, b, ident):
            continue
        h = listing._clean(href)
        if h not in out and h.rstrip("/") != (page_url or "").rstrip("/"):
            out.append(h)
    return out[:MAX_FOLLOW]


def next_page_link(d, page_url, links):
    """The page's own Next anchor (same host). Pagination is a click on this, never a built page=N URL."""
    for l in links or []:
        href = (l.get("href") or "").split("#")[0]
        if not href or d not in urlparse(href).netloc or href.rstrip("/") == (page_url or "").rstrip("/"):
            continue
        if NEXT_TEXT.match(l.get("text") or "") or (l.get("aria") or "").strip().lower() in ("next", "next page"):
            return href
    return None


def _blocker(r):
    return ("%s %s" % (r.status or r.err or "no-status", " ".join((r.text or "")[:120].split()))).strip()


def _judge(d, b, r):
    """Read NAP from THIS page. Google uses the map-panel judge (phone anchor). -> (ok, ev, why)"""
    if d == "google.com":
        import mapnap
        return mapnap.judge_map(r.text, b)
    return core.judge_listing(r.text, b)


def _accept(d, b, r, ident):
    """A fetched page is the listing only if the URL is a record shape, the page is not a results page, and its own NAP agrees."""
    if core.classify(r, b) != "ok":
        return None
    if not is_listing_page(d, r.url, r.text):
        return None
    ok, ev, why = _judge(d, b, r)
    if not ok:
        return None
    return dict(status="found", url=listing._clean(r.url), ev=ev, text=r.text, note="resolver", why=why)


def resolve_cell(fetcher, d, b, ident, search_box=None):
    """Resolve one business x Directory to its listing page. Read only. -> dict(status found|miss|blocked, ...)"""
    res = dict(status="miss", url=None, ev=None, text=None, note="", log=[], blocker=None)
    if not in_scope(d) or b == "FAKE":
        res.update(status="miss", note="out of scope"); return res
    n = [0]; blocked = []; ok_seen = [False]

    def fetch(url, label):
        n[0] += 1
        r = fetcher.fetch(url, label)
        c = core.classify(r, b)
        res["log"].append("%s:%s:%s" % (c, r.status or r.err, url[:110]))
        if c == "blocked":
            blocked.append(_blocker(r))
        else:
            ok_seen[0] = True
        return r, c

    for kind, url in plan(d, b, ident):
        if n[0] >= MAX_FETCHES:
            break
        if kind == "box":     # n49: the site form with the location suggestion PICKED, via the existing discover.own_search_box
            if search_box is None:
                res["log"].append("box:no search_box provided"); continue
            r = search_box(d, b)
            n[0] += 1
            c = core.classify(r, b)
            res["log"].append("box:%s:%s:%s" % (c, r.status or r.err, (r.url or "")[:110]))
            if c == "blocked":
                blocked.append(_blocker(r)); continue
            ok_seen[0] = True
            pages = [(r, c)]
        else:
            r, c = fetch(url, "%s %s resolver %s" % (d, b, kind))
            if c == "blocked":
                continue
            pages = [(r, c)]
        if kind == "direct":
            got = _accept(d, b, r, ident)
            if got:
                res.update(got); return res
            continue
        pg = 0
        while pages:
            r, c = pages.pop(0)
            if c != "ok":
                break
            got = _accept(d, b, r, ident)         # the result URL may already be the listing (one-match auto resolve)
            if got:
                res.update(got); return res
            for h in cards_to_follow(d, r.url, r.links, b, ident):
                if n[0] >= MAX_FETCHES:
                    break
                r2, c2 = fetch(h, "%s %s resolver listing" % (d, b))
                got = _accept(d, b, r2, ident)
                if got:
                    res.update(got); return res
            nxt = next_page_link(d, r.url, r.links) if pg < MAX_PAGES and n[0] < MAX_FETCHES else None
            if nxt:
                pg += 1
                r3, c3 = fetch(nxt, "%s %s resolver next page" % (d, b))
                pages.append((r3, c3))
    if blocked and not ok_seen[0]:
        res.update(status="blocked", blocker=blocked[0], note="blocked")
    else:
        res.update(status="miss", note="no agreeing listing found", blocker=(blocked[0] if blocked else None))
    return res


def needs_resolving(combined, b, d):
    """True when the cell is found but its stored URL fails the permalink gate (so build() would flip it)."""
    res, src = combined[(b, d)]
    return res == "found" and src is not None and not permalink.is_permalink(d, src.get("url"))[0]


def resolve_found_rows(rows, fetcher, ident, dirs, search_box=None, resolve=None):
    """For each SCC/NM in-scope cell that is found with a gate-failing URL, resolve it. -> new rows to append to rows.jsonl.
    A miss adds nothing (the cell keeps today's path and the gate marks it). FAKE is never resolved."""
    import judge
    comb = judge.combine(rows, dirs, set(ident.get("UNSEARCHABLE", [])))
    out = []
    for b in ("SCC", "NM"):
        for d in INSCOPE:
            if (b, d) not in comb or not needs_resolving(comb, b, d):
                continue
            r = (resolve or resolve_cell)(fetcher, d, b, ident, search_box)
            if r["status"] != "found":
                continue
            out.append(dict(kind="dir", method="chrome-resolver", biz=b, dir=d, status="found", url=r["url"], ev=r["ev"], note="resolver",
                            log=" | ".join(r["log"]), blocked_on_purpose=False, verified=False, results=0, _text=r.get("text")))
    return out
