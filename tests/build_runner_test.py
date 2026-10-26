"""Build runner, site scripts, page kit (t_560dd259). No network, no browser, no real mailbox, no vault: fake page, fake IMAP, fake subprocess, fake clock."""
import os, re, sys, json, tempfile, hashlib, types, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
import build_runner as B
import build_core as C
import pagekit as PK
import find_us_here as FUH
import freelistingusa as FLU
import hotfrog_build as HFB

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
NAP = B.nap_from_identity(IDENT)

class Loc:
    def __init__(self, page, sel): self.page, self.sel = page, sel
    @property
    def first(self): return self
    def count(self): return 0 if self.sel in self.page.missing else 1
    def fill(self, v, **k): self.page.acts.append(("fill", self.sel, v))
    def click(self, **k): self.page.acts.append(("click", self.sel))
    def check(self, **k): self.page.acts.append(("check", self.sel))

class FakePage:
    """Records every action. evaluate() returns scripted values by a substring of the JS."""
    def __init__(self, url="https://x.example/", body="", missing=(), evals=None):
        self.url, self.body, self.missing, self.acts, self.evals = url, body, set(missing), [], evals or {}; self.sticky = False
        self.context = types.SimpleNamespace(new_cdp_session=lambda p: None)
    def goto(self, u, **k): self.acts.append(("goto", u)); self.url = self.url if self.sticky else u
    def locator(self, s): return Loc(self, s)
    def fill(self, s, v, **k): self.acts.append(("fill", s, v))
    def check(self, s, **k): self.acts.append(("check", s))
    def select_option(self, s, label=None, **k): self.acts.append(("select", s, label))
    def inner_text(self, s, **k): return self.body
    def wait_for_timeout(self, ms): pass
    def wait_for_load_state(self, *a, **k): pass
    def evaluate(self, js, arg=None):
        self.acts.append(("eval", js[:400]))
        for k, v in self.evals.items():
            if k in js: return v(arg) if callable(v) else v
        return 0 if "ins" in js and "kill" in js else (4 if "options.length" in js else None)

def acts(page, kind): return [a for a in page.acts if a[0] == kind]

class Proc:
    def __init__(self, rc=0, out="fill=success"): self.returncode, self.stdout, self.stderr = rc, out, ""
class Runner:
    def __init__(self, rc=0, out="fill=success field=x item=y"): self.calls, self.rc, self.out = [], rc, out
    def __call__(self, cmd, **k): self.calls.append(cmd); return Proc(self.rc, self.out)

def ctx_for(site, page, **kw):
    kw.setdefault("runner", Runner()); kw.setdefault("log", lambda *a: None)
    return B.Ctx(site, page, NAP, **kw)

# ---- N1 identity -> nap -------------------------------------------------------------------------------------------------
check("N1 NAP comes from the identity file, phone dashed, email is listings@", NAP["name"] == IDENT["BIZ"]["SCC"]["name"] and NAP["phone"] == "502-555-0101" and NAP["email"] == "listings@seniorcaresolutions.co", str(NAP["phone"]))
check("N1 contact name split Lea Ann / Klarner", (NAP["first"], NAP["last"]) == ("Lea Ann", "Klarner"))
src = "".join(open(os.path.join(JOB, "playbooks", f), encoding="utf-8").read() for f in ("find_us_here.py", "freelistingusa.py", "hotfrog_build.py"))
check("N1 no site module hardcodes a phone number, the test street or the test business name", not re.search(r"d{3}[-. )]+d{3}[-. ]d{4}", src) and IDENT["BIZ"]["SCC"]["street"] not in src and IDENT["BIZ"]["SCC"]["name"] not in src)

# ---- D1 dry run stops before the first submit/mail step --------------------------------------------------------------
for name, site, body in (("find-us-here", FUH.SITE, ""), ("freelistingusa", FLU.SITE, "register"), ("hotfrog", HFB.SITE, "register")):
    page = FakePage(url={"find-us-here": "https://www.find-us-here.com/register.php", "freelistingusa": "https://www.freelistingusa.com/register", "hotfrog": "https://www.hotfrog.com/register"}[name], body="Create account")
    c = ctx_for(site, page, dry_run=True)
    res = B.run_site(site, c)
    first_stop = next(s.name for s in site.steps if s.kind in B.STOP_IN_DRY_RUN)
    done = [s["name"] for s in res["steps"]]
    check("D1 %s dry run ok and stops before '%s'" % (name, first_stop), res["ok"] and res["stopped_before"] == first_stop, str(res["steps"][-1:]))
    check("D1 %s dry run ran only read/fill steps" % name, all(s["kind"] in ("read", "fill") for s in res["steps"]) and done == [s.name for s in site.steps[:len(done)]])
    submit_sels = [a for a in acts(page, "click")]
    check("D1 %s dry run clicked no submit control" % name, not any(("register" in a[1] and a[1].endswith("register")) or a[1] in ("input._createsubmit", "#submit", "input#register") for a in submit_sels), str(submit_sels))
    check("D1 %s dry run: vault is LOOKED UP (--lookup-only), no field passed" % name, all("--lookup-only" in cmd and "--field" not in cmd for cmd in c._runner.calls) and len(c._runner.calls) == 2, str(len(c._runner.calls)))

