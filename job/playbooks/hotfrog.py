"""hotfrog.com build playbook, scripted from the run that went live 2026-10-25 (batch 4, Lis): register -> email verify from listings@ -> add website.

Drives the build Chrome through CDP (default http://127.0.0.1:9333, start it with job/build_chrome.py). Reads the verify mail through the
LISTINGS_IMAP_HOST / _PORT / _USER / _PASSWORD env (read-only: EXAMINE + peek). Never prints or returns a password.
NOT run live in the card that added it. Every network edge is injectable (page, mailbox) so tests make no call.

  python job/playbooks/hotfrog.py --dry-run          # prints the plan, touches nothing
  python job/playbooks/hotfrog.py --live             # real run; a Nate card must name it (writes a Directory account)

The NAP comes from cfg (the approved SCC identity file), never from this file. The account password is supplied by `get_password()`
(Vaultwarden helper at run time); this module has no default and refuses to run without one.
"""
import email, imaplib, os, re, sys, time
from email.header import decode_header, make_header

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

CDP_URL = "http://127.0.0.1:9333"
REGISTER_URL = "https://www.hotfrog.com/register"
VERIFY_RE = re.compile(r"https://www\.hotfrog\.com/verify-email/[^\s\"'<>)]+")
SENDER_HINT = "hotfrog"
WEBSITE = "https://seniorcaresolutions.co"


def site_value(website):
    """The value hotfrog's website field takes: one https:// in front, nothing doubled (t_64c4d511). The page then shows the bare host and links the https URL."""
    w = re.sub(r"^(?:https?://)+", "", (website or "").strip(), flags=re.I).strip("/ ")
    if not w: raise PlaybookError("website is empty")
    return "https://" + w.lower()
STEPS = ("register", "read_verify_mail", "open_verify_link", "add_website")


class PlaybookError(Exception):
    pass


class MailboxNotRead(PlaybookError):
    """The mailbox login could not be had (env empty and vault unreadable). The message starts MAILBOX NOT READ."""


def extract_verify_link(raw_message):
    """First hotfrog verify-email link in a raw RFC822 message (text or html part, quoted-printable decoded). None if absent."""
    msg = email.message_from_bytes(raw_message) if isinstance(raw_message, bytes) else email.message_from_string(raw_message)
    for part in msg.walk():
        if part.get_content_type() not in ("text/plain", "text/html"): continue
        body = part.get_payload(decode=True)
        if body is None: continue
        m = VERIFY_RE.search(body.decode(part.get_content_charset() or "utf-8", "replace").replace("&amp;", "&"))
        if m: return m.group(0)
    return None


def mail_env(env=None, vault=None):
    """listings@ IMAP login. The env wins. LISTINGS_IMAP_PASSWORD empty -> read the vault item (job/imap_vault.py, t_d2f75685), password in memory only.
    The vault is asked when env is None (the real process env) or a `vault` callable is passed; an explicit env dict without a password is an error."""
    use_vault_ok = env is None or vault is not None
    env = os.environ if env is None else env
    out = {k.lower(): env.get("LISTINGS_IMAP_" + k) for k in ("HOST", "PORT", "USER", "PASSWORD")}
    if not out["password"] and use_vault_ok:
        import imap_vault as IV
        try: got = (vault or IV.fetch)()
        except IV.MailboxNotRead as e: raise MailboxNotRead(str(e))
        for k in ("host", "port", "user", "password"):
            out[k] = out[k] or got.get(k)
    for k in ("host", "port", "user", "password"):
        if not out[k]:
            if k == "password": raise MailboxNotRead("MAILBOX NOT READ: LISTINGS_IMAP_PASSWORD is not set and the vault was not asked")
            raise PlaybookError("LISTINGS_IMAP_%s is not set" % k.upper())
    return out


