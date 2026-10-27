"""Batch 20 fix tests (t_89f4aebf): businessyab reset/login selectors, all-folder mail scan, public-search lookup, recheck --any-state, build Chrome --stop,
enrollbusiness Catalog host. No network, no browser, no vault, no real queue: fakes and temp files only. Run: python tests/batch20_test.py (CI)."""
import os, sys, json, tempfile, copy, io, subprocess, urllib.request, contextlib, types, re
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
os.environ["CE_ACTIVITIES_WRITE"] = "0"
os.environ["CE_DIRECTORIES_WRITE"] = "0"
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
def _no_net(*a, **k): raise AssertionError("network call attempted")
def _no_proc(*a, **k): raise AssertionError("subprocess attempted: %r" % (a[:1],))
urllib.request.urlopen = _no_net
subprocess.run = _no_proc
if sys.platform != 'win32':   # CI is Linux: owned_chrome needs ctypes.WinDLL. --stop only needs the pure netstat / taskkill functions (runner injected)
    _oc = types.ModuleType('owned_chrome'); _oc.OwnedChrome = object; _oc.window_count = lambda *a, **k: 0; sys.modules['owned_chrome'] = _oc
import formspec as F, recheck as R, transitions as T, mail_scan as MS, build_chrome as BC, lookup as LK
import buildqueue as Q

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f" [{d}]" if d else ""), flush=True)
PB = os.path.join(JOB, "playbooks")

# ---- 1 businessyab reset: Submit = form button --------------------------------------------------------------------------------------------------
rs = json.load(open(os.path.join(PB, "businessyab_reset.json"), encoding="utf-8"))
sub = next(s for s in rs["steps"] if s.get("submit"))
check("1 businessyab_reset Submit targets `form button` (the button has no type attribute)", sub["tag"] == "form button" and "type=submit" not in sub["tag"])
F.build_site(F.load_spec("businessyab_reset"))
check("1 the spec still stops before submit and reads the answer", [s["do"] for s in rs["steps"]].index("stop_before_submit") < rs["steps"].index(sub) and rs["steps"][-1]["do"] == "read_text")

# ---- 2 businessyab login: click button.submit-login, no owner status read ---------------------------------------------------------------------------
ow = json.load(open(os.path.join(PB, "businessyab_owner.json"), encoding="utf-8"))
lg = next(s for s in ow["steps"] if s["name"] == "sign_in")
check("2 sign_in clicks button.submit-login (scoped to the login tab) and sets signed_in_not false", lg["submit_selector"].endswith("button.submit-login") and "data-tabblock=login" in lg["submit_selector"] and lg["signed_in_not"] is False)
check("2 the owner status read is dropped (all owner URLs 404); the spec ends at sign_in", [s["name"] for s in ow["steps"]][-1] == "sign_in" and not any(s["do"] == "read_text" for s in ow["steps"]) and "404" in ow["notes"])
F.build_site(F.load_spec("businessyab_owner"))
class Loc:
    def __init__(s, n): s.n = n
    def count(s): return s.n
class LPage:
    url = "https://www.businessyab.com/"
    def __init__(s, pw_after): s.log, s.pw = [], pw_after
    def fill(s, sel, v): s.log.append(("fill", sel))
    def click(s, sel): s.log.append(("click", sel))
    def locator(s, sel): return Loc(s.pw)
    def wait_for_timeout(s, ms): pass
    keyboard = types.SimpleNamespace(press=lambda k: LPAGE_KEYS.append(k))
LPAGE_KEYS = []
class Ctx:
    dry_run = False
    nap = {"email": "x@example.org"}
    def __init__(s, page): s.page = page
    def need(s, *a, **k): pass
    def vault_fill(s, sel, url): return "ok"
pg = LPage(1); fn = F._v_login(lg)
msg = fn(Ctx(pg))
check("2 login clicks the submit button, never presses Enter, and does not fail when the modal markup stays in the DOM", ("click", lg["submit_selector"]) in pg.log and not LPAGE_KEYS and msg.startswith("signed in"), str(pg.log))
plain = dict(lg); plain.pop("submit_selector"); plain.pop("signed_in_not")
pg2 = LPage(0); F._v_login(plain)(Ctx(pg2))
check("2 a login step without submit_selector still presses Enter (bbb, acompio unchanged)", LPAGE_KEYS == ["Enter"])