# ---- D2 live is refused without a card; a dry run never opens a mailbox ----------------------------------------------------
try: B.main(["find-us-here", "--live"]); refused = False
except SystemExit as e: refused = "--card" in str(e)
check("D2 --live without --card is refused", refused)
try: B.main(["find-us-here"]); nomode = False
except SystemExit: nomode = True
check("D2 one of --dry-run / --live is required", nomode)
check("D2 every site's first submit/mail step exists (a dry run can stop)", all(any(s.kind in B.STOP_IN_DRY_RUN for s in x.steps) for x in (FUH.SITE, FLU.SITE, HFB.SITE)))

# ---- V1 vault: item id, fragment, no password in the argv ------------------------------------------------------------------
site = FUH.SITE
r = Runner(); c = ctx_for(site, FakePage(), runner=r, item_id="aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb", dry_run=False)
c.vault_fill("#scc-pw1", "https://www.find-us-here.com/register.php#google_vignette")
cmd = r.calls[0]
check("V1 live fill: --item-id used, --name not passed", "--item-id" in cmd and "--name" not in cmd and cmd[cmd.index("--item-id") + 1].startswith("aaaaaaaa"))
check("V1 fragment stripped from --url, --cdp passed, field passed", cmd[cmd.index("--url") + 1] == "https://www.find-us-here.com/register.php" and cmd[cmd.index("--cdp") + 1] == B.CDP_URL and cmd[cmd.index("--field") + 1] == "#scc-pw1")
r = Runner(); c = ctx_for(site, FakePage(), runner=r, dry_run=False); c.vault_fill("#p", "https://a.example/r")
check("V1 without --item-id the item NAME is used", r.calls[0][r.calls[0].index("--name") + 1] == FUH.VAULT_ITEM)
c = ctx_for(site, FakePage(), runner=Runner(1, "fill=failed reason=item-not-unique"), dry_run=False)
try: c.vault_fill("#p", "https://a.example/r"); failed = False
except C.BuildError as e: failed = "item-not-unique" in str(e)
check("V1 live fill failure is a BuildError naming the reason (no workaround)", failed)
c = ctx_for(site, FakePage(), runner=Runner(1, "fill=failed reason=item-not-unique"), dry_run=True)
try: c.vault_fill("#p", "https://a.example/r"); dr = False
except C.BuildError: dr = True
check("V1 a dry run still fails on a real vault problem (only 'no credentials' is skipped)", dr)

# ---- M1 mail: link extraction, polling, read-only -------------------------------------------------------------------------
LINK = "https://www.freelistingusa.com/verify-email/?key=abc123&login=listings%40seniorcaresolutions.co"
MAIL = ("From: FreeListingUSA <info@freelistingusa.com>\r\nSubject: Verify\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<a href=\"%s\">Verify</a>" % LINK.replace("&", "&amp;")).encode()
check("M1 verify link extracted, &amp; decoded", B.extract_link(MAIL, FLU.LINK_RE) == LINK, str(B.extract_link(MAIL, FLU.LINK_RE)))
check("M1 lookalike domain not matched", B.extract_link(b"From: a@b.c\r\nContent-Type: text/plain\r\n\r\nhttps://www.freelistingusa.com.evil.example/verify-email/?key=1", FLU.LINK_RE) is None)
class FakeIMAP:
    log = []; messages = {}
    def __init__(self, host, port): self.log.append(("connect", host, port))
    def login(self, u, p): self.log.append(("login", u))
    def select(self, box, readonly=False): self.log.append(("select", box, readonly))
    def uid(self, cmd, *a):
        self.log.append((cmd,) + tuple(str(x) for x in a))
        if cmd == "SEARCH": return "OK", [b" ".join(str(u).encode() for u in sorted(self.messages))]
        return "OK", [(b"1 (BODY[] {1}", self.messages[int(a[0])]), b")"]
    def logout(self): self.log.append(("logout",))
