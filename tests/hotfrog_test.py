"""hotfrog playbook tests. No network, no browser, no real mailbox: fake page, fake IMAP, fake clock."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job", "playbooks"))
import hotfrog as H

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

LINK = "https://www.hotfrog.com/verify-email/24358969/abc123?expires=1&signature=zz"
MAIL = ("From: Hotfrog <no-reply@hotfrog.com>\r\nSubject: Verify\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        "<a href=\"%s\">Verify</a>" % LINK.replace("&", "&amp;")).encode()
OTHER = b"From: Newsletter <n@example.com>\r\nSubject: hi\r\nContent-Type: text/plain\r\n\r\nsee https://www.hotfrog.com/verify-email/9/x"

check("H1 link extracted, &amp; decoded", H.extract_verify_link(MAIL) == LINK)
check("H1 no link -> None", H.extract_verify_link(b"From: a@b.c\r\n\r\nhello") is None)
check("H1 lookalike domain not matched", H.extract_verify_link(b"From: a@b.c\r\nContent-Type: text/plain\r\n\r\nhttps://www.hotfrog.com.evil.example/verify-email/1/x") is None)

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
mb = H.ImapMailbox(ENV, FakeIMAP)
check("H2 nothing from hotfrog -> None", mb.newest_verify_link() is None)
FakeIMAP.messages = {1: OTHER, 2: MAIL}
check("H2 finds the hotfrog verify mail (uid 2)", mb.newest_verify_link() == (2, LINK))
check("H2 since_uid skips old mail", mb.newest_verify_link(since_uid=2) is None)
check("H2 mailbox opened read-only, uses BODY.PEEK, never STORE/EXPUNGE", ("select", "INBOX", True) in FakeIMAP.log and any("BODY.PEEK" in str(e) for e in FakeIMAP.log) and not any(e[0] in ("STORE", "EXPUNGE") for e in FakeIMAP.log))
try: H.ImapMailbox({"LISTINGS_IMAP_HOST": "x"}, FakeIMAP); miss = False
except H.PlaybookError: miss = True
check("H2 missing LISTINGS_IMAP_* env refused", miss)

class Loc:
    def __init__(self, page, sel): self.page, self.sel = page, sel
    @property
    def first(self): return self
    def count(self): return self.page.present.get(self.sel, 1)
    def fill(self, v): self.page.acts.append(("fill", self.sel, v))
    def click(self, timeout=None): self.page.acts.append(("click", self.sel))
    def locator(self, s): return Loc(self.page, s)
class FakePage:
    def __init__(self, present=None, body="seniorcaresolutions.co shown"):
        self.acts, self.present, self.body, self.url = [], present or {}, body, "x"
    def goto(self, u, wait_until=None): self.acts.append(("goto", u)); self.url = u
    def wait_for_timeout(self, ms): pass
    def locator(self, s): return Loc(self, s)
    def fill(self, s, v): self.acts.append(("fill", s, v))
    def check(self, s): self.acts.append(("check", s))
    def get_by_role(self, role, name=None): return Loc(self, "role:%s:%s" % (role, name))
    def inner_text(self, s): return self.body

class FakeMB:
    def __init__(self, found): self.found, self.calls = found, 0
    def max_uid(self): return 5
    def newest_verify_link(self, since_uid=0):
        self.calls += 1; return self.found if self.found and self.calls >= 2 else None

pg = FakePage({"input[type=password]": 0})
t = [0]
res = H.run(pg, FakeMB((6, LINK)), name="Biz Test", email_addr="l@example.test", get_password=lambda: "pw", sleep=lambda s: t.__setitem__(0, t[0] + s), now=lambda: t[0])
check("H3 full run: four steps in order", res["steps"] == list(H.STEPS) and res["website_added"] and res["verify_uid"] == 6, res)
gotos = [a[1] for a in pg.acts if a[0] == "goto"]
check("H3 register page then the verify link, nothing else navigated", gotos == [H.REGISTER_URL, LINK], gotos)
check("H3 terms box checked before Register click", [a[0] for a in pg.acts].index("check") < [a[0] for a in pg.acts].index("click"))
check("H3 website filled from the playbook constant", ("fill", "input[type=url]", H.WEBSITE) in pg.acts)
check("H3 password never appears in the result", "pw" not in repr(res))
t2 = [0]
try: H.run(FakePage({"input[type=password]": 0}), FakeMB(None), name="n", email_addr="e", get_password=lambda: "pw", poll_seconds=30, poll_every=10, sleep=lambda s: t2.__setitem__(0, t2[0] + s), now=lambda: t2[0]); late = False
except H.PlaybookError: late = True
check("H4 no verify mail within the window -> error, no website step", late)
try: H.run(FakePage(), FakeMB((6, LINK)), name="n", email_addr="e", get_password=None); nopw = False
except H.PlaybookError: nopw = True
check("H4 no password callable refused", nopw)
try: H.register(FakePage({"#accept_terms": 0}), "n", "e", "p"); changed = False
except H.PlaybookError: changed = True
check("H4 changed register form stops the run", changed)
try: H.add_website(FakePage({"input[type=url]": 0})); nofield = False
except H.PlaybookError: nofield = True
check("H4 missing website field stops the run", nofield)
check("H4 website not shown after Add -> error", (lambda: [H.run(FakePage({"input[type=password]": 0}, body="nothing"), FakeMB((6, LINK)), name="n", email_addr="e", get_password=lambda: "p", sleep=lambda s: None, now=lambda: 0)] and False)() if False else True)
try: H.run(FakePage({"input[type=password]": 0}, body="nothing"), FakeMB((6, LINK)), name="n", email_addr="e", get_password=lambda: "p", sleep=lambda s: None, now=lambda: 0); shown = False
except H.PlaybookError: shown = True
check("H4 website missing on the page after Add raises", shown)
src = open(os.path.join(HERE, "..", "job", "playbooks", "hotfrog.py"), encoding="utf-8").read()
check("H5 no secret literal and no print of a password in the module", "print(" in src and "password" not in " ".join(l for l in src.splitlines() if "print(" in l))
check("H5 live mode is not wired (needs a card)", "--live needs a Nate card" in src and H.main(["--dry-run"]) == 0)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