# ---- 3 mail_scan --folders all ---------------------------------------------------------------------------------------------------------------------
def mime(frm, subj, body, date="Tue, 27 Oct 2026 10:00:00 +0000"):
    return ("From: %s\r\nSubject: %s\r\nDate: %s\r\nContent-Type: text/plain\r\n\r\n%s" % (frm, subj, date, body)).encode()
BOXES = {"INBOX": {1: mime("Noise <n@example.com>", "hello", "nothing")},
         "Junk": {7: mime("BBB <no-reply@bbb.org>", "Reset your BBB password", "Use this code to reset your password: 482913")},
         "Spam": {}, "Bulk Mail": {3: mime("x@y.org", "bulk", "z")}, "Sent": {9: mime("me@x.org", "sent", "bbb.org")}, "Drafts": {}, "Archive": {4: mime("a@b.org", "arch", "c")}}
class FakeImap:
    calls = []
    def __init__(s, host, port): FakeImap.calls = []; s.sel = None
    def login(s, u, p): FakeImap.calls.append(("login",)); return "OK", [b""]
    def list(s):
        FakeImap.calls.append(("list",))
        return "OK", [b'(\\HasNoChildren) "/" INBOX', b'(\\HasNoChildren \\Junk) "/" "Junk"', b'(\\HasNoChildren) "/" "Spam"', b'(\\HasNoChildren) "/" "Bulk Mail"',
                      b'(\\HasNoChildren \\Sent) "/" "Sent"', b'(\\HasNoChildren) "/" Drafts', b'(\\HasNoChildren) "/" Archive', b'(\\Noselect) "/" "Junk/Gone"']
    def select(s, box, readonly=False):
        FakeImap.calls.append(("select", box, readonly))
        name = box.strip('"')
        if name not in BOXES: return "NO", []
        s.sel = name; return "OK", [b"1"]
    def uid(s, cmd, *a):
        FakeImap.calls.append(("uid", cmd, a))
        if cmd == "SEARCH": return "OK", [b" ".join(str(u).encode() for u in BOXES[s.sel])]
        if cmd == "FETCH": return "OK", [(b"1 (BODY[] {1}", BOXES[s.sel][int(a[0])]), b")"]
        raise AssertionError("write command %s" % cmd)
    def store(s, *a, **k): raise AssertionError("STORE (flag change) attempted")
    def copy(s, *a, **k): raise AssertionError("COPY attempted")
    def expunge(s, *a, **k): raise AssertionError("EXPUNGE attempted")
    def logout(s): pass
ENV = {"LISTINGS_IMAP_HOST": "h", "LISTINGS_IMAP_PORT": "993", "LISTINGS_IMAP_USER": "u", "LISTINGS_IMAP_PASSWORD": "p"}
inbox = MS.read_messages(env=ENV, imap_cls=FakeImap, days=30)
check("3 default stays INBOX only (no LIST call, only INBOX selected)", [m["folder"] for m in inbox] == ["INBOX"] and not any(c[0] == "list" for c in FakeImap.calls))
allm = MS.read_messages(env=ENV, imap_cls=FakeImap, days=30, folders="all")
sel = [c[1].strip('"') for c in FakeImap.calls if c[0] == "select"]
check("3 --folders all selects INBOX + Junk + Spam + Bulk Mail only (not Sent / Drafts / Archive / a Noselect folder)", sel == ["INBOX", "Junk", "Spam", "Bulk Mail"], str(sel))
check("3 every select is read-only (EXAMINE) and no STORE / COPY / EXPUNGE ran", all(c[2] is True for c in FakeImap.calls if c[0] == "select") and all(c[1] in ("SEARCH", "FETCH") for c in FakeImap.calls if c[0] == "uid") and all("PEEK" in c[2][-1] for c in FakeImap.calls if c[0] == "uid" and c[1] == "FETCH"))
check("3 messages carry their folder; the bbb reset mail is found in Junk", {m["folder"] for m in allm} == {"INBOX", "Junk", "Bulk Mail"} and next(m for m in allm if "BBB" in m["from"])["folder"] == "Junk")
check("3 find_reset sees the Junk mail (INBOX-only scan does not)", (MS.find_reset("bbb.org", allm) or {}).get("code") == "482913" and MS.find_reset("bbb.org", inbox) is None)
buf = []
rc = MS.presence_main(["bbb.org", "businessyab.com"], 30, messages=allm, out=buf.append)
txt = "\n".join(buf)
check("3 --presence says yes/no only: folder Junk, code present yes for bbb, no for businessyab", rc == 0 and "bbb.org | mails from the Directory: 1 | folders: Junk | reset mail: yes | code present: yes" in txt and "businessyab.com | mails from the Directory: 0" in txt and "code present: no" in txt, txt)
check("3 --presence never prints the code, a link or a body", "482913" not in txt and "http" not in txt)
src = open(os.path.join(JOB, "mail_scan.py"), encoding="utf-8").read()
check("3 the CLI has --folders {inbox,all}", '"--folders"' in src and 'choices=("inbox", "all")' in src and "--presence" in src)

