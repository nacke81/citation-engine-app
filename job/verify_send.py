"""Verify Now send run (SMS and phone call). Which send runs is data: config/verify_directories.json says send=script (the Cylex driver below)
or send=agent (the default: the submitter agent oneshot, driven through job/verify_step.py; see _agent_send and build_prompt). A Directory or
channel not in the file fails no_playbook with 0 site loads. The vault item's username is the login email and must equal the expected
listings@ address (fail closed signin_failed); an NM send outside the mail relay window (08:00-19:58 CT) fails timeout before any site load.
Started by job/verify_bridge.py as a direct subprocess:

  python job/verify_send.py --request-id <uuid>

One run handles ONE claimed request and makes at most one Directory session (sitegate.reserve once, before the browser opens).
  1. Re-read the request: it must be 'starting' (claimed). Run the same fence() the bridge ran (client allow-list, verification row
     client match, Cylex playbook). Anything else: no Directory is touched.
  2. Vault lookup for the tenant's Cylex login. Missing item -> failed/signin_failed, no browser.
  3. Per-tenant owned Chrome (headful, off-screen unless CE_CHROME_VISIBLE=1, own profile per tenant), sign in. If the Directory mails an
     access code before the phone step, read it from the mailbox path for that tenant (NM relay file, SCC IMAP, spam included).
  4. Open the phone verify modal, read the number there, build the masked number, tick the consent box, click send. Then mark_code_sent.
  5. Poll consume_verify_code every 10 s for up to 30 min. No code -> failed/code_expired. Each pass first re-reads the request: when
     it is no longer code_sent/checking (the client asked for a new code and the portal closed it as failed/resend) the browser is
     closed and the run exits WITHOUT finish_code_request (log: superseded).
  0. (before 2) One send run per tenant: a per-tenant lock is taken before the browser opens and held to the end of the run. A busy
     tenant: exit without finish; the request stays 'starting' and the bridge retries it on its next pass.
  6. Enter the code, read the result. Accepted -> set the citation_verification row live (transitions.set_verification_live, the verification-queue PATCH that
     transitions.record_transition performs on a move to live), then finish_code_request('verified'). Rejected -> failed/code_rejected.

Rules: a code (SMS or mailed) lives in a local variable only: never logged, printed, written, or put in an exception message. Every
failure path ends in finish_code_request with an allowlisted fail code and logs the reason code only, never exception text.
The live phone-step selectors come from spike 1 (#registerCompanyPhoneModalVerify JS click, consent, 'Send verification code'); the
Edit-profile navigation and the code-entry field are fail-closed (send_failed) when not found and must be confirmed in the live-run card.
"""
import argparse, contextlib, datetime, os, posixpath, re, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import portal as P
import verify_bridge as B
import verify_scoreboard as SB
import playbook as PB

DOMAIN = "cylex.us"
SIGNIN_URL = "https://www.cylex.us.com/signin/"
TENANTS = {   # client_id -> (business code, vault organization). The vault item name comes from config/verify_directories.json (vault_items).
    P.ALLOWED["SCC"]: ("SCC", "Senior Care Consulting"),
    P.ALLOWED["NM"]: ("NM", "Na" + "cke Media"),
}
EXPECTED_LOGIN = {"NM": "listings@na" + "ckemedia.com", "SCC": "listings@seniorcaresolutions.co"}   # the vault item's username must equal this, else signin_failed (Nate stop 2)
RELAY_OPEN_MIN, RELAY_CLOSE_MIN = 8 * 60, 19 * 60 + 58   # nm-listings-relay cron "*/2 8-19" (Central): last run 19:58
AGENT_START_S = 1500      # kill the oneshot at 25 min when no `sent` call happened
SUBMITTER_PROFILE = "citation-submitter"
AGENT_AFTER_SENT_S = B.POLL_MAX_S + 300   # 30 min code wait + 5 min to type it; then the run ends the oneshot
AGENT_GRACE_S = 60        # a closed request: the agent gets this long to exit on its own
AGENT_TICK_S = 5
LOCK_TRIES, LOCK_WAIT_S = 4, 2   # a bridge probe holds the tenant lock for a blink; do not let that defer a real run (Nate stop 7)
COLLECTION = "Citations"
# t_45fe02d4: the ONE record of which browser a tenant's agent run uses (profile dir under %LOCALAPPDATA%/citation-engine, CDP port). NM never gets the SCC profile.
TENANT_BROWSER = {"NM": ("nm-chrome-profile", 9334), "SCC": ("build-profile", 9333)}


class BrowserError(Exception): pass


