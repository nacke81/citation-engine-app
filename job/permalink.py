"""Permalink gate. A found row may store only a listing (record) URL, never a search, category or guessed-slug page. Pure functions, no network.

is_permalink(directory, url) -> (ok, reason)
  - empty url fails
  - fixlist.SEARCHY_URL_RE match fails (a Bing local_ypid link is the one exception: it lives on a /maps/search path but names one place)
  - a directory in LISTING_SHAPES must also match its shape
  - a directory with no known shape passes if not searchy; apply_gate then marks the row _permalink_unverified so the portal and Mike can see it
apply_gate(check) is called once per row in run.build(), the single point every row passes before the build DB, portal, Directory database and Proof.
A found row whose URL fails becomes couldnt_check, note "no permalink", url None, and keeps the rejected URL in _rejected_url. It is never dropped.
Local keys start with "_" and are stripped before any database write, so there is no schema change.
"""
import re
from urllib.parse import urlparse

from fixlist import SEARCHY_URL_RE

NO_PERMALINK = "no permalink"

# directory -> regex over path (+ ?query). Bing is matched over the whole URL (local_ypid lives in the query).
LISTING_SHAPES = {
    "yellowpages.com": r"^/[^/]+/mip/[^/?]+-\d+",
    "superpages.com": r"^/[^/]+/bpp/[^/?]+-\d+",
    "dexknows.com": r"^/[^/]+/bp/[^/?]+-\d+",
    "google.com": r"^/maps/place/",
    "maps.apple.com": r"^/place\?|place-id=",
    "bing.com": r"local_ypid|ss=id\.",
    "facebook.com": r"^/(p/[^/?]+-\d+|people/[^/]+/\d+|(?!(?:search|public|pages|groups|watch|marketplace|events|login|help|policies|sharer|share|l\.php)(?:/|$))[A-Za-z0-9.\-]{3,})/?$",
    "merchantcircle.com": r"^/[a-z0-9\-]+-[a-z]{2}/?$",
    "hotfrog.com": r"^/company/[^/?]+/[^/?]+",
    "cybo.com": r"^/US-biz/[^/]+/?$",
    "mapquest.com": r"^/[^?#]*-\d+/?$",
    "n49.com": r"^/biz/\d+",
    "yellowbot.com": r"^/[^/?]+\.html$",
    "yelp.com": r"^/biz/[^/?]+",
    "bbb.org": r"/profile/",
    "chamberofcommerce.com": r"^/united-states/[^?]*/\d+-",
}


def _path(u):
    p = urlparse(u)
    return p.path + (("?" + p.query) if p.query else "")


def is_verified_shape(directory):
    """True when the directory has a known listing shape (so a pass is a verified pass)."""
    return directory in LISTING_SHAPES


def is_permalink(directory, url):
    """-> (ok, reason). reason is '' on a pass."""
    if not url or not str(url).strip():
        return False, "empty url"
    url = str(url)
    shape = LISTING_SHAPES.get(directory)
    is_bing_place = directory == "bing.com" and re.search(LISTING_SHAPES["bing.com"], url)
    if SEARCHY_URL_RE.search(url) and not is_bing_place:
        return False, "searchy url"
    if shape is None:
        return True, ""
    target = url if directory == "bing.com" else _path(url)
    if not re.search(shape, target):
        return False, "not a listing shape for " + directory
    return True, ""


def apply_gate(c):
    """Mutates one build() check in place. Only a found row is touched. Returns the same dict."""
    if c.get("result") != "found":
        return c
    # build() runs listing.resolve first, which sets url None when only a search page matched; the page it matched on is _page.
    ok, why = is_permalink(c.get("directory"), c.get("url"))
    if ok:
        if not is_verified_shape(c.get("directory")):
            c["_permalink_unverified"] = True
        return c
    c["_rejected_url"] = c.get("url") or c.get("_page")
    c["_permalink_reason"] = why
    c.update(result="couldnt_check", url=None, note=NO_PERMALINK, name_match=None, street_match=None, phone_match=None,
             match=None, nap_shown=None, diffs=None)
    for k in ("_claim", "_proof", "_page"):
        c.pop(k, None)
    return c