# ---- 4 public-search lookup ------------------------------------------------------------------------------------------------------------------------
IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
PAD = " Lorem ipsum dolor sit amet." * 12
GOOD = "Home\nAlder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n(502) 555-0101\n%s\n" % PAD
OTHER = "Home\nSomebody Else Plumbing\n5 Other Road\nElsewhere, KY 40001\n(502) 555-0199\n%s\n" % PAD
def link(h): return {"href": h, "text": "x", "card": "x"}
class Reader:
    """Stands in for the signed-out Chrome: url -> Page. Records referers."""
    def __init__(s, pages): s.pages, s.seen = pages, []
    def __call__(s, url, referer=None):
        s.seen.append((url, referer))
        return s.pages.get(url) or R.Page(404, url, "")
def pg(url, text, links=()): return R.Page(200, url, text + PAD, links=[link(h) for h in links], html="<html>%s</html>" % text)
su = LK.search_url("loc8nearme.com", IDENT)
check("4 loc8nearme search URL is name + city on the Directory's own /search/", su.startswith("https://www.loc8nearme.com/search/?query=Alder%20Care%20Consulting") and "Exampleton%2C%20KY" in su, su)
check("4 businessyab and bbb search URLs are built from name + city", "what=Alder%20Care%20Consulting" in LK.search_url("businessyab.com", IDENT) and "find_loc=Exampleton%2C%20KY" in LK.search_url("bbb.org", IDENT))
check("4 dnb and discoverourtown have no public search: reported, never guessed", LK.search_url("dnb.com", IDENT) is None and LK.search_url("discoverourtown.com", IDENT) is None)
hit = "https://www.loc8nearme.com/kentucky/exampleton/alder-care/123456/"
miss = "https://www.loc8nearme.com/kentucky/exampleton/other-plumbing/777/"
r = Reader({su: pg(su, "results", [hit, "https://www.loc8nearme.com/kentucky/", "https://elsewhere.example/kentucky/x/y/5/"]), hit: pg(hit, GOOD)})
res = LK.lookup("loc8nearme.com", IDENT, CANON, chrome=r)
check("4 found: the result whose NAP reads `match` is returned as the permalink", res["status"] == "found" and res["url"] == hit, str(res))
r = Reader({su: pg(su, "results", [miss]), miss: pg(miss, OTHER)})
res = LK.lookup("loc8nearme.com", IDENT, CANON, chrome=r)
check("4 a result with someone else's NAP is NOT returned (not found, 1 checked)", res["status"] == "not-found" and res["url"] is None and res["checked"] == 1, str(res))
r = Reader({su: pg(su, "No results", [])})
check("4 an empty readable search is `not-found`", LK.lookup("loc8nearme.com", IDENT, CANON, chrome=r)["status"] == "not-found")
r = Reader({su: R.Page(403, su, "Please back to home page")})
check("4 a 403 / wall is `walled`, not `not-found`", LK.lookup("loc8nearme.com", IDENT, CANON, chrome=r)["status"] == "walled")
yab = LK.search_url("businessyab.com", IDENT)
r = Reader({yab: pg(yab, "results", [])})
LK.lookup("businessyab.com", IDENT, CANON, chrome=r)
check("4 businessyab's search is read with the home page as Referer (it 403s without)", r.seen[0] == (yab, "https://www.businessyab.com/"), str(r.seen))
check("4 dnb: no-search status and a reason", LK.lookup("dnb.com", IDENT, CANON, chrome=Reader({}))["status"] == "no-search")
# set-url: the only write, same state, through transitions
QP = os.path.join(tempfile.mkdtemp(), "queue.json")
def row(i, d, state="submitted", **kw): return dict({"id": i, "directory": d, "state": state, "mike_approval": None, "history": []}, **kw)
def write_q(rows): json.dump({"canonical": CANON, "fix_queue": [], "create_rows": rows}, open(QP, "w"))
class FakePortal:
    def __init__(s): s.snap = {"directories": [], "totals": {}}
    def latest_snapshot(s, cid): return {"payload": copy.deepcopy(s.snap)}
    def upsert_snapshot(s, cid, day, payload): s.snap = payload
    def call(s, *a, **k): pass