def tenant_browser(biz):
    """-> (profile dir, port, cdp url) for a tenant code. An unknown tenant raises: no browser, no run."""
    if biz not in TENANT_BROWSER: raise BrowserError("no browser configured for tenant")
    name, port = TENANT_BROWSER[biz]
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")   # os.path.expandvars("%X%") is a no-op off Windows (t_45fe02d4 round 2)
    return os.path.join(local, "citation-engine", name), port, "http://127.0.0.1:%d" % port


_UDD_RE = re.compile(r'(")?--user-data-dir=(")?')


def cmd_user_data_dir(cmd):
    """The --user-data-dir value of a Chrome command line, or None. Both live Windows shapes: "--user-data-dir=C:/a b/p" (quote BEFORE the flag, the
    main process) and --user-data-dir="C:\\a b\\p" (quote after the =, renderers); a bare unquoted value ends at whitespace."""
    m = _UDD_RE.search(cmd or "")
    if not m: return None
    rest = (cmd or "")[m.end():]
    if m.group(1) or m.group(2):
        end = rest.find('"')
        val = rest if end < 0 else rest[:end]
    else:
        val = rest.split()[0] if rest.split() else ""
    return val or None


def profile_key(path):
    """One comparable form of a profile path: quotes stripped, \\ -> /, normpath, no trailing slash, lower case. Same answer on every OS."""
    p = str(path or "").strip().strip("\"'").replace("\\", "/")
    return posixpath.normpath(p).rstrip("/").lower() if p else ""


def same_profile(cmd, prof):
    got = cmd_user_data_dir(cmd)
    return bool(got) and profile_key(got) == profile_key(prof)
FILL_JS = os.environ.get("CE_FILL_JS") or os.path.expandvars("%LOCALAPPDATA%/hermes/profiles/citation-submitter/skills/devops/vaultwarden-cli-write/scripts/vaultwarden-cli-fill.js")
VERIFY_LEASE = "verify:"   # card prefix of the build-Chrome lease an SCC verify run holds (t_45fe02d4)
LEASE_BEAT_S = 60
LIVE_STATUSES = ("code_sent", "checking")   # request states in which this run still owns the poll
POLL_EVERY_S = 10
POLL_MAX_S = 1800
EMAIL_WAIT_S = 300
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
        baseline = self.rt.mail_baseline(self.tenant)   # mail already in the box BEFORE the Sign in click; None = unreadable
        self._try("signin_failed", p.goto, SIGNIN_URL)
        self._try("signin_failed", p.fill, EMAIL_IN, email)
        self._try("signin_failed", p.click, TERMS_BOX)
        self._try("signin_failed", p.click, CONTINUE_BTN)
        self._try("signin_failed", p.wait_for_timeout, 1500)
        if not self.rt.vault_fill(self.tenant, SIGNIN_URL, self.cdp): raise DriverError("signin_failed")
        self._try("signin_failed", p.click, SIGNIN_BTN)
        self._try("signin_failed", p.wait_for_timeout, 4000)
        if self._has(ACCESS_CODE_IN):   # the Directory mails an access code BEFORE the phone step on a new account
            code = self.rt.access_code(self.tenant, baseline)
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


# ---- agent path --------------------------------------------------------------------------------------------------------------------
class AgentProc:
    """The running oneshot. kill() ends the WHOLE process tree (on Windows `taskkill /T`): killing only the parent leaves the model's child
    processes running (lesson 2026-11-11-a-child-you-kill-does-not-end-its-parent). Idempotent."""
    def __init__(self, proc, runner=None):
        self.proc, self._run = proc, runner or subprocess.run

    def poll(self):
        return self.proc.poll()

    def kill(self):
        if self.proc.poll() is not None: return
        try:
            if os.name == "nt": self._run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True, timeout=60)
            else: self.proc.kill()
        except Exception as e:
            log("agent kill failed: %s" % type(e).__name__)
        try: self.proc.kill()
        except Exception: pass


def central_now(dt_utc):
    """UTC -> US Central wall time (CST UTC-6, CDT UTC-5 from the 2nd Sunday of March 2:00 to the 1st Sunday of November 2:00). No tz database needed."""
    y = dt_utc.year
    def nth_sunday(month, n):
        d = datetime.date(y, month, 1)
        return d + datetime.timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))
    start = datetime.datetime.combine(nth_sunday(3, 2), datetime.time(8), tzinfo=datetime.timezone.utc)    # 2:00 CST = 08:00 UTC
    end = datetime.datetime.combine(nth_sunday(11, 1), datetime.time(7), tzinfo=datetime.timezone.utc)     # 2:00 CDT = 07:00 UTC
    off = -5 if start <= dt_utc < end else -6
    return (dt_utc + datetime.timedelta(hours=off)).replace(tzinfo=None)


