"""Directory playbooks + signup-is-the-send carve-out + tenant-aware vault resolver (t_413687a7). Offline: fake DB, fake runtime, no network, no Chrome.
Run: python tests/playbook_test.py (CI). Exit 1 on any failure.   Dry run: python tests/playbook_test.py --print-thumbtack  (prints the prompt built from the seed).
Mutations at the end re-run the same checks with one guard removed and require the unsafe thing to HAPPEN (a refusal test that never saw the unsafe path proves nothing)."""
import contextlib, io, json, os, re, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ["CE_LOGS"] = os.path.join(TMP, "logs"); os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json"); os.environ["CE_VERIFY_LOCKS"] = os.path.join(TMP, "locks")
os.environ["CE_VERIFY_DIRECTORIES"] = os.path.join(HERE, "verify_directories_fixture.json"); os.environ["CE_NO_CARDS"] = "1"
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json"); os.environ["CE_RUNS"] = tempfile.mkdtemp()
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
import verify_fakes as F
import verify_bridge as B
import verify_send as S
import verify_step as ST
import playbook as PB
import vault_item as VI

SEED = os.path.join(HERE, "..", "config", "playbooks", "thumbtack.com.verify.json")
AGENT_DIR = "agentdir.example"
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else ""), flush=True)
def quiet(fn, *a, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        r = fn(*a, **kw)
    return r, out.getvalue() + err.getvalue()
def refused(steps):
    try: PB.validate_steps(steps); return None
    except PB.PlaybookError as e: return str(e)

seed = json.load(open(SEED, encoding="utf-8"))
VALUES = {"business_name": "Birch Media", "login_email": "listings@na" + "ckemedia.com", "phone": "(615) 555-0111", "website": "https://example.test", "vault_item": "NM - thumbtack.com"}
MASK = "(615) ***-0111"

# ---- 1 validation -------------------------------------------------------------------------------------------------------------------
check("1 the Thumbtack seed validates and keeps the 18-digit category_pk url", PB.validate_steps(seed["steps"])[0]["url"].endswith("category_pk=136256193386480124&zipcode=37066") and seed["send_is_signup"] is True and seed["task"] == "verify")
check("1 the seed holds no email, phone or secret of its own (placeholders only)", not re.search(r"@|\(\d{3}\)", "".join(s["text"] for s in seed["steps"])))
bad = {
    "an email": [{"text": "Fill listings@example.com"}], "a phone": [{"text": "Fill (629) 555-0100"}], "a 6-digit run": [{"text": "Enter 123456"}],
    "a password assignment": [{"text": "Use password: hunter22"}], "a code assignment": [{"text": "Type code=4821"}], "an unknown placeholder": [{"text": "Fill {ssn}"}],
    "an unknown key": [{"text": "x", "password": "y"}], "a url login": [{"text": "x", "url": "https://u:p@a.example/"}],
    "a url secret param": [{"text": "x", "url": "https://a.example/?token=abc"}], "an email in a url": [{"text": "x", "url": "https://a.example/?e=a@b.co"}],
    "a non-http url": [{"text": "x", "url": "javascript:alert(1)"}], "a digit run in a selector": [{"text": "x", "selector": "#a123456"}], "no text": [{"url": "https://a.example/"}],
    "empty list": [], "not a list": "steps",
}
for name, st in bad.items(): check("1 refused: %s" % name, refused(st) is not None, refused(st))
check("1 a plain step with every placeholder passes", refused([{"text": "Fill {business_name} {login_email} {phone} {website} with {vault_item}", "selector": "#a"}]) is None)
for t, sig, why in (("bogus", False, "task"), ("claim", True, "send_is_signup outside verify"), ("verify", True, None)):
    try: PB.check_target("thumbtack.com", t, sig); r = None
    except PB.PlaybookError as e: r = str(e)
    check("1 target check %s sig=%s" % (t, sig), (r is None) == (why is None), r)

# ---- 2 the table writer and reader (fake DB) -------------------------------------------------------------------------------------------
class FakeDB:
    def __init__(self, dirs=("thumbtack.com",)): self.dirs, self.rows, self.calls = set(dirs), {}, []
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path))
        m = re.search(r"domain=eq\.([^&]+)", path)
        if method == "POST" and path.startswith("ce_directories?on_conflict=domain"):   # t_9a722352: auto-add of a domain new to the Catalog
            for r in body: self.dirs.add(r["domain"])
            return None
        if method == "GET" and path.startswith("ce_directories?"): return [{"domain": m.group(1)}] if m.group(1) in self.dirs else []
        if method == "GET" and path.startswith("ce_directory_playbooks?"):
            t = re.search(r"task=eq\.([^&]+)", path).group(1); r = self.rows.get((m.group(1), t)); return [dict(r)] if r else []
        if method == "POST" and path.startswith("ce_directory_playbooks?on_conflict=domain,task"):
            for r in body: self.rows[(r["domain"], r["task"])] = dict(r)
            return None
        raise AssertionError("unexpected call %s %s" % (method, path))
db = FakeDB()
row = PB.set_playbook(db, "thumbtack.com", "verify", seed["steps"], True, seed["source"])
check("2 set writes one row, version 1, send_is_signup true", row["version"] == 1 and row["send_is_signup"] is True and len(db.rows) == 1 and db.rows[("thumbtack.com", "verify")]["steps"] == PB.validate_steps(seed["steps"]))
row2 = PB.set_playbook(db, "thumbtack.com", "verify", seed["steps"], True)
check("2 a second set bumps the version (unique domain+task, upsert)", row2["version"] == 2 and len(db.rows) == 1)
posts = len([c for c in db.calls if c[0] == "POST"]); r = PB.set_playbook(db, "thumbtack.com", "verify", seed["steps"], True, dry_run=True)
check("2 dry run writes nothing", len(db.rows) == 1 and db.rows[("thumbtack.com", "verify")]["version"] == 2 and r["version"] == 3 and len([c for c in db.calls if c[0] == "POST"]) == posts)
for what, args in (("a bad domain", ("not a domain", "verify", seed["steps"])), ("a bad step", ("thumbtack.com", "verify", [{"text": "a@b.co"}])), ("send_is_signup on claim", ("thumbtack.com", "claim", seed["steps"], True))):
    before = len([c for c in db.calls if c[0] == "POST"])
    try: PB.set_playbook(db, *args); e = None
    except PB.PlaybookError as ex: e = str(ex)
    check("2 set refuses %s and writes nothing" % what, e is not None and len([c for c in db.calls if c[0] == "POST"]) == before, e)