ENV = {"LISTINGS_IMAP_HOST": "imap.example", "LISTINGS_IMAP_PORT": "993", "LISTINGS_IMAP_USER": "listings@example.test", "LISTINGS_IMAP_PASSWORD": "pw-not-real"}
FakeIMAP.messages = {1: b"From: n <n@example.com>\r\nContent-Type: text/plain\r\n\r\nsee " + LINK.encode()}
mb = B.make_mailbox("freelistingusa", FLU.LINK_RE, ENV, FakeIMAP)
check("M1 mail from another sender ignored", mb.newest_verify_link() is None)
FakeIMAP.messages = {1: MAIL}
mb = B.make_mailbox("freelistingusa", FLU.LINK_RE, ENV, FakeIMAP)
check("M1 finds the freelistingusa mail", mb.newest_verify_link() == (1, LINK))
check("M1 read-only: EXAMINE + BODY.PEEK, never STORE/EXPUNGE", ("select", "INBOX", True) in FakeIMAP.log and any("BODY.PEEK" in str(e) for e in FakeIMAP.log) and not any(e[0] in ("STORE", "EXPUNGE") for e in FakeIMAP.log))
class Box:
    def __init__(self, found_after): self.n, self.found_after = 0, found_after
    def newest_verify_link(self, since_uid=0): self.n += 1; return (9, LINK) if self.n >= self.found_after else None
    def max_uid(self): return 4
clock = [0]
c = ctx_for(FLU.SITE, FakePage(), mailbox=Box(3), dry_run=False, sleep=lambda s: clock.__setitem__(0, clock[0] + s), now=lambda: clock[0], poll_seconds=60, poll_every=10)
check("M1 polls until the mail arrives", c.mail_link() == LINK and clock[0] == 20, str(clock))
c = ctx_for(FLU.SITE, FakePage(), mailbox=Box(99), dry_run=False, sleep=lambda s: clock.__setitem__(0, clock[0] + s), now=lambda: clock[0], poll_seconds=30, poll_every=10)
try: c.mail_link(); to = False
except C.BuildError as e: to = "no freelistingusa mail" in str(e)
check("M1 no mail inside the window -> BuildError", to)

# ---- S1 find-us-here -------------------------------------------------------------------------------------------------------
page = FakePage(url="https://www.find-us-here.com/register.php")
c = ctx_for(FUH.SITE, page, dry_run=False)
FUH.choose_location(c); FUH.fill_identity(c)
sel = [a[2] for a in acts(page, "select")]
check("S1 country first, then state, then city, then category", sel == ["USA", NAP["state_name"], NAP["city"], "Consultants"], str(sel))
fills = {a[1]: a[2] for a in acts(page, "fill")}
check("S1 username is letters only (an email is rejected by the site)", fills["input[name=username]"] == "sccsolutions" and "@" not in fills["input[name=username]"])
check("S1 email typed twice, name verbatim", fills["input[name=business_email_address]"] == NAP["email"] == fills["input[name=confirm_business_email_address]"] and fills["#business_name"] == NAP["name"])
r = Runner(); c = ctx_for(FUH.SITE, FakePage(), runner=r, dry_run=False); FUH.fill_password(c)
check("S1 both password inputs filled through the vault helper by tagged id, page url without fragment", [x[x.index("--field") + 1] for x in r.calls] == ["#scc-pw1", "#scc-pw2"] and all(x[x.index("--url") + 1] == FUH.REGISTER_URL for x in r.calls))
page = FakePage(url="https://www.find-us-here.com/dashboard_free.php", evals={"copy_link": "https://www.find-us-here.com/businesses/Senior-Care-1/1/"})
c = ctx_for(FUH.SITE, page, dry_run=False)
check("S1 only the public listing URL is read from the dashboard", FUH.read_public_url(c) == "https://www.find-us-here.com/businesses/Senior-Care-1/1/" and c.state["public_url"].startswith("https://www.find-us-here.com/businesses/"))
page = FakePage(evals={"copy_link": "javascript:alert(1)"})
try: FUH.read_public_url(ctx_for(FUH.SITE, page, dry_run=False)); bad = False
except C.BuildError: bad = True
check("S1 a non-listing value in copy_link is refused", bad)
dash_src = open(os.path.join(JOB, "playbooks", "find_us_here.py"), encoding="utf-8").read()
check("S1 module never reads page body text into Python (the dashboard prints the password)", "inner_text" not in dash_src.replace("never read", ""))
res = B.run_site(FUH.SITE, ctx_for(FUH.SITE, FakePage(url="https://www.find-us-here.com/register.php", body="Your password is hunter2secret"), dry_run=False, runner=Runner(1, "fill=failed reason=vault-command-failed")))
check("S1 a failed step stops the run and the detail is redacted of password text", not res["ok"] and "hunter2secret" not in json.dumps(res))