def relay_window_open(dt_utc):
    """True from 08:00 to 19:58 Central, the minutes the nm-listings-relay cron (*/2 8-19) runs. NM mailed access codes arrive only then."""
    c = central_now(dt_utc)
    return RELAY_OPEN_MIN <= c.hour * 60 + c.minute <= RELAY_CLOSE_MIN


REPO_ROOT = os.path.dirname(HERE)
STEP_PY = os.path.join(HERE, "verify_step.py")


def helper_command():
    """The helper as the agent must run it: this interpreter and the absolute helper path, both quoted (the run dir has spaces), forward slashes
    (the agent's terminal is bash on Windows). Never a relative path: the oneshot's cwd is not guaranteed."""
    q = lambda p: '"%s"' % os.path.abspath(p).replace("\\", "/")
    return "%s %s" % (q(sys.executable), q(STEP_PY))


NO_ACCOUNT_RULE = "- No CapSolver, no account creation, no payment, no client contact.\n"
SIGN_IN_STEP = ("1. Sign in to the Directory with the vault helper (the Vaultwarden Citations item for %(biz)s on %(dom)s). Use ONLY the browser at %(cdp)s (already open). Do not open another browser. When you run vaultwarden-cli-fill.js, always pass --cdp %(cdp)s.\n")
STEP3_SIGNIN = "3. Click the send button. Before you click it, if the page shows a paid upsell, a plan purchase, or a marketing consent that is not required for the code, do NOT click; end the session and report it.\n"
PHONE_STEP = "2. Go to the phone verification step. Check the phone shown there against the masked phone above. If it differs, or you cannot read it, STOP.\n"


# t_2cb780c2: every directory run ends by saying whether the Directory playbook was right. The agent has no DB access (no service key), so it never
# writes the playbook itself: the trace it logged is the evidence, and `playbook.py from-trace --proven` (run by the owner after an accepted result)
# turns it into the verify playbook. last_proven_at is set only by that accepted run.
WRITE_BACK_STEP = ("8. Playbook note (last thing you do, then end the session): the stored steps for this site are one shared record. You cannot write it. "
                   "If a step above was wrong, missing or out of order, run once: %(helper)s note --request-id %(rid)s --text \"<what changed>\" "
                   "(one line, max 400 chars, no values, no codes; a note with a long number, an email or a phone is refused). Never print the note instead. "
                   "Skip it if every step worked as written. The trace you logged is turned into the verify playbook only when the result is accepted.\n")


def playbook_block(playbook):
    """The numbered Directory playbook (already rendered: placeholders filled, no secrets) as prompt lines."""
    lines = []
    for i, s in enumerate(playbook["steps"], 1):
        extra = "".join(" [%s: %s]" % (k, s[k]) for k in ("url", "selector") if s.get(k))
        lines.append("  %d. %s%s" % (i, s["text"], extra))
    return "Directory playbook (version %s, from the Directory DB; follow these in order, they win over the row steps):\n%s\n" % (playbook.get("version", "?"), "\n".join(lines))


STEP4_SIGNIN = "4. Choose the %(ch)s option and send the code. Immediately run: %(helper)s sent --request-id %(rid)s --masked \"%(masked)s\"\n"
STEP3_MARKED = "3. Do the send step (playbook step %d) once. Before you click it, if the page shows a paid upsell, a plan purchase, or a marketing consent that is not required for the code, do NOT click; end the session and report it.\n"
STEP4_MARKED = "4. Playbook step %(n)s already sent the code. Do NOT click any other send, resend or SMS option after it. Immediately run: %(helper)s sent --request-id %(rid)s --masked \"%(masked)s\"\n"


