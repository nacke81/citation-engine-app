"""bizapedia.com claim playbook, scripted from the run that went live 2026-10-25 (batch 5, t_1682540a) and the claim form read on 2026-10-25 (t_64c4d511).

Free claim of an existing Secretary-of-State mirror page: open the company page -> "Claim Profile" -> email + new account -> company details -> terms ->
submit -> validate through the mail sent to listings@ -> Bizapedia approves ("Claim Request Approved") -> the public page shows "Claimed", the phone and the site.
Drives the build Chrome through CDP (default http://127.0.0.1:9333, start it with job/build_chrome.py). The site's Cloudflare Turnstile ("Performing a quick
security check") clears by itself in the real Chrome; this module waits for it and never tries to solve or bypass it.
Reads the validation mail through LISTINGS_IMAP_HOST / _PORT / _USER / _PASSWORD (read-only, same reader as hotfrog.py). Never prints or returns a password.
NOT run live in the card that added it. Every network edge is injectable (page, mailbox), so tests make no call.

  python job/playbooks/bizapedia.py --dry-run     # prints the plan, touches nothing
  python job/playbooks/bizapedia.py --live        # refused here: a Nate card must name it (writes a Directory account)

Form facts (read, not guessed):
  * The password inputs allow 20 characters (maxlength=20). A longer vault password is cut silently, so run() refuses one.
  * Relationship is a select (Owner, Co-Owner, ...); official job title is free text. SCC: Owner / Owner.
  * Website: the form text says the value must be a live https:// URL ("start with https://") or it is not approved. Its FormatUrl() only trims and lowercases,
    it does NOT prepend a scheme. So the value is typed WITH https:// exactly once. The public page's JSON-LD showed "https://https://seniorcaresolutions.co"
    for the live listing, which means that value was typed with a second scheme; site_value() below makes that impossible.
  * Company phone has an onchange FormatUsPhone, so any 10-digit format is accepted.
The NAP comes from the caller (cfg: the approved SCC identity file), never from this file.
"""
import os, re, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hotfrog as H   # shared IMAP reader and PlaybookError

PlaybookError = H.PlaybookError
CDP_URL = "http://127.0.0.1:9333"
CLAIM_PATH_RE = re.compile(r"https://www\.bizapedia\.com/company-claim\.aspx\?companyid=[A-Za-z0-9]+")
VERIFY_RE = re.compile(r"https://www\.bizapedia\.com/(?=[^\s\"'<>)]*(?:valid|confirm|verify))[A-Za-z0-9_\-./]*\.aspx\?[^\s\"'<>)]+", re.I)   # unverified shape: see risks in the card handoff
SENDER_HINT = "bizapedia"
PASSWORD_MAX = 20
RELATIONSHIPS = ("Owner", "Co-Owner", "Partner", "Member", "Manager", "CEO", "President", "Vice-President", "Director", "Associate", "Employee", "Independent Contractor/Consultant")
STEPS = ("open_company", "open_claim", "account", "company_details", "terms_submit", "read_validate_mail", "open_validate_link", "check_public_page")
WALL = re.compile(r"(?i)performing a quick security check|just a moment")


def site_value(website):
    """The value the website field must hold: https:// exactly once (the form does not add it), lower case, no trailing slash."""
    w = re.sub(r"^(?:https?://)+", "", (website or "").strip(), flags=re.I).strip("/ ")
    if not w: raise PlaybookError("website is empty")
    return "https://" + w.lower()


def split_name(full):
    """'Pat Example Smith' -> ('Pat Example', 'Smith'). Last word is the surname."""
    parts = (full or "").split()
    if len(parts) < 2: raise PlaybookError("contact name needs a first and a last name")
    return " ".join(parts[:-1]), parts[-1]


def extract_validate_link(raw_message):
    """First bizapedia validation link in a raw message. None if absent. Reuses hotfrog's decoding with this site's pattern."""
    saved = H.VERIFY_RE
    H.VERIFY_RE = VERIFY_RE
    try: return H.extract_verify_link(raw_message)
    finally: H.VERIFY_RE = saved


def mailbox(env=None, imap_cls=None):
    kw = {"imap_cls": imap_cls} if imap_cls else {}
    return H.ImapMailbox(env, extract=extract_validate_link, sender_hint=SENDER_HINT, **kw)


