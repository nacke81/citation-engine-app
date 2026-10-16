"""Pure fix-list logic: one found listing -> the NAP+site fields that differ from canonical. No network, no browser.

Slice 2: every field the listing SHOWS is compared to canonical by normalized value (not against a stale list).
A diff is {field, live, canonical[, label]}. Fields: name, phone, address, site. `label` is only a hint ("old phone", "old address").

Rules (generic, none tied to one URL):
  - Only the listing's own block of the page is read (from the line that starts with the business name to the next stop marker),
    so other businesses' phones/streets on list pages never count.
  - phone: digits only, so format never matters. Any shown phone that is not canonical is a diff.
  - address: a diff exists only when the listing SHOWS a street line that differs. No street line shown (service-area listing)
    = no address diff. Suite/Ste/#, St/Street, Dr/Drive..., punctuation and case are folded. A missing unit is not a diff.
  - site: scheme, www., path, query/tracking params and trailing slash are ignored. A block that shows a phone or street but no site
    and no "Website" button is a diff with live "missing". A bare "Website" button with no readable URL is not flagged (cannot tell).
  - no readable block (thin page) = no new diffs from this module; the slice-1 evidence flags still apply.
"""
import difflib, re
from urllib.parse import urlparse, parse_qs, unquote

PHONE_RE = re.compile(r"(?<!\d)\(?(\d{3})\)?[\s.\-]*(\d{3})[\s.\-]*(\d{4})(?!\d)")

STOP_RE = re.compile(r"(?i)^(claim (this|your) (business|listing)|is this your business|manage your free|showing \d|featured\b|"
                     r"places near|similar |you might also like|people also|.{0,40} near me in |"
                     r"ratings and reviews)")
SEARCHY_URL_RE = re.compile(r"(?i)/search|[?&](q|query|search|search_terms|find_desc|find_text|what)=|/explore|/maps/search")
STATE_ZIP_RE = re.compile(r"(?i)^[A-Za-z .'\-]+,?\s+[A-Z]{2}\.?,?\s+\d{5}|\b[A-Z]{2}\s+\d{5}\b|^\d{5}\b")
SITE_LABEL_RE = re.compile(r"(?i)^(historical |business )?(website|web|site|visit website|url|homepage)$")
DOMAIN_RE = re.compile(r"(?i)^(?:(?:visit|website|web|site|url)\s*:?\s*)?(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)*\.[a-z]{2,})(?::\d+)?(?:[/?#]\S*)?$")
URL_IN_TEXT_RE = re.compile(r"(?i)\bhttps?://(?:www\.)?([a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)*\.[a-z]{2,})[^\s)]*")
WRONG_HOSTS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "google.com", "facebook.com", "youtube.com",
               "instagram.com", "twitter.com", "x.com", "linkedin.com"}

TYPE_MAP = {"street": "st", "str": "st", "drive": "dr", "road": "rd", "boulevard": "blvd", "avenue": "ave", "lane": "ln", "court": "ct",
            "circle": "cir", "parkway": "pkwy", "highway": "hwy", "place": "pl", "trail": "trl", "square": "sq"}
TYPES = set(TYPE_MAP.values()) | {"pike", "way"}
UNIT_RX = r"(?:suite|ste|unit|apt|apartment|fl|floor|room|rm)\.?\s*#?\s*([A-Za-z0-9\-]+)|#\s*([A-Za-z0-9\-]+)"
UNIT_LINE_RE = re.compile(r"(?i)^(?:" + UNIT_RX + r")$")
UNIT_ANY_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(?:" + UNIT_RX + r")")
UNIT_START_RE = re.compile(r"(?i)^(?:" + UNIT_RX + r")\b")


def fmt_phone(p10):
    return f"({p10[:3]}) {p10[3:6]}-{p10[6:]}"


def canon(ident, b):
    x = ident["BIZ"][b]
    c = dict((ident.get("CANON") or {}).get(b) or {})
    c.setdefault("name", x["name"])
    c.setdefault("phone", fmt_phone(x["phones"][0]))
    c.setdefault("address", f"{x['street']}, {x['city']}, {x['st']} {x['zip']}")
    if x.get("site"):
        c.setdefault("site", x["site"])
    return c


def _norm_name(s):
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(llc|inc|the|and)\b", " ", s)
    return " ".join(s.split())


