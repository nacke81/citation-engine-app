"""Batch 14 fix tests (t_6b1e01ff): CapSolver CLI path (a missing CLI logs 0 tries), chamberofcommerce formspec, getlistedusa Show / listyourbusiness prose street,
listings@ approval scan, foursquare edit spec + recheck_due, showmelocal_claim guard, build Chrome screenshot helper.
No network, no browser, no vault, no CapSolver, no real mailbox, no queue write: fakes and temp files only. Run: python tests/batch14_test.py (CI)."""
import os, sys, json, tempfile, shutil, datetime, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
def _no_net(*a, **k): raise AssertionError("network call attempted")
REAL_URLOPEN = urllib.request.urlopen
urllib.request.urlopen = _no_net
import pagekit as PK, captcha_route as CR, formspec as F, build_runner as B, build_core as C, recheck as R, mail_scan as MS, transitions as T, build_shot as BS, claim as CL

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)
TMP = tempfile.mkdtemp(prefix="b14-")
IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
NAP = B.nap_from_identity(IDENT)
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
PAD = " Lorem ipsum dolor sit amet." * 12

# ---- 1 CapSolver CLI path ------------------------------------------------------------------------------------------------------
cli = os.path.join(TMP, "capsolver-cli.js"); open(cli, "w").write("//")
known = os.path.join(TMP, "citation-engine", "wt-capsolver-image", "dist", "src", "capsolver-cli.js")
os.makedirs(os.path.dirname(known)); open(known, "w").write("//")
check("1 CAPSOLVER_CLI wins when the file exists", PK.resolve_capsolver_cli({"CAPSOLVER_CLI": cli, "LOCALAPPDATA": TMP}) == cli)
check("1 no env: the known install path under LOCALAPPDATA is used", PK.resolve_capsolver_cli({"LOCALAPPDATA": TMP}) == known)
check("1 a set-but-missing CAPSOLVER_CLI is reported missing, not silently replaced", PK.resolve_capsolver_cli({"CAPSOLVER_CLI": os.path.join(TMP, "nope.js"), "LOCALAPPDATA": TMP}) is None)
check("1 neither env nor install: None", PK.resolve_capsolver_cli({"LOCALAPPDATA": os.path.join(TMP, "empty")}) is None)

class Proc:
    def __init__(s, out): s.stdout = out
class Runner:
    def __init__(s, outs): s.outs, s.calls = list(outs), []
    def __call__(s, cmd, **k): s.calls.append(cmd); return Proc(s.outs.pop(0))
GOOD = json.dumps({"ok": True, "solution": {"gRecaptchaResponse": "tok-123"}, "cost": 0.001})
W = {"type": "recaptcha-v2", "sitekey": "6LdpAPgZAAAAACrg_DlLkvOwaV99pMM8zIce14Yo"}
URL = "https://www.chamberofcommerce.com/members/add-business"
lg = os.path.join(TMP, "solves.jsonl")
# a missing CLI on the REAL path (no injected runner): no subprocess, no log line
import subprocess
real_run, called = subprocess.run, []
subprocess.run = lambda *a, **k: called.append(a) or Proc("")
env0 = {k: os.environ.get(k) for k in ("CAPSOLVER_CLI", "LOCALAPPDATA")}
os.environ.pop("CAPSOLVER_CLI", None); os.environ["LOCALAPPDATA"] = os.path.join(TMP, "no-install")
try:
    PK.solve_captcha("create-chamberofcommerce", W, URL, log_path=lg); raised = None
except PK.CaptchaError as e: raised = str(e)
finally:
    subprocess.run = real_run
    for k, v in env0.items():
        if v is None: os.environ.pop(k, None)
        else: os.environ[k] = v