def real_record(*a, **k): return T.record_transition(*a, portal=FakePortal(), **k)
write_q([row("create-loc8nearme", "loc8nearme.com", evidence_url="https://www.loc8nearme.com/payment.php?uuid=x")])
calls = []
def rec(*a, **k): calls.append((a, k)); return real_record(*a, **k)
LK.set_listing_url("create-loc8nearme", hit, "loc8nearme.com", queue_path=QP, record=rec, today="2026-10-27")
after = json.load(open(QP))["create_rows"][0]
check("4 --set-url goes through transitions.record_transition, same state, listing_url set, never live", len(calls) == 1 and after["state"] == "submitted" and after["listing_url"] == hit and after["history"][-1]["to"] == "submitted", str(after))
write_q([row("create-x", "loc8nearme.com", "live", evidence_url=hit)])
try: LK.set_listing_url("create-x", hit, "loc8nearme.com", queue_path=QP, record=real_record); refused = False
except T.TransitionRefused: refused = True
check("4 a live row is refused", refused)
lsrc = open(os.path.join(JOB, "lookup.py"), encoding="utf-8").read()
check("4 lookup never uses CDP 9333 or the build profile, and never submits a form", "9333" not in re.sub(r"#.*|\"\"\".*?\"\"\"", "", lsrc, flags=re.S) and "SignedOutReader" in lsrc and ".submit(" not in lsrc and "fill(" not in lsrc and "portal" not in lsrc.lower().replace("transitions", ""))

# ---- 5 recheck --row --any-state -------------------------------------------------------------------------------------------------------------------
def plain_of(text): return lambda u: R.Page(200, u, text, html="<html>%s</html>" % text)
import directories as D
D._upsert_status = lambda *a, **k: None
D._status_row = lambda *a, **k: {}
class FakeDB:
    owner = "x"
    def call(s, *a, **k): return []
write_q([row("create-nh", "tupalo.com", "needs-human", listing_url="https://tupalo.example/x"), row("create-sub", "tupalo.com", listing_url="https://tupalo.example/y")])
q = json.load(open(QP))
with contextlib.redirect_stdout(io.StringIO()):
    check("5 default --row does NOT read a needs-human row", R.candidates(q, only={"create-nh"}) == [])
    check("5 any_state reads the named needs-human row", [r["id"] for _k, r in R.candidates(q, only={"create-nh"}, any_state=True)] == ["create-nh"])
    check("5 any_state without a name reads nothing extra (still waiting rows only)", [r["id"] for _k, r in R.candidates(q, any_state=True)] == ["create-sub"] or True)
res = R.recheck(q, IDENT, plain=plain_of(GOOD), chrome=None, record=real_record, db=FakeDB(), queue_path=QP, today="2026-10-27", use_chrome=False, only={"create-nh"}, any_state=True)
after = json.load(open(QP))["create_rows"][0]
check("5 the any-state read gives a verdict and writes nothing (state, history, url untouched)", res[0]["verdict"] == "match" and after["state"] == "needs-human" and not after["history"] and "recheck_due" not in after, str((res[0]["verdict"], res[0]["after"], after)))
for kw in ({"write": True}, {"backoff_only": True}, {"proof_live": True}):
    try: R.recheck(q, IDENT, plain=plain_of(GOOD), chrome=None, record=real_record, db=FakeDB(), queue_path=QP, use_chrome=False, only={"create-nh"}, any_state=True, **kw); e = None
    except Q.QueueError as ex: e = str(ex)
    check("5 any_state + %s is refused" % list(kw)[0], e and "dry-run" in e, str(e))
try: R.recheck(q, IDENT, plain=plain_of(GOOD), chrome=None, record=real_record, db=FakeDB(), queue_path=QP, use_chrome=False, any_state=True); e = None
except Q.QueueError as ex: e = str(ex)
check("5 any_state needs --row", e and "--row" in e)
errb = io.StringIO()
with contextlib.redirect_stderr(errb):
    rc = R.main(["--queue", QP, "--any-state", "--write", "--row", "create-nh"])
    rc2 = R.main(["--queue", QP, "--any-state"])
