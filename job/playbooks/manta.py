"""manta.com claim/create playbook, scripted from the batch 11 run (t_cc3bafef, 2026-10-26) that put SCC live: https://www.manta.com/c/m0example/alder-care-consulting-solutions

What batch 11 proved (and what it did not):
  * curl gets 403. The site sits behind a Cloudflare checkbox that PASSES in the real build Chrome (job/build_chrome.py, CDP 9333). That checkbox is a
    full-page interstitial: this module waits for it to clear and never solves or bypasses it. If it does not clear: WALL:cloudflare-click (Mike's rule).
  * Flow: sign up (email + password) -> verification mail at listings@ -> link (it can EXPIRE: use "Resend" once, then the newest mail) -> "add your company"
    form (name, address, phone, website, category) -> a reCAPTCHA v2 checkbox (passed on one plain click in batch 11; if it does not pass,
    job/captcha_route.py prints the CapSolver command, 3 tries at most) -> the public page shows the listing as Claimed.
  * No phone/SMS/postcard step appeared, so no verify_type is ever recorded for manta.
Form fields are found by their visible LABEL, not by guessed ids; a missing label stops the run with "form changed: <label>" (no guessing).
Mail goes through hotfrog.ImapMailbox (read-only, LISTINGS_IMAP_*). Never prints or returns a password.
NOT run live in the card that added it. Every network edge is injectable (page, mailbox, sleep, clock), so tests make no call.

  python job/playbooks/manta.py --dry-run     # prints the plan, touches nothing
  python job/playbooks/manta.py --live        # refused here: a Nate card must name it (writes a Directory account)
"""
import os, re, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hotfrog as H   # shared IMAP reader and PlaybookError

PlaybookError = H.PlaybookError
CDP_URL = "http://127.0.0.1:9333"
HOME = "https://www.manta.com/"
VERIFY_RE = re.compile(r"https://www\.manta\.com/(?=[^\s\"'<>)]*(?:verify|confirm|activate|validate))[A-Za-z0-9_\-./]*(?:\?[^\s\"'<>)]+)?", re.I)   # shape unverified: batch 11 did not save a mail
SENDER_HINT = "manta"
STEPS = ("open_home", "wait_cloudflare", "sign_up", "read_verify_mail", "open_verify_link", "add_company", "recaptcha", "check_public_page")
WALL = re.compile(r"(?i)just a moment|performing security verification|performing a quick security check|verify you are (a )?human")
PUBLIC_RE = re.compile(r"^https://www\.manta\.com/c/[A-Za-z0-9]+/[a-z0-9\-]+$")
PASSWORD_MAX = 64
NAP_LABELS = (("name", "Business name"), ("street", "Address"), ("city", "City"), ("zip", "Zip"), ("phone", "Phone"), ("website", "Website"))


def extract_verify_link(raw_message):
    saved = H.VERIFY_RE
    H.VERIFY_RE = VERIFY_RE
    try: return H.extract_verify_link(raw_message)
    finally: H.VERIFY_RE = saved


def mailbox(env=None, imap_cls=None):
    kw = {"imap_cls": imap_cls} if imap_cls else {}
    return H.ImapMailbox(env, extract=extract_verify_link, sender_hint=SENDER_HINT, **kw)


def site_value(website):
    return H.site_value(website)