def build_prompt(request_id, req, row, entry, tenant, masked, username, playbook=None):
    """The agent's instructions. Request id, tenant, directory, channel, the row's steps and URL, the masked phone, the hard rules. Holds NO code
    and no secret (the username is the login email, not a credential).
    playbook (t_413687a7): the RENDERED `verify` playbook for this Directory ({steps: [{text, url?, selector?}], send_is_signup, version}) or None.
    Its steps are listed. ONLY when send_is_signup is true is the account for THIS Directory created (the playbook's step marked send is the send); otherwise the old
    'no account creation' rule stands. Payment and client contact are never allowed either way. CapSolver (cap 3 per request, NM) only with the carve-out."""
    biz = tenant[0]
    signup = bool(playbook and playbook.get("send_is_signup"))
    # t_8b8c2650: EVERY stored verify playbook names its one marked send step (PlaybookError when 0 or 2+: no prompt, fail closed). No playbook: generic steps.
    n = PB.send_step_number(playbook.get("steps"), signup) if playbook else 0
    pb_txt = playbook_block(playbook) if playbook else ""
    sign_in = SIGN_IN_STEP
    phone_step = PHONE_STEP
    step3 = STEP3_SIGNIN
    rules = NO_ACCOUNT_RULE
    if n:   # t_8b8c2650: the marked step IS the send on the sign-in path too: one order, no generic second click
        phone_step = "2. Go to the phone verification step. Before the send step (playbook step %d), check the phone shown there against the masked phone above. If it differs, or you cannot read it, STOP.\n" % n
        step3 = STEP3_MARKED % n
    if signup:
        sign_in = ("1. This Directory's send IS the signup: do NOT sign in. Follow the Directory playbook above with the vault helper for the password (the Vaultwarden Citations item %(item)s for %(biz)s on %(dom)s). Use ONLY the browser at %(cdp)s (already open). Do not open another browser. When you run vaultwarden-cli-fill.js, always pass --cdp %(cdp)s.\n")
        # t_3223ee18: n is the playbook's own send step (computed above), never "the Sign up click"
        phone_step = "2. Before the send step (playbook step %d), check the phone shown in the form against the masked phone above. If it differs, or you cannot read it, STOP.\n" % n
        step3 = STEP3_MARKED % n
        rules = ("- No payment, no client contact. You may create ONE account, only the one the playbook describes, only for %(dom)s, only with the vault item's login. No other account anywhere.\n"
                 + ("- CapSolver is allowed only for a CAPTCHA on this signup page, at most 3 solves for this request: python job/capsolver_solve.py --row verify-%(rid)s --kind <kind> --url <page url> --sitekey <key>. A fourth try is never allowed.\n" if biz == "NM" else "- No CapSolver.\n"))
    steps = row.get("steps")
    steps_txt = "\n".join("  - %s" % s for s in steps) if isinstance(steps, list) and steps else "  (none on the row)"
    ch = req.get("channel")
    how = "a text message (SMS)" if ch == "sms" else "an automated phone call that reads the code aloud"
    helper = helper_command()
    step4 = (STEP4_MARKED if n else STEP4_SIGNIN) % {"ch": ch, "helper": helper, "rid": request_id, "masked": masked or "(not on file; read it from the page)", "n": n}
    fmt = {"rid": request_id, "biz": biz, "dom": entry["domain"], "item": tenant[2], "cdp": tenant_browser(biz)[2]}
    return (
        "You are the citation-submitter agent. Finish ONE Verify Now request for a client. Work only on this request.\n\n"
        "Request id: %(rid)s\nTenant: %(biz)s\nDirectory: %(dom)s\nChannel: %(ch)s (the Directory sends the code by %(how)s)\n"
        "Directory page: %(url)s\nRow steps:\n%(steps)s\n%(pb)sMasked phone on file: %(masked)s\nLogin (vault item username): %(user)s\n\n"
        "Steps:\n"
        "0. FIRST command of the run, before anything else (it times your start): %(helper)s stage --request-id %(rid)s --name ready   If it exits nonzero, carry on.\n"
        "%(sign_in)s"
        "   Speed log (do not skip, it is how this step becomes a script): after each page action from sign-in to the send click, run: %(helper)s trace --request-id %(rid)s --action <goto, click, fill or press> --url <page url> --selector \"<css selector>\"\n"
        "   (no values, never what you typed). When you are signed in, run: %(helper)s stage --request-id %(rid)s --name signed_in. If either exits nonzero, carry on.\n"
        "%(phone_step)s"
        "%(step3)s"
        "%(step4)s"
        "   (use the masked number you saw on the page when it differs in format). If it exits nonzero, stop.\n"
        "5. Run: %(helper)s code --request-id %(rid)s   (run it with the terminal tool's timeout set to 600, in the foreground)\n"
        "   Each call waits up to 9 minutes. Exit 0 means the code is on its stdout. Exit 6 means no code yet: run the same command again, as many times as needed (the 30 minute limit does not restart).\n"
        "   Exit 3 means superseded and exit 4 means expired: stop at once. Any other nonzero exit: stop.\n"
        "6. Type the code into the Directory field and nowhere else. Read the page for accepted or rejected.\n"
        "7. Run: %(helper)s result --request-id %(rid)s --outcome accepted   (or rejected).\n"
        "%(wb)s\n"
        "Hard rules:\n"
        "- One Directory session through sitegate for this run. Never open a second one and never retry a send.\n"
        "- Never type the code anywhere except the Directory. Never print, log, write, quote or summarize the code.\n"
        "- Never run any other command against the portal. The helper above is the only way to report progress. You do not have the service key.\n"
        "%(rules)s"
        "- If you are unsure at any step, stop. The run turns an unfinished request into a safe failure.\n"
        % {"rid": request_id, "biz": biz, "dom": entry["domain"], "ch": ch, "how": how, "url": row.get("directory_url") or entry["signin_url"],
           "sign_in": sign_in % fmt, "phone_step": phone_step, "step3": step3, "step4": step4, "rules": rules % fmt, "pb": pb_txt, "item": tenant[2],
           "steps": steps_txt, "masked": masked or "(not on file; read it from the page)", "user": username, "helper": helper, "wb": WRITE_BACK_STEP % {"helper": helper, "rid": request_id}})