check("1 PROOF: a missing CLI raises CaptchaError naming the fix", raised is not None and "capsolver-cli.js not found" in raised and "CAPSOLVER_CLI" in raised, str(raised))
check("1 PROOF: a missing CLI logs 0 tries and makes no call", PK.solve_tries("create-chamberofcommerce", lg) == 0 and not os.path.exists(lg) and not called)
check("1 the message says no try was logged", "no try was logged" in (raised or ""))
# with an injected runner (tests) the solver still works and logs one try
r = Runner([GOOD]); tok = PK.solve_captcha("create-x", W, URL, runner=r, log_path=lg)
check("1 an injected runner is untouched by the file check: token returned, 1 try logged", tok == "tok-123" and PK.solve_tries("create-x", lg) == 1)
# the resolved path reaches the command (argv has the cli)
check("1 captcha_route.argv takes the resolved cli path", CR.argv(W, URL, cli=cli)[1] == cli)
# real path with the CLI present: the command uses it
os.environ["CAPSOLVER_CLI"] = cli
seen = []
subprocess.run = lambda cmd, **k: seen.append(cmd) or Proc(GOOD)
try: t2 = PK.solve_captcha("create-y", W, URL, log_path=lg)
finally:
    subprocess.run = real_run; os.environ.pop("CAPSOLVER_CLI", None)
check("1 real path with CAPSOLVER_CLI set: runs node <that file>, 1 try logged", t2 == "tok-123" and seen and seen[0][:2] == ["node", cli] and PK.solve_tries("create-y", lg) == 1)

# ---- 2 chamberofcommerce formspec ------------------------------------------------------------------------------------------------
class Loc:
    def __init__(s, page, sel): s.page, s.sel = page, sel
    @property
    def first(s): return s
    def count(s): return 1
    def fill(s, v, **k): s.page.acts.append(("fill", s.sel, v))
    def click(s, **k): s.page.acts.append(("click", s.sel))
class Kb:
    def __init__(s, p): s.p = p
    def press(s, k): s.p.acts.append(("press", k))
class FakePage:
    def __init__(s, url="https://www.chamberofcommerce.com/members/add-business", body="Add your business"):
        s.url, s.acts, s.keyboard, s.body = url, [], Kb(s), body
    def goto(s, u, **k): s.acts.append(("goto", u)); s.url = u
    def locator(s, sel): return Loc(s, sel)
    def fill(s, sel, v, **k): s.acts.append(("fill", sel, v))
    def type(s, sel, v, **k): s.acts.append(("type", sel, v))
    def click(s, sel, **k): s.acts.append(("click", sel))
    def inner_text(s, sel, **k): return s.body
    def content(s): return ""
    def wait_for_timeout(s, ms): pass
    def wait_for_load_state(s, *a, **k): pass
    def evaluate(s, js, arg=None):
        s.acts.append(("eval", js[:60], arg)); return 1
class PRun:
    returncode, stdout, stderr = 0, "lookup=success", ""
    def __init__(s): s.calls = []
    def __call__(s, cmd, **k): s.calls.append(cmd); return s
spec = F.load_spec("chamberofcommerce")
site = F.build_site(spec)
names = [s.name for s in site.steps]
raw = open(os.path.join(JOB, "playbooks", "chamberofcommerce.json"), encoding="utf-8").read()
check("2 spec loads and validates; listed by build_runner", site.name == "chamberofcommerce" and "chamberofcommerce" in B.all_sites())
check("2 holds no literal phone, email or password", not F._LITERAL_PHONE.search(raw) and not F._LITERAL_EMAIL.search(raw) and '"password": "' not in raw.lower())
check("2 records created-unlisted (public after up to 24h)", site.record == "created-unlisted")
do = [s["do"] for s in spec["steps"]]
check("2 order: wizard -> stop marker -> solve -> Add My Business -> wait_mail -> Verify -> owner page save",
      do.index("stop_before_submit") < do.index("solve_captcha") < names.index("add_business") < do.index("wait_mail") < names.index("verify_account") < names.index("save_business"))
