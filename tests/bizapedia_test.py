"""bizapedia playbook + website-value tests (t_64c4d511). No network, no browser, no real mailbox: fake page, fake IMAP, fake clock."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job", "playbooks"))
import bizapedia as B
import hotfrog as H

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

# W1 website value: https:// exactly once, from every input shape, in BOTH playbooks
for fn, name in ((B.site_value, "bizapedia"), (H.site_value, "hotfrog")):
    for raw in ("seniorcaresolutions.co", "https://seniorcaresolutions.co", "https://https://seniorcaresolutions.co", "http://seniorcaresolutions.co/", " HTTPS://SeniorCareSolutions.co "):
        check("W1 %s site_value(%r)" % (name, raw), fn(raw) == "https://seniorcaresolutions.co", fn(raw))
    try: fn(""); empty = False
    except B.PlaybookError: empty = True
    check("W1 %s empty website refused" % name, empty)

LINK = "https://www.bizapedia.com/order-validate.aspx?id=AB12&token=zz"
MAIL = ("From: Bizapedia <noreply@bizapedia.com>\r\nSubject: Validate your order\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<a href=\"%s\">Validate</a>" % LINK.replace("&", "&amp;")).encode()
OTHER = b"From: x <n@example.com>\r\nSubject: hi\r\nContent-Type: text/plain\r\n\r\nsee https://www.bizapedia.com/order-validate.aspx?id=1"
check("B1 validate link extracted, &amp; decoded", B.extract_validate_link(MAIL) == LINK, str(B.extract_validate_link(MAIL)))
check("B1 hotfrog pattern restored after use", H.VERIFY_RE.pattern.startswith("https://www\\.hotfrog"))
check("B1 no link -> None", B.extract_validate_link(b"From: a@b.c\r\n\r\nhello") is None)
check("B1 lookalike domain not matched", B.extract_validate_link(b"From: a@b.c\r\nContent-Type: text/plain\r\n\r\nhttps://www.bizapedia.com.evil.example/order-validate.aspx?id=1") is None)

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
FakeIMAP.messages = {1: OTHER}
check("B2 mail from a non-bizapedia sender ignored", B.mailbox(ENV, FakeIMAP).newest_verify_link() is None)
FakeIMAP.messages = {1: OTHER, 2: MAIL}
mb = B.mailbox(ENV, FakeIMAP)
check("B2 finds the bizapedia mail (uid 2)", mb.newest_verify_link() == (2, LINK))
check("B2 read-only: EXAMINE + BODY.PEEK, never STORE/EXPUNGE", ("select", "INBOX", True) in FakeIMAP.log and any("BODY.PEEK" in str(e) for e in FakeIMAP.log) and not any(e[0] in ("STORE", "EXPUNGE") for e in FakeIMAP.log))
check("B2 hotfrog reader unchanged by the reuse", H.ImapMailbox(ENV, FakeIMAP).sender_hint == "hotfrog")
try: B.mailbox({"LISTINGS_IMAP_HOST": "x"}, FakeIMAP); miss = False
except B.PlaybookError: miss = True
check("B2 missing LISTINGS_IMAP_* refused", miss)

class Loc:
    def __init__(self, page, sel): self.page, self.sel = page, sel
    @property
    def first(self): return self
    def count(self): return self.page.present.get(self.sel, 1)
    def click(self, timeout=None): self.page.acts.append(("click", self.sel))
class FakePage:
    CLAIM = "https://www.bizapedia.com/company-claim.aspx?companyid=29FD0AFC9C2F"
    def __init__(self, present=None, body="Claimed\nphone (502) 555-0101 site seniorcaresolutions.co", claim_target=None):
        self.acts, self.present, self.body, self.url = [], present or {}, body, "x"
        self.claim_target = "document.location.href = '%s';" % self.CLAIM if claim_target is None else claim_target
    def goto(self, u, wait_until=None): self.acts.append(("goto", u)); self.url = u
    def wait_for_timeout(self, ms): pass
    def locator(self, s): return Loc(self, s)
    def fill(self, s, v): self.acts.append(("fill", s, v))
    def check(self, s): self.acts.append(("check", s))
    def select_option(self, s, label=None): self.acts.append(("select", s, label))
    def get_by_role(self, role, name=None): return Loc(self, "role:%s:%s" % (role, name))
    def inner_text(self, s): return self.body
    def evaluate(self, js): return self.claim_target

class FakeMB:
    def __init__(self, found): self.found, self.calls = found, 0
    def max_uid(self): return 5
    def newest_verify_link(self, since_uid=0):
        self.calls += 1; return self.found if self.found and self.calls >= 2 else None

KW = dict(company_url="https://www.bizapedia.com/ky/alder-care-consulting-and-solutions-llc.html", name="Pat Example Smith", email_addr="listings@example.test",
          category_group="Health & Medical", category="Home Health Care", products="Senior care consulting", company_email="listings@example.test",
          phone="(502) 555-0101", website="https://seniorcaresolutions.co")
pg = FakePage(); t = [0]
res = B.run(pg, FakeMB((6, LINK)), get_password=lambda: "pw-short-20chars", sleep=lambda s: t.__setitem__(0, t[0] + s), now=lambda: t[0], **KW)
check("B3 full run: steps in order up to the validate link", res["steps"] == list(B.STEPS[:7]) and res["verify_uid"] == 6, res)
gotos = [a[1] for a in pg.acts if a[0] == "goto"]
check("B3 company page, claim page (id read from the button), validate link; nothing else", gotos == [KW["company_url"], KW["company_url"], FakePage.CLAIM, LINK], gotos)
check("B3 website typed with https:// once, not doubled", ("fill", "#txtCompanyWebsite", "https://seniorcaresolutions.co") in pg.acts and not any(a[0] == "fill" and "https://https://" in str(a[2]) for a in pg.acts))
check("B3 relationship Owner and job title Owner", ("select", "#ctl00_selRelationshipType", "Owner") in pg.acts and ("fill", "#txtJobTitle", "Owner") in pg.acts)
check("B3 name split: first Pat Example, last Smith", ("fill", "#txtNewFirstName", "Pat Example") in pg.acts and ("fill", "#txtNewLastName", "Smith") in pg.acts)
kinds = [a[0] for a in pg.acts]
check("B3 both terms boxes checked before Submit click", [a[1] for a in pg.acts if a[0] == "check"] == ["#chbTermsOfUse", "#chbIndemnify"] and max(i for i, k in enumerate(kinds) if k == "check") < max(i for i, k in enumerate(kinds) if k == "click"))
check("B3 password never appears in the result", "pw-short" not in repr(res))

# B4 refusals
for label, kw, exc in (
    ("21-char password", dict(get_password=lambda: "x" * 21), True),
    ("20-char password ok", dict(get_password=lambda: "x" * 20), False),
    ("no password callable", dict(get_password=None), True),
    ("empty password", dict(get_password=lambda: ""), True)):
    try: B.run(FakePage(), FakeMB((6, LINK)), sleep=lambda s: None, now=lambda: 0, **dict(KW, **kw)); raised = False
    except B.PlaybookError: raised = True
    check("B4 %s -> %s" % (label, "refused" if exc else "accepted"), raised == exc)
try: B.run(FakePage(claim_target=""), FakeMB((6, LINK)), get_password=lambda: "pw", sleep=lambda s: None, now=lambda: 0, **KW); noclaim = False
except B.PlaybookError: noclaim = True
check("B4 no Claim Profile button (already claimed) stops the run", noclaim)
try: B.fill_account(FakePage({"#txtNewPassword": 0}), "e", "p", "A", "B"); changed = False
except B.PlaybookError: changed = True
check("B4 changed claim form stops the run", changed)
t2 = [0]
try: B.run(FakePage(), FakeMB(None), get_password=lambda: "pw", poll_seconds=30, poll_every=10, sleep=lambda s: t2.__setitem__(0, t2[0] + s), now=lambda: t2[0], **KW); late = False
except B.PlaybookError: late = True
check("B4 no validation mail within the window -> error", late)
try: B.run(FakePage(body="Performing a quick security check..."), FakeMB((6, LINK)), get_password=lambda: "pw", sleep=lambda s: None, now=lambda: 0, **KW); walled = False
except B.PlaybookError as e: walled = "not a bypass" in str(e)
check("B4 a wall that never clears is reported, not bypassed", walled)
try: B.split_name("Cher"); one = False
except B.PlaybookError: one = True
check("B4 single-word contact name refused", one)

# B5 public page check
r = B.check_public_page(FakePage(), KW["company_url"], phone_digits="5025550101", site="seniorcaresolutions.co")
check("B5 public page: Claimed + phone + site", r == {"claimed": True, "phone": True, "site": True}, str(r))
r = B.check_public_page(FakePage(body="Home\nACTIVE\nWrite Review\nseniorcaresolutions.co"), KW["company_url"], phone_digits="5025550101", site="seniorcaresolutions.co")
check("B5 no 'Claimed' text and no phone are reported as such", r["claimed"] is False and r["phone"] is False and r["site"] is True, str(r))

# B6 safety
src = open(os.path.join(HERE, "..", "job", "playbooks", "bizapedia.py"), encoding="utf-8").read()
check("B6 no secret literal and no print of a password", "print(" in src and "password" not in " ".join(l for l in src.splitlines() if "print(" in l))
try: B.main(["--live"]); live = True
except SystemExit as e: live = False
check("B6 --live is refused without a card", live is False and B.main(["--dry-run"]) == 0)

print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
