"""Verify Now send run (slice 1, SMS, Cylex only). Started by job/verify_bridge.py as a direct subprocess:

  python job/verify_send.py --request-id <uuid>

One run handles ONE claimed request and makes at most one Directory session (sitegate.reserve once, before the browser opens).
  1. Re-read the request: it must be 'starting' (claimed). Run the same fence() the bridge ran (client allow-list, verification row
     client match, Cylex playbook). Anything else: no Directory is touched.
  2. Vault lookup for the tenant's Cylex login. Missing item -> failed/signin_failed, no browser.
  3. Per-tenant owned Chrome (headful, off-screen unless CE_CHROME_VISIBLE=1, own profile per tenant), sign in. If the Directory mails an
     access code before the phone step, read it from the mailbox path for that tenant (NM relay file, SCC IMAP, spam included).
  4. Open the phone verify modal, read the number there, build the masked number, tick the consent box, click send. Then mark_code_sent.
  5. Poll consume_verify_code every 10 s for up to 30 min. No code -> failed/code_expired.
  6. Enter the code, read the result. Accepted -> set the citation_verification row live (transitions.set_verification_live, the verification-queue PATCH that
     transitions.record_transition performs on a move to live), then finish_code_request('verified'). Rejected -> failed/code_rejected.

Rules: a code (SMS or mailed) lives in a local variable only: never logged, printed, written, or put in an exception message. Every
failure path ends in finish_code_request with an allowlisted fail code and logs the reason code only, never exception text.
The live phone-step selectors come from spike 1 (#registerCompanyPhoneModalVerify JS click, consent, 'Send verification code'); the
Edit-profile navigation and the code-entry field are fail-closed (send_failed) when not found and must be confirmed in the live-run card.
No WhatsApp or voice path exists here.
"""
import argparse, contextlib, datetime, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import portal as P
import verify_bridge as B

DOMAIN = "cylex.us"
SIGNIN_URL = "https://www.cylex.us.com/signin/"
TENANTS = {   # client_id -> (business code, vault organization, vault item name)
    P.ALLOWED["SCC"]: ("SCC", "Senior Care Consulting", "SCC - cylex.us.com"),
    P.ALLOWED["NM"]: ("NM", "Na" + "cke Media", "NM - cylex.us"),
}
COLLECTION = "Citations"
FILL_JS = os.environ.get("CE_FILL_JS") or os.path.expandvars("%LOCALAPPDATA%/hermes/profiles/citation-submitter/skills/devops/vaultwarden-cli-write/scripts/vaultwarden-cli-fill.js")
POLL_EVERY_S = 10
POLL_MAX_S = 1800
EMAIL_WAIT_S = 300
CODE_RE = re.compile(r"(?:code|verification code)[^0-9A-Za-z]{0,20}([0-9]{4,8})", re.I)
PHONE_RE = re.compile(r"\(?(\d{3})\)?[\s.\-]*(\d{3})[\s.\-]*(\d{4})")
# selectors
EMAIL_IN, TERMS_BOX, PASSWORD_IN = "#email", "#register-terms-checkbox", "input[type=password]"
CONTINUE_BTN, SIGNIN_BTN = "button:has-text('Continue')", "button:has-text('Sign in')"
ACCESS_CODE_IN = "input[name*=code i]"
VERIFY_NOW = "#registerCompanyPhoneModalVerify"
SEND_BTN = "button:has-text('Send verification code')"
SMS_CODE_IN = "input[autocomplete=one-time-code], input[name*=code i], input[id*=code i]"
SUBMIT_CODE_BTN = "button:has-text('Verify')"


class DriverError(Exception):
    """Carries ONLY an allowlisted fail code."""
    def __init__(self, fail_code):
        assert fail_code in B.FAIL_CODES
        super().__init__(fail_code); self.fail_code = fail_code


def log(msg):
    print("verify_send: " + msg, file=sys.stderr, flush=True)