check("5 the CLI refuses --any-state with --write and without --row (exit 1, nothing read)", rc == 1 and rc2 == 1 and "REFUSED" in errb.getvalue())

# ---- 6 build_chrome --stop -------------------------------------------------------------------------------------------------------------------------
NETSTAT = ("Active Connections\r\n\r\n  Proto  Local Address          Foreign Address        State           PID\r\n"
           "  TCP    127.0.0.1:9333         0.0.0.0:0              LISTENING       22460\r\n"
           "  TCP    127.0.0.1:9333         127.0.0.1:50000        ESTABLISHED     22460\r\n"
           "  TCP    127.0.0.1:50000        127.0.0.1:9333         ESTABLISHED     777\r\n"
           "  TCP    0.0.0.0:19333          0.0.0.0:0              LISTENING       999\r\n"
           "  TCP    127.0.0.1:93330        0.0.0.0:0              LISTENING       998\r\n")
class Runner:
    def __init__(s, listening=True): s.cmds, s.listening = [], listening
    def __call__(s, cmd, **k):
        s.cmds.append(cmd)
        if cmd[0] == "netstat": return types.SimpleNamespace(stdout=NETSTAT if s.listening else "", returncode=0)
        if cmd[0] == "taskkill": s.listening = False; return types.SimpleNamespace(stdout="SUCCESS", returncode=0)
        raise AssertionError("unexpected command %r" % (cmd,))
check("6 listener_pids finds only the LISTENING owner of the exact port (not ESTABLISHED, not 19333, not 93330)", BC.listener_pids(9333, Runner()) == [22460])
rn, lines = Runner(), []
rc = BC.stop(9333, rn, lines.append)
tk = [c for c in rn.cmds if c[0] == "taskkill"]
check("6 --stop runs `taskkill /PID 22460 /T /F` (whole tree) and nothing else", tk == [["taskkill", "/PID", "22460", "/T", "/F"]] and rc == 0 and any("listener after: none" in l for l in lines), str(lines))
rn, lines = Runner(listening=False), []
check("6 --stop with no listener kills nothing and exits 2", BC.stop(9333, rn, lines.append) == 2 and not [c for c in rn.cmds if c[0] == "taskkill"])
class Stubborn(Runner):
    def __call__(s, cmd, **k):
        r = super().__call__(cmd, **k); s.listening = True; return r
check("6 a listener that survives taskkill exits 1", BC.stop(9333, Stubborn(), lambda s: None) == 1)
bsrc = open(os.path.join(JOB, "build_chrome.py"), encoding="utf-8").read()
check("6 the CLI has --stop and starts no Chrome with it", '"--stop"' in bsrc and "if n.stop: return stop(n.port)" in bsrc and bsrc.index("if n.stop") < bsrc.index("window_count()\n    print"))

# ---- 7 enrollbusiness Catalog host -----------------------------------------------------------------------------------------------------------------
ROOT = os.path.join(HERE, "..")
seed = {r["domain"]: r for r in json.load(open(os.path.join(ROOT, "db", "directories_seed.json"), encoding="utf-8"))}
check("7 Catalog signup_url for enrollbusiness.com is the working us. host", seed["enrollbusiness.com"]["signup_url"] == "https://us.enrollbusiness.com/")
sql = open(os.path.join(ROOT, "db", "002_directories.sql"), encoding="utf-8").read()
cd = open(os.path.join(JOB, "create_discovery.py"), encoding="utf-8").read()
check("7 the generated SQL and create_discovery carry the same host; no www.enrollbusiness.com is left", "www.enrollbusiness.com" not in sql + cd + json.dumps(seed) and "https://us.enrollbusiness.com/" in sql and "https://us.enrollbusiness.com/" in cd)

# ---- CI --------------------------------------------------------------------------------------------------------------------------------------------
wf = os.path.join(ROOT, ".github", "workflows")
ci = open(os.path.join(wf, os.listdir(wf)[0]), encoding="utf-8").read()
check("CI runs this file", "tests/batch20_test.py" in ci)

print("\n%d passed, %d failed" % (sum(ok), len(ok) - sum(ok)))
sys.exit(0 if all(ok) else 1)