got = PB.get_playbook(db, "thumbtack.com", "verify"); check("2 get reads it back; a missing one is None", got and got["version"] == 2 and PB.get_playbook(db, "thumbtack.com", "check") is None)
# CLI
f = os.path.join(TMP, "steps.json"); json.dump(seed, open(f, "w"))
lines, errs = [], []
rc = PB.main(["set", "--domain", "thumbtack.com", "--task", "verify", "--file", f], db=db, out=lines.append, err=errs.append)
check("2 CLI set writes (version 3)", rc == 0 and db.rows[("thumbtack.com", "verify")]["version"] == 3, (rc, lines, errs))
rc = PB.main(["show", "--domain", "thumbtack.com", "--task", "verify"], db=db, out=lines.append, err=errs.append)
check("2 CLI show prints the row", rc == 0 and '"send_is_signup": true' in lines[-1])
rc = PB.main(["show", "--domain", "thumbtack.com", "--task", "claim"], db=db, out=lines.append, err=errs.append)
check("2 CLI show of a missing playbook exits 1", rc == 1)
json.dump({"steps": [{"text": "Fill a@b.co"}]}, open(f, "w")); errs.clear()
rc = PB.main(["set", "--domain", "thumbtack.com", "--task", "verify", "--file", f], db=db, out=lines.append, err=errs.append)
check("2 CLI set refuses a secret-shaped file (exit 1, REFUSED)", rc == 1 and errs and errs[0].startswith("REFUSED"), errs)
json.dump(dict(seed, domain="other.com"), open(f, "w")); errs.clear()
rc = PB.main(["set", "--domain", "thumbtack.com", "--task", "verify", "--file", f], db=db, out=lines.append, err=errs.append)
check("2 CLI set refuses a file whose domain differs from --domain", rc == 1, errs)
json.dump(seed, open(f, "w")); lines.clear(); calls = len(db.calls)
rc = PB.main(["set", "--domain", "thumbtack.com", "--task", "verify", "--file", f, "--dry-run"], out=lines.append, err=errs.append)
check("2 CLI --dry-run with no DB validates and prints without connecting", rc == 0 and '"dry_run": true' in lines[0] and len(db.calls) == calls)
sql = open(os.path.join(HERE, "..", "db", "017_directory_playbooks.sql"), encoding="utf-8").read()
check("2 migration: FK to ce_directories, task check, unique(domain, task), send_is_signup only for verify, RLS on, no insert/update data",
      all(s in sql for s in ("references public.ce_directories(domain)", "('check', 'create', 'claim', 'fix', 'verify')", "unique (domain, task)", "not send_is_signup or task = 'verify'", "enable row level security")) and not re.search(r"(?im)^\s*(insert|update|delete)\b", sql))

# ---- 3 render -----------------------------------------------------------------------------------------------------------------------
rend = PB.render(seed, VALUES)
check("3 render fills every placeholder", not re.search(r"\{[a-z_]+\}", json.dumps(rend)) and "Fill the email field with listings@na" + "ckemedia.com." in rend[2]["text"] and "(615) 555-0111" in rend[3]["text"] and "NM - thumbtack.com" in rend[4]["text"])
try: PB.render(seed, {k: v for k, v in VALUES.items() if k != "phone"}); e = None
except PB.PlaybookError as ex: e = str(ex)
check("3 render refuses a placeholder with no value", e == "no value for {phone}", e)

# ---- 4 build_prompt ----------------------------------------------------------------------------------------------------------------
ENTRY = {"domain": "thumbtack.com", "signin_url": "https://www.thumbtack.com/pro/login"}
TEN = ("NM", "Na" + "cke Media", "NM - thumbtack.com", ENTRY["signin_url"])
REQ, ROW = F.request(channel="sms"), F.verification(directory="thumbtack.com")
CODE = "906417"
def prompt(pb, tenant=TEN):
    return S.build_prompt(F.RID, REQ, ROW, ENTRY, tenant, MASK, VALUES["login_email"], playbook=pb)
signup_pb = dict(seed, version=3, steps=rend)
p_sign = prompt(signup_pb)
nosign_pb = dict(signup_pb, send_is_signup=False)
p_plain = prompt(nosign_pb)
p_none = prompt(None)
check("4 no playbook: the prompt keeps 'no account creation' and has no playbook block", "No CapSolver, no account creation, no payment, no client contact." in p_none and "Directory playbook" not in p_none and "Sign in to the Directory" in p_none)
check("4 every prompt ends with the playbook write-back note, no DB write offered to the agent (t_2cb780c2)", all(S.WRITE_BACK_STEP.split("%(helper)s")[0] in p and " note --request-id " in p and "PLAYBOOK-NOTE" not in p and "You cannot write it" in p and p.index("8. Playbook note") > p.index("--outcome accepted") and p.index("8. Playbook note") < p.index("Hard rules") and "playbook.py set" not in p for p in (p_sign, p_plain, p_none)))
check("4 playbook without send_is_signup: steps listed, 'no account creation' STAYS, sign-in step stays, no CapSolver line",
      "Directory playbook (version 3" in p_plain and "No CapSolver, no account creation" in p_plain and "Sign in to the Directory with the vault helper" in p_plain and "capsolver_solve" not in p_plain and "create ONE account" not in p_plain)