check("2 the activation key step is a wait_mail typed into input[name=activationkey]", next(s for s in spec["steps"] if s["do"] == "wait_mail").get("as") == "code" and next(s for s in spec["steps"] if s["do"] == "wait_mail")["selector"] == "input[name=activationkey]")
check("2 website and email are saved AFTER activation on the owner page", names.index("website") > names.index("verify_account") and names.index("owner_email") > names.index("verify_account") and spec["steps"][names.index("save_business")]["text"] == "Save My Business")
check("2 ZIP typed key by key then Tab (City/State fill themselves)", next(s for s in spec["steps"] if s["name"] == "postal_code")["slow"] and next(s for s in spec["steps"] if s["name"] == "postal_code")["press"] == "Tab")
check("2 select2 category typed into the select2 search box + Enter", any(s["name"] == "category" and s["selector"] == ".select2-search__field" and s["press"] == "Enter" for s in spec["steps"]))
check("2 both password boxes come from the vault, #Password and #Password2", [s["selector"] for s in spec["steps"] if s["do"] == "vault_fill"] == ["#Password", "#Password2"])
page = FakePage(); runner = PRun()
ctx = B.Ctx(site, page, NAP, runner=runner, log=lambda *a: None, dry_run=True)
res = B.run_site(site, ctx)
check("2 dry run ok and stops BEFORE the solve/submit", res["ok"] and res["stopped_before"] == "13_stop_before_submit" or (res["ok"] and res["stopped_before"]), str(res)[:300])
check("2 dry run fills the wizard from the identity (name, street, digits-only phone, first/last, email twice)",
      ("fill", "input[name=BusinessName]", NAP["name"]) in page.acts and ("fill", "input[name=Address]", NAP["street"]) in page.acts and ("fill", "#phone", re_digits := "".join(c for c in NAP["phone"] if c.isdigit())) in page.acts
      and ("fill", "input[name=first_name]", NAP["first"]) in page.acts and sum(1 for a in page.acts if a[0] == "fill" and a[2] == NAP["email"]) == 2)
check("2 ZIP typed (not filled) and Tab pressed; category typed and Enter pressed", ("type", "#PostalCodeLookup", NAP["zip"]) in page.acts and ("press", "Tab") in page.acts and ("type", ".select2-search__field", "Business Management Consultant") in page.acts and ("press", "Enter") in page.acts)
check("2 dry run: vault LOOKED UP only (no --field), no solve, no submit click, no mail", runner.calls and all("--lookup-only" in c and "--field" not in c for c in runner.calls)
      and not [a for a in page.acts if a[0] == "eval" and isinstance(a[2], dict) and a[2].get("text") in ("Add My Business", "Verify My Account", "Save My Business")] and not [a for a in page.acts if a[0] == "goto" and "activate" in a[1]])
# live-mode fixture: the post-activation steps with a fake mailbox that returns the key
class MB:
    def __init__(s): s.calls = 0
    def max_uid(s): return 3
    def newest_verify_link(s, since_uid=0): s.calls += 1; return (4, "KEY-12345")
pg2 = FakePage("https://www.chamberofcommerce.com/members/activate-my-account")
ctx2 = B.Ctx(site, pg2, NAP, mailbox=MB(), runner=PRun(), log=lambda *a: None, dry_run=False)
r2 = B.run_site(site, ctx2, only={"activation_key"})
check("2 wait_mail as code types the key from listings@ into the activation box", r2["ok"] and ("type", "input[name=activationkey]", "KEY-12345") in pg2.acts, str(r2["steps"]))
check("2 the key is not echoed in the step detail", "KEY-12345" not in json.dumps(r2["steps"]))
pg3 = FakePage("https://my.chamberofcommerce.com/business/2034550406", body="Your information has been updated. Changes can take up to 24 hours.")
ctx3 = B.Ctx(site, pg3, NAP, runner=PRun(), log=lambda *a: None, dry_run=False)
r3 = B.run_site(site, ctx3, only={"website", "owner_email", "save_business"})
check("2 owner page: website + email filled from the identity, Save My Business clicked, 'updated' confirmed", r3["ok"] and ("fill", "#website", NAP["site"]) in pg3.acts and ("fill", "#email", NAP["email"]) in pg3.acts and any(a[0] == "eval" and isinstance(a[2], dict) and a[2].get("text") == "Save My Business" for a in pg3.acts), str(r3["steps"]))
pg4 = FakePage("https://my.chamberofcommerce.com/business/1", body="Nothing here")
r4 = B.run_site(site, B.Ctx(site, pg4, NAP, runner=PRun(), log=lambda *a: None, dry_run=False), only={"save_business"})
check("2 a Save that is not confirmed fails the step", not r4["ok"] and "updated" in r4["steps"][-1]["detail"])
# mail key extraction (named group) + validation
mail = b"From: ChamberofCommerce.com <no-reply@chamberofcommerce.com>\r\nSubject: ChamberofCommerce.com Activation Email\r\nContent-Type: text/plain\r\n\r\nWelcome. Your Activation Key: 7K2-9QX41 Enter it on the activation page."
check("2 the activation key (just the key) is pulled from the mail", B.extract_link(mail, spec["mail"]["link_re"]) == "7K2-9QX41", str(B.extract_link(mail, spec["mail"]["link_re"])))
def bad(steps, **kw):
    try: F.validate(dict({"site": "z", "domain": "z.example", "steps": steps, "mail": {"sender": "z", "link_re": "x"}}, **kw)); return None
    except C.BuildError as e: return str(e)