def _short_lines(text, n=90):
    return [l.strip() for l in (text or "").split("\n") if l.strip() and len(l.strip()) <= n]


def _is_name_line(l, rx):
    l2 = re.sub(r"^\d+\.\s*", "", l)
    if len(l2) > 70 or not rx.match(l2) or "," in l2 or " in " in l2.lower() or " - " in l2 or "|" in l2:
        return None
    return l2


def listing_block(text, ident, b):
    """Lines from the first line that starts with the business name to the next stop marker. [] if there is no such line."""
    rx = re.compile(ident["RX"]["name"][b], re.I)
    lines = [l.strip() for l in (text or "").replace("\r", "").split("\n") if l.strip()]
    for i, l in enumerate(lines):
        l2 = _is_name_line(l, rx)
        if not l2:
            continue
        out = [l2]
        for l3 in lines[i + 1:]:
            if STOP_RE.match(l3):
                break
            out.append(l3)
            if len(out) > 120:
                break
        return out
    return []


# ---- phone --------------------------------------------------------------------------------------------------------
def phones_in(block):
    seen = []
    for l in block:
        if len(l) > 200:
            continue
        for m in PHONE_RE.finditer(l):
            p = m.group(1) + m.group(2) + m.group(3)
            if p not in seen:
                seen.append(p)
    return seen


def phone_diffs(text, ident, b, ev_stale, block=None):
    """Shown phones (10 digits) that are not canonical. Thin page (no block) falls back to the known stale phones the job saw."""
    x = ident["BIZ"][b]
    ok = set(x["phones"])
    block = listing_block(text, ident, b) if block is None else block
    if block:
        return [p for p in phones_in(block) if p not in ok]
    return list(x.get("stale_phones") or []) if ev_stale else []


# ---- name (unchanged from slice 1) --------------------------------------------------------------------------------
def name_diff(text, ident, b):
    x = ident["BIZ"][b]
    rx = re.compile(ident["RX"]["name"][b], re.I)
    ok = {_norm_name(x["name"]), _norm_name(x["short"])}
    for l in _short_lines(text, 70):
        l2 = re.sub(r"^\d+\.\s*", "", l)
        m = rx.match(l2)
        if not m or "," in l2 or " in " in l2.lower() or " - " in l2 or "|" in l2:
            continue
        n = _norm_name(l2)
        if n in ok:
            return None
        if any(n and difflib.SequenceMatcher(None, n, o).ratio() >= 0.8 for o in ok) and not any(o.startswith(n) for o in ok):
            return l2
    return None


# ---- address ------------------------------------------------------------------------------------------------------
def _tok(s):
    return [TYPE_MAP.get(t, t) for t in re.sub(r"[#.,;]", " ", (s or "").lower()).split()]


def parse_street(line):
    """'200 Sample Blvd., Suite 200' -> dict(num, name tokens, type, unit). None if the line does not start with a street number."""
    m = re.match(r"^\s*(\d{1,6})\s+(.+)$", line or "")
    if not m:
        return None
    parts = [p.strip() for p in m.group(2).split(",")]
    head, unit = parts[0], None
    mu = UNIT_ANY_RE.search(head)
    if mu:
        unit = (mu.group(1) or mu.group(2)).lower()
        head = head[:mu.start()]
    elif len(parts) > 1:
        mu = UNIT_START_RE.match(parts[1])
        if mu:
            unit = (mu.group(1) or mu.group(2)).lower()
    toks = _tok(head)
    typ = None
    if toks and toks[-1] in TYPES:
        typ = toks[-1]
        toks = toks[:-1]
    return dict(num=m.group(1), name=toks, type=typ, unit=unit) if toks else None


def street_equal(live, want):
    """Same number and street name; type/unit compared only when both sides show one; a unit shown where canonical has none is a diff."""
    if live["num"] != want["num"] or live["name"] != want["name"]:
        return False
    if live["type"] and want["type"] and live["type"] != want["type"]:
        return False
    if live["unit"] and want["unit"] and live["unit"] != want["unit"]:
        return False
    return not (live["unit"] and not want["unit"])


