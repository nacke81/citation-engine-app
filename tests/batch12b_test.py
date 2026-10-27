"""Batch 12 resume fixes (t_f707b644): recheck nap-incomplete, created-unlisted recording, acompio/tupalo/showmelocal formspecs, playbook_write.
No network, no browser, no CapSolver, no vault, no queue write: fake page, fake runner, temp files."""
import os, sys, json, tempfile, copy, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
import build_runner as B, build_core as C, formspec as F, recheck as R, transitions as T, buildqueue as Q, claim as CL, playbook_write as PW

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
NAP = B.nap_from_identity(IDENT)
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example, Exampleton KY 40000", "phone": "(502) 555-0101"}
PAD = " Lorem ipsum dolor sit amet." * 12

# ---- N1 recheck: nap-incomplete vs mismatch, one fixture HTML per Directory ----------------------------------------------------
TUPALO = """<html><body><nav>Tupalo</nav><main><h1>Alder Care Consulting &amp; Solutions</h1>
<div class="address">100 Example</div><div>Exampleton, KY 40000</div><div>Category: Local Service</div><p>No phone number has been added for this place.</p>%s</main></body></html>""" % PAD
ACOMPIO = """<html><body><main><h1>Alder Care Consulting &amp; Solutions</h1>
<div>Address not listed</div><div>Phone: +1 502-555-0101</div><div>Website: https://alder.example</div>%s</main></body></html>""" % PAD
SHOWMELOCAL = """<html><body><div class="banner">This listing is HIDDEN until ACTIVATED</div><main><h1>Alder Care Consulting &amp; Solutions</h1>
<div>100 Example</div><div>Exampleton, KY 40000</div><div>(502) 555-0101</div>%s</main></body></html>""" % PAD
WRONG_PHONE = TUPALO.replace("<p>No phone number has been added for this place.</p>", "<div>(502) 555-0199</div>")
FULL = TUPALO.replace("<p>No phone number has been added for this place.</p>", "<div>(502) 555-0101</div>")
def cmp_html(h): return R.compare(CL.html_to_text(h), CANON, h)
for label, h in (("tupalo (no phone)", TUPALO), ("acompio (Address not listed)", ACOMPIO), ("showmelocal (paused, NAP matches)", SHOWMELOCAL)):
    c = cmp_html(h)
    want = "not-public" if "showmelocal" in label else "nap-incomplete"   # t_bbc32230: a hidden / paused banner is not-public; a missing field is nap-incomplete
    check("N1 %s -> %s, never mismatch or match" % (label, want), c["verdict"] == want and not c["wrong"], str(c))
check("N1 tupalo names phone as the missing field", cmp_html(TUPALO)["gaps"] == ["phone"], str(cmp_html(TUPALO)))
check("N1 acompio names address as the missing field", "address" in cmp_html(ACOMPIO)["gaps"], str(cmp_html(ACOMPIO)))
check("N1 showmelocal names the paused listing, not a NAP field", cmp_html(SHOWMELOCAL)["gaps"] == ["listing visibility"], str(cmp_html(SHOWMELOCAL)))
check("N1 a WRONG phone is still a mismatch", cmp_html(WRONG_PHONE)["verdict"] == "mismatch" and cmp_html(WRONG_PHONE)["wrong"][0][0] == "phone")
check("N1 a complete public page is still a match", cmp_html(FULL)["verdict"] == "match")
check("N1 note wording for a paused page", "paused or not public yet" in R.note_for(cmp_html(SHOWMELOCAL)))

# ---- N2 recheck over created-unlisted rows ---------------------------------------------------------------------------------------
class FakeDB:
    owner = "owner-1"
    def __init__(self): self.calls = []
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))
class FakePortal(FakeDB):
    def __init__(self): super().__init__(); self.snap = {"found": 1, "directories": []}
    def latest_snapshot(self, cid): return {"payload": copy.deepcopy(self.snap)}
    def upsert_snapshot(self, cid, day, payload): self.calls.append(("snap", day))