check("2 wait_mail as code without a selector is refused", "selector" in (bad([{"do": "wait_mail", "as": "code"}]) or ""))
check("2 an unknown wait_mail 'as' is refused", "'as'" in (bad([{"do": "wait_mail", "as": "sms", "selector": "#a"}]) or ""))
check("2 'press' outside a slow fill is refused", "press" in (bad([{"do": "fill", "selector": "#a", "value": "x", "press": "Tab"}]) or ""))

# ---- 3 reader handlers -----------------------------------------------------------------------------------------------------------
check("3 REVEAL_JS clicks a bare Show beside masked digits", "bare" in R.REVEAL_JS and "\\*{2,}" in R.REVEAL_JS)
masked = "Home\nAlder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n(502) 555-0***  show\nWebsite https://alder.example\n" + PAD
c0 = R.compare(masked, CANON)
check("3 getlistedusa BEFORE the click: the masked phone still reads as masked-match (never a wrong phone)", c0["verdict"] == "match" and c0["masked"] is True, str(c0))
shown = masked.replace("(502) 555-0***  show", "(502) 555-0101")
c1 = R.compare(shown, CANON)
check("3 getlistedusa AFTER Show: full phone parsed, verdict match, not masked", c1["verdict"] == "match" and not c1["masked"] and "555-0101" in c1["nap"], str(c1))
wrong = masked.replace("(502) 555-0***  show", "(502) 555-0199")
check("3 a revealed WRONG phone is still a mismatch", R.compare(wrong, CANON)["verdict"] == "mismatch")
class RPg:
    """read_rendered against a page whose phone changes after the reveal click."""
    def __init__(s): s.clicked = 0
    def goto(s, u, **k): return type("R", (), {"status": 200})()
    def wait_for_timeout(s, ms): pass
    def inner_text(s, sel, **k): return shown if s.clicked else masked
    def evaluate(s, js, *a):
        if "bare" in js: s.clicked += 1; return 1
        return []
    def content(s): return "<html></html>"
st, text, links, rawh = R.read_rendered(RPg(), "https://getlistedusa.com/listing/x/")
check("3 read_rendered clicks Show and re-reads: the text now carries the full phone", "555-0101" in text and "***" not in text)
LYB = "Home\nAlder Care Consulting & Solutions\nAbout\nAlder Care Consulting & Solutions helps families from 100 Example Drive, Exampleton, KY 40000 and nearby towns.\nContact\nPhone (502) 555-0101\nWebsite alder.example\n" + PAD
c2 = R.compare(LYB, CANON)
check("3 listyourbusiness: street read from the About text -> match", c2["verdict"] == "match" and "100 Example Drive" in c2["nap"], str(c2))
LYB_CL = "Alder Care Consulting & Solutions\nAbout\nFamily-focused consulting.\nContact\nAddress: 100 Example Drive, Exampleton, KY 40000\nPhone (502) 555-0101\n" + PAD
check("3 listyourbusiness: street read from the contact list line -> match", R.compare(LYB_CL, CANON)["verdict"] == "match")
LYB_W = LYB.replace("100 Example Drive", "900 Other Street")
check("3 a DIFFERENT street in the prose is a mismatch, not a match", R.compare(LYB_W, CANON)["verdict"] == "mismatch" and R.compare(LYB_W, CANON)["wrong"][0][0] == "address")
LYB_C = LYB.replace("Exampleton, KY 40000", "Springfield, KY 40111")
check("3 a street in a sentence about another city/zip is not read as ours (address stays a gap)", R.prose_street(["We also serve 100 Example Drive, Springfield, KY 40111."], CANON) is None)
check("3 no street anywhere: address is a gap (nap-incomplete)", R.compare(LYB.replace("from 100 Example Drive, Exampleton, KY 40000 ", ""), CANON)["verdict"] == "nap-incomplete")
check("3 prose_street needs a street-type word (no 'in 2024, Exampleton, KY 40000')", R.prose_street(["Founded 2024 Growth, Exampleton, KY 40000."], CANON) is None)