def street_in(block):
    """First street line in the block -> (text as shown, parsed, zip or None). None when the block shows no street (service-area listing)."""
    for i, l in enumerate(block):
        if len(l) > 120 or PHONE_RE.search(l):
            continue
        p = parse_street(l)
        if not p:
            continue
        if p["num"].lstrip("0") == "":
            continue
        nxt = block[i + 1] if i + 1 < len(block) else ""
        nxt2 = block[i + 2] if i + 2 < len(block) else ""
        # a street line has a street-type word, or is followed (same line / next two lines) by "City, ST zip"
        if not (p["type"] or STATE_ZIP_RE.search(l) or STATE_ZIP_RE.match(nxt) or (UNIT_LINE_RE.match(nxt) and STATE_ZIP_RE.match(nxt2))):
            continue
        shown = l
        if not p["unit"] and i + 1 < len(block):                  # a unit on its own line, e.g. "Ste 200"
            mu = UNIT_LINE_RE.match(block[i + 1])
            if mu:
                p = dict(p, unit=(mu.group(1) or mu.group(2)).lower())
                shown = l + " " + block[i + 1]
        zone = re.sub(r"^\s*\d{1,6}\s", "", " ".join(block[i:i + 6]))
        zm = re.search(r"(?<![\d.\-])(\d{5})(?:-\d{4})?(?![\d.])", zone)
        return shown, p, (zm.group(1) if zm else None)
    return None


def address_diff(block, ident, b, labels=False):
    c = canon(ident, b)
    ap = c["address"].split(",")
    want = parse_street(ap[0] + (", " + ap[1] if len(ap) > 1 else ""))
    got = street_in(block)
    if not got or not want:
        return None
    shown, p, zipc = got
    czip = re.search(r"\b(\d{5})\b", c["address"])
    zip_bad = bool(zipc and czip and zipc != czip.group(1))
    if street_equal(p, want) and not zip_bad:
        return None
    out = {"field": "address", "live": shown + (f" {zipc}" if zip_bad else ""), "canonical": c["address"]}
    rx = (ident["RX"].get("old_street") or {}).get(b)
    if labels and rx and re.search(rx, shown, re.I):
        out["label"] = "old address"
    return out


def old_street_live(text, ident, b):
    rx = (ident["RX"].get("old_street") or {}).get(b)
    if not rx:
        return None
    m = re.search("(?i)(" + rx + r")[^\n]{0,40}", text or "")
    return " ".join(m.group(0).split()) if m else None


# ---- site ---------------------------------------------------------------------------------------------------------
def site_host(s):
    """Normalized host: scheme, www., path, query/tracking params, trailing slash and case dropped. '' if no host."""
    s = (s or "").strip()
    m = DOMAIN_RE.match(s) or URL_IN_TEXT_RE.match(s)
    return m.group(1).lower() if m else ""


def sites_in(block, skip_host=""):
    """Website candidates shown in the block (bare-domain / URL lines and URLs in prose). Directory host, email and social hosts dropped."""
    out, has_label = [], False

    def add(h):
        h = (h or "").lower()
        if h and h not in out and h not in WRONG_HOSTS and not (skip_host and (h == skip_host or h.endswith("." + skip_host))):
            out.append(h)
    for l in block:
        if SITE_LABEL_RE.match(l):
            has_label = True
            continue
        if "@" in l:
            continue
        add(site_host(l) if len(l) <= 120 else "")
        for m in URL_IN_TEXT_RE.finditer(l):
            add(m.group(1))
    return out, has_label


SITE_LINK_TEXT_RE = re.compile(r"(?i)^(visit\s+)?(the\s+)?(business\s+)?(website|web\s*site|site|homepage|web|visit\s+site|official\s+site)(\s+(for|of)\b.*)?$")
WRAP_PARAMS = ("url", "u", "to", "dest", "destination", "redirect", "target", "link", "q")


def _unwrap(href):
    """A tracking/redirect wrapper (?url=https%3A%2F%2Fsite...) -> the real target. Unchanged when not a wrapper."""
    for _ in range(2):
        qs = parse_qs(urlparse(href).query)
        nxt = next((v[0] for k in WRAP_PARAMS for v in [qs.get(k)] if v and re.match(r"(?i)https?://", unquote(v[0]))), None)
        if not nxt:
            break
        href = unquote(nxt)
    return href