# ---- page driver (a Playwright-like page: goto, fill, click, evaluate, inner_text, query_selector, wait_for_timeout, url) -------------
class CylexDriver:
    def __init__(self, page, runtime, tenant, cdp=None):
        self.page, self.rt, self.tenant, self.cdp = page, runtime, tenant, cdp

    def _try(self, fail_code, fn, *a):
        try:
            return fn(*a)
        except DriverError:
            raise
        except Exception:
            raise DriverError(fail_code) from None   # never chain: the original text may quote a typed value

    def _has(self, sel):
        return bool(self._try("other", self.page.query_selector, sel))

    def sign_in(self, email, since):
        p = self.page
        self._try("signin_failed", p.goto, SIGNIN_URL)
        self._try("signin_failed", p.fill, EMAIL_IN, email)
        self._try("signin_failed", p.click, TERMS_BOX)
        self._try("signin_failed", p.click, CONTINUE_BTN)
        self._try("signin_failed", p.wait_for_timeout, 1500)
        if not self.rt.vault_fill(self.tenant, SIGNIN_URL, self.cdp): raise DriverError("signin_failed")
        self._try("signin_failed", p.click, SIGNIN_BTN)
        self._try("signin_failed", p.wait_for_timeout, 4000)
        if self._has(ACCESS_CODE_IN):   # the Directory mails an access code BEFORE the phone step on a new account
            code = self.rt.access_code(self.tenant, since)
            if not code:
                log("access code not found in the mailbox before the wait ended: other")
                raise DriverError("other")
            try:
                self._try("signin_failed", p.fill, ACCESS_CODE_IN, code)
                self._try("signin_failed", p.keyboard.press, "Enter")
            finally:
                code = None
            self._try("signin_failed", p.wait_for_timeout, 4000)
        if self._has(PASSWORD_IN): raise DriverError("signin_failed")

    def open_phone_verify(self):
        """-> the modal text that carries the number. Fail closed (send_failed) when the control or the number is not there."""
        p = self.page
        if not self._has(VERIFY_NOW):
            self._try("send_failed", p.click, "a:has-text('Edit profile')")
            self._try("send_failed", p.wait_for_timeout, 4000)
        if not self._has(VERIFY_NOW): raise DriverError("send_failed")
        self._try("send_failed", p.evaluate, "document.querySelector('%s').click()" % VERIFY_NOW)   # a page modal blocks a normal click (spike 1)
        self._try("send_failed", p.wait_for_timeout, 3000)
        text = self._try("send_failed", p.evaluate, "(() => { const m = document.querySelector('.modal.show, [role=dialog]'); return m ? m.innerText : ''; })()")
        return text if isinstance(text, str) else ""

    def click_send(self):
        p = self.page
        self._try("send_failed", p.evaluate, "document.querySelectorAll('.modal.show input[type=checkbox], [role=dialog] input[type=checkbox]').forEach(c => { if (!c.checked) c.click(); })")
        if not self._has(SEND_BTN): raise DriverError("send_failed")
        self._try("send_failed", p.click, SEND_BTN)
        self._try("send_failed", p.wait_for_timeout, 2000)

    def enter_code(self, code):
        """-> 'verified' | 'rejected'. The code only goes into the field."""
        p = self.page
        try:
            if not self._has(SMS_CODE_IN): raise DriverError("send_failed")
            self._try("other", p.fill, SMS_CODE_IN, code)
            self._try("other", p.click, SUBMIT_CODE_BTN)
        finally:
            code = None
        for _ in range(10):
            self._try("other", p.wait_for_timeout, 2000)
            body = str(self._try("other", p.inner_text, "body") or "").lower()
            if "verification completed" in body: return "verified"
            if re.search(r"incorrect|invalid|wrong code|expired|did not match", body): return "rejected"
        raise DriverError("other")