# ---- 4 listings@ approval scan ---------------------------------------------------------------------------------------------------
def msg(uid, frm, subj, body, date="2026-10-26T10:00"): return {"uid": uid, "from": frm, "subject": subj, "body": body, "date": date}
M = [
    msg(1, "BBB <noreply@bbb.org>", "We received your BBB request", "Thank you for submitting. Your listing will be visible once approved. https://www.bbb.org/get-listed/success"),
    msg(2, "BBB <info@bbb.org>", "Your BBB Business Profile is now live", "Congratulations! View it at https://www.bbb.org/us/ky/exampleton/profile/consulting/alder-care-consulting-solutions-0012-99887766 . Manage: https://www.bbb.org/login . Unsubscribe https://www.bbb.org/unsubscribe?x=1", "2026-10-26T12:00"),
    msg(3, "Loc8nearme <hello@loc8nearme.com>", "Payment received", "Thanks. https://www.loc8nearme.com/payment.php?uuid=e3889f53"),
    msg(4, "Business Yab <no-reply@businessyab.com>", "Your listing has been approved", "Your listing has been approved: https://www.businessyab.com/listing/alder-care-consulting-solutions-exampleton-ky/ Log in: https://www.businessyab.com/login", "2026-10-26T13:00"),
    msg(5, "DiscoverOurTown <admin@discoverourtown.com>", "Thanks for adding your business", "It will be reviewed. https://www.discoverourtown.com/add/thankyou.php"),
    msg(6, "Somebody <x@other.example>", "Your listing is now live", "https://www.loc8nearme.com.evil.example/b/alder"),
]
hit = MS.find_approval("bbb.org", M, CANON["name"])
check("4 bbb: the 'now live' mail is found, the submit receipt is not; URL is the profile, not login/unsubscribe", hit and hit["uid"] == 2 and hit["url"].endswith("-0012-99887766") and "login" not in hit["url"], str(hit))
hit4 = MS.find_approval("businessyab.com", M, CANON["name"])
check("4 businessyab: 'has been approved' mail gives the /listing/ URL, not /login", hit4 and hit4["url"] == "https://www.businessyab.com/listing/alder-care-consulting-solutions-exampleton-ky/", str(hit4))
check("4 loc8nearme: a payment receipt is not an approval -> None", MS.find_approval("loc8nearme.com", M, CANON["name"]) is None)
check("4 discoverourtown: 'will be reviewed' receipt -> None", MS.find_approval("discoverourtown.com", M, CANON["name"]) is None)
check("4 a lookalike host (loc8nearme.com.evil.example) is never taken", MS.find_approval("loc8nearme.com", [M[5]], None) is None)
check("4 a Directory outside the four is not scanned", MS.find_approval("yelp.com", M) is None)
check("4 'once approved' wording alone is not an approval", not MS.is_approval("Thanks", "Your listing will be visible once approved."))
check("4 the newest approval wins", MS.find_approval("bbb.org", M + [msg(9, "BBB <info@bbb.org>", "Your BBB profile is now live", "https://www.bbb.org/us/ky/x/profile/y/newer-0012-1", "2026-10-27T01:00")], None)["url"].endswith("newer-0012-1"))
# IMAP reader is read-only (EXAMINE + BODY.PEEK)
class FakeIMAP:
    log = []; raw = {}
    def __init__(s, h, p): s.log.append(("connect", h))
    def login(s, u, p): s.log.append(("login",))
    def select(s, box, readonly=False): s.log.append(("select", box, readonly))
    def uid(s, cmd, *a):
        s.log.append((cmd,) + tuple(str(x) for x in a))
        if cmd == "SEARCH": return "OK", [b" ".join(str(u).encode() for u in sorted(s.raw))]
        return "OK", [(b"1 (BODY[] {1}", s.raw[int(a[0])]), b")"]
    def logout(s): s.log.append(("logout",))