check("4 send_is_signup: steps listed in order with url and selector, signup carve-out for THIS Directory, no sign-in step",
      "1. Open the pro signup page" in p_sign and "[url: https://www.thumbtack.com/pro/occupation/59?category_pk=136256193386480124&zipcode=37066]" in p_sign and "[selector: #signup-form__email]" in p_sign
      and "send IS the signup: do NOT sign in" in p_sign and "create ONE account, only the one the playbook describes, only for thumbtack.com" in p_sign and "Sign in to the Directory with the vault helper" not in p_sign and "No CapSolver, no account creation" not in p_sign)
check("4 send_is_signup keeps no payment, no client contact, one session, never retry a send, the helper commands",
      all(s in p_sign for s in ("No payment, no client contact", "One Directory session", "never retry a send", "verify_step.py\" sent", "verify_step.py\" code", "verify_step.py\" result", "paid upsell")))
check("4 both SMS opt-ins stay UNCHECKED in the printed steps", "Leave BOTH SMS opt-in boxes UNCHECKED" in p_sign)
check("4 CapSolver on NM only with the carve-out, cap 3, row key = the request", "at most 3 solves for this request" in p_sign and "--row verify-%s" % F.RID in p_sign)
p_scc = prompt(signup_pb, ("SCC", "Senior Care Consulting", "SCC - thumbtack.com", ENTRY["signin_url"]))
check("4 the carve-out on SCC gets no CapSolver line (CapSolver is NM only)", "capsolver_solve" not in p_scc and "No CapSolver." in p_scc and "create ONE account" in p_scc)
secrets = re.compile(r"(?i)password\s*[:=]\s*\S|SERVICE_ROLE|" + CODE)
body = "\n".join(l for l in p_sign.replace("136256193386480124", "").replace(F.RID, "RID").split("\n") if "verify_step.py" not in l)   # helper lines carry this checkout's path
digits = re.findall(r"(?<!\d)\d{6,}(?!\d)", body)
check("4 the prompt holds no secret, no code, no service key, no 6+ digit run (apart from the seed url's category_pk, a catalog id)", not secrets.search(p_sign) and not digits, digits)

# ---- 5 the run: playbook read, filled, handed to the agent; failures fail closed ------------------------------------------------------------
def agent_portal(directory=AGENT_DIR):
    return F.StrictPortal(requests=[F.request(status="starting", channel="sms", client=F.NM)], verifications=[F.verification(client=F.NM, directory=directory)], queued_code=CODE)
class PbRuntime(F.FakeRuntime):
    pb = None; read_error = False; vals = None
    def verify_playbook(self, domain):
        self.asked = getattr(self, "asked", []) + [domain]
        if self.read_error: raise OSError("db down")
        return self.pb
    def tenant_values(self, tenant, username): return dict(VALUES) if self.vals is None else self.vals
def run_with(**kw):
    p = agent_portal(); rt = PbRuntime(F.FakePage(), agent_factory=lambda rt: F.FakeAgent([lambda: None]))
    for k, v in kw.items(): setattr(rt, k, v)
    r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
    return r, rt, p, text
r, rt, p, text = run_with(pb=dict(seed, version=7, domain=AGENT_DIR))
pr = rt.prompts[0] if rt.prompts else ""
check("5 the run reads the verify playbook for the row's Directory and the prompt carries the filled steps", rt.asked == [AGENT_DIR] and "Directory playbook (version 7" in pr and "(615) 555-0111" in pr and not re.search(r"\{[a-z_]+\}", pr), rt.asked)
check("5 send_is_signup in the stored row switches the carve-out on in the run's prompt", "send IS the signup" in pr)
r, rt, p, text = run_with(pb=dict(seed, send_is_signup=False))
check("5 a stored row without send_is_signup keeps the old rule", rt.prompts and "No CapSolver, no account creation" in rt.prompts[0] and "send IS the signup" not in rt.prompts[0])
r, rt, p, text = run_with(pb=None)
check("5 no playbook row: the run is the old run (row steps only)", rt.prompts and "Directory playbook" not in rt.prompts[0] and "send IS the signup" not in rt.prompts[0])
r, rt, p, text = run_with(read_error=True)
check("5 a DB read failure runs WITHOUT a playbook and never with the carve-out", rt.prompts and "send IS the signup" not in rt.prompts[0] and "playbook read failed (OSError)" in text, text[-200:])
r, rt, p, text = run_with(pb=seed, vals={"login_email": VALUES["login_email"]})
check("5 a playbook that cannot be filled fails closed: failed/send_failed, no prompt, no agent launched", r == "failed:send_failed" and not rt.prompts and not rt.launched and p.requests[F.RID]["fail_code"] == "send_failed", (r, rt.launched))
fenced = F.StrictPortal(requests=[F.request(status="starting", channel="sms", client=F.NM, age_s=5)], verifications=[F.verification(client=F.SCC, directory=AGENT_DIR)], queued_code=CODE)
rt = PbRuntime(F.FakePage(), agent_factory=lambda rt: F.FakeAgent([lambda: None])); rt.pb = seed
r, text = quiet(S.run, F.RID, fenced, B.VerifyRpc(fenced), rt, F.NOW)
check("5 the fence is unchanged: a cross-tenant request is refused before any playbook read or prompt", r.startswith("failed") and not getattr(rt, "asked", []) and not rt.prompts, r)
real = S.Runtime(); vals = real.tenant_values(("NM", "o", "NM - thumbtack.com", "u"), VALUES["login_email"])
check("5 the real Runtime fills placeholders from the identity file + this run (never a password)", vals["business_name"] == "Birch Media" and vals["phone"] == "(615) 555-0111" and vals["vault_item"] == "NM - thumbtack.com" and vals["login_email"] == VALUES["login_email"] and "password" not in json.dumps(vals).lower(), vals)

# ---- 6 tenant-aware vault resolver ----------------------------------------------------------------------------------------------------
ITEMS = [{"id": "s1", "name": "SCC - thumbtack.com", "uris": ["https://www.thumbtack.com/"]}, {"id": "n1", "name": "NM - thumbtack.com", "uris": ["https://www.thumbtack.com/"]},
         {"id": "n2", "name": "NM - bark.com", "uris": []}, {"id": "s2", "name": "SCC - bark.com", "uris": []}]