def wait_out_check(page, seconds=60):
    """The Cloudflare checkbox/interstitial clears in the real build Chrome. Wait; never solve. Error text carries the Mike-rule wall name."""
    for _ in range(max(1, seconds // 2)):
        if not WALL.search(page.inner_text("body")[:3000]): return
        page.wait_for_timeout(2000)
    raise PlaybookError("WALL:cloudflare-click: the check did not clear in %ds in the build Chrome; park the row, no CapSolver, no bypass" % seconds)


def field(page, label):
    loc = page.get_by_label(label, exact=False)
    if loc.count() == 0: raise PlaybookError("form changed: no field labelled %r" % label)
    return loc.first


def sign_up(page, email_addr, password):
    if not password or len(password) > PASSWORD_MAX: raise PlaybookError("password is empty or longer than %d characters" % PASSWORD_MAX)
    field(page, "Email").fill(email_addr)
    field(page, "Password").fill(password)
    btn = page.get_by_role("button", name=re.compile(r"sign up|create account|continue|register", re.I))
    if btn.count() == 0: raise PlaybookError("form changed: no sign-up button")
    btn.first.click()
    page.wait_for_timeout(5000)


def add_company(page, *, name, street, city, zip_code, phone, website):
    """Fills the add-company form from the caller's NAP (cfg: the approved SCC identity). Never defaults a value."""
    vals = {"name": name, "street": street, "city": city, "zip": zip_code, "phone": phone, "website": site_value(website)}
    for k, v in vals.items():
        if not v: raise PlaybookError("%s is empty; NAP comes from the approved identity" % k)
    for key, label in NAP_LABELS: field(page, label).fill(vals[key])


def recaptcha_click(page):
    """Batch 11: one plain click on the v2 checkbox passed. Returns True when the response token is set. If not, the caller runs job/captcha_route.py (3 tries max)."""
    frame = page.frame_locator("iframe[src*='recaptcha/api2/anchor']")
    box = frame.locator("#recaptcha-anchor")
    if box.count() == 0: return None   # no widget on this page
    box.click(); page.wait_for_timeout(3000)
    return bool(page.evaluate("() => { const t = document.querySelector('textarea[name=g-recaptcha-response]'); return !!(t && t.value); }"))


def check_public_page(page, url, *, phone_digits, name):
    """Public page, signed out, rendered: the listing shows the name, the phone, and Claimed."""
    if not PUBLIC_RE.match(url or ""): raise PlaybookError("not a manta listing URL: %r" % url)
    page.goto(url, wait_until="domcontentloaded"); wait_out_check(page)
    t = page.inner_text("body")
    return {"claimed": bool(re.search(r"(?i)\bclaimed\b", t)), "phone": phone_digits in re.sub(r"\D", "", t), "name": name.lower() in t.lower()}


def run(page, mb, *, email_addr, get_password, name, street, city, zip_code, phone, website, poll_seconds=180, poll_every=10, sleep=time.sleep, now=time.time):
    """Returns {steps, verify_uid, recaptcha}. Raises PlaybookError at the first step that cannot be confirmed."""
    if get_password is None: raise PlaybookError("a get_password() callable (Vaultwarden) is required")
    res = {"steps": [], "verify_uid": None, "recaptcha": None}
    base = mb.max_uid()
    page.goto(HOME, wait_until="domcontentloaded"); res["steps"].append("open_home")
    wait_out_check(page); res["steps"].append("wait_cloudflare")
    sign_up(page, email_addr, get_password()); res["steps"].append("sign_up")
    deadline, found = now() + poll_seconds, None
    while now() < deadline:
        found = mb.newest_verify_link(since_uid=base)
        if found: break
        sleep(poll_every)
    if not found: raise PlaybookError("no manta verification mail at listings@ within %ds (a link can expire: click Resend once, then rerun)" % poll_seconds)
    res["verify_uid"], link = found; res["steps"].append("read_verify_mail")
    page.goto(link, wait_until="domcontentloaded"); wait_out_check(page); res["steps"].append("open_verify_link")
    add_company(page, name=name, street=street, city=city, zip_code=zip_code, phone=phone, website=website); res["steps"].append("add_company")
    res["recaptcha"] = recaptcha_click(page); res["steps"].append("recaptcha")
    return res   # the caller submits, then reads the public page with check_public_page (signed out)


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="manta.com claim/create playbook (build Chrome, CDP 9333)")
    a.add_argument("--cdp", default=CDP_URL)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true"); g.add_argument("--live", action="store_true")
    n = a.parse_args(argv)
    if n.dry_run:
        print("steps: %s\ncdp: %s\ncloudflare: wait only, WALL:cloudflare-click if it does not clear\nrecaptcha: one plain click, else job/captcha_route.py (3 tries)\nverify_type: none (no phone/SMS step in batch 11)\nmail: LISTINGS_IMAP_* env, read-only; links can expire (Resend once)" % (" -> ".join(STEPS), n.cdp))
        return 0
    raise SystemExit("--live needs a Nate card and a Vaultwarden password callable; wire them in the calling scratch file (run(page, mb, ...)).")


if __name__ == "__main__":
    sys.exit(main())