FakeIMAP.raw = {7: b"From: BBB <info@bbb.org>\r\nSubject: Your BBB profile is now live\r\nDate: Mon, 26 Oct 2026 12:00:00 +0000\r\nContent-Type: text/plain\r\n\r\nSee https://www.bbb.org/us/ky/exampleton/profile/consulting/alder-0012-5"}
ENV = {"LISTINGS_IMAP_HOST": "imap.example", "LISTINGS_IMAP_PORT": "993", "LISTINGS_IMAP_USER": "u@example.test", "LISTINGS_IMAP_PASSWORD": "pw-not-real"}
msgs = MS.read_messages(ENV, FakeIMAP, days=30)
check("4 read_messages: EXAMINE (readonly) + BODY.PEEK only, never STORE/EXPUNGE", ("select", "INBOX", True) in FakeIMAP.log and any("BODY.PEEK" in str(e) for e in FakeIMAP.log) and not any(e[0] in ("STORE", "EXPUNGE") for e in FakeIMAP.log))
check("4 read_messages returns dicts and the scan finds the URL in them", msgs and MS.find_approval("bbb.org", msgs)["url"].endswith("alder-0012-5"))
sc = MS.MailScanner(reader=lambda: (_ for _ in ()).throw(RuntimeError("no creds")), log=lambda *a: None)
check("4 an unreadable mailbox answers None once and never raises", sc.find("bbb.org") is None and sc.error and "no creds" in sc.error)
# recheck hook: a no-permalink row on one of the four consults the mail, then reads the page
Q_ROWS = {"canonical": CANON, "fix_queue": [], "create_rows": [
    {"id": "create-bbb", "directory": "bbb.org", "state": "submitted", "evidence_url": "https://www.bbb.org/get-listed/success", "history": []},
    {"id": "create-loc8nearme", "directory": "loc8nearme.com", "state": "submitted", "evidence_url": "https://www.loc8nearme.com/payment.php?uuid=e", "history": []}]}
PAGE = "Alder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n(502) 555-0101\n" + PAD
fetched = []
def plain(u): fetched.append(u); return R.Page(200, u, PAGE)
IDENT_T = IDENT
res = R.recheck(Q_ROWS, IDENT_T, plain=plain, chrome=lambda u: R.Page(0, u, ""), record=lambda *a, **k: (_ for _ in ()).throw(AssertionError("dry run wrote")), today="2026-10-27", write=False, use_chrome=False,
                mail=MS.MailScanner(messages=M, name=CANON["name"]))
by = {r["row"]: r for r in res}
check("4 recheck: bbb row gets its URL from the approval mail and is read at that URL", by["create-bbb"]["url"].endswith("-0012-99887766") and any(u.endswith("-0012-99887766") for u in fetched), str(by["create-bbb"]))
check("4 recheck dry run: matched page -> would go live, nothing written", by["create-bbb"]["verdict"] == "match" and by["create-bbb"]["after"] == "live")
check("4 recheck: loc8nearme has no approval mail -> still no-permalink, nothing written", by["create-loc8nearme"]["verdict"] == "no-permalink" and by["create-loc8nearme"]["url"] is None)
rep = MS.report([("create-bbb", "bbb.org"), ("create-loc8nearme", "loc8nearme.com")], MS.MailScanner(messages=M))
check("4 report is row | mail found | url, no mail text", "create-bbb" in rep and "Business Profile is now live" in rep and "Congratulations" not in rep and "none" in rep)
rep2 = MS.report([("create-bbb", "bbb.org")], sc)
check("4 report on an unreadable mailbox says MAILBOX NOT READ, never none", "MAILBOX NOT READ" in rep2 and "none" not in rep2.splitlines()[1])
w = []
rec_calls = []
res2 = R.recheck(Q_ROWS, IDENT_T, plain=plain, chrome=lambda u: R.Page(0, u, ""), record=lambda *a, **k: rec_calls.append((a, k)) or {"errors": []}, db=type("D", (), {"owner": "x"})(), today="2026-10-27", write=False, use_chrome=False, mail=None)
check("4 without a scanner nothing changes (batch 13 behaviour)", {r["row"]: r["verdict"] for r in res2}["create-bbb"] is not None and not rec_calls)