# ---- runtime (everything with a side effect outside the page) ----------------------------------------------------------------------
class Runtime:
    """Real implementations. Tests pass a fake with the same methods. Nothing here prints a secret."""
    def __init__(self, runner=None, sleep=time.sleep, now=time.time, popen=None):
        self._run, self.sleep, self.now, self._popen = runner or subprocess.run, sleep, now, popen
        self.email_wait_s = EMAIL_WAIT_S

    def vault_lookup(self, tenant):
        _biz, org, item, url = tenant
        r = self._run(["node", FILL_JS, "--organization", org, "--collection", COLLECTION, "--name", item, "--url", url, "--lookup-only"],
                      capture_output=True, text=True, timeout=180)
        return getattr(r, "returncode", 1) == 0

    def vault_fill(self, tenant, url, cdp):
        _biz, org, item, _u = tenant
        r = self._run(["node", FILL_JS, "--organization", org, "--collection", COLLECTION, "--name", item, "--url", url, "--field", PASSWORD_IN, "--cdp", cdp or ""],
                      capture_output=True, text=True, timeout=180)
        return getattr(r, "returncode", 1) == 0

    def login_username(self, tenant):
        """The vault item's username field (the login email; never the password). None when the item has no username or cannot be read."""
        import json
        _biz, org, item, url = tenant
        r = self._run(["node", os.path.join(HERE, "vault_username.cjs"), "--fill-js", FILL_JS, "--organization", org, "--collection", COLLECTION, "--name", item, "--url", url],
                      capture_output=True, text=True, timeout=180)
        if getattr(r, "returncode", 1) != 0: return None
        try:
            u = json.loads(r.stdout).get("username")
        except Exception:
            return None
        return u.strip() if isinstance(u, str) and u.strip() else None

    def business_phone_masked(self, tenant):
        """The masked business phone the Directory will text or call, from the approved identity file; None when unreadable."""
        import json
        try:
            ident = os.environ.get("CE_IDENTITY") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/identity.json")
            with open(ident, encoding="utf-8") as f:
                return B.mask_phone(json.load(f)["BIZ"][tenant[0]]["phones"][0])
        except Exception:
            return None

    def verify_playbook(self, domain):
        """The Directory DB `verify` playbook row for this Directory (t_413687a7) or None. A read failure raises (the caller logs it and runs without)."""
        import directories as D
        return PB.get_playbook(D.DirDB(), domain, "verify")

    def tenant_values(self, tenant, username):
        """Placeholder values for the playbook: business name, phone, website from the approved identity file; the login email and vault item NAME from this run.
        Only what is known; render() refuses a placeholder with no value. No password, ever."""
        import json
        vals = {"login_email": username, "vault_item": tenant[2]}
        try:
            ident = os.environ.get("CE_IDENTITY") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/identity.json")
            with open(ident, encoding="utf-8") as f: b = json.load(f)["BIZ"][tenant[0]]
            vals["business_name"] = b.get("name")
            d = re.sub(r"\D", "", (b.get("phones") or [""])[0])[-10:]
            if len(d) == 10: vals["phone"] = "(%s) %s-%s" % (d[:3], d[3:6], d[6:])
            vals["website"] = b.get("site")
            vals["contact_name"] = b.get("contact")   # t_f683311e: from identity.json only. No key (SCC, or NM unset) = no value = render refuses = send_failed before launch
        except Exception:
            pass
        return {k: v for k, v in vals.items() if isinstance(v, str) and v}

    def write_prompt(self, request_id, text):
        import sitegate
        d = os.path.join(sitegate.logs_dir(), "verify-prompts"); os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "verify-agent-%s.txt" % request_id)
        with open(path, "w", encoding="utf-8", newline="\n") as f: f.write(text)
        return path

    def launch_agent(self, prompt_path, cdp=None):
        """Start the submitter agent oneshot. Its output is NOT kept (the code passes through its context); the helper logs reason words to its own stderr.
        The child env drops any service-role variable. -> a handle with poll() and kill() (kills the whole tree)."""
        import postcard_step as PS
        argv = [PS._hermes_exe(), "-p", SUBMITTER_PROFILE, "chat", "--query-file", prompt_path, "--oneshot"]
        env = {k: v for k, v in os.environ.items() if "SERVICE_ROLE" not in k.upper()}
        env["TERMINAL_CWD"] = REPO_ROOT   # the agent's terminal starts in the app clone, whatever cwd the bridge had
        env.pop("BROWSER_CDP_URL", None)
        if cdp: env["BROWSER_CDP_URL"] = cdp   # t_45fe02d4: hermes browser tools attach to THIS Chrome (the tenant's), never start their own
        kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, cwd=REPO_ROOT)
        return AgentProc((self._popen or subprocess.Popen)(argv, **kw), self._run)

    def messages(self, tenant):
        import mail_scan as M
        return M.read_relay_messages(days=1) if tenant[0] == "NM" else M.read_messages(days=1, folders="all")

    @staticmethod
    def _key(m): return (m.get("folder") or "INBOX", str(m.get("uid")))

    def mail_baseline(self, tenant):
        """Keys of every message in the box now. A mailed access code is only accepted from a message NOT in this set, so no clock or
        Date-header offset can drop it and no stale mail can be read as new. None when the box cannot be read (access_code then fails closed)."""
        try:
            return {self._key(m) for m in self.messages(tenant)}
        except Exception as e:
            log("mailbox baseline failed: %s" % type(e).__name__); return None

    def access_code(self, tenant, baseline):
        """Code from a Directory mail that arrived after the baseline, or None after email_wait_s. The code is returned, never logged."""
        import html, mail_scan as M
        if baseline is None:
            log("access code skipped: mailbox baseline unreadable"); return None
        end = self.now() + self.email_wait_s
        while True:
            try:
                msgs = [m for m in self.messages(tenant) if self._key(m) not in baseline and M.mail_is_from(m, DOMAIN)]
            except Exception as e:
                log("mailbox read failed: %s" % type(e).__name__); msgs = []
            for m in sorted(msgs, key=lambda x: str(x.get("uid")), reverse=True):
                hit = M.RESET_CODE_RE.search(re.sub(r"https?://\S+", " ", html.unescape(m.get("body") or "")))
                if hit: return hit.group(1) or hit.group(2)
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


    @contextlib.contextmanager
    def agent_browser(self, tenant):
        """t_45fe02d4: the tenant's persistent Chrome (profile + port from TENANT_BROWSER) for the agent. Port already listening: its process must carry THIS
        tenant's --user-data-dir (else BrowserError, nothing started); it is reused and left running. Not listening: OwnedChrome on that profile and port,
        closed on exit, profile kept. The build port (SCC, 9333) is shared with build batches: refused while a build lease is fresh, a verify lease is held
        and refreshed for the whole run, and a Chrome started for it is detached and left to the keepalive timer (a batch may have started meanwhile)."""
        import build_chrome as BC, chrome_keepalive as KA
        from owned_chrome import OwnedChrome
        prof, port, url = tenant_browser(tenant[0])
        shared = port == KA.PORT
        lease = stop = beat = None
        if shared:
            held = KA.lease_active()
            if held and not str(held.get("card") or "").startswith(VERIFY_LEASE):
                log("build Chrome is leased by %s; SCC verify run refused" % (held.get("card") or "?")); raise BrowserError("the build Chrome on port %d is leased by a build batch" % port)
            lease = KA.Lease("%s%d" % (VERIFY_LEASE, os.getpid())); lease.touch()
            stop = threading.Event()
            def keep():
                while not stop.wait(LEASE_BEAT_S):
                    cur = KA.lease_read()
                    if cur and cur.get("card") == lease.card: lease.touch()
                    else: log("verify lease on the build Chrome was taken over"); return
            beat = threading.Thread(target=keep, daemon=True); beat.start()
        try:
            pids = BC.listener_pids(port)
            if pids:
                procs = {q["pid"]: q["cmd"] for q in BC.list_procs()}
                if not all(same_profile(procs.get(pid), prof) for pid in pids):
                    raise BrowserError("port %d is held by a process with another profile" % port)
                yield url
            elif shared:
                try: KA.ensure_up(port, prof)   # detached, same build profile: outlives this run, the keepalive timer owns its end
                except RuntimeError as e: raise BrowserError(str(e)) from e
                yield url
            else:
                with OwnedChrome(profile=prof, port=port) as oc:
                    yield oc.cdp_url
        finally:
            if stop: stop.set()
            if lease:
                cur = KA.lease_read()
                if cur and cur.get("card") == lease.card: KA.lease_release()   # never remove a lease a build batch has taken over

    def write_back(self, request_id, domain, note=None):
        """t_eae8e59f: the bridge (this process holds the Directory DB access, the agent has none) proves the verify playbook after an accepted code."""
        import directories as D, playbook_proven as PP
        return PP.write_proven(D.DirDB(), request_id, domain, os.path.join(SB._dir(), "verify-traces"), note, log=log)


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
    base = TENANTS[req["client_id"]]
    for attempt in range(LOCK_TRIES):   # one send run per tenant; held until this run ends, however it ends
        with B.tenant_lock(req["client_id"]) as got:
            if got: return _send(request_id, portal, rpc, rt, req, row, base, now_dt, end)
        if attempt < LOCK_TRIES - 1: rt.sleep(LOCK_WAIT_S)   # a bridge probe takes the lock for a blink; a real holder outlasts this
    log("tenant busy; %s stays starting, the bridge retries it" % request_id)
    B.clear_started(request_id)
    return "deferred"