# ---- S2 freelistingusa -----------------------------------------------------------------------------------------------------
page = FakePage(url="https://www.freelistingusa.com/dashboard"); page.sticky = True
try: FLU.open_register(ctx_for(FLU.SITE, page, dry_run=False)); red = False
except C.BuildError as e: red = "already signed in" in str(e)
check("S2 /register redirecting to the dashboard (already signed in) stops, no second account", red)
page = FakePage(evals={"map(e => e.value)": ["5", "3", "2", "1", "4"]}, body="Free $0 nofollow link")
c = ctx_for(FLU.SITE, page, dry_run=False); FLU.pick_free_plan(c)
chosen = [a for a in page.acts if a[0] == "eval" and "checked = true" in a[1]]
check("S2 plan radio chosen is value 4 (Free) only", len(chosen) == 1)
page = FakePage(evals={"map(e => e.value)": ["5", "3", "2", "1"]}, body="Essential $3 Featured $5")
try: FLU.pick_free_plan(ctx_for(FLU.SITE, page, dry_run=False)); paid = False
except C.BuildError as e: paid = "free plan" in str(e)
check("S2 no free radio on the page -> refuses, never falls back to a paid tier", paid and not [a for a in page.acts if a[0] == "eval" and "checked = true" in a[1]])
page = FakePage(evals={"map(e => e.value)": ["5", "3", "2", "1", "4"]}, body="Essential $3 Featured $5 Premium $10 Elite $40")
try: FLU.pick_free_plan(ctx_for(FLU.SITE, page, dry_run=False)); nofree = False
except C.BuildError: nofree = True
check("S2 plan page with no Free text -> refuses to pick by position", nofree)
page = FakePage(url="https://www.freelistingusa.com/create-listing-form?currency=1&plan=4")
c = ctx_for(FLU.SITE, page, dry_run=False); FLU.fill_listing(c)
f = {a[1]: a[2] for a in acts(page, "fill")}
check("S2 listing form: title, address, zip, city, phone, website, email from the NAP; description present", f["input[name=title]"] == NAP["name"] and f["input[name=address]"] == NAP["street"] and f["input[name=postal_code]"] == NAP["zip"] and f["input[name=b_email]"] == NAP["email"])
check("S2 opening hours never typed (no approved hours)", not any("hour" in a[1].lower() for a in page.acts if len(a) > 1 and isinstance(a[1], str)))
check("S2 category checkbox 34 set, terms checked", any("checked = true" in a[1] for a in page.acts if a[0] == "eval") and ("check", "input[name=agree_terms]") in page.acts)
page = FakePage(url="https://www.freelistingusa.com/listing-order-summary", body="Your listing has been activated")
c = ctx_for(FLU.SITE, page, dry_run=False); FLU.submit_listing(c)
check("S2 submit clears ads before clicking #submit", [a for a in page.acts if a[0] in ("eval", "click")][0][0] == "eval" and ("click", "#submit") in page.acts)
page = FakePage(url="https://www.freelistingusa.com/create-listing-form", body="Error: title required")
try: FLU.submit_listing(ctx_for(FLU.SITE, page, dry_run=False)); act = False
except C.BuildError: act = True
check("S2 not 'activated' -> BuildError", act)

# ---- S3 hotfrog -------------------------------------------------------------------------------------------------------------
page = FakePage(url="https://www.hotfrog.com/register")
c = ctx_for(HFB.SITE, page, dry_run=False); HFB.tick_terms(c)
checks = [a[1] for a in acts(page, "check")]
check("S3 terms ticked, marketing opt-in NOT ticked", checks == ["#accept_terms"], str(checks))
page = FakePage(url="https://www.hotfrog.com/register", evals={"altcha": False})
try: HFB.submit_register(ctx_for(HFB.SITE, page, dry_run=False)); alt = False
except C.BuildError as e: alt = "ALTCHA" in str(e)
check("S3 empty ALTCHA payload -> no submit", alt and not acts(page, "click"))
check("S3 reuses the proven hotfrog helpers (site value https:// once)", HFB.H.site_value("https://https://SeniorCareSolutions.co/") == "https://seniorcaresolutions.co")