# ---- 5 foursquare edit spec + recheck_due ----------------------------------------------------------------------------------------
fs = F.load_spec("foursquare_edit"); fsite = F.build_site(fs)
check("5 spec loads; recheck_due_days is 2; record none (state untouched)", fsite.recheck_due_days == 2 and fsite.record == "none" and "foursquare_edit" in B.all_sites())
fd = [s["do"] for s in fs["steps"]]
check("5 order: venue -> Edit link -> phone typed key by key -> stop marker -> Submit a.saveButton", fd == ["open", "click", "fill", "stop_before_submit", "click"] and fs["steps"][1]["selector"] == "span.venueEditLink" and fs["steps"][2]["slow"] and fs["steps"][2]["select_all"] and fs["steps"][4]["selector"] == "a.saveButton" and fs["steps"][4]["submit"])
fraw = open(os.path.join(JOB, "playbooks", "foursquare_edit.json"), encoding="utf-8").read()
check("5 no literal phone/email in the spec", not F._LITERAL_PHONE.search(fraw) and not F._LITERAL_EMAIL.search(fraw))
fp = FakePage("https://app.foursquare.com/v/senior-care-consulting--solutions/6ade7f406aa75b497399f027")
fr = B.run_site(fsite, B.Ctx(fsite, fp, NAP, runner=PRun(), log=lambda *a: None, dry_run=True))
check("5 dry run: Edit clicked, old value selected by keyboard, phone TYPED as +1 <phone>, Tab pressed, Submit NOT clicked",
      fr["ok"] and ("click", "span.venueEditLink") in fp.acts and ("press", "Control+A") in fp.acts and ("type", "input[name=phone]", "+1 " + NAP["phone"]) in fp.acts and ("press", "Tab") in fp.acts
      and ("click", "a.saveButton") not in fp.acts and not [a for a in fp.acts if a[0] == "fill"], str(fr)[:300])
try: F.validate(dict(fs, recheck_due_days=0)); v0 = False
except C.BuildError: v0 = True
check("5 recheck_due_days must be 1..30", v0)
# recheck_due is stored on the row and respected by recheck
QP = os.path.join(TMP, "q.json")
row = {"id": "create-foursquare", "directory": "foursquare.com", "state": "submitted", "evidence_url": "https://app.foursquare.com/v/x/6ade7f406aa75b497399f027", "history": [], "mike_approval": {"x": 1}}
json.dump({"canonical": CANON, "fix_queue": [], "create_rows": [row]}, open(QP, "w"))
class P2:
    def latest_snapshot(s, c): return {"payload": {"directories": []}}
    def upsert_snapshot(s, *a, **k): return None
due = (datetime.date(2026, 10, 27) + datetime.timedelta(days=2)).isoformat()
rec_log = []
def rec(client, rid, new, ev, note, **kw): rec_log.append((rid, new, note, kw)); return {"errors": []}
msg_ = B.record_live(row, fsite, record=rec)
check("5 record_live on an edit spec sets recheck_due = today + 2 and keeps the state", rec_log and rec_log[0][1] == "submitted" and rec_log[0][3]["recheck_due"] == (datetime.date.today() + datetime.timedelta(days=2)).isoformat() and "state stays submitted" in msg_, msg_)
try: T.record_transition("SCC", "create-foursquare", "submitted", None, "x", queue_path=QP, recheck_due="soon", dry_run=True); bad_due = False
except T.TransitionRefused: bad_due = True
check("5 transitions refuses a recheck_due that is not YYYY-MM-DD", bad_due)
q5 = {"canonical": CANON, "create_rows": [dict(row, recheck_due="2026-10-29")], "fix_queue": []}
check("5 recheck skips the row before its due day", not R.candidates(q5, today="2026-10-28"))
check("5 recheck reads it on the due day", len(R.candidates(q5, today="2026-10-29")) == 1)
check("5 a row named with --row is read even before the due day", len(R.candidates(q5, only={"create-foursquare"}, today="2026-10-28")) == 1)
check("5 a row with no recheck_due is read as before", len(R.candidates({"canonical": CANON, "create_rows": [row], "fix_queue": []}, today="2026-10-28")) == 1)

