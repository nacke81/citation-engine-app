"""Claim-status detection for one found listing. Pure functions: page text in, status out. The only network code is http_get (GET only).

claim_status is one of:
  unclaimed  the page of THIS listing shows a marker that only an unclaimed listing shows (a "Claim this business" call to action)
  claimed    the page of THIS listing shows a marker that only a claimed listing shows (a "Claimed" badge)
  unknown    no positive marker was found

Golden rule (same as absent): a status needs a positive marker. A missing unclaimed marker never means claimed. A marker the
Directory shows on every page (a site footer "Claim your business") is not a marker for this listing and is never used.
Only Directories whose marker was seen on a real page have a rule here. Everything else is unknown by design (see UNVERIFIED).

claim_evidence = {text, url, date, directory}: the exact on-page text, the page it was read from, and the day.
"""
import re
from datetime import date

import fixlist

CLAIM_ACTION = "claim"
LOGIN_UNCLAIMED = "none: unclaimed, citation-submitter creates account under listings@"
LOGIN_CLAIMED = "client account needed"


def page_lines(text):
    return [l.strip() for l in (text or "").replace("\r", "").split("\n") if l.strip()]


def html_to_text(html):
    """Rendered-text approximation of a GET response: scripts/styles dropped, one line per tag boundary."""
    import html as H
    s = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>", "\n", html or "")
    s = re.sub(r"(?s)<!--.*?-->", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", "\n", s)
    return "\n".join(l.strip() for l in H.unescape(s).replace("\xa0", " ").split("\n") if l.strip())


# ---- per-Directory marker rules. Each returns (status, quote) or None. ------------------------------------------------
def _mapquest(lines, ctx):
    # record page: the infosheet shows "Own this business?" then a "Claim it" button. The footer "Claim your business" is ignored.
    for i, l in enumerate(lines[:-1]):
        if l == "Own this business?" and lines[i + 1] == "Claim it":
            return "unclaimed", "Own this business? / Claim it"
    return None


def _merchantcircle(lines, ctx):
    # record page: "Is this your business?" directly followed by "Claim your business now". Both lines are required.
    for i, l in enumerate(lines[:-1]):
        if l == "Is this your business?" and lines[i + 1] == "Claim your business now":
            return "unclaimed", "Is this your business? / Claim your business now"
    return None


def _yellowpages(lines, ctx):
    # record page: a "Claimed" badge in the listing header, on its own line or glued to the category line ("ClaimedSenior ...").
    # Positive marker only: this rule can return claimed, never unclaimed (the unclaimed page was a 403 wall, not verified).
    for l in lines[:40]:
        if l == "Claimed":
            return "claimed", l
        if re.match(r"^Claimed(?=[A-Z])", l):
            return "claimed", "Claimed"
    return None


def _hotfrog(lines, ctx):
    # The call to action must sit directly under THIS listing's own block (name, category, street) so another business's button never counts.
    if ctx.get("permalink"):
        # record page (/company/...): the page is the listing; the call to action is two lines. A claimed listing does not show it.
        for i, l in enumerate(lines):
            if l == "Is this your business? Claim this business":      # one line in the engine's Chrome text
                return "unclaimed", "Is this your business? / Claim this business"
            if l == "Is this your business?" and i + 1 < len(lines) and lines[i + 1] == "Claim this business":   # two lines in GET html
                return "unclaimed", "Is this your business? / Claim this business"
        return None
    ident, b = ctx.get("ident"), ctx.get("biz")
    if not ident or not b:
        return None
    block = fixlist.listing_block("\n".join(lines), ident, b)
    if not block:
        return None
    for i in range(len(lines) - len(block)):
        if lines[i:i + len(block)] == block:
            nxt = lines[i + len(block)]
            return ("unclaimed", nxt) if nxt == "Is this your business? Claim this business" else None
    return None


RULES = {"mapquest.com": _mapquest, "merchantcircle.com": _merchantcircle, "yellowpages.com": _yellowpages, "hotfrog.com": _hotfrog}
# Hotfrog's own results page carries the listing card with its call to action; every other rule needs a record permalink.
RESULTS_PAGE_OK = ("hotfrog.com",)
# Not verified on 2026-10-20. Always unknown. Reasons:
#   superpages, dexknows: 403 bot wall on GET (the weekly job's Chrome text had only a site-wide footer link, which is not a listing marker)
#   bing, google: results shell with no readable text on GET; the engine's own saved text has no claim marker
#   maps.apple.com: "Claim This Place" seen only on a place page of another business; the SCC match is a search page. No SCC place link to verify
#   cybo: "Claim Business" is shown, but the page strings also say "This business is already claimed", so the button may show on claimed pages too
#   n49: "Business Claimed" next to "Verified by Yext" with no unclaimed page to compare; a Yext feed is not an owner claim
UNVERIFIED = ("superpages.com", "dexknows.com", "bing.com", "google.com", "maps.apple.com", "cybo.com", "n49.com")


def detect(directory, page_url, text, ident=None, biz=None, day=None):
    """-> {claim_status, claim_evidence}. page_url = the page the text was read from."""
    import listing
    day = day or date.today().isoformat()
    unknown = {"claim_status": "unknown", "claim_evidence": None}
    fn = RULES.get(directory)
    if not fn or not text or not page_url:
        return unknown
    perm = listing.is_permalink(directory, page_url)
    if directory not in RESULTS_PAGE_OK and not perm:
        return unknown
    got = fn(page_lines(text), {"ident": ident, "biz": biz, "permalink": perm})
    if not got:
        return unknown
    status, quote = got
    return {"claim_status": status, "claim_evidence": {"text": quote, "url": page_url, "date": day, "directory": directory}}


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def http_get(url):
    """GET only. Returns (status code, html). A 4xx/5xx or a network failure returns (code, '') so the caller records unknown."""
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"}), timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def read_claim(directory, page_url, ident, biz, getter=None, day=None):
    """GET-only re-read of one page -> claim fields. A page that does not load gives unknown."""
    if not page_url:
        return {"claim_status": "unknown", "claim_evidence": None}
    code, html = (getter or http_get)(page_url)
    return detect(directory, page_url, html_to_text(html) if code == 200 else "", ident, biz, day)


def apply_to_queue_row(row, claim):
    """Return a copy of a fix_queue row updated from claim. state and mike_approval are never touched. unknown leaves the row as is."""
    out = dict(row)
    st = claim.get("claim_status", "unknown")
    out["claim_status"] = st
    out["claim_evidence"] = claim.get("claim_evidence") if st != "unknown" else row.get("claim_evidence")
    if st == "unclaimed":
        out["fix_method"], out["login"] = CLAIM_ACTION, LOGIN_UNCLAIMED
    elif st == "claimed":
        out["login"] = LOGIN_CLAIMED
    return out


def merge_into_queue(queue, claims):
    """claims: {directory: claim dict}. Updates fix_queue rows in place by directory. Idempotent. Returns queue.
    An unknown read never downgrades a known status already on the row (a blocked re-read is not evidence)."""
    for i, r in enumerate(queue.get("fix_queue", [])):
        c = claims.get(r.get("directory"))
        if c is None:
            continue
        if c.get("claim_status") == "unknown" and r.get("claim_status") in ("claimed", "unclaimed"):
            continue
        queue["fix_queue"][i] = apply_to_queue_row(r, c)
    return queue