def website_hosts(links, ident, b, listing_url=""):
    """Hosts of the listing's own 'Website' link or button (href, not shown text). Saved by the job so a button is checked like a shown URL.

    Only anchors whose text or aria-label says Website/Visit website/Homepage count. Directory-own hosts and social hosts drop out.
    On a page with several such links (a results page) a link counts only if its own card names this business, so another
    business's button never lands on this listing. Returns [] when nothing usable: no href is never a 'missing' or a Site row.
    """
    rx = re.compile(ident["RX"]["name"][b], re.I)
    hu = urlparse(listing_url or "").netloc.lower().replace("www.", "")
    skip = ".".join(hu.split(".")[-2:]) if hu else ""
    cand = [l for l in (links or []) if isinstance(l, dict) and (SITE_LINK_TEXT_RE.match((l.get("text") or "").strip()) or SITE_LINK_TEXT_RE.match((l.get("aria") or "").strip()))]
    out = []
    for l in cand:
        if len(cand) > 1 and not rx.search(l.get("card") or ""):
            continue
        if len(cand) == 1 and SEARCHY_URL_RE.search(listing_url or "") and not rx.search(l.get("card") or ""):
            continue
        href = _unwrap((l.get("href") or "").strip())
        if not re.match(r"(?i)^https?://", href):
            continue
        h = site_host(href)
        if not h or h in WRONG_HOSTS or (skip and (h == skip or h.endswith("." + skip))) or h in out:
            continue
        out.append(h)
    return out


def site_diff(block, ident, b, listing_url="", hrefs=()):
    c = canon(ident, b)
    want = site_host(c.get("site", ""))
    if not want or not (block or hrefs):
        return None
    hu = urlparse(listing_url or "").netloc.lower().replace("www.", "")
    got, has_label = sites_in(block or [], ".".join(hu.split(".")[-2:]) if hu else "")
    got = [h for h in hrefs if h not in got] + got            # a Website button's href is checked like a shown URL
    if any(h == want or h.endswith("." + want) for h in got):
        return None
    if got:
        return {"field": "site", "live": got[0], "canonical": c["site"]}
    if has_label or not (phones_in(block) or street_in(block)):
        return None
    if SEARCHY_URL_RE.search(listing_url or ""):      # a results page / card cannot prove the listing has no site
        return None
    return {"field": "site", "live": "missing", "canonical": c["site"]}


def _is_list_page(text, block):
    """True when the page shows 3+ other phone numbers outside this listing's block: a results/category page of many businesses."""
    inside = set(block)
    other = set()
    for l in (text or "").replace("\r", "").split("\n"):
        l = l.strip()
        if not l or l in inside or len(l) > 200:
            continue
        for m in PHONE_RE.finditer(l):
            other.add(m.group(1) + m.group(2) + m.group(3))
    return len(other) >= 3


# ---- entry point --------------------------------------------------------------------------------------------------
def diffs_for(text, ev, ident, b, url="", labels=False, links=None):
    """ev = the discovery row's evidence flags (name/street/old_street/phones/stale_phone). Returns a list of diffs."""
    ev = ev or {}
    c = canon(ident, b)
    stale = set(ident["BIZ"][b].get("stale_phones") or [])
    block = listing_block(text, ident, b) if text else []
    out = []
    for p in phone_diffs(text, ident, b, ev.get("stale_phone"), block):
        d = {"field": "phone", "live": fmt_phone(p), "canonical": c["phone"]}
        if labels and p in stale:
            d["label"] = "old phone"
        out.append(d)
    ad = address_diff(block, ident, b, labels) if block else None
    if ad:
        out.append(ad)
    elif not block and ev.get("old_street") and not ev.get("street"):
        live = old_street_live(text, ident, b) or ident["BIZ"][b].get("old_street", "old street")
        d = {"field": "address", "live": live, "canonical": c["address"]}
        if labels:
            d["label"] = "old address"
        out.append(d)
    sd = site_diff(block, ident, b, url, website_hosts(links, ident, b, url))
    if sd and sd["live"] == "missing" and _is_list_page(text, block):     # one card among many businesses cannot prove "no site"
        sd = None
    if sd:
        out.append(sd)
    nd = name_diff(text, ident, b) if text else None
    if nd:
        out.append({"field": "name", "live": nd, "canonical": c["name"]})
    return out
