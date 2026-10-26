"""citysquares.com claim playbook, scripted from the batch 11 run (t_cc3bafef, 2026-10-26) that put SCC live: https://citysquares.com/b/alder-care-consulting-solutions-10000001

CitySquares already HAD a listing for the business, so this is a CLAIM of an existing listing, not a create: find the listing -> Claim -> account (vault item
`SCC - citysquares.com`) -> the listing shows the approved NAP. Batch 11 saw no verify step (no mail, phone, SMS or postcard), so no verify_type.
The site's Cloudflare checkbox cleared in the build Chrome (job/build_chrome.py, CDP 9333); this module waits for it and never solves or bypasses it
(a full-page interstitial that does not clear = WALL:cloudflare-click). Batch 11 saved no selectors, so fields are found by visible LABEL and a missing
label stops the run with "form changed: ..." (no guessing). Add-business entry point for a NEW listing: https://citysquares.com/add_business (not scripted: claim only).
NOT run live in the card that added it. Every network edge is injectable. NAP comes from the caller (approved SCC identity), never from this file.

  python job/playbooks/citysquares.py --dry-run
  python job/playbooks/citysquares.py --live      # refused here: a Nate card must name it (writes a Directory account)
"""
import os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hotfrog as H

PlaybookError = H.PlaybookError
CDP_URL = "http://127.0.0.1:9333"
LISTING_RE = re.compile(r"^https://citysquares\.com/b/[a-z0-9\-]+-\d+$")
STEPS = ("open_listing", "wait_cloudflare", "claim", "account", "check_public_page")
WALL = re.compile(r"(?i)just a moment|performing security verification|performing a quick security check|verify you are (a )?human")
PASSWORD_MAX = 64


def wait_out_check(page, seconds=60):
    for _ in range(max(1, seconds // 2)):
        if not WALL.search(page.inner_text("body")[:3000]): return
        page.wait_for_timeout(2000)
    raise PlaybookError("WALL:cloudflare-click: the check did not clear in %ds in the build Chrome; park the row, no CapSolver, no bypass" % seconds)


def listing_url(url):
    if not LISTING_RE.match(url or ""): raise PlaybookError("not a citysquares listing URL (https://citysquares.com/b/<slug>-<id>): %r" % url)
    return url


def field(page, label):
    loc = page.get_by_label(label, exact=False)
    if loc.count() == 0: raise PlaybookError("form changed: no field labelled %r" % label)
    return loc.first


def click_claim(page):
    b = page.get_by_role("link", name=re.compile(r"claim", re.I))
    if b.count() == 0: b = page.get_by_role("button", name=re.compile(r"claim", re.I))
    if b.count() == 0: raise PlaybookError("no Claim control on the listing (already claimed, or the page changed)")
    b.first.click(); page.wait_for_timeout(4000)


def account(page, email_addr, password):
    if not password or len(password) > PASSWORD_MAX: raise PlaybookError("password is empty or longer than %d characters" % PASSWORD_MAX)
    field(page, "Email").fill(email_addr)
    field(page, "Password").fill(password)
    btn = page.get_by_role("button", name=re.compile(r"sign up|create|continue|claim|submit|register", re.I))
    if btn.count() == 0: raise PlaybookError("form changed: no account submit button")
    btn.first.click(); page.wait_for_timeout(5000)


def check_public_page(page, url, *, phone_digits, name, street):
    """Signed-out render of the listing: name, street and phone all shown."""
    page.goto(listing_url(url), wait_until="domcontentloaded"); wait_out_check(page)
    t = page.inner_text("body")
    return {"name": name.lower() in t.lower(), "street": street.lower() in t.lower(), "phone": phone_digits in re.sub(r"\D", "", t)}


def run(page, *, url, email_addr, get_password):
    """Returns {steps}. Raises PlaybookError at the first step that cannot be confirmed. Never prints the password."""
    if get_password is None: raise PlaybookError("a get_password() callable (Vaultwarden) is required")
    res = {"steps": []}
    page.goto(listing_url(url), wait_until="domcontentloaded"); res["steps"].append("open_listing")
    wait_out_check(page); res["steps"].append("wait_cloudflare")
    click_claim(page); res["steps"].append("claim")
    account(page, email_addr, get_password()); res["steps"].append("account")
    return res   # the caller then reads the public page with check_public_page (signed out)


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="citysquares.com claim playbook (build Chrome, CDP 9333)")
    a.add_argument("--cdp", default=CDP_URL)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true"); g.add_argument("--live", action="store_true")
    n = a.parse_args(argv)
    if n.dry_run:
        print("steps: %s\ncdp: %s\nkind: claim of an EXISTING listing (https://citysquares.com/b/<slug>-<id>)\ncloudflare: wait only, WALL:cloudflare-click if it does not clear\nverify_type: none (no verify step in batch 11)" % (" -> ".join(STEPS), n.cdp))
        return 0
    raise SystemExit("--live needs a Nate card and a Vaultwarden password callable; wire them in the calling scratch file (run(page, ...)).")


if __name__ == "__main__":
    sys.exit(main())
