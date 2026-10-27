"""Listing URL resolution + honest per-row reasons. Pure functions, no network, no browser.

A found row's URL must be the page of the listing itself (a record permalink). Never a search page, a category page or a guessed slug.
If the engine matched on a search/category page, it takes the permalink linked from that page for the matched business; if there is none it
stores None with urlKind 'search' (the UI says "listing has no direct link").
"""
import re
from urllib.parse import urlparse

# directory -> regex over path (+ ?query) that a real record page matches
PERMALINK = {
    "yellowpages.com": r"/mip/[^/?]+-\d+",
    "superpages.com": r"/bpp/[^/?]+-\d+",
    "dexknows.com": r"/bp/[^/?]+-\d+",
    "merchantcircle.com": r"^/[a-z0-9\-]+-[a-z0-9\-]+-[a-z]{2}/?(\?.*)?$",
    "hotfrog.com": r"^/company/",
    "n49.com": r"^/biz/\d+",
    "cybo.com": r"^/US-biz/[^/]+/?$",
    "mapquest.com": r"^/us/[a-z\-]+/[^/?]+-\d+",
    "google.com": r"^/maps/place/",
    "maps.apple.com": r"^/place\?.*place-id=",
    "bing.com": r"local_ypid|ss=id\.",
    "yelp.com": r"^/biz/[^/?]+",
    "bbb.org": r"/profile/",
    "chamberofcommerce.com": r"^/united-states/[^?]*/\d+-",
    "yellowbot.com": r"^/[^/?]+\.html$",
    "facebook.com": r"^/(people/[^/]+/\d+|[A-Za-z0-9.\-]{3,})/?$",
    "localsolution.com": r"^/b/[^/?]+/[^/?]+",                                  # t_3ac43137: /b/<city-st>/<slug>; the homepage / add form are not listings
    "listyourbusiness.us": r"^/category/[^/?]+/[a-z\-]+/[^/?]+/?$",            # /category/<cat>/<state>/<slug>
}
SEARCHY = re.compile(r"(?i)/search|/s/|[?&](q|query|search_terms|find_desc|what|find_text)=|/explore|/category|/categories")

# Why a row could not be checked. Plain English, shown to the client.
REASON_BY_DIR = {
    "brownbook.net": "unsearchable",
    "yellowbook.com": "no public search", "localstack.com": "no public search",
    "facebook.com": "login required", "nextdoor.com": "login required", "foursquare.com": "login required",
    "yelp.com": "bot wall", "cybo.com": "bot wall",
}
REASON_TEXT = {
    "unsearchable": "This directory has no search that works without an account, so it cannot be checked automatically.",
    "no public search": "This directory has no public search, so we cannot look the business up.",
    "login required": "This directory needs a login to look the business up. We never log in to directories.",
    "bot wall": "This directory blocked our automated visit with a security check. We do not get around it.",
    "no usable result": "We searched, but the page gave no result we could read.",
    "page error": "The directory page failed to load.",
    "no permalink": "We found a search or category page for this business, but not its own listing page, so we do not count it as found.",
}


def reason_for(directory, result, note):
    """(reason, plain text) for a couldn't-check / unsearchable row, else (None, None)."""
    if result not in ("couldnt_check", "unsearchable"):
        return None, None
    r = REASON_BY_DIR.get(directory)
    if not r:
        n = (note or "")
        r = "no permalink" if n == "no permalink" else "bot wall" if n == "blocked" else "page error" if n == "error" else "unsearchable" if result == "unsearchable" else "no usable result"
    return r, REASON_TEXT[r]


def _path(u):
    p = urlparse(u)
    return p.path + (("?" + p.query) if p.query else "")


def is_permalink(directory, url):
    """True only when url is a record page for that directory (not search / category / guessed slug)."""
    if not url: return False
    pat = PERMALINK.get(directory)
    path = _path(url)
    if SEARCHY.search(path) and not (directory == "bing.com" and re.search(PERMALINK["bing.com"], url)) and directory != "listyourbusiness.us":   # LYB listings live under /category/ (t_3ac43137); its pattern is explicit
        return False
    if pat is None: return True
    target = url if directory == "bing.com" else path
    return bool(re.search(pat, target))


def _tok(s): return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t]


def _name_hit(text, name):
    """Prefix-3 overlap of the canonical name's words in the text (survives 'Consltng' style abbreviations)."""
    want = [t[:3] for t in _tok(name) if t not in ("and", "the", "llc", "inc")]
    have = {t[:3] for t in _tok(text)}
    return bool(want) and sum(1 for w in want if w in have) >= max(2, round(len(want) * 0.75))


def _clean(u):
    return re.sub(r"[?#].*$", "", u) if "?" in u and "place-id" not in u and "ss=id" not in u else u


def resolve(directory, page_url, links, name, phones=()):
    """-> (url or None, urlKind 'listing'|'search'). links = [{href, text, card?, aria?}] from the matched page."""
    if is_permalink(directory, page_url):
        return _clean(page_url), "listing"
    pd = re.sub(r"^www\.", "", urlparse(page_url or "").netloc)
    for l in links or []:
        href = l.get("href") or ""
        if directory not in urlparse(href).netloc or not is_permalink(directory, href): continue
        hay = " ".join([l.get("text") or "", l.get("aria") or ""])
        card = l.get("card") or ""
        digits = re.sub(r"\D", "", card)
        if _name_hit(hay, name) or any(p and p in digits for p in phones) or _name_hit(card, name) and len(_tok(card)) < 60:
            return _clean(href), "listing"
    return None, "search"