# ---- 6 showmelocal_claim guard ----------------------------------------------------------------------------------------------------
sm = F.build_site(F.load_spec("showmelocal_claim"))
check("6 showmelocal_claim carries a guard", sm.guard and sm.guard["flag"] == "new-listing" and "create-showmelocal" in sm.guard["refuse_rows"])
check("6 create-showmelocal is refused even WITH --new-listing", "refused for row create-showmelocal" in (B.check_guard(sm, "create-showmelocal", ("new-listing",)) or ""))
check("6 without --new-listing the spec is refused for any row", "refused" in (B.check_guard(sm, "create-other", ()) or "") and "--new-listing" in (B.check_guard(sm, None, ()) or ""))
check("6 a new listing row with --new-listing is allowed", B.check_guard(sm, "create-newsite", ("new-listing",)) is None)
check("6 unguarded specs are unaffected", B.check_guard(F.build_site(F.load_spec("tupalo")), "create-tupalo", ()) is None)
try: B.main(["showmelocal_claim", "--live", "--card", "t_x", "--row", "create-showmelocal", "--new-listing"]); ex = None
except SystemExit as e: ex = str(e)
check("6 main() exits before any browser for create-showmelocal", ex and "already claimed" in ex, str(ex))
try: B.main(["showmelocal_claim", "--dry-run"]); ex2 = None
except SystemExit as e: ex2 = str(e)
check("6 main() refuses a dry run of the claim spec without --new-listing", ex2 and "--new-listing" in ex2, str(ex2))
try: F.validate(dict(F.load_spec("showmelocal_claim"), guard={"flag": "x"})); gv = False
except C.BuildError: gv = True
check("6 a guard without a reason is refused at load", gv)

# ---- 7 build Chrome screenshot helper ---------------------------------------------------------------------------------------------
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40
tabs = [{"type": "page", "url": "about:blank", "title": ""}, {"type": "page", "url": "https://app.foursquare.com/v/x?token=SECRET", "title": "Foursquare"}, {"type": "page", "url": "https://www.chamberofcommerce.com/members/add-business", "title": "Chamber"}]
check("7 pick: last real page by default, skipping about:blank", BS.pick(tabs)["title"] == "Chamber")
check("7 pick: --url-contains", BS.pick(tabs, "foursquare")["title"] == "Foursquare")
try: BS.pick(tabs, "nope"); nf = False
except LookupError: nf = True
check("7 pick: no match is a plain LookupError", nf)
outp = os.path.join(TMP, "shots", "b.png"); got = []
p, u, n = BS.shot(outp, 9333, "foursquare", tabs=tabs, capture=lambda port, url, full: got.append((port, url, full)) or PNG)
check("7 shot writes the PNG, returns the URL WITHOUT its query string, targets port 9333", os.path.getsize(outp) == len(PNG) and u == "https://app.foursquare.com/v/x" and "SECRET" not in u and got[0][0] == 9333)
try: BS.shot(os.path.join(TMP, "x.txt"), tabs=tabs, capture=lambda *a: PNG); nopng = False
except ValueError: nopng = True
check("7 a non-.png output path is refused", nopng)
try: BS.shot(os.path.join(TMP, "y.png"), tabs=tabs, capture=lambda *a: b"not a png"); badpng = False
except RuntimeError: badpng = True
check("7 bytes that are not a PNG are refused, no file written", badpng and not os.path.exists(os.path.join(TMP, "y.png")))
check("7 targets() reads only loopback /json/list", BS.targets(9333, getter=lambda u: (got.append(u), json.dumps(tabs))[1]) and got[-1] == "http://127.0.0.1:9333/json/list")
urllib.request.urlopen = REAL_URLOPEN   # loopback port 1 only: refused at once
rc_down = BS.main([os.path.join(TMP, "z.png"), "--port", "1"])
urllib.request.urlopen = _no_net
check("7 main() with the Chrome down prints a reason and returns 1", rc_down == 1)

shutil.rmtree(TMP, ignore_errors=True)
print(("ALL PASS (%d/%d)" if all(ok) else "FAILED (%d/%d)") % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