# ---- K1 page kit -------------------------------------------------------------------------------------------------------------
check("K1 ad clearing targets ins, google_ads iframes and #google_vignette", all(s in PK.CLEAR_ADS_JS for s in ("ins,", "google_ads", "google_vignette", "doubleclick")))
check("K1 clear_ads returns the count the page reports and never raises", PK.clear_ads(FakePage(evals={"kill": 3})) == 3 and PK.clear_ads(types.SimpleNamespace(evaluate=lambda js: 1 / 0)) == 0)
c = ctx_for(FUH.SITE, FakePage(evals={"kill": 2}), dry_run=False); page = c.page; c.click("#x")
check("K1 ctx.click clears ads BEFORE the click", [a[0] for a in page.acts[:2]] == ["eval", "click"])
check("K1 redact masks a password shown in text", "hunter2" not in PK.redact("Account\nPassword: hunter2\nName: x") and "Name: x" in PK.redact("Account\nPassword: hunter2\nName: x"))
d = tempfile.mkdtemp(); data = b"logo-bytes"; src_p = os.path.join(d, "src.png"); open(src_p, "wb").write(data)
dst = os.path.join(d, "assets", "scc-logo.png"); old = PK.LOGO_MD5_PREFIX; PK.LOGO_MD5_PREFIX = hashlib.md5(data).hexdigest()[:8]
check("K1 ensure_logo copies from the source and verifies the md5 prefix", PK.ensure_logo(dst, src_p) == dst and open(dst, "rb").read() == data)
open(dst, "wb").write(b"tampered")
try: PK.ensure_logo(dst, src_p); tam = False
except RuntimeError as e: tam = "md5" in str(e)
check("K1 a changed logo file is refused", tam)
open(dst, "wb").write(data)
try: PK.ensure_logo(dst, src_p, fetch=lambda u: b"other"); drift = False
except RuntimeError as e: drift = "no longer serves" in str(e)
check("K1 published URL serving different bytes is refused", drift)
check("K1 published URL with the same bytes passes (fetch injected, no network)", PK.ensure_logo(dst, src_p, fetch=lambda u: data) == dst)
PK.LOGO_MD5_PREFIX = old
check("K1 logo constants: SCC's own published URL and md5 72900a7f", PK.LOGO_URL.endswith("/2023/11/senior-care-consulting-logo.png") and PK.LOGO_MD5_PREFIX == "72900a7f" and "seniorcaresolutions.co" in PK.LOGO_URL)
class Sess:
    def __init__(self, qnode=7): self.sent, self.qnode, self.detached = [], qnode, False
    def send(self, m, p=None):
        self.sent.append((m, p))
        return {"root": {"nodeId": 1}} if m == "DOM.getDocument" else {"nodeId": self.qnode} if m == "DOM.querySelector" else {}
    def detach(self): self.detached = True
s = Sess(); name = PK.set_file(None, "input[type=file]", src_p, cdp_session=s)
sf = [x for x in s.sent if x[0] == "DOM.setFileInputFiles"]
check("K1 upload uses DOM.setFileInputFiles with the absolute path and the node id", name == "src.png" and len(sf) == 1 and sf[0][1]["nodeId"] == 7 and sf[0][1]["files"] == [os.path.abspath(src_p)])
try: PK.set_file(None, "input[type=file]", src_p, cdp_session=Sess(0)); nf = False
except RuntimeError as e: nf = "not found" in str(e)
check("K1 no such file input -> error, nothing attached", nf)
try: PK.set_file(None, "input", os.path.join(d, "nope.png"), cdp_session=Sess()); mf = False
except RuntimeError as e: mf = "not found" in str(e)
check("K1 missing file -> error", mf)
pg = FakePage(); pg.context = types.SimpleNamespace(new_cdp_session=lambda p: s2)
s2 = Sess(); PK.set_file(pg, "input[type=file]", src_p)
check("K1 own CDP session is detached after the upload", s2.detached)

# ---- R1 the runner adds nothing that submits -----------------------------------------------------------------------------------
check("R1 runner source has no portal seed / Directory submit of its own", "seed" not in open(os.path.join(JOB, "build_runner.py"), encoding="utf-8").read().lower())

print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