TMP = tempfile.mkdtemp()
def run(state, html, url="https://a.example/listing/1"):
    p = os.path.join(TMP, "q.json")
    json.dump({"canonical": CANON, "fix_queue": [{"id": "create-x", "directory": "a.example", "state": state, "mike_approval": None, "evidence_url": url, "history": []}]}, open(p, "w"))
    db, fp = FakeDB(), FakePortal()
    rec = lambda *a, **k: T.record_transition(*a, portal=fp, activities=fp, verification=fp, directories=db, **k)
    plain = lambda u: R.Page(200, u, CL.html_to_text(html), html=html)
    res = R.recheck(json.load(open(p)), IDENT, plain=plain, chrome=plain, record=rec, db=db, queue_path=p, today="2026-11-02", write=True)
    return res, json.load(open(p))["fix_queue"][0]
for label, h in (("tupalo", TUPALO), ("acompio", ACOMPIO), ("showmelocal", SHOWMELOCAL)):
    res, r = run("created-unlisted", h)
    check("N2 created-unlisted + %s page: recheck reads it, verdict %s, state stays created-unlisted, a note is written" % (label, "not-public" if label == "showmelocal" else "nap-incomplete"),
          res and res[0]["verdict"] == ("not-public" if label == "showmelocal" else "nap-incomplete") and r["state"] == "created-unlisted" and r["history"] and r["history"][-1]["note"].startswith("weekly recheck:"), str(res))
res, r = run("created-unlisted", FULL)
check("N2 created-unlisted + complete public page -> live (Proof first)", res[0]["verdict"] == "match" and r["state"] == "live" and r["evidence_url"])
res, r = run("created-unlisted", WRONG_PHONE)
check("N2 created-unlisted + wrong phone -> mismatch note, state unchanged", res[0]["verdict"] == "mismatch" and r["state"] == "created-unlisted")

# ---- N3 --live records created-unlisted for a spec that says so ------------------------------------------------------------------
calls = []
rec = lambda *a: calls.append(a) or "recorded-ok"
def row(**kw):
    r = {"id": "create-acompio", "directory": "acompio.com", "state": "needs-human", "cost": "free", "vaultwarden_item": "SCC - acompio.com",
         "mike_approval": {"approved_by": "mike", "at": "2026-10-26T10:00:00", "row_id": "create-acompio"}}
    r.update(kw); return r
ac = B.load_site("acompio")
msg = B.record_live(row(), ac, record=rec)
check("N3 acompio (record created-unlisted) records created-unlisted, never submitted", calls and calls[0][2] == "created-unlisted" and "created-unlisted" in msg, msg)
calls.clear(); msg = B.record_live(row(), B.load_site("showmelocal_claim"), record=rec)
check("N3 showmelocal_claim (record none) records nothing", not calls and "record none" in msg)
calls.clear(); sb = B.load_site("storeboard"); sb.record = "submitted"; B.record_live(row(), sb, record=rec)
check("N3 a submitted spec still records submitted", calls and calls[0][2] == "submitted")
try: Q.submit_row(row(), lambda i: {"u": 1}, record=rec, live=True, to="live"); bad = False
except Q.SubmitRefused: bad = True
check("N3 submit_row refuses to record any other state (live)", bad)
def validates(spec):
    try: F.validate(spec); return ""
    except C.BuildError as e: return str(e)
base = {"site": "z", "domain": "z.example", "steps": [{"do": "stop_before_submit"}, {"do": "wait", "ms": 1}]}
check("N3 record created-unlisted needs a final submit step like submitted does", "needs a final submit step" in validates(dict(base, record="created-unlisted")))
check("N3 an unknown record value is refused", "record must be" in validates(dict(base, record="live")))

# ---- N4 formspec dry runs on a fake page ---------------------------------------------------------------------------------------
class Loc:
    def __init__(self, page, sel): self.page, self.sel = page, sel
    @property
    def first(self): return self
    def count(self): return 1
    def fill(self, v, **k): self.page.acts.append(("fill", self.sel, v))
    def click(self, **k): self.page.acts.append(("click", self.sel))
class Kb:
    def __init__(self, p): self.p = p
    def press(self, k): self.p.acts.append(("press", k))
class FakePage:
    def __init__(self, url):
        self.url, self.acts, self.keyboard = url, [], Kb(self)
    def goto(self, u, **k): self.acts.append(("goto", u)); self.url = u
    def locator(self, s): return Loc(self, s)
    def get_by_text(self, t, **k): self.acts.append(("get_by_text", t)); return Loc(self, "text:" + t)
    def fill(self, s, v, **k): self.acts.append(("fill", s, v))
    def type(self, s, v, **k): self.acts.append(("type", s, v))
    def click(self, s, **k): self.acts.append(("click", s))
    def check(self, s, **k): self.acts.append(("check", s))
    def uncheck(self, s, **k): self.acts.append(("uncheck", s))
    def select_option(self, s, **k): self.acts.append(("select", s, k))
    def inner_text(self, s, **k): return "Create your account"
    def content(self): return ""
    def wait_for_timeout(self, ms): pass
    def wait_for_load_state(self, *a, **k): pass
    def evaluate(self, js, arg=None):
        self.acts.append(("eval", js[:70], arg)); return [] if "input,select,textarea" in js else 1
