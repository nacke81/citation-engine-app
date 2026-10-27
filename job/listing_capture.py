"""Capture what a Directory shows right after a submit (t_3ac43137): the public listing URL if the page is one, else the owner-view URL or the
confirmation URL, plus a listing id when the page prints one. Five rows (bbb, loc8nearme, getlistedusa, businessyab, discoverourtown) were recorded with
no permalink because nothing kept these. Pure: capture(directory, page_url, text) never touches the network.

Stored on the queue row as listing_url (+ listing_id). recheck maps an owner-view URL to the public URL only where the pattern is KNOWN
(OWNER_TO_PUBLIC below, verified per Directory); otherwise it keeps reading the stored URL as before.
"""
import re
from urllib.parse import urlparse

import listing as L

# Entry / confirmation pages: the way INTO a Directory or its thank-you step. Worth keeping as a lead, never a permalink.
CONFIRM_RE = re.compile(r"(?i)/(thank-?you[^/]*|success|submission|payment(\.php)?|confirm(ation)?)([/?#.]|$)|thankyou|[?&](uuid|submission_id)=")
# Owner-view pages (logged-in listing manager). Never read as the public listing: signed-in views give false lives (t_ac8b1bdd).
OWNER_RE = re.compile(r"(?i)/(account|dashboard|my-?listings?|manage|owner)/")
ID_PATTERNS = (
    re.compile(r"(?i)\b(?:company|listing|business|spot|submission|reference|confirmation)\s*(?:id|number|no\.?|#)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-]{3,24})"),
    re.compile(r"(?i)[?&](?:uuid|id|listing_?id|business_?id)=([A-Za-z0-9\-]{4,40})"),
    re.compile(r"(?i)/(?:businesses?|listings?|spots?|companies)/(\d{2,12})(?:[/?#]|$)"),
)
# Owner-view URL -> public URL, only where the pattern is known and verified. {id} comes from the owner URL's last numeric/slug id.
# Empty entries are honest: a Directory not listed here keeps its stored URL (listyourbusiness /account/businesses/<id> has NO id-based public page: 404).
OWNER_TO_PUBLIC = {
    # "example.com": (r"^https://example\.com/account/listings/(?P<id>\d+)", "https://example.com/listing/{id}"),
}


def listing_id(text, url=""):
    for rx in ID_PATTERNS:
        m = rx.search(url or "") if rx.pattern.startswith("(?i)[?&]") or rx.pattern.startswith("(?i)/") else rx.search(text or "")
        if m: return m.group(1)
    return None


def public_url(directory, url, table=None):
    """The public listing URL for an owner-view URL when the Directory's pattern is known, else None."""
    pat = (table if table is not None else OWNER_TO_PUBLIC).get(directory)
    if not pat or not url: return None
    m = re.search(pat[0], url)
    return pat[1].format(**m.groupdict()) if m else None


def capture(directory, page_url, text="", table=None):
    """-> {"listing_url": str|None, "kind": "listing"|"public-from-owner"|"owner"|"confirmation"|None, "listing_id": str|None}.
    Priority: a real permalink on the page > a public URL built from an owner-view id > the owner-view URL > the confirmation URL."""
    url = (page_url or "").split("#")[0]
    out = {"listing_url": None, "kind": None, "listing_id": listing_id(text, url)}
    if not url or urlparse(url).scheme not in ("http", "https") or "@" in urlparse(url).netloc: return out
    path = urlparse(url).path
    pub = public_url(directory, url, table)
    if pub: out.update(listing_url=pub, kind="public-from-owner")
    elif CONFIRM_RE.search(path + "?" + (urlparse(url).query or "")): out.update(listing_url=url, kind="confirmation")
    elif OWNER_RE.search(path): out.update(listing_url=url, kind="owner")
    elif L.is_permalink(directory, url) and path.strip("/") and not _entry(url): out.update(listing_url=url, kind="listing")   # a register / add / signup form is never kept
    return out


def _entry(url):
    import recheck as R   # the add / register / claim / dashboard page test lives with recheck
    return R._is_entry_page(url)