def _send(request_id, portal, rpc, rt, req, row, base, now_dt, end):
    entry = B.directory_entry(row.get("directory"), req.get("channel"))
    if not entry or (entry["send"] == "script" and entry["domain"] != DOMAIN):
        log("no send path for %s" % request_id); return end("failed", "no_playbook")
    biz, org = base
    item = entry["vault_items"].get(biz)
    if not item:
        log("no vault item named for %s on this Directory" % biz); return end("failed", "signin_failed")
    tenant = (biz, org, item, entry["signin_url"])
    SB.stamp(request_id, None, tenant=biz, domain=entry["domain"], channel=req.get("channel"), send_mode=entry["send"])
    since = now_dt or datetime.datetime.now(datetime.timezone.utc)
    if biz == "NM" and not relay_window_open(since):   # Nate stop 3: the mailed access code comes from the relay cron, 08:00-19:58 CT only
        log("NM send outside the mail relay window (08:00-19:58 CT); no Directory touched"); return end("failed", "timeout")
    if not rt.vault_lookup(tenant):
        log("vault item for %s missing or unreadable" % biz); return end("failed", "signin_failed")
    email = rt.login_username(tenant)
    if not email:
        log("vault item for %s has no username" % biz); return end("failed", "signin_failed")
    if email.strip().lower() != EXPECTED_LOGIN[biz]:   # fail closed: no fallback to any other address
        log("vault username for %s is not the expected listings address" % biz); return end("failed", "signin_failed")
    g = rt.guard().reserve(entry["domain"], request_id)   # the one Directory session for this request
    if not g.get("ok"):
        log("sitegate refused: %s" % ("cooldown or cap")); return end("could_not_start", "other")
    if entry["send"] == "agent":
        return _agent_send(request_id, portal, rt, req, row, entry, tenant, email, end)
    code = None
    try:
        with rt.browser(tenant) as (page, cdp):
            d = CylexDriver(page, rt, tenant, cdp)
            SB.stamp(request_id, "agent_start_at")   # script mode: the browser is open and the driver starts
            d.sign_in(email, since)
            SB.stamp(request_id, "signed_in_at")
            modal = d.open_phone_verify()
            m = PHONE_RE.search(modal or "")
            masked = B.mask_phone("".join(m.groups())) if m else None
            if not masked:
                log("number not readable in the verify step; not sending"); raise DriverError("send_failed")
            if not B.request_row(portal, request_id, status="starting"):   # last look: still claimed (the sweeper may have ended it)
                log("claim lost before send for %s" % request_id); return "claim_lost"
            d.click_send()
            SB.stamp(request_id, "send_clicked_at")
            try: rpc.mark_sent(request_id, masked)
            except B.BridgeError as e:
                log(str(e)); raise DriverError("other") from None
            SB.stamp(request_id, "code_sent_at")
            deadline = rt.now() + POLL_MAX_S
            misses = 0
            while True:
                try:   # one cheap portal read per pass: a request the portal closed (client asked for a new code) ends this run
                    cur = B.request_row(portal, request_id)
                    if cur is None: raise B.BridgeError("empty status read")   # an empty read is a miss, not a verdict (Nate stop 5)
                    if cur.get("status") not in LIVE_STATUSES:
                        log("superseded: %s is no longer waiting for a code; closing the browser, no finish" % request_id)
                        SB.finalize(request_id, "superseded")   # the first attempt's timing row; not finish_code_request
                        return "superseded"
                    code = rpc.consume(request_id); misses = 0
                except B.BridgeError as e:
                    misses += 1; log(str(e))
                    if misses >= 3: raise DriverError("other") from None
                except Exception as e:
                    misses += 1; log("status read failed: %s" % type(e).__name__)
                    if misses >= 3: raise DriverError("other") from None
                if code: break
                if rt.now() >= deadline: raise DriverError("code_expired")
                rt.sleep(POLL_EVERY_S)
            SB.stamp(request_id, "code_submitted_at")
            try: result = d.enter_code(code)
            finally: code = None
            SB.stamp(request_id, "code_entered_at")
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