class Proc:
    returncode, stdout, stderr = 0, "lookup=success", ""
class Runner:
    def __init__(self): self.calls = []
    def __call__(self, cmd, **k): self.calls.append(cmd); return Proc()
def dry(name, url):
    site = B.load_site(name); page = FakePage(url); runner = Runner()
    ctx = B.Ctx(site, page, NAP, runner=runner, log=lambda *a: None, dry_run=True)
    return site, page, ctx, B.run_site(site, ctx)
raw = lambda n: open(os.path.join(JOB, "playbooks", n + ".json"), encoding="utf-8").read()
for n in ("acompio", "tupalo", "showmelocal_claim"):
    s = B.load_site(n)
    check("N4 %s spec loads and validates" % n, s.name == n and any(x.kind in B.STOP_IN_DRY_RUN for x in s.steps))
    check("N4 %s holds no literal phone, email or password" % n, not F._LITERAL_PHONE.search(raw(n)) and not F._LITERAL_EMAIL.search(raw(n)) and "password\": \"" not in raw(n).lower())
    check("N4 %s is listed by build_runner" % n, n in B.all_sites())

# acompio: the account steps stop before signup submit (batch 12 behavior); the new Contact/Description/Summary steps sit AFTER the first stop marker and a second marker guards Finish Listing
acs = json.load(open(os.path.join(JOB, "playbooks", "acompio.json"), encoding="utf-8"))["steps"]
names = [s.get("name") or s["do"] for s in acs]
stops = [i for i, s in enumerate(acs) if s["do"] == "stop_before_submit"]
check("N4 acompio has Contact, Description and Finish Listing steps", all(x in names for x in ("contact_phone", "contact_name", "contact_web", "contact_email", "description", "finish_listing")))
check("N4 acompio Contact selectors are the ones seen live", {s["selector"]: s["key"] for s in acs if s.get("name", "").startswith("contact_") and s.get("selector")} == {"#company-phone": "phone", "#company-contact": "contact", "#company-webpage": "site", "#company-email": "email"})
check("N4 acompio Description types into SunEditor .se-wrapper-wysiwyg from the identity description_long (t_d2f75685: acompio rejected the short one)", any(s["do"] == "type_text" and s["selector"] == ".se-wrapper-wysiwyg" and s.get("value") == "{description_long}" for s in acs))
check("N4 acompio: Finish Listing is a submit click behind a stop marker", stops and stops[-1] < names.index("finish_listing") and next(s for s in acs if s.get("name") == "finish_listing").get("submit") is True)
check("N4 acompio has no list_fields discovery step left", not any(s["do"] == "list_fields" for s in acs))
site, page, ctx, res = dry("acompio", "https://account.acompio.com/signup.php?source=8")
check("N4 acompio dry run ok, stopped before signup submit, only read/fill steps", res["ok"] and res["stopped_before"] == next(x.name for x in site.steps if x.kind in B.STOP_IN_DRY_RUN) and all(s["kind"] in ("read", "fill") for s in res["steps"]), str(res["steps"][-1:]))
check("N4 acompio dry run: vault LOOKED UP only, no --field", ctx._runner.calls and all("--lookup-only" in c and "--field" not in c for c in ctx._runner.calls))
# run the post-login steps (Contact .. Description) on the fake page by --only, dry-run: they are fill kinds up to the final marker
fills = [s.name for s in site.steps if s.kind == "fill" and s.name in ("clear_overlay", "contact_phone", "contact_name", "contact_web", "contact_email", "next_contact", "clear_overlay_2", "description", "next_description")]
NAP2 = dict(NAP, description_long="We help families compare senior living and care options in plain language. Our consultants explain costs and guide each family through every step of the decision.")
page2 = FakePage("https://account.acompio.com/dashboard"); ctx2 = B.Ctx(site, page2, NAP2, runner=Runner(), log=lambda *a: None, dry_run=True)
res2 = B.run_site(site, ctx2, only=set(fills))
check("N4 acompio Contact/Description steps run on a fake page and use the identity NAP", res2["ok"] and len(res2["steps"]) == len(fills) + 1 and res2["steps"][0]["name"] == "open_signup"   # t_03a74bae: --only runs the open step first
     
      and ("fill", "#company-phone", NAP["phone"]) in page2.acts and ("fill", "#company-contact", NAP["contact"]) in page2.acts
      and ("fill", "#company-webpage", NAP["site"]) in page2.acts and ("fill", "#company-email", NAP["email"]) in page2.acts
      and ("type", ".se-wrapper-wysiwyg", NAP2["description_long"]) in page2.acts, str(res2["steps"]))