class ImapMailbox:
    """Read-only: EXAMINE the INBOX and PEEK. Marks nothing read, deletes nothing."""
    def __init__(self, env=None, imap_cls=imaplib.IMAP4_SSL, extract=None, sender_hint=None, vault=None):
        self.cfg, self.imap_cls = mail_env(env, vault), imap_cls   # t_d2f75685: vault fallback when the env has no password
        self.extract, self.sender_hint = extract or extract_verify_link, sender_hint or SENDER_HINT   # other playbooks reuse this reader with their own link pattern

    def newest_verify_link(self, since_uid=0, sender_hint=None):
        sender_hint = sender_hint or self.sender_hint
        m = self.imap_cls(self.cfg["host"], int(self.cfg["port"]))
        try:
            m.login(self.cfg["user"], self.cfg["password"])
            m.select("INBOX", readonly=True)
            typ, data = m.uid("SEARCH", None, "ALL")
            uids = [int(u) for u in (data[0] or b"").split()]
            for uid in sorted((u for u in uids if u > since_uid), reverse=True)[:15]:
                typ, d = m.uid("FETCH", str(uid), "(BODY.PEEK[])")
                raw = next((x[1] for x in d if isinstance(x, tuple)), None)
                if raw is None: continue
                msg = email.message_from_bytes(raw)
                frm = str(make_header(decode_header(msg.get("From", ""))))
                if sender_hint not in frm.lower(): continue
                link = self.extract(raw)
                if link: return uid, link
            return None
        finally:
            try: m.logout()
            except Exception: pass

    def max_uid(self):
        m = self.imap_cls(self.cfg["host"], int(self.cfg["port"]))
        try:
            m.login(self.cfg["user"], self.cfg["password"]); m.select("INBOX", readonly=True)
            typ, data = m.uid("SEARCH", None, "ALL")
            return max([int(u) for u in (data[0] or b"").split()] or [0])
        finally:
            try: m.logout()
            except Exception: pass


def register(page, name, email_addr, password, goto_wait_ms=3000):
    """Fill the register form and submit. Stops with an error if the form is not the expected one (no guessing)."""
    page.goto(REGISTER_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(goto_wait_ms)
    for sel in ("#name", "#email", "#accept_terms"):
        if page.locator(sel).count() == 0: raise PlaybookError("register form changed: %s not found" % sel)
    page.fill("#name", name)
    page.fill("#email", email_addr)
    if page.locator("input[type=password]").count(): page.fill("input[type=password]", password)  # present on some variants only
    page.check("#accept_terms")
    page.get_by_role("button", name="Register").first.click()
    page.wait_for_timeout(7000)
    return page.url


def add_website(page, website=WEBSITE):
    """On the company edit page: first type=url input, then the Add button after it. Returns True when the site text shows on the page."""
    inp = page.locator("input[type=url]").first
    if page.locator("input[type=url]").count() == 0: raise PlaybookError("website field not found on this page")
    inp.fill(site_value(website))
    inp.locator("xpath=following::button[normalize-space()='Add' or @type='submit'][1]").click(timeout=10000)
    page.wait_for_timeout(5000)
    return site_value(website).replace("https://", "") in page.inner_text("body")


def run(page, mailbox, *, name, email_addr, get_password, website=WEBSITE, poll_seconds=120, poll_every=10, sleep=time.sleep, now=time.time):
    """Full playbook. Returns {steps, verify_uid, website_added}. Raises PlaybookError at the first step that cannot be confirmed."""
    if get_password is None: raise PlaybookError("a get_password() callable (Vaultwarden) is required")
    res = {"steps": [], "verify_uid": None, "website_added": False}
    base = mailbox.max_uid()
    register(page, name, email_addr, get_password())
    res["steps"].append("register")
    deadline = now() + poll_seconds
    found = None
    while now() < deadline:
        found = mailbox.newest_verify_link(since_uid=base)
        if found: break
        sleep(poll_every)
    if not found: raise PlaybookError("no hotfrog verify mail from listings@ within %ds" % poll_seconds)
    res["verify_uid"], link = found
    res["steps"].append("read_verify_mail")
    page.goto(link, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    res["steps"].append("open_verify_link")
    res["website_added"] = add_website(page, website)
    if not res["website_added"]: raise PlaybookError("website was not shown after Add; check the page by hand")
    res["steps"].append("add_website")
    return res


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="hotfrog.com build playbook (build Chrome, CDP 9333)")
    a.add_argument("--cdp", default=CDP_URL)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true"); g.add_argument("--live", action="store_true")
    n = a.parse_args(argv)
    if n.dry_run:
        print("steps: %s\ncdp: %s\nregister: %s\nmail: LISTINGS_IMAP_* env, read-only" % (" -> ".join(STEPS), n.cdp, REGISTER_URL))
        return 0
    raise SystemExit("--live needs a Nate card and a Vaultwarden password callable; wire them in the calling scratch file (run(page, mailbox, ...)).")


if __name__ == "__main__":
    sys.exit(main())
