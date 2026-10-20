"""Verified per-Directory claim markers. Pure rules; no fetching or queue updates."""
import re

import fixlist

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
    # Chrome rendered form (read 2026-10-20): head, one blurb line, then the button
    return _cta(lines, ("Is this your business?",), ("Claim your business to updated business information, add photos and more.",),
                "Claim this business", "Is this your business? / Claim this business")


def _yellowpages(lines, ctx):
    # record page. Claimed: a "Claimed" badge in the listing header, on its own line or glued to the category line ("ClaimedSenior ...").
    # Unclaimed (verified by Chrome read 2026-10-20): the header block "Is this your business?" / ["Customize this page."] / "Claim This Business".
    # The footer "Manage your free listing / Claim Your Listing" is site-wide and never counts. Both markers on one page is a conflict: unknown.
    claimed = None
    for l in lines[:40]:
        if l == "Claimed":
            claimed = ("claimed", l); break
        if re.match(r"^Claimed(?=[A-Z])", l):
            claimed = ("claimed", "Claimed"); break
    cta = _cta(lines, ("Is this your business?",), ("Customize this page.",), "Claim This Business", "Is this your business? / Claim This Business")
    if claimed and cta:
        return None
    return claimed or cta


def _cta(lines, heads, optional, button, quote):
    """A call to action: a head line, optional filler lines, then the button line, all consecutive (so a stray button never counts)."""
    for i, l in enumerate(lines):
        if l not in heads:
            continue
        j = i + 1
        while j < len(lines) and lines[j] in optional:
            j += 1
        if j < len(lines) and lines[j] == button:
            return "unclaimed", quote
    return None


def _superpages(lines, ctx):
    # record page (/bpp/...): "Are you the business owner?" directly followed by "Claim This Business" (verified by Chrome read 2026-10-20).
    # superpages answers a plain GET with 403, so this is read from the engine's Chrome text. Footer "Claim Your Business / Claim Your Listing" is ignored.
    # Only the unclaimed side is proven: a page without the pair stays unknown, never claimed.
    return _cta(lines, ("Are you the business owner?",), (), "Claim This Business", "Are you the business owner? / Claim This Business")


def _n49(lines, ctx):
    # record page (/biz/<id>): the unclaimed control is "Own this Business" followed by "Get Verified" (the owner call to action).
    # "Business Claimed / Update your Business" is NOT read as claimed: see UNVERIFIED note on n49.
    return _cta(lines, ("Own this Business",), (), "Get Verified", "Own this Business / Get Verified")


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


RULES = {"mapquest.com": _mapquest, "merchantcircle.com": _merchantcircle, "yellowpages.com": _yellowpages, "hotfrog.com": _hotfrog,
         "superpages.com": _superpages, "n49.com": _n49}
# Hotfrog's own results page carries the listing card with its call to action; every other rule needs a record permalink.
RESULTS_PAGE_OK = ("hotfrog.com",)