check("N4 acompio description has no phone or street in it (the Directory refuses them)", not F._LITERAL_PHONE.search(NAP["description"]) and NAP["street"] not in NAP["description"])
check("N4 acompio dry run never clicks Finish Listing", not [a for a in page2.acts if a[0] == "eval" and isinstance(a[2], dict) and a[2].get("text") == "Finish Listing"])

# tupalo
site, page, ctx, res = dry("tupalo", "https://www.tupalo.co/en/api/v5/spot/new")
check("N4 tupalo dry run ok and stops BEFORE the first solve/submit", res["ok"] and res["stopped_before"] == next(x.name for x in site.steps if x.kind in B.STOP_IN_DRY_RUN), str(res))
check("N4 tupalo dry run reached the email step and sent no solve", [s["name"] for s in res["steps"]][-1] == "email" and not [a for a in page.acts if a[0] == "eval" and "g-recaptcha" in a[1]])
check("N4 tupalo: name and street filled from the identity, address picked via the .pointer.pa2 suggestion",
      ("fill", "#name", NAP["name"]) in page.acts and any(a[0] == "type" and a[1] == "#address" and NAP["street"] in a[2] and NAP["zip"] in a[2] for a in page.acts) and ("click", ".pointer.pa2") in page.acts)
check("N4 tupalo: sl-input email, lat and long set by script (set_value)", sum(1 for a in page.acts if a[0] == "eval" and a[1].startswith("(a) => { const el = document.querySelector(a.sel)")) == 4)
check("N4 tupalo: the category is the sl-menu-item 'Local Service'", any(a[0] == "eval" and isinstance(a[2], dict) and a[2].get("text") == "Local Service" and a[2].get("tag") == "sl-menu-item" for a in page.acts))
tu = json.load(open(os.path.join(JOB, "playbooks", "tupalo.json"), encoding="utf-8"))
tn = [s["do"] for s in tu["steps"]]
check("N4 tupalo: solve_captcha comes after the stop marker, Save is a submit sl-button last", tn.index("stop_before_submit") < tn.index("solve_captcha") < len(tn) - 1 and tu["steps"][-1].get("submit") is True and tu["steps"][-1]["tag"] == "sl-button")
check("N4 tupalo records created-unlisted (no phone on the add form)", tu["record"] == "created-unlisted" and B.load_site("tupalo").record == "created-unlisted")
check("N4 tupalo cookie decline is optional (a missing banner is not a failure)", tu["steps"][1].get("optional") is True and res["steps"][1]["status"] == "ok")