def _status(portal, request_id):
    try:
        cur = B.request_row(portal, request_id)
    except Exception:
        return None
    return cur.get("status") if cur else None


def _agent_send(request_id, portal, rt, req, row, entry, tenant, username, end):
    """Hand ONE request to the submitter agent and own its clocks. The agent reports only through job/verify_step.py (sent, code, result).
    -> verified | closed (the helper or portal closed it) | failed:<code> | unknown. The tenant lock and the sitegate reservation are already held."""
    masked = rt.business_phone_masked(tenant)
    playbook = None
    try:
        raw = rt.verify_playbook(entry["domain"]) if hasattr(rt, "verify_playbook") else None
    except Exception as e:   # no DB read = no playbook = no signup carve-out; the run falls back to the row steps
        log("playbook read failed (%s); running without one" % type(e).__name__); raw = None
    if raw:
        try:
            playbook = dict(raw, steps=PB.render(raw, rt.tenant_values(tenant, username)))
            PB.send_step_number(playbook["steps"], bool(playbook.get("send_is_signup")))   # t_3223ee18 / t_8b8c2650: no marked send step (signup or sign-in) = no agent
        except PB.PlaybookError as e:   # a playbook that cannot be filled never reaches the agent
            log("playbook not usable: %s" % e); return end("failed", "send_failed")
    with contextlib.ExitStack() as stack:   # t_45fe02d4: the tenant's Chrome is up BEFORE the agent starts and closed after it (profile kept)
        try:
            if hasattr(rt, "agent_browser"): stack.enter_context(rt.agent_browser(tenant))
        except (BrowserError, OSError, RuntimeError) as e:
            log("agent browser not available: %s" % (e if isinstance(e, BrowserError) else type(e).__name__)); return end("failed", "send_failed")
        return _agent_run(request_id, portal, rt, req, row, entry, tenant, username, end, masked, playbook)