# ---- runtime (everything with a side effect outside the page) ----------------------------------------------------------------------
class Runtime:
    """Real implementations. Tests pass a fake with the same methods. Nothing here prints a secret."""
    def __init__(self, runner=None, sleep=time.sleep, now=time.time):
        self._run, self.sleep, self.now = runner or subprocess.run, sleep, now
        self.email_wait_s = EMAIL_WAIT_S

    def vault_lookup(self, tenant):
        _biz, org, item = tenant
        r = self._run(["node", FILL_JS, "--organization", org, "--collection", COLLECTION, "--name", item, "--url", SIGNIN_URL, "--lookup-only"],
                      capture_output=True, text=True, timeout=180)
        return getattr(r, "returncode", 1) == 0

    def vault_fill(self, tenant, url, cdp):
        _biz, org, item = tenant
        r = self._run(["node", FILL_JS, "--organization", org, "--collection", COLLECTION, "--name", item, "--url", url, "--field", PASSWORD_IN, "--cdp", cdp or ""],
                      capture_output=True, text=True, timeout=180)
        return getattr(r, "returncode", 1) == 0

    def login_email(self, tenant):
        biz = tenant[0]
        v = os.environ.get("CE_VERIFY_LOGIN_EMAIL_" + biz)
        if v: return v
        try:
            import json
            ident = os.environ.get("CE_IDENTITY") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/identity.json")
            return json.load(open(ident, encoding="utf-8"))["BIZ"][biz].get("listing_email")
        except Exception:
            return None

    def messages(self, tenant):
        import mail_scan as M
        return M.read_relay_messages(days=1) if tenant[0] == "NM" else M.read_messages(days=1, folders="all")

    def access_code(self, tenant, since):
        """Newest Directory mail at or after `since` (UTC datetime) with a code in it, or None after email_wait_s. The code is returned, never logged."""
        import mail_scan as M
        floor = (since - datetime.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M")
        end = self.now() + self.email_wait_s
        while True:
            try:
                msgs = [m for m in self.messages(tenant) if M.mail_is_from(m, DOMAIN) and (m.get("date") or "") >= floor]
            except Exception as e:
                log("mailbox read failed: %s" % type(e).__name__); msgs = []
            for m in sorted(msgs, key=lambda x: x.get("date") or "", reverse=True):
                hit = CODE_RE.search(m.get("body") or "")
                if hit: return hit.group(1)
            if self.now() >= end: return None
            self.sleep(10)

    def guard(self):
        import sitegate
        return sitegate.SiteGuard()

    @contextlib.contextmanager
    def browser(self, tenant):
        """Owned headful Chrome, own profile per tenant, closed (whole tree) on exit. Yields (page, cdp_url)."""
        from owned_chrome import OwnedChrome
        from playwright.sync_api import sync_playwright
        prof = os.path.expandvars("%LOCALAPPDATA%/citation-engine/verify-profiles/" + tenant[0].lower())
        with OwnedChrome(profile=prof) as oc:
            pw = sync_playwright().start()
            try:
                b = pw.chromium.connect_over_cdp(oc.cdp_url)
                ctx = b.contexts[0]
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                yield page, oc.cdp_url
            finally:
                pw.stop()


def set_live(portal, row, client_id, now=None):
    """The verification-queue step of transitions.record_transition for a move to live: PATCH state live + verified_at, only a row of THIS client
    that is not live yet. Returns True when exactly one row changed. The queue row's own live move still needs public-page Proof and is not done here."""
    if row.get("state") == "live": return True
    import transitions as T   # the one live writer (tests/proof_gap_test.py P5 forbids a second one)
    return T.set_verification_live(portal, row["id"], client_id, now)


def run(request_id, portal, rpc, rt, now_dt=None):
    """-> outcome: verified | failed:<code> | could_not_start:<code> | not_claimed | claim_lost. Never raises on a Directory problem."""
    def end(status, code=None):
        try: rpc.finish(request_id, status, code)
        except B.BridgeError as e: log(str(e))
        out = status if not code else "%s:%s" % (status, code)
        log("done %s %s" % (request_id, out)); return out

    try:
        req = B.request_row(portal, request_id, status="starting")
    except Exception as e:
        log("request read failed: %s" % type(e).__name__); return "not_claimed"
    if not req:
        log("%s is not a claimed request; nothing sent" % request_id); return "not_claimed"
    verdict, row = B.fence(req, portal)
    if verdict != "ok":
        log("fence refused %s: %s" % (request_id, verdict)); return end("failed", B.FENCE_FAIL[verdict])
    tenant = TENANTS[req["client_id"]]
    if not rt.vault_lookup(tenant):
        log("vault item for %s missing or unreadable" % tenant[0]); return end("failed", "signin_failed")
    email = rt.login_email(tenant)
    if not email:
        log("login email not configured for %s" % tenant[0]); return end("failed", "signin_failed")
    g = rt.guard().reserve(DOMAIN, request_id)   # the one Directory session for this request
    if not g.get("ok"):
        log("sitegate refused: %s" % ("cooldown or cap")); return end("could_not_start", "other")
    since = now_dt or datetime.datetime.now(datetime.timezone.utc)
    code = None
    try:
        with rt.browser(tenant) as (page, cdp):
            d = CylexDriver(page, rt, tenant, cdp)
            d.sign_in(email, since)
            modal = d.open_phone_verify()
            m = PHONE_RE.search(modal or "")
            masked = B.mask_phone("".join(m.groups())) if m else None
            if not masked:
                log("number not readable in the verify step; not sending"); raise DriverError("send_failed")
            if not B.request_row(portal, request_id, status="starting"):   # last look: still claimed (the sweeper may have ended it)
                log("claim lost before send for %s" % request_id); return "claim_lost"
            d.click_send()
            try: rpc.mark_sent(request_id, masked)
            except B.BridgeError as e:
                log(str(e)); raise DriverError("other") from None
            deadline = rt.now() + POLL_MAX_S
            misses = 0
            while True:
                try:
                    code = rpc.consume(request_id); misses = 0
                except B.BridgeError as e:
                    misses += 1; log(str(e))
                    if misses >= 3: raise DriverError("other") from None
                if code: break
                if rt.now() >= deadline: raise DriverError("code_expired")
                rt.sleep(POLL_EVERY_S)
            try: result = d.enter_code(code)
            finally: code = None
        if result == "rejected": return end("failed", "code_rejected")
        if not set_live(portal, row, req["client_id"]):
            log("row could not be set live after an accepted code"); return end("failed", "other")
        return end("verified")
    except DriverError as e:
        return end("failed", e.fail_code)
    except Exception as e:
        log("unexpected %s" % type(e).__name__); return end("failed", "other")
    finally:
        code = None


def main(argv=None):
    a = argparse.ArgumentParser(description="Verify Now send run (one claimed request)")
    a.add_argument("--request-id", required=True)
    n = a.parse_args(argv)
    if not B.UUID_RE.match(n.request_id): log("bad request id"); return 2
    portal = P.Portal(*P.load_portal_env())
    out = run(n.request_id, portal, B.VerifyRpc(portal), Runtime())
    return 0 if out in ("verified", "not_claimed", "claim_lost") or out.startswith(("failed", "could_not_start")) else 1


if __name__ == "__main__":
    sys.exit(main())