def wait_out_check(page, seconds=60):
    """Turnstile page clears by itself in the real Chrome. Wait; never solve. Error if it does not clear."""
    for _ in range(max(1, seconds // 2)):
        if not WALL.search(page.inner_text("body")[:3000]): return
        page.wait_for_timeout(2000)
    raise PlaybookError("security check did not clear in %ds; needs a human or a proxy, not a bypass" % seconds)


def open_claim(page, company_url):
    """Company page -> its Claim Profile target. The claim link carries a per-company id that differs from the contact link's id, so read it from the button."""
    page.goto(company_url, wait_until="domcontentloaded")
    wait_out_check(page)
    target = page.evaluate("() => { const b = [...document.querySelectorAll('a,button,input[type=button]')].find(e => /claim profile/i.test(e.innerText || e.value || '')); "
                           "return b ? ((b.href || '') + ' ' + (b.getAttribute('onclick') || '')) : ''; }")
    m = CLAIM_PATH_RE.search(target or "")
    if not m: raise PlaybookError("no Claim Profile button on the company page (already claimed, or the page changed)")
    page.goto(m.group(0), wait_until="domcontentloaded")
    wait_out_check(page)
    return m.group(0)


def need(page, *sels):
    for s in sels:
        if page.locator(s).count() == 0: raise PlaybookError("claim form changed: %s not found" % s)


def fill_account(page, email_addr, password, first, last):
    """Email -> Continue unlocks the rest. New account: password, first and last name."""
    need(page, "#txtEmail", "#txtPassword")
    page.fill("#txtEmail", email_addr)
    page.get_by_role("button", name="Continue").first.click()
    page.wait_for_timeout(4000)
    need(page, "#txtNewPassword", "#txtNewFirstName", "#txtNewLastName")
    page.fill("#txtNewPassword", password)
    page.fill("#txtNewFirstName", first)
    page.fill("#txtNewLastName", last)


def fill_company(page, *, relationship, job_title, category_group, category, location_type, products, company_email, phone, website):
    if relationship not in RELATIONSHIPS: raise PlaybookError("relationship %r is not one of the form's options" % relationship)
    need(page, "#ctl00_selRelationshipType", "#txtJobTitle", "#ctl00_selBusinessCategoryGroup", "#ctl00_selBusinessCategory", "#ctl00_selLocationType",
         "#txtProductsServices", "#txtCompanyEmail", "#txtCompanyPhone", "#txtCompanyWebsite")
    page.select_option("#ctl00_selRelationshipType", label=relationship)
    page.fill("#txtJobTitle", job_title)
    page.select_option("#ctl00_selBusinessCategoryGroup", label=category_group)
    page.wait_for_timeout(1500)   # the category list is rebuilt on group change
    page.select_option("#ctl00_selBusinessCategory", label=category)
    page.select_option("#ctl00_selLocationType", label=location_type)
    page.fill("#txtProductsServices", products)
    page.fill("#txtCompanyEmail", company_email)
    page.fill("#txtCompanyPhone", phone)
    page.fill("#txtCompanyWebsite", site_value(website))


def submit_claim(page):
    need(page, "#chbTermsOfUse", "#chbIndemnify")
    page.check("#chbTermsOfUse"); page.check("#chbIndemnify")
    page.get_by_role("button", name="Submit").first.click()
    page.wait_for_timeout(6000)


def check_public_page(page, company_url, *, phone_digits, site):
    """Public page, rendered: Claimed + phone + site all shown. Returns {claimed, phone, site}."""
    page.goto(company_url, wait_until="domcontentloaded")
    wait_out_check(page)
    t = page.inner_text("body")
    digits = re.sub(r"\D", "", t)
    return {"claimed": bool(re.search(r"(?m)^\s*Claimed\s*$", t)), "phone": phone_digits in digits, "site": site_value(site).replace("https://", "") in t.lower()}


def run(page, mb, *, company_url, name, email_addr, get_password, relationship="Owner", job_title="Owner", category_group, category, location_type="Single Location",
        products, company_email, phone, website, poll_seconds=180, poll_every=10, sleep=time.sleep, now=time.time):
    """Full playbook. Returns {steps, verify_uid, public}. Raises PlaybookError at the first step that cannot be confirmed."""
    if get_password is None: raise PlaybookError("a get_password() callable (Vaultwarden) is required")
    password = get_password()
    if not password or len(password) > PASSWORD_MAX:
        raise PlaybookError("the Bizapedia password field holds %d characters; use a vault item of at most that length" % PASSWORD_MAX)
    first, last = split_name(name)
    res = {"steps": [], "verify_uid": None, "public": None}
    base = mb.max_uid()
    page.goto(company_url, wait_until="domcontentloaded"); wait_out_check(page); res["steps"].append("open_company")
    open_claim(page, company_url); res["steps"].append("open_claim")
    fill_account(page, email_addr, password, first, last); res["steps"].append("account")
    fill_company(page, relationship=relationship, job_title=job_title, category_group=category_group, category=category, location_type=location_type,
                 products=products, company_email=company_email, phone=phone, website=website); res["steps"].append("company_details")
    submit_claim(page); res["steps"].append("terms_submit")
    deadline, found = now() + poll_seconds, None
    while now() < deadline:
        found = mb.newest_verify_link(since_uid=base)
        if found: break
        sleep(poll_every)
    if not found: raise PlaybookError("no bizapedia validation mail at listings@ within %ds" % poll_seconds)
    res["verify_uid"], link = found; res["steps"].append("read_validate_mail")
    page.goto(link, wait_until="domcontentloaded"); wait_out_check(page); res["steps"].append("open_validate_link")
    return res   # approval is by Bizapedia, later: the caller (or the weekly recheck) reads the public page, see check_public_page


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="bizapedia.com claim playbook (build Chrome, CDP 9333)")
    a.add_argument("--cdp", default=CDP_URL)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true"); g.add_argument("--live", action="store_true")
    n = a.parse_args(argv)
    if n.dry_run:
        print("steps: %s\ncdp: %s\nwebsite value: https:// once (form does not add it)\nsecret length limit: %d chars\nmail: LISTINGS_IMAP_* env, read-only" % (" -> ".join(STEPS), n.cdp, PASSWORD_MAX))
        return 0
    raise SystemExit("--live needs a Nate card and a Vaultwarden password callable; wire them in the calling scratch file (run(page, mb, ...)).")


if __name__ == "__main__":
    sys.exit(main())