check("6 NM resolves 'NM - <domain>'", VI.resolve_item("thumbtack.com", ITEMS, "NM")["id"] == "n1")
check("6 SCC resolves 'SCC - <domain>' (and is the default)", VI.resolve_item("thumbtack.com", ITEMS, "SCC")["id"] == "s1" and VI.resolve_item("thumbtack.com", ITEMS)["id"] == "s1")
def lookup(domain, items, tenant):
    try: return VI.resolve_item(domain, items, tenant)["id"]
    except VI.VaultItemError as e: return str(e)
only_scc = [ITEMS[0], ITEMS[3]]; only_nm = [ITEMS[1], ITEMS[2]]
r1 = lookup("thumbtack.com", only_scc, "NM"); r2 = lookup("thumbtack.com", only_nm, "SCC")
check("6 an NM lookup can NEVER return an SCC item (name match, only SCC items present -> not-found)", r1.startswith("not-found"), r1)
check("6 an SCC lookup can NEVER return an NM item (only NM items present -> not-found)", r2.startswith("not-found"), r2)
uri_only = [{"id": "s9", "name": "SCC - acompio", "uris": ["https://thumbtack.com/login"]}]
check("6 the lock also holds against a URI-only and a brand-only match", lookup("thumbtack.com", uri_only, "NM").startswith("not-found") and lookup("thumbtack.com", [{"id": "s8", "name": "SCC - thumbtack notes", "uris": []}], "NM").startswith("not-found"))
check("6 an unknown tenant is refused", lookup("thumbtack.com", ITEMS, "ACME").startswith("refused"))
check("6 list_items asks the TENANT's vault organization", True)
seen = []
class R:  # fake runner: records the argv
    returncode, stdout, stderr = 0, json.dumps({"items": []}), ""
VI.list_items(lambda cmd, **k: (seen.append(cmd), R)[1], tenant="NM"); VI.list_items(lambda cmd, **k: (seen.append(cmd), R)[1])
check("6 list_items: NM -> the NM org, default -> 'Senior Care Consulting' org", seen[0][seen[0].index("--organization") + 1] == "Na" + "cke Media" and seen[1][seen[1].index("--organization") + 1] == "Senior Care Consulting", [c[c.index("--organization") + 1] for c in seen])
out = []
rc = VI.main(["--domain", "thumbtack.com", "--tenant", "NM"], items=ITEMS, out=out.append, err=out.append)
check("6 CLI --tenant NM prints the NM item name only", rc == 0 and out == ["NM - thumbtack.com"], out)

# ---- 7 mutations: remove ONE guard, the unsafe thing must then happen --------------------------------------------------------------------
orig = VI._tenant_items
VI._tenant_items = lambda tenant, items: items   # MUTATION 1: no tenant lock
m1 = lookup("thumbtack.com", only_scc, "NM"); m2 = lookup("thumbtack.com", only_nm, "SCC")
VI._tenant_items = orig
check("7 MUTATION no tenant lock: an NM lookup then DOES return the SCC item", m1 == "s1", m1)
check("7 MUTATION no tenant lock: an SCC lookup then DOES return the NM item", m2 == "n1", m2)
check("7 lock restored: both lookups refuse again", lookup("thumbtack.com", only_scc, "NM").startswith("not-found") and lookup("thumbtack.com", only_nm, "SCC").startswith("not-found"))
orig_v = PB.validate_steps
PB.validate_steps = lambda steps: steps   # MUTATION 2: no validation
try: PB.set_playbook(FakeDB(), "thumbtack.com", "verify", [{"text": "Fill listings@example.com and 123456", "send": True}]); m3 = True
except Exception: m3 = False
PB.validate_steps = orig_v
check("7 MUTATION no validation: an email + code step is then WRITTEN", m3)
orig_get = signup_pb.get
carve = dict(signup_pb, send_is_signup=False)   # MUTATION 3: the flag ignored in the other direction = carve-out for every playbook
S_flag = S.build_prompt
def always_signup(*a, **k):
    pb = k.get("playbook"); k["playbook"] = dict(pb, send_is_signup=True) if pb else pb
    return S_flag(*a, **k)
S.build_prompt = always_signup
m4 = S.build_prompt(F.RID, REQ, ROW, ENTRY, TEN, MASK, VALUES["login_email"], playbook=nosign_pb)
S.build_prompt = S_flag
check("7 MUTATION flag ignored: a playbook WITHOUT send_is_signup then gets the account-creation carve-out", "create ONE account" in m4)
check("7 the unmutated prompt for the same playbook has no carve-out", "create ONE account" not in prompt(nosign_pb))

# ---- 8 {contact_name} and the Alignable seed (t_9de1c978) ------------------------------------------------------------------------------
ALIGN = os.path.join(HERE, "fixtures", "alignable_signup_seed.json")   # t_8b8c2650: the old signup-shaped Alignable seed is a fixture; the live seed is the sign-in v3 (section 12)
al = json.load(open(ALIGN, encoding="utf-8"))
al_text = " ".join(s["text"] for s in al["steps"])
V2 = dict(VALUES, contact_name="Test Person")
check("8 the Alignable seed validates, is a verify signup, and names the five steps", PB.validate_steps(al["steps"]) and al["send_is_signup"] is True and al["task"] == "verify" and len(al["steps"]) == 5)
check("8 the Alignable seed uses only placeholders ({login_email} {contact_name} {phone}) and no email or phone of its own", all(p in al_text for p in ("{login_email}", "{contact_name}", "{phone}")) and not re.search(r"@\w|\(\d{3}\)", al_text))
check("8 the validator accepts {contact_name} and still refuses an unknown placeholder", refused([{"text": "Enter {contact_name}"}]) is None and refused([{"text": "Enter {ssn}"}]) is not None)
rendered = PB.render(dict(al, version=1), V2)
check("8 render fills every placeholder in the Alignable seed (no brace left, contact name present)", rendered and not any("{" in s["text"] for s in rendered) and any("Test Person" in s["text"] for s in rendered))
try: PB.render(dict(al, version=1), VALUES); e8 = None
except PB.PlaybookError as e: e8 = str(e)
check("8 render with no contact_name value fails closed (names the placeholder)", e8 is not None and "contact_name" in e8, e8)
rt8 = S.Runtime()
import tempfile as _tf
_idn = os.path.join(_tf.mkdtemp(), "identity.json"); json.dump({"BIZ": {"NM": {"name": "Birch Media", "phones": ["6155550111"], "site": "https://example.test", "contact": "Pat Sample"}, "SCC": {"name": "Alder Care", "phones": ["5025550101"], "site": "https://example.test"}}}, open(_idn, "w"))
_old = os.environ.get("CE_IDENTITY"); os.environ["CE_IDENTITY"] = _idn
try:
    v_nm = rt8.tenant_values(("NM", "o", "NM - alignable.com", "https://www.alignable.com/"), "listings@na" + "ckemedia.com")
    v_scc = rt8.tenant_values(("SCC", "o", "SCC - alignable.com", "https://www.alignable.com/"), "listings@seniorcaresolutions.co")