def _agent_run(request_id, portal, rt, req, row, entry, tenant, username, end, masked, playbook):
    try:
        prompt = build_prompt(request_id, req, row, entry, tenant, masked, username, playbook=playbook)
        agent = rt.launch_agent(rt.write_prompt(request_id, prompt), tenant_browser(tenant[0])[2])
        SB.stamp(request_id, "agent_start_at")
    except Exception as e:
        log("agent did not start: %s" % type(e).__name__); return end("failed", "send_failed")
    t0 = rt.now(); sent_at = closed_at = None; capped = False
    try:
        while agent.poll() is None:
            now = rt.now(); st = _status(portal, request_id)
            if st in LIVE_STATUSES and sent_at is None: sent_at = now
            if st in ("verified", "failed", "could_not_start") and closed_at is None: closed_at = now
            if sent_at is None and closed_at is None and now - t0 >= AGENT_START_S and st not in LIVE_STATUSES:
                log("agent never reported the send in %d s; killing it" % AGENT_START_S)
                agent.kill(); return end("failed", "send_failed")
            if sent_at is not None and closed_at is None and now - sent_at >= AGENT_AFTER_SENT_S:
                log("agent still running %d s after the send; killing it" % AGENT_AFTER_SENT_S); capped = True; break
            if closed_at is not None and now - closed_at >= AGENT_GRACE_S:
                log("request closed but the agent is still running; killing it"); break
            rt.sleep(AGENT_TICK_S)
    finally:
        agent.kill()   # idempotent; every way out of this function leaves no oneshot (or its children) behind
    st = _status(portal, request_id)
    if st == "verified":
        log("done %s verified (finished by the helper)" % request_id)
        if hasattr(rt, "write_back"):   # accepted only: rejected, failed, superseded and unknown never reach this line
            try: log("playbook write-back: %s" % rt.write_back(request_id, entry["domain"], SB.take_note(request_id)))
            except Exception as e: log("playbook write-back failed: %s" % type(e).__name__)   # never changes the run's result
        return "verified"
    if st in ("failed", "could_not_start"):
        log("done %s closed by the helper or the portal" % request_id); return "closed"
    if st in ("starting", "requested"):
        log("agent ended without a send report"); return end("failed", "send_failed")
    if st in LIVE_STATUSES:
        log("agent ended without a result"); return end("failed", "code_expired" if capped else "other")
    log("final status unreadable for %s; the sweeper will close it if it is stuck" % request_id); return "unknown"


def main(argv=None):
    a = argparse.ArgumentParser(description="Verify Now send run (one claimed request)")
    a.add_argument("--request-id", required=True)
    n = a.parse_args(argv)
    if not B.UUID_RE.match(n.request_id): log("bad request id"); return 2
    portal = P.Portal(*P.load_portal_env())
    out = run(n.request_id, portal, B.VerifyRpc(portal), Runtime())
    return 0 if out in ("verified", "not_claimed", "claim_lost", "deferred", "superseded", "closed", "unknown") or out.startswith(("failed", "could_not_start")) else 1


if __name__ == "__main__":
    sys.exit(main())