# showmelocal claim
site, page, ctx, res = dry("showmelocal_claim", "https://www.showmelocal.com/claim-listing.aspx?bid=37893637")
check("N4 showmelocal_claim dry run ok, stops before the CAPTCHA solve", res["ok"] and res["stopped_before"] == next(x.name for x in site.steps if x.kind in B.STOP_IN_DRY_RUN) and res["steps"][-1]["name"] == "business_email", str(res))
sm = json.load(open(os.path.join(JOB, "playbooks", "showmelocal.json" if os.path.exists(os.path.join(JOB, "playbooks", "showmelocal.json")) else "showmelocal_claim.json"), encoding="utf-8"))
sn = [s["do"] for s in sm["steps"]]
check("N4 showmelocal_claim: solve_captcha after the stop marker, then the cmdRegister submit, then the activation mail", sn.index("stop_before_submit") < sn.index("solve_captcha") < sn.index("wait_mail"))
check("N4 showmelocal_claim: fields seen live (txtEmail, txtPassword, txtBusinessEmail, cmdRegister) are the only selectors used", {s["selector"] for s in sm["steps"] if s.get("selector")} == {"[id$=txtEmail]", "[id$=txtPassword]", "[id$=txtBusinessEmail]", "[id$=cmdRegister]"})
check("N4 showmelocal_claim keeps record none (name/checkbox ids were never seen) and has a discovery step", sm["record"] == "none" and "list_fields" in sn)
check("N4 showmelocal_claim never clicks RELEASE LISTING and never touches /dashboard/correct-data.aspx", "release" not in raw("showmelocal_claim").lower().replace("never click release listing", "") and "correct-data.aspx\"" not in raw("showmelocal_claim"))
check("N4 showmelocal_claim dry run: the claim password is only looked up (--lookup-only)", ctx._runner.calls and all("--lookup-only" in c for c in ctx._runner.calls))
# a dry run of ANY new spec refuses solve_captcha
for n in ("tupalo", "showmelocal_claim"):
    s = B.load_site(n); st = next(x for x in s.steps if x.name == "recaptcha")
    c = B.Ctx(s, FakePage("https://x.example/"), NAP, runner=Runner(), log=lambda *a: None, dry_run=True)
    try: st.fn(c); bad = False
    except C.BuildError: bad = True
    check("N4 %s: solve_captcha is refused in a dry run (never spends)" % n, bad)

# new verbs are validated
check("N4 set_value / type_text need key or value", "needs key or value" in validates({"site": "z", "domain": "z.example", "record": "none", "steps": [{"do": "set_value", "selector": "#a"}]}) and "needs key or value" in validates({"site": "z", "domain": "z.example", "record": "none", "steps": [{"do": "type_text", "selector": "#a"}]}))
check("N4 a literal phone in a set_value value is refused", "literal phone" in validates({"site": "z", "domain": "z.example", "record": "none", "steps": [{"do": "set_value", "selector": "#a", "value": "555-010-1234"}]}))

# ---- P1 playbook_write -----------------------------------------------------------------------------------------------------------
pb = os.path.join(tempfile.mkdtemp(), "playbooks", "build"); os.makedirs(pb)
open(os.path.join(pb, "acompio.com.md"), "w", encoding="utf-8").write("old\n")
before = set(os.listdir(pb))
p = PW.write_playbook("acompio.com.md", "# acompio\nit's new, with an apostrophe\n", base=pb)
check("P1 replaces an existing playbook and returns the path", open(p, encoding="utf-8").read() == "# acompio\nit's new, with an apostrophe\n" and os.path.basename(p) == "acompio.com.md")
check("P1 no temp file is left behind", set(os.listdir(pb)) == before)
check("P1 creates a new playbook", os.path.isfile(PW.write_playbook("newsite.com.md", "# n", base=pb)))
def refused(name, text="x", base=pb):
    try: PW.write_playbook(name, text, base=base); return False
    except PW.PlaybookWriteRefused: return True
outside = os.path.join(os.path.dirname(pb), "evil.md")
check("P1 refuses ../ traversal", refused("../evil.md") and not os.path.exists(outside))
check("P1 refuses an absolute path outside playbooks/build", refused(outside) and not os.path.exists(outside))
check("P1 refuses a sub-folder", refused("sub/x.md"))
check("P1 refuses a non-markdown name", refused("acompio.com.json") and refused("notes.txt"))
check("P1 refuses a hidden file and an empty name", refused(".hidden.md") and refused(""))
check("P1 refuses empty text and leaves the old file alone", refused("acompio.com.md", "   ") and "apostrophe" in open(os.path.join(pb, "acompio.com.md"), encoding="utf-8").read())
check("P1 refuses a base that does not exist", refused("a.md", base=os.path.join(pb, "nope")))
check("P1 an absolute path INSIDE playbooks/build is accepted", PW.write_playbook(os.path.join(pb, "abs.md"), "# a", base=pb).endswith("abs.md"))
check("P1 default directory is the vault playbooks/build", PW.PLAYBOOK_DIR.replace("\\", "/").endswith("Projects/citation-engine/playbooks/build") or "CE_PLAYBOOK_DIR" in os.environ)
src = open(os.path.join(JOB, "playbook_write.py"), encoding="utf-8").read()
check("P1 makes no network call and reads no secret", "urllib" not in src and "socket" not in src and "environ" in src and "password" not in src.lower().split('"""')[2])

if __name__ == "__main__":
    print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