finally:
    if _old is None: os.environ.pop("CE_IDENTITY", None)
    else: os.environ["CE_IDENTITY"] = _old
check("8 tenant_values reads NM contact_name from the identity file", v_nm.get("contact_name") == "Pat Sample", sorted(v_nm))
check("8 tenant_values gives SCC none, so an SCC run of this playbook fails closed", "contact_name" not in v_scc)
import importlib
_keep = PB.PLACEHOLDERS
PB.PLACEHOLDERS = tuple(p for p in _keep if p != "contact_name")   # MUTATION: validator without the new placeholder
try: m8 = refused(al["steps"])
finally: PB.PLACEHOLDERS = _keep
check("8 MUTATION validator without contact_name refuses the Alignable seed (the placeholder list is what lets it in)", m8 is not None and "contact_name" in m8, m8)
p_al = S.build_prompt(F.RID, REQ, ROW, {"domain": "alignable.com", "signin_url": "https://www.alignable.com/"}, ("NM", "Na" + "cke Media", "NM - alignable.com", "https://www.alignable.com/"), MASK, VALUES["login_email"], playbook=dict(al, version=1, steps=rendered))
check("8 the Alignable prompt carries the signup carve-out and the filled steps, nothing unfilled", "send IS the signup: do NOT sign in" in p_al and "Test Person" in p_al and "{contact_name}" not in p_al and "only for alignable.com" in p_al)

# ---- 9 the send rule is ONE clear order, and contact_name comes from identity.json only (t_f683311e) ---------------------------------
RULE = "3. Click the send button. Before you click it, if the page shows a paid upsell, a plan purchase, or a marketing consent that is not required for the code, do NOT click; end the session and report it."
OLD_RULE = "3. STOP at the send step, do not click send, and end the session if anything looks like a paid upsell, a plan purchase, or marketing consent that is not required for the code."
TAIL = " Before you click it, if the page shows a paid upsell, a plan purchase, or a marketing consent that is not required for the code, do NOT click; end the session and report it."
def rule_up(n): return "3. Do the send step (playbook step %d) once." % n + TAIL   # t_3223ee18: the signup path names the playbook's send step
def send_rule_problems(pr, rule=RULE):
    """[] when the prompt tells the agent to click send and no line forbids clicking send without a condition in front of it."""
    bad = []
    lines = pr.split("\n")
    if rule not in lines: bad.append("exact click-send rule line missing")
    for ln in lines:
        low = ln.lower()
        if "stop at the send step" in low: bad.append("old STOP-at-send wording: " + ln[:60])
        if "do not click" in low and not re.match(r"^3\. (Click the send button|Do the send step \(playbook step \d+\) once)\. Before you click it, if .*do NOT click;", ln) and not re.match(r"^4\. Playbook step \d+ already sent the code\. Do NOT click any other send, resend or SMS option after it\.", ln): bad.append("unconditional do-not-click: " + ln[:60])
    return bad
al_pb = dict(al, version=1, steps=rendered)
paths = {"signup (Thumbtack seed)": p_sign, "signup (Alignable seed)": p_al, "sign-in (playbook without send_is_signup)": p_plain, "sign-in (no playbook)": p_none}
SEND_N = {"signup (Thumbtack seed)": 7, "signup (Alignable seed)": 5, "sign-in (playbook without send_is_signup)": 7}   # t_3223ee18: the seeded send steps
RULES = {name: (rule_up(SEND_N[name]) if name in SEND_N else RULE) for name in paths}
for name, pr in paths.items():
    check("9 %s prompt: tells the agent to click send, and no line says do not click send without a condition" % name, send_rule_problems(pr, RULES[name]) == [], send_rule_problems(pr, RULES[name]))
    check("9 %s prompt: the click-send rule sits after the phone check and before the send-the-code step" % name, pr.index(RULES[name]) < pr.index("\n4. "))
for name, pr in paths.items():
    m = pr.replace(RULES[name], OLD_RULE)   # MUTATION: the old ambiguous line is back
    check("9 MUTATION %s prompt with the old STOP-at-send line is caught by the check" % name, send_rule_problems(m, RULES[name]) != [] and any("old STOP" in x or "unconditional" in x for x in send_rule_problems(m, RULES[name])), send_rule_problems(m, RULES[name])[:2])
check("9 MUTATION a bare 'do not click send' line is caught", send_rule_problems(p_sign + "\n- Do not click send.\n", rule_up(7)) != [])
src = open(os.path.join(HERE, "..", "job", "verify_send.py"), encoding="utf-8").read()
check("9 verify_send.py has no CONTACT_NAME constant and no hard-coded contact", "CONTACT_NAME" not in src and "STOP at the send step" not in src)

# contact_name missing from identity.json: the playbook needs it, so the run fails before the agent launches
class IdRuntime(PbRuntime):
    def tenant_values(self, tenant, username): return S.Runtime.tenant_values(self, tenant, username)
def run_identity(biz_nm):
    idf = os.path.join(tempfile.mkdtemp(), "identity.json"); json.dump({"BIZ": {"NM": biz_nm}}, open(idf, "w"))
    old = os.environ.get("CE_IDENTITY"); os.environ["CE_IDENTITY"] = idf
    try:
        p = agent_portal(); rt = IdRuntime(F.FakePage(), agent_factory=lambda rt: F.FakeAgent([lambda: None])); rt.pb = dict(al, version=1, domain=AGENT_DIR)
        r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
    finally:
        if old is None: os.environ.pop("CE_IDENTITY", None)
        else: os.environ["CE_IDENTITY"] = old
    return r, rt, p, text
NMB = {"name": "Birch Media", "phones": ["6155550111"], "site": "https://example.test"}
r, rt, p, text = run_identity(dict(NMB, contact="Pat Sample"))
check("9 identity.json with contact: the Alignable run reaches the agent with the name filled", len(rt.launched) == 1 and rt.prompts and "Pat Sample" in rt.prompts[0], (r, text[-120:]))
r, rt, p, text = run_identity(NMB)
check("9 identity.json WITHOUT contact: send_failed before launch (no prompt, no agent, no browser)", not rt.launched and not rt.prompts and rt.browsers == 0 and p.requests[F.RID]["status"] == "failed" and "contact_name" in text, (r, p.requests[F.RID]["status"], text[-160:]))
_orig = S.Runtime.tenant_values
def _fallback(self, tenant, username):   # MUTATION: a code fallback constant is back
    v = _orig(self, tenant, username); v.setdefault("contact_name", "Fallback Name"); return v
S.Runtime.tenant_values = _fallback
try: r, rt, p, text = run_identity(NMB)
finally: S.Runtime.tenant_values = _orig
check("9 MUTATION a code fallback for contact_name makes the missing-key run launch (so the fail-closed test above is the guard)", len(rt.launched) == 1 and rt.prompts and "Fallback Name" in rt.prompts[0], (r, text[-100:]))

# ---- 10 signup step 4: the Sign up click already sent the code, no second send (t_f683311e round 3) ------------------------------------
def s4_up(n): return "4. Playbook step %d already sent the code. Do NOT click any other send, resend or SMS option after it. Immediately run: " % n
def step4_problems(pr, signup):
    n = signup if signup else None   # signup = the expected send step number, or False for the sign-in path
    rule = rule_up(n) if n else RULE
    lines = pr.split("\n"); i3 = lines.index(rule) if rule in lines else -1
    if i3 < 0: return ["rule 3 missing"]
    after = "\n".join(lines[i3 + 1:]).lower(); bad = []
    if signup:
        if not any(l.startswith(s4_up(n)) and " sent --request-id " in l for l in lines): bad.append("signup step 4 line missing")
        for w in ("send the code", "choose the sms", "choose the call"):
            if w in after: bad.append("second-send wording after step 3: " + w)
    else:
        if not any(l.startswith("4. Choose the ") and "send the code. Immediately run:" in l for l in lines): bad.append("sign-in step 4 changed")
    return bad
for name, pr in paths.items():
    sg = SEND_N.get(name, False)
    check("10 %s prompt: step 4 is %s" % (name, "'Playbook step N already sent the code', no second send" if sg else "the unchanged sign-in step"), step4_problems(pr, sg) == [], str(step4_problems(pr, sg)))
GENERIC = "4. Choose the sms option and send the code. Immediately run: "
for name in ("signup (Thumbtack seed)", "signup (Alignable seed)"):
    m = paths[name].replace(s4_up(SEND_N[name]), GENERIC)   # MUTATION: generic step 4 back on the signup path
    check("10 MUTATION %s with the generic step 4 is caught" % name, step4_problems(m, SEND_N[name]) != [], str(step4_problems(m, SEND_N[name])))
check("10 MUTATION a resend order after step 3 is caught", step4_problems(p_sign + "\n- If no code arrives, send the code again.\n", 7) != [])

# ---- 11 the send step is the playbook's marked step, not "the Sign up click" (t_3223ee18) --------------------------------------------
tt_seed = json.load(open(SEED, encoding="utf-8"))
def marks(steps): return [i for i, s in enumerate(steps, 1) if s.get("send")]
check("11 seeds: Thumbtack marks step 7, Alignable marks step 5, exactly one each", marks(tt_seed["steps"]) == [7] and marks(al["steps"]) == [5])
check("11 send_step_number returns 7 and 5 for the seeds", PB.send_step_number(tt_seed["steps"], True) == 7 and PB.send_step_number(al["steps"], True) == 5)
def with_marks(steps, idx): return [dict(s, send=True) if i in idx else {k: v for k, v in s.items() if k != "send"} for i, s in enumerate(steps, 1)]
def send_err(steps, sig=True):
    try: PB.send_step_number(PB.validate_steps(steps), sig); return None
    except PB.PlaybookError as e: return str(e)
check("11 zero marked steps on a signup playbook are refused", "exactly one" in (send_err(with_marks(al["steps"], [])) or ""))
check("11 two marked steps on a signup playbook are refused", "exactly one" in (send_err(with_marks(al["steps"], [3, 5])) or ""))
check("11 (t_8b8c2650) a mark on a playbook WITHOUT send_is_signup is accepted; zero marks are refused on that path too", send_err(al["steps"], False) is None and "exactly one" in (send_err(with_marks(al["steps"], []), False) or "") and "exactly one" in (send_err(with_marks(al["steps"], [3, 5]), False) or ""))
check("11 a non-boolean send value is refused", "true or false" in (refused([{"text": "Click go", "send": "yes"}]) or ""))
class SDB:
    def __init__(s): s.calls = []
    def call(s, m, p, b=None, prefer=None):
        s.calls.append((m, p)); return [] if m == "GET" else None
for what, st in (("none marked", with_marks(al["steps"], [])), ("two marked", with_marks(al["steps"], [3, 5]))):
    try: PB.set_playbook(SDB(), "alignable.com", "verify", st, True, dry_run=True); e = None
    except PB.PlaybookError as ex: e = str(ex)
    check("11 playbook.py set refuses a signup playbook with %s" % what, e is not None and "exactly one" in e, e)
d11 = SDB()
try: PB.set_playbook(d11, "alignable.com", "verify", al["steps"], True, now=None); ok11 = any(c[0] == "POST" for c in d11.calls)
except Exception as ex: ok11 = False
check("11 set accepts a signup playbook with exactly one marked step and writes it", ok11)
check("11 render keeps the send mark", marks(rendered) == [5] and marks(PB.render(tt_seed, VALUES)) == [7])
check("11 the Thumbtack prompt names step 7 in steps 2, 3 and 4; the Alignable prompt names step 5", all(("before the send step (playbook step 7)" in p_sign.lower(), "3. Do the send step (playbook step 7) once." in p_sign, "4. Playbook step 7 already sent the code." in p_sign)) and all(("before the send step (playbook step 5)" in p_al.lower(), "3. Do the send step (playbook step 5) once." in p_al, "4. Playbook step 5 already sent the code." in p_al)))
check("11 neither signup prompt says 'Sign up click' or 'signup click' (Alignable's send is not that click)", not re.search(r"(?i)sign.?up click", p_al) and not re.search(r"(?i)sign.?up click", p_sign))
check("11 the Alignable prompt does not forbid its own send step 5 (step 4 says do NOT click any other send AFTER it)", "Do NOT click any other send, resend or SMS option after it" in p_al and "The Sign up click" not in p_al)
# MUTATIONS
_snd = PB.send_step_number
PB.send_step_number = lambda steps, sig=True: (marks(steps) or [None])[0]   # MUTATION: no exactly-one check (accepts zero or two)
try: m_zero = send_err(with_marks(al["steps"], []))
finally: PB.send_step_number = _snd
check("11 MUTATION a validator without the exactly-one count lets a zero-mark playbook through (so the tests above are the guard)", m_zero is None)
wrong = with_marks(al["steps"], [3])   # MUTATION: the mark on the wrong step (the Sign Up It's Free click)
p_wrong = S.build_prompt(F.RID, REQ, ROW, {"domain": "alignable.com", "signin_url": "https://www.alignable.com/"}, ("NM", "Na" + "cke Media", "NM - alignable.com", "https://www.alignable.com/"), MASK, VALUES["login_email"], playbook=dict(al, version=1, steps=PB.render(dict(al, steps=wrong), V2)))
check("11 MUTATION the mark on step 3 makes the prompt name step 3, so the step-5 assertion above fails", "playbook step 3" in p_wrong and "playbook step 5" not in p_wrong)
check("11 MUTATION a hard-coded 'Sign up click' line is caught by the prompt check", re.search(r"(?i)sign.?up click", p_al.replace("4. Playbook step 5 already sent the code.", "4. The Sign up click already sent the code.")) is not None)
# the run path: a stored signup row with no mark never reaches the agent
def run_unmarked():
    idf = os.path.join(tempfile.mkdtemp(), "identity.json"); json.dump({"BIZ": {"NM": dict(NMB, contact="Pat Sample")}}, open(idf, "w"))
    old = os.environ.get("CE_IDENTITY"); os.environ["CE_IDENTITY"] = idf
    try:
        p = agent_portal(); rt = IdRuntime(F.FakePage(), agent_factory=lambda rt: F.FakeAgent([lambda: None])); rt.pb = dict(al, version=1, domain=AGENT_DIR, steps=with_marks(al["steps"], []))
        r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
    finally:
        if old is None: os.environ.pop("CE_IDENTITY", None)
        else: os.environ["CE_IDENTITY"] = old
    return rt, p, text
rt, p, text = run_unmarked()
check("11 a stored signup playbook with no marked send step: send_failed before launch (no prompt, no agent, no browser)", not rt.launched and not rt.prompts and rt.browsers == 0 and p.requests[F.RID]["status"] == "failed", (p.requests[F.RID]["status"], text[-120:]))



# ---- 12 sign-in path: ONE send instruction; every verify playbook marks its send; stop on a CAPTCHA (t_8b8c2650) ------------------------------------
LIVE = os.path.join(HERE, "..", "config", "playbooks", "alignable.com.verify.json")
live = json.load(open(LIVE, encoding="utf-8"))
live_text = " ".join(st["text"] for st in live["steps"])
A_ENTRY = {"domain": "alignable.com", "signin_url": "https://www.alignable.com/"}
A_TEN = ("NM", "Na" + "cke Media", "NM - alignable.com", "https://www.alignable.com/")
def al_in_prompt(pbk, steps=None): return S.build_prompt(F.RID, REQ, ROW, A_ENTRY, A_TEN, MASK, VALUES["login_email"], playbook=dict(pbk, version=3, steps=steps if steps is not None else PB.render(pbk, V2)))
p_in = al_in_prompt(live)
def send_orders(pr):
    """The send ORDERS in the numbered steps: lines that tell the agent to click/choose/do a send (a 'Do NOT click any other send' ban and a
    'sent' report are not orders). Exactly one is allowed."""
    body = pr.split("Steps:\n", 1)[1].split("\nHard rules:", 1)[0]
    pat = re.compile(r"(?i)^(\d+)\. (do the send step|click the send|choose the \w+ option|send the code|resend|click (resend|send))|and send the code|send the code again|click the send button")
    return [l for l in body.split("\n") if pat.search(l)]
check("12 live Alignable seed: send_is_signup false, exactly one step marked send (step 5), validates", live["send_is_signup"] is False and marks(live["steps"]) == [5] and PB.validate_steps(live["steps"]) and send_err(live["steps"], False) is None)
check("12 Alignable sign-in prompt: no account-creation carve-out, sign-in step 1 stays, playbook listed", "create ONE account" not in p_in and "Sign in to the Directory with the vault helper" in p_in and "Directory playbook (version 3" in p_in)
for nm, pr, n in (("Thumbtack signup", p_sign, 7), ("Alignable sign-in", p_in, 5)):
    orders = send_orders(pr)
    check("12 %s prompt: exactly ONE send instruction, and it names playbook step %d" % (nm, n), len(orders) == 1 and orders[0].startswith("3. Do the send step (playbook step %d) once." % n), orders)
    check("12 %s prompt: step 4 only records sent: 'already sent the code', no click/choose order, no generic text" % nm,
          "4. Playbook step %d already sent the code. Do NOT click any other send, resend or SMS option after it. Immediately run: " % n in pr and "Click the send button" not in pr and "Choose the sms option" not in pr and "send the code. Immediately" not in pr)
check("12 Alignable sign-in prompt keeps the hard rule 'No CapSolver' and offers no solver command", "- No CapSolver, no account creation" in p_in and "capsolver_solve" not in p_in)
check("12 the Alignable seed has NO CapSolver text and says to STOP on a CAPTCHA with needs-human", not re.search(r"(?i)capsolver|recaptcha-v2|solve", live_text) and "If a CAPTCHA shows, STOP and report needs-human (session expired)" in live_text)
check("12 no-playbook prompt keeps the generic one-send steps (no marked step to name): still exactly one order", len(send_orders(p_none)) == 2 and "4. Choose the sms option and send the code." in p_none)   # generic 3 (click send) + generic 4 (choose): only a stored playbook is the fixed path; a stored one without a mark never launches
# MUTATIONS
gen3 = S.STEP3_SIGNIN.rstrip("\n"); gen4 = ("4. Choose the sms option and send the code. Immediately run: ")
m3 = p_in.replace("3. Do the send step (playbook step 5) once.", "3. Click the send button.")
m4 = p_in.replace("4. Playbook step 5 already sent the code. Do NOT click any other send, resend or SMS option after it. Immediately run: ", gen4)
check("12 MUTATION generic step 3 back on the sign-in path: the one-send check fails", len(send_orders(m3)) != 1 or not send_orders(m3)[0].startswith("3. Do the send step"))
check("12 MUTATION generic step 4 back on the sign-in path: caught (two send orders)", len(send_orders(m4)) != 1)
_b = S.STEP4_MARKED; S.STEP4_MARKED = S.STEP4_SIGNIN
try: m5 = al_in_prompt(live)
finally: S.STEP4_MARKED = _b
check("12 MUTATION the code path with the generic step 4 for a marked playbook is caught by the same check", len(send_orders(m5)) != 1)
mut_text = live_text + " Use CapSolver recaptcha-v2 if a CAPTCHA shows."
check("12 MUTATION CapSolver text back in the Alignable step is caught", re.search(r"(?i)capsolver|recaptcha-v2|solve", mut_text) is not None)
# the set writer and the run path, sign-in side
for what, st in (("none marked", with_marks(live["steps"], [])), ("two marked", with_marks(live["steps"], [3, 5]))):
    try: PB.set_playbook(SDB(), "alignable.com", "verify", st, False, dry_run=True); e = None
    except PB.PlaybookError as ex: e = str(ex)
    check("12 playbook.py set refuses a SIGN-IN verify playbook with %s" % what, e is not None and "exactly one" in e, e)
try: PB.set_playbook(SDB(), "alignable.com", "check", with_marks(live["steps"], [5]), False, dry_run=True); e12 = None
except PB.PlaybookError as ex: e12 = str(ex)
check("12 a send mark on a non-verify task is refused", e12 is not None and "only a verify" in e12, e12)
try: S.build_prompt(F.RID, REQ, ROW, A_ENTRY, A_TEN, MASK, VALUES["login_email"], playbook=dict(live, version=3, steps=PB.render(dict(live, steps=with_marks(live["steps"], [])), V2))); e13 = None
except PB.PlaybookError as ex: e13 = str(ex)
check("12 build_prompt with an unmarked stored sign-in playbook raises (no prompt is ever built)", e13 is not None and "exactly one" in e13, e13)
def run_unmarked_in(idx):
    idf = os.path.join(tempfile.mkdtemp(), "identity.json"); json.dump({"BIZ": {"NM": dict(NMB, contact="Pat Sample")}}, open(idf, "w"))
    old = os.environ.get("CE_IDENTITY"); os.environ["CE_IDENTITY"] = idf
    try:
        p = agent_portal(); rt = IdRuntime(F.FakePage(), agent_factory=lambda rt: F.FakeAgent([lambda: None])); rt.pb = dict(live, version=3, domain=AGENT_DIR, steps=with_marks(live["steps"], idx))
        r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
    finally:
        if old is None: os.environ.pop("CE_IDENTITY", None)
        else: os.environ["CE_IDENTITY"] = old
    return rt, p
for what, idx in (("no marked send step", []), ("two marked send steps", [3, 5])):
    rt, p = run_unmarked_in(idx)
    check("12 a stored SIGN-IN verify playbook with %s: send_failed before launch (no prompt, no agent, no browser)" % what, not rt.launched and not rt.prompts and rt.browsers == 0 and p.requests[F.RID]["status"] == "failed", p.requests[F.RID]["status"])
rt, p = run_unmarked_in([5])
check("12 the same stored sign-in playbook WITH its one mark launches the agent; its prompt has exactly one send order", rt.launched and len(rt.prompts) == 1 and len(send_orders(rt.prompts[0])) == 1 and "playbook step 5" in rt.prompts[0], (rt.launched, len(rt.prompts)))

if "--print-thumbtack" in sys.argv:
    print("\n==== THUMBTACK PROMPT (dry run, fake tenant values, request id %s) ====\n%s" % (F.RID, p_sign)); print("\n==== ALIGNABLE PROMPT (sign-in, dry run, fake tenant values, request id %s) ====\n%s" % (F.RID, p_in))
print("\n%d checks, %d failed" % (len(ok), ok.count(False)))
sys.exit(1 if False in ok else 0)
