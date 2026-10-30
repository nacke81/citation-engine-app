"""Batch 16 fix tests (t_d2f75685): IMAP vault fallback, rejected -> queued, description_long validator, acompio_owner order-safe status read, recheck_due,
vault_item CLI, cylex dry-run fixture, client-email verify type.
No network, no browser, no vault, no CapSolver, no real mailbox, no real queue: fakes and temp files only. Run: python tests/batch16_test.py (CI).
Lesson applied (green CI hid a real side effect): urlopen / subprocess.run / imaplib are blocked FIRST, so a test that forgets a fake fails loudly."""
import os, sys, json, tempfile, copy, io, subprocess, urllib.request, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
os.environ["CE_ACTIVITIES_WRITE"] = "0"
os.environ["CE_DIRECTORIES_WRITE"] = "0"
for k in ("LISTINGS_IMAP_HOST", "LISTINGS_IMAP_PORT", "LISTINGS_IMAP_USER", "LISTINGS_IMAP_PASSWORD"): os.environ.pop(k, None)
sys.path.insert(0, HERE)
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
def _no_net(*a, **k): raise AssertionError("network call attempted")
def _no_proc(*a, **k): raise AssertionError("subprocess attempted: %r" % (a[:1],))
urllib.request.urlopen = _no_net
subprocess.run = _no_proc
import imaplib
class _NoImap:
    def __init__(s, *a, **k): raise AssertionError("real IMAP attempted")
imaplib.IMAP4_SSL = _NoImap
import build_runner as B, formspec as F, recheck as R, mail_scan as MS, transitions as T, proof as PR, walls as W
import buildqueue as Q, vault_item as VI, imap_vault as IV, description_long as DL, hotfrog as H

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f" [{d}]" if d else ""), flush=True)

IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
NAP = B.nap_from_identity(IDENT)
SECRET = "pw-SECRET-not-real-9d41"

# ---- 1 IMAP vault fallback --------------------------------------------------------------------------------------------------------------------
class Proc:
    def __init__(s, rc, out="", err=""): s.returncode, s.stdout, s.stderr = rc, out, err
class VaultRunner:
    def __init__(s, proc): s.proc, s.calls = proc, []
    def __call__(s, cmd, **k): s.calls.append(cmd); return s.proc
good = Proc(0, json.dumps({"host": "imap.example", "port": "993", "user": "listings@example.test", "password": SECRET}) + "\n")
vr = VaultRunner(good)
got = IV.fetch(runner=vr)
check("1 vault fetch returns the login from the pipe", got["password"] == SECRET and got["user"] == "listings@example.test")
check("1 the password is NOT in the helper's argv (pipe only)", all(SECRET not in str(c) for c in vr.calls) and len(vr.calls) == 1)
def raises(fn, exc):
    try: fn(); return None
    except exc as e: return str(e)
    except Exception as e: return "WRONG:%s:%s" % (type(e).__name__, e)
m = raises(lambda: IV.fetch(runner=VaultRunner(Proc(0, json.dumps({"host": "h", "port": "1", "user": "u"})))), IV.MailboxNotRead)
check("1 vault item without a password -> MAILBOX NOT READ", m and m.startswith("MAILBOX NOT READ"), str(m))
m = raises(lambda: IV.fetch(runner=VaultRunner(Proc(1, "", "imap-vault=failed reason=item not found"))), IV.MailboxNotRead)
check("1 vault missing -> MAILBOX NOT READ with the short reason, no stack", m and m.startswith("MAILBOX NOT READ") and "item not found" in m, str(m))
check("1 the vault error never carries the password", m and SECRET not in m)

# mail_env: env wins, empty env asks the vault, missing vault is an error
ENV_FULL = {"LISTINGS_IMAP_HOST": "imap.example", "LISTINGS_IMAP_PORT": "993", "LISTINGS_IMAP_USER": "u@example.test", "LISTINGS_IMAP_PASSWORD": "env-pw"}
asked = []
cfg = H.mail_env(ENV_FULL, vault=lambda: asked.append(1) or {})
check("1 env password set -> the vault is never asked", cfg["password"] == "env-pw" and not asked)
os.environ.pop("LISTINGS_IMAP_PASSWORD", None)
cfg = H.mail_env(None, vault=lambda: {"host": "imap.example", "port": "993", "user": "listings@example.test", "password": SECRET})
check("1 env empty + vault -> login from the vault", cfg["password"] == SECRET and cfg["host"] == "imap.example")
m = raises(lambda: H.mail_env(None, vault=lambda: (_ for _ in ()).throw(IV.MailboxNotRead("MAILBOX NOT READ: vault read failed (no output)"))), H.MailboxNotRead)
check("1 env empty + vault missing -> MailboxNotRead (a PlaybookError)", m and m.startswith("MAILBOX NOT READ") and issubclass(H.MailboxNotRead, H.PlaybookError), str(m))
m = raises(lambda: H.mail_env({"LISTINGS_IMAP_HOST": "h", "LISTINGS_IMAP_PORT": "1", "LISTINGS_IMAP_USER": "u"}), H.MailboxNotRead)
check("1 an explicit env dict with no password never calls a vault (tests and callers stay deterministic)", m and m.startswith("MAILBOX NOT READ"))

# mail_scan.read_messages through a fake IMAP: env empty + mocked vault = mailbox read
RAW = b"From: Directory <noreply@bbb.org>\r\nSubject: Your listing is now live\r\nDate: Tue, 27 Oct 2026 10:00:00 +0000\r\nContent-Type: text/plain\r\n\r\nSee https://www.bbb.org/us/ky/exampleton/profile/consultant/alder-0001\r\n"
class FakeIMAP:
    logins = []
    def __init__(s, host, port): s.host = host
    def login(s, u, p): FakeIMAP.logins.append((u, p))
    def select(s, *a, **k): return ("OK", [b"1"])
    def uid(s, cmd, *a):
        if cmd == "SEARCH": return ("OK", [b"7"])
        return ("OK", [(b"7 (BODY[] {1}", RAW), b")"])
    def logout(s): pass
msgs = MS.read_messages(env=None, imap_cls=FakeIMAP, vault=lambda: {"host": "imap.example", "port": "993", "user": "listings@example.test", "password": SECRET})
check("1 env empty + mocked vault = mailbox read (1 message, logged in with the vault login)", len(msgs) == 1 and FakeIMAP.logins == [("listings@example.test", SECRET)], str(FakeIMAP.logins))
imb = H.ImapMailbox(None, imap_cls=FakeIMAP, vault=lambda: {"host": "imap.example", "port": "993", "user": "listings@example.test", "password": SECRET})
check("1 the wait_mail reader (ImapMailbox) takes the same fallback", imb.cfg["password"] == SECRET)

# CLI: mail_scan.main with env empty + vault missing -> clear MAILBOX NOT READ, non-zero
QP = os.path.join(tempfile.mkdtemp(), "queue.json")
def row(i, d, state="submitted", **kw): return dict({"id": i, "directory": d, "state": state, "mike_approval": None, "history": []}, **kw)
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
def write_q(rows):
    json.dump({"canonical": CANON, "fix_queue": [], "create_rows": rows}, open(QP, "w"))
write_q([row("create-bbb", "bbb.org")])
os.environ["CE_IMAP_VAULT_JS"] = os.path.join(tempfile.mkdtemp(), "does-not-exist.js")   # helper absent: the real fetch() refuses before spawning anything
buf, ebuf = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
    code = MS.main(["--queue", QP])
out = buf.getvalue() + ebuf.getvalue()
check("1 mail_scan CLI: env empty + vault missing -> 'MAILBOX NOT READ' and exit non-zero", code != 0 and "MAILBOX NOT READ" in out, "%s %s" % (code, out[:200]))
check("1 ...and the row is not reported as 'none' (no approval mail)", "| none" not in buf.getvalue())
# recheck.main wiring: lazy scanner; an unreadable mailbox is reported on stderr and the run goes on
import types
seen = {}
orig_rf = R.recheck_file
def fake_rf(path=None, ident=None, **kw): seen.update(kw); kw["mail"].messages(); return []
R.recheck_file = fake_rf
ebuf = io.StringIO()
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(ebuf):
    rc = R.main(["--queue", QP, "--no-chrome"])
R.recheck_file = orig_rf
check("1 recheck.main passes a lazy MailScanner and reports MAILBOX NOT READ when the vault is missing (not fatal)", isinstance(seen.get("mail"), MS.MailScanner) and "MAILBOX NOT READ" in ebuf.getvalue() and rc == 0, ebuf.getvalue()[:160])
# the secret never reaches a log line
buf = io.StringIO()
sc = MS.MailScanner(reader=lambda: MS.read_messages(env=None, imap_cls=FakeIMAP, vault=lambda: {"host": "h", "port": "1", "user": "u", "password": SECRET}), log=lambda m: buf.write(m))
sc.messages()
check("1 the password is in no log line and no exception text", SECRET not in buf.getvalue() and sc.error is None)

# ---- 2 rejected -> queued ---------------------------------------------------------------------------------------------------------------------
def rec(rid, new, **kw):
    if new == "live" and "proof" not in kw and not kw.get("refresh_url"): kw["proof"] = {"proof_url": "https://x.example/p", "proof_nap": "NAP", "proof_at": "2026-10-28T00:00:00Z", "proof_nap_match": True, "build_action": "new"}   # t_d660babc
    return T.record_transition("SCC", rid, new, kw.pop("evidence", None), kw.pop("note", None), queue_path=QP, today=kw.pop("today", "2026-10-28"),
                               portal=FakePortal(), **kw)
class FakePortal:
    def __init__(s): s.snap = {"directories": [], "totals": {}}
    def latest_snapshot(s, cid): return {"payload": copy.deepcopy(s.snap)}
    def upsert_snapshot(s, cid, day, payload): s.snap = payload
    def call(s, *a, **k): pass
class FakeDirs:
    owner = "x"
    def call(s, *a, **k): return []
write_q([row("create-acompio", "acompio.us", "rejected", history=[{"at": "2026-10-27", "from": "created-unlisted", "to": "rejected", "evidence_url": None, "note": "Insufficient description"}])])
m = raises(lambda: rec("create-acompio", "queued"), T.TransitionRefused)
check("2 rejected -> queued without --reason is refused", m and "--reason" in m, str(m))
m = raises(lambda: rec("create-acompio", "queued", reason="short"), T.TransitionRefused)
check("2 a reason under 10 characters is refused", m and "--reason" in m, str(m))
before = open(QP, "rb").read()
d = rec("create-acompio", "queued", reason="description_long written from the site, 180 chars", dry_run=True)
check("2 dry run writes nothing", open(QP, "rb").read() == before and d["to"] == "queued")
r = rec("create-acompio", "queued", reason="description_long written from the site, 180 chars")
q = json.load(open(QP)); row_ = q["create_rows"][0]; last = row_["history"][-1]
check("2 rejected -> queued with a reason: row is queued", row_["state"] == "queued" and r["from"] == "rejected")
check("2 it is LOGGED, not silent: history keeps the rejection and adds a requeue entry with the reason", len(row_["history"]) == 2 and row_["history"][0]["to"] == "rejected"
      and last.get("requeue") is True and last.get("reason", "").startswith("description_long written") and last["note"].startswith("re-create after rejection:"), str(last))
check("2 mike_approval untouched", row_["mike_approval"] is None)
for bad_from in ("live", "submitted", "needs-human", "found"):
    write_q([row("create-x", "x.example", bad_from)])
    m = raises(lambda: rec("create-x", "queued", reason="a perfectly good reason"), T.TransitionRefused)
    check("2 %s -> queued stays refused (only rejected may go back)" % bad_from, m and "only a rejected row" in m, str(m))
write_q([row("create-x", "x.example", "queued")])
m = raises(lambda: rec("create-x", "submitted", reason="a perfectly good reason"), T.TransitionRefused)
check("2 --reason on any other transition is refused", m and "only applies" in m, str(m))
# the hard-block cap still holds: a STOPPED rejected row cannot be re-queued
h = [{"at": "2026-10-2%d" % i, "from": "x", "to": "needs-human", "wall": "hard-block", "try": i, "note": "WALL:hard-block try %d/3" % i} for i in (6, 7, 8)]
write_q([row("create-stop", "stop.example", "rejected", history=h)])
m = raises(lambda: rec("create-stop", "queued", reason="a perfectly good reason"), T.TransitionRefused)
check("2 a hard-block STOPPED row cannot be re-queued (only Mike's reset)", m and "STOPPED" in m, str(m))
# transitions CLI has --reason
write_q([row("create-acompio", "acompio.us", "rejected")])
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = T.main(["--row", "create-acompio", "--to", "queued", "--reason", "new original description", "--queue", QP, "--dry-run", "--today", "2026-10-28"])
check("2 transitions CLI: --reason accepted (dry run)", code == 0 and '"to": "queued"' in buf.getvalue())
with contextlib.redirect_stderr(io.StringIO()):
    code = T.main(["--row", "create-acompio", "--to", "queued", "--queue", QP, "--dry-run"])
check("2 transitions CLI: no --reason -> REFUSED, exit 1", code == 1)

# description_long validator
GOOD = ("We help families in western Kentucky compare senior living and care options. Our consultants explain costs, "
        "answer questions, and guide each family through the decision with plain language.")
check("2 validator accepts original full sentences of 100 to 300 chars", DL.validate(GOOD) == GOOD and 100 <= len(GOOD) <= 300, str(len(GOOD)))
def refused(text, word):
    m = raises(lambda: DL.validate(text), DL.DescriptionError)
    return bool(m) and word in m and not m.startswith("WRONG"), str(m)
for label, text, word in (
    ("too short", "We help families find senior care.", "too short"),
    ("empty", "", "empty"),
    ("too long", GOOD + " " + GOOD + " " + GOOD, "too long"),
    ("street address", GOOD + " Visit us at 100 Example Drive for a free visit today.", "address"),
    ("ZIP and City, ST", "We guide families through senior care choices with patience and plain language every day. Based in Exampleton, KY serving the whole region.", "address"),
    ("PO box", GOOD + " Write to P.O. Box 12 anytime.", "address"),
    ("hours", GOOD + " We are open Monday through Friday, 9 am to 5 pm.", "hours"),
    ("day of week only", GOOD + " Call on Saturday if you like.", "hours"),
    ("24/7", GOOD + " Support is available 24/7 for every family.", "hours"),
    ("phone", GOOD + " Call 502-555-0101 today.", "phone"),
    ("email", GOOD + " Write to hello@example.test now.", "email"),
    ("url", GOOD + " See www.example.test for more.", "web address"),
    ("not sentences", "senior care consulting family guidance costs questions decisions plain language help available throughout the region for families", "full sentences"),
    ("one sentence", "We help families in western Kentucky compare senior living and care options and understand the costs of each choice they face", "full sentences"),
):
    okk, msg = refused(text, word)
    check("2 validator refuses: %s" % label, okk, msg)
check("2 whitespace is folded before the length check", DL.validate("  " + GOOD.replace(" ", "   ") + "  ") == GOOD)
# the NAP key: from identity only, validated, never invented
check("2 no description_long in the identity -> no key (nothing invented in code)", "description_long" not in NAP)
ident2 = copy.deepcopy(IDENT); ident2["BIZ"]["SCC"]["description_long"] = GOOD
nap2 = B.nap_from_identity(ident2)
check("2 identity description_long passing the validator becomes {description_long}", nap2["description_long"] == GOOD)
ident3 = copy.deepcopy(IDENT); ident3["BIZ"]["SCC"]["description_long"] = "Call 502-555-0101 now."
nap3 = B.nap_from_identity(ident3)
check("2 a bad identity text is not a key; rendering it raises the validator's reason", "description_long" not in nap3 and "too short" in (raises(lambda: F.render("{description_long}", nap3), B.BuildError) or ""))
m = raises(lambda: F.render("{description_long}", NAP), B.BuildError)
check("2 a run without description_long fails before typing (no invented text)", m and "description_long" in m, str(m))
spec = F.load_spec("acompio"); site = F.build_site(spec)
dstep = next(s for s in spec["steps"] if s.get("name") == "description")
check("2 acompio.json description step reads {description_long}", dstep.get("value") == "{description_long}" and "key" not in dstep)

class P2:
    def __init__(s): s.acts, s.url = [], "https://account.acompio.com/x"
    def locator(s, sel):
        o = types.SimpleNamespace(count=lambda: 1); return o
    def click(s, sel, **k): s.acts.append(("click", sel))
    def type(s, sel, v, **k): s.acts.append(("type", sel, v))
    def wait_for_timeout(s, ms): pass
dsite = F.build_site({"site": "d", "domain": "acompio.com", "record": "none", "steps": [dstep]})
pg = P2(); res = B.run_site(dsite, B.Ctx(dsite, pg, nap2, dry_run=False, log=lambda *a: None))
check("2 the live step types exactly the validated text", res["ok"] and ("type", ".se-wrapper-wysiwyg", GOOD) in pg.acts, str(res)[:200])
pg = P2(); res = B.run_site(dsite, B.Ctx(dsite, pg, nap3, dry_run=False, log=lambda *a: None))
check("2 a bad text types nothing and fails the step with the validator's reason", not res["ok"] and not pg.acts and "too short" in res["steps"][0]["detail"], str(res)[:200])

# ---- 3 acompio_owner notes + order-safe read_text -----------------------------------------------------------------------------------------------
raw = open(os.path.join(JOB, "playbooks", "acompio_owner.json"), encoding="utf-8").read()
ao = json.loads(raw)
check("3 acompio_owner notes name listing 47872152 and status rejected", "47872152" in ao["notes"] and "rejected" in ao["notes"])
check("3 the wrong facts are gone ('company 10000001, ... status pending' as the listing)", "company 10000001, Free Listing" not in ao["notes"])
class P3:
    def __init__(s, body): s.body, s.url = body, "https://account.acompio.com/"
    def goto(s, *a, **k): pass
    def wait_for_timeout(s, ms): pass
    def inner_text(s, sel, **k): return s.body
rt = next(s for s in ao["steps"] if s["do"] == "read_text")
fn = F._v_read_text(rt)
def read(body):
    c = B.Ctx(types.SimpleNamespace(name="a", domain="acompio.com", vault_item="x"), P3(body), NAP, log=lambda *a: None); return fn(c)
d = read("Dashboard\nListing 47872152\nStatus: Pending review\nYour listing was rejected: Insufficient description")
check("3 a page showing 'pending' BEFORE 'rejected' reports rejected", d.startswith("status text: rejected"), d)
check("3 the other word is listed, not hidden", "pending" in d)
d = read("Your listing is inactive. Activate it to be active.")
check("3 'inactive' is not read as 'active' (whole words)", d.startswith("status text: inactive"), d)
d = read("Status: Pending")
check("3 a lone 'pending' is still pending", d == "status text: pending", d)
m = raises(lambda: read("Welcome"), B.BuildError)
check("3 no status word still fails (no silent pass)", m and "none of" in m)
check("3 spec order is terminal words first", ao["steps"][-1]["expect_any"][:2] == ["rejected", "suspended"] and ao["steps"][-1]["expect_any"].index("rejected") < ao["steps"][-1]["expect_any"].index("pending"))

# ---- 4 recheck_due ----------------------------------------------------------------------------------------------------------------------------
write_q([row("create-citylocalpro", "citylocalpro.com", "pending-verify", history=[{"at": "2026-10-27", "from": "submitted", "to": "pending-verify", "evidence_url": None, "note": "verify mail never came"}])])
r = rec("create-citylocalpro", "pending-verify", note="re-send hit the 24h sender limit (SMTP 503); retry after 10/28", recheck_due="2026-10-29", today="2026-10-27")
q = json.load(open(QP)); cl = q["create_rows"][0]
check("4 recheck_due is stored on the row via transitions, state unchanged", cl.get("recheck_due") == "2026-10-29" and cl["state"] == "pending-verify")
check("4 ...and logged in the history entry", cl["history"][-1].get("recheck_due") == "2026-10-29")
def cands(today, only=None): 
    with contextlib.redirect_stdout(io.StringIO()): return R.candidates(json.load(open(QP)), today=today, only=only)
check("4 recheck skips the row before the due date", not cands("2026-10-28"))
check("4 recheck reads it on the due date", len(cands("2026-10-29")) == 1)
check("4 ...and after", len(cands("2026-11-02")) == 1)
check("4 a row NAMED with --row is read anyway", len(cands("2026-10-28", only={"create-citylocalpro"})) == 1)
os.environ["_X"] = "1"
qq = json.load(open(QP))
check("4 proof's waiting rows skip it too (today = real date; due is in the future)", "citylocalpro.com" not in PR._waiting_rows(dict(qq, create_rows=[dict(cl, recheck_due="2999-01-01")])) and "citylocalpro.com" in PR._waiting_rows(dict(qq, create_rows=[dict(cl, recheck_due="2000-01-01")])))
write_q([dict(cl, recheck_due="2999-01-01"), row("create-bbb", "bbb.org")])
buf = io.StringIO(); MS_main_rc = None
FakeIMAP.logins = []
orig_rm = MS.read_messages
MS.read_messages = lambda days=30, **k: []
with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
    MS_main_rc = MS.main(["--queue", QP, "--directory", "bbb.org", "--directory", "citylocalpro.com"])
MS.read_messages = orig_rm
check("4 mail_scan lists the due row and skips the not-yet-due one", "create-bbb" in buf.getvalue() and "create-citylocalpro" not in buf.getvalue(), buf.getvalue()[:200])
check("4 Q.not_due: future = the date, today/past/none = None", Q.not_due({"recheck_due": "2026-10-29"}, "2026-10-28") == "2026-10-29" and Q.not_due({"recheck_due": "2026-10-28"}, "2026-10-28") is None and Q.not_due({}, "2026-10-28") is None)
m = raises(lambda: rec("create-bbb", "submitted", note="n", recheck_due="tomorrow", dry_run=True), T.TransitionRefused)
check("4 recheck_due must be YYYY-MM-DD", m and "YYYY-MM-DD" in m)
# a state change drops a stale marker
write_q([dict(cl, state="pending-verify", recheck_due="2026-10-29")])
rec("create-citylocalpro", "live", evidence="https://citylocalpro.com/listing/alder", today="2026-10-30")
check("4 a state change drops the stale retry marker", "recheck_due" not in json.load(open(QP))["create_rows"][0])
write_q([dict(cl, state="pending-verify", recheck_due="2026-10-29")])
rec("create-citylocalpro", "pending-verify", note="still waiting on the mail", today="2026-10-30")
check("4 a note refresh in the same state keeps the marker", json.load(open(QP))["create_rows"][0].get("recheck_due") == "2026-10-29")
# build_runner --live skips a not-due row before any browser
write_q([row("create-citylocalpro", "citylocalpro.com", "queued", recheck_due="2999-01-01", mike_approval={"approved_by": "mike", "at": "2026-10-20", "row_id": "create-citylocalpro"})])
Q_PATH = Q.QUEUE_PATH
Q.QUEUE_PATH = QP
orig_find = B.find_row
B.find_row = lambda rid, site, queue_path=None: orig_find(rid, site, QP)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = B.main(["citylocalpro", "--live", "--card", "t_x", "--row", "create-citylocalpro"])
B.find_row = orig_find; Q.QUEUE_PATH = Q_PATH
check("4 build_runner --live skips a not-yet-due row before any browser starts", rc == 0 and "SKIP create-citylocalpro: recheck_due 2999-01-01" in buf.getvalue(), buf.getvalue()[:200])

# ---- 5 vault_item CLI -------------------------------------------------------------------------------------------------------------------------
ITEMS = [{"id": "id-clp", "name": "SCC - citylocalpro", "uris": ["https://citylocalpro.com/login"]}, {"id": "id-other", "name": "SCC - hotfrog.com", "uris": []}]
out_l, err_l = [], []
rc = VI.main(["--domain", "citylocalpro.com"], items=ITEMS, out=out_l.append, err=err_l.append)
check("5 CLI prints the resolved item NAME ('SCC - citylocalpro' for citylocalpro.com)", rc == 0 and out_l == ["SCC - citylocalpro"], str(out_l))
out_l = []; VI.main(["--domain", "https://www.citylocalpro.com/x", "--print", "id"], items=ITEMS, out=out_l.append, err=err_l.append)
check("5 --print id gives the id; a URL is reduced to its domain", out_l == ["id-clp"], str(out_l))
rc = VI.main(["--domain", "nothing.example"], items=ITEMS, out=out_l.append, err=err_l.append)
check("5 not found -> exit 1, REFUSED on stderr, nothing on stdout", rc == 1 and err_l and "not-found" in err_l[-1] and out_l == ["id-clp"])
rc = VI.main(["--domain", "dup.com"], items=[{"id": "1", "name": "SCC - dup.com", "uris": []}, {"id": "2", "name": "SCC - dup.com", "uris": []}], out=out_l.append, err=err_l.append)
check("5 two matches -> exit 1 item-not-unique", rc == 1 and "item-not-unique" in err_l[-1])
# no secret: the lister is id/name/uris only, and the CLI output holds no password key
js = open(os.path.join(JOB, "vault_resolve.cjs"), encoding="utf-8").read()
check("5 the lister reads id / name / uris only", "password" not in js.lower().replace("no secret field", "") and "username" not in js and "notes" not in js and "totp" not in js)
with contextlib.redirect_stderr(io.StringIO()):
    rc = VI.main(["--domain", "x.com"], runner=lambda *a, **k: Proc(1, "", "list=failed reason=credentials-unavailable"))
check("5 a vault problem -> exit 1, no traceback", rc == 1)
# the fill helper takes the resolved name: --item-name beats the spec's name
class PRun:
    returncode, stdout, stderr = 0, "fill=success", ""
    def __init__(s): s.calls = []
    def __call__(s, cmd, **k): s.calls.append(cmd); return s
clp = types.SimpleNamespace(name="citylocalpro", domain="citylocalpro.com", vault_item="SCC - citylocalpro.com")
fake_clp = types.SimpleNamespace(url="https://citylocalpro.com/add-your-business", bring_to_front=lambda: None)
pr = PRun(); c = B.Ctx(clp, fake_clp, NAP, runner=pr, dry_run=False, log=lambda *a: None); c.item_name = "SCC - citylocalpro"
c.vault_fill("#password", "https://citylocalpro.com/add-your-business")
cmd = pr.calls[0]
check("5 fill helper is called with the RESOLVED name (--name 'SCC - citylocalpro'), not the spec's", cmd[cmd.index("--name") + 1] == "SCC - citylocalpro")
pr = PRun(); c = B.Ctx(clp, fake_clp, NAP, runner=pr, dry_run=False, log=lambda *a: None)
c.vault_fill("#password", "https://citylocalpro.com/add-your-business")
check("5 no --item-name: the spec's vault_item is used as before", pr.calls[0][pr.calls[0].index("--name") + 1] == "SCC - citylocalpro.com")
ap = B.argparse if hasattr(B, "argparse") else None
src = open(os.path.join(JOB, "build_runner.py"), encoding="utf-8").read()
check("5 build_runner has --item-name wired to ctx.item_name", '"--item-name"' in src and "ctx.item_name = n.item_name" in src)

# ---- 6 cylex spec (dry-run fixture only) ------------------------------------------------------------------------------------------------------
cs = F.load_spec("cylex"); csite = F.build_site(cs)
check("6 cylex.json loads, validates, is listed by build_runner", csite.name == "cylex" and "cylex" in B.all_sites())
check("6 domain cylex.us = the queue row's directory (walls.gate counts it); record none", csite.domain == "cylex.us" and csite.record == "none")
i_stop = next(i for i, s in enumerate(cs["steps"]) if s["do"] == "stop_before_submit")
subs = [i for i, s in enumerate(cs["steps"]) if s.get("submit") or s["do"] in ("wait_mail", "solve_captcha")]
check("6 every submit / mail step comes after stop_before_submit (dry run stops before submit)", subs and all(i > i_stop for i in subs))
rawc = open(os.path.join(JOB, "playbooks", "cylex.json"), encoding="utf-8").read()
check("6 no literal phone / email / password in the spec", not F._LITERAL_EMAIL.search(rawc) and not F._LITERAL_PHONE.search(rawc) and '"password": "' not in rawc)
check("6 the notes prohibit replay registration and distinguish code entry from success", "Never run registration again" in cs["notes"] and "typed code is not server verification" in cs["notes"])
class Loc6:
    def __init__(s, pg, sel): s.pg, s.sel = pg, sel
    @property
    def first(s): return s
    def count(s): return 1
    def fill(s, v, **k): s.pg.acts.append(("fill", s.sel, v))
    def click(s, **k): s.pg.acts.append(("click", s.sel))
class Page6:
    def __init__(s): s.acts, s.url, s.keyboard = [], "https://www.cylex.us.com/", types.SimpleNamespace(press=lambda k: s.acts.append(("press", k)))
    def goto(s, u, **k): s.acts.append(("goto", u)); s.url = u
    def locator(s, sel): return Loc6(s, sel)
    def fill(s, sel, v, **k): s.acts.append(("fill", sel, v))
    def type(s, sel, v, **k): s.acts.append(("type", sel, v))
    def click(s, sel, **k): s.acts.append(("click", sel))
    def inner_text(s, sel, **k): return "Cylex Register Sign in"
    def content(s): return "<html></html>"
    def title(s): return "Cylex"
    def wait_for_timeout(s, ms): pass
    def wait_for_load_state(s, *a, **k): pass
    def evaluate(s, js, arg=None): s.acts.append(("eval", str(js)[:30])); return [] if str(js).lstrip().startswith("() => [...document") else True
    def query_selector_all(s, sel): return []
pg6 = Page6(); pr6 = PRun()
res6 = B.run_site(csite, B.Ctx(csite, pg6, NAP, runner=pr6, dry_run=True, log=lambda *a: None))
check("6 dry run: stops BEFORE the submit step (stopped_before set), nothing clicked as submit", res6["stopped_before"] is not None and not any(a[0] == "click" and "submit" in a[1] for a in pg6.acts), json.dumps(res6["steps"][-2:])[:900])
check("6 dry run touched only cylex.us.com, no vault write (lookup only)", all(a[1].startswith("https://www.cylex.us.com") for a in pg6.acts if a[0] == "goto") and all("--lookup-only" in c or "--field" not in c for c in pr6.calls), str(pg6.acts)[:200])
# walls.gate counts both tries (2 of 3) for cylex.us and blocks a hard-block same day; allows the next day
cylex_row = row("create-cylex", "cylex.us", "needs-human", history=[
    {"at": "2026-10-26", "from": "queued", "to": "needs-human", "evidence_url": None, "note": "WALL:hard-block try 1/3 cloudflare sorry you have been blocked"},
    {"at": "2026-10-27", "from": "needs-human", "to": "needs-human", "evidence_url": None, "note": "x", "wall": "hard-block", "try": 1, "ray_id": "a50f7322cf193555"}])
gq = {"fix_queue": [], "create_rows": [cylex_row]}
check("6 walls.gate: cylex.us has 2 tries; same day blocked", len(W.tries(cylex_row)) == 2 and W.gate(gq, "cylex.us", "2026-10-27"))
check("6 walls.gate: try 3 is allowed on 10/28 (run_site wall_gate uses site.domain = cylex.us)", W.gate(gq, csite.domain, "2026-10-28") is None)
wq = os.path.join(tempfile.mkdtemp(), "q.json"); json.dump(gq, open(wq, "w"))
check("6 build_runner.wall_gate(cylex) on 10/27 refuses before any browser", "SKIP cylex.us" in (B.wall_gate(csite, wq, "2026-10-27") or ""))

# ---- 7 client-email verify type ---------------------------------------------------------------------------------------------------------------
check("7 client-email is a verify type", "client-email" in T.VERIFY_TYPES)
write_q([row("create-showmelocal", "showmelocal.com", "created-unlisted")])
class VerPortal(FakePortal):
    def __init__(s): super().__init__(); s.calls = []
    def call(s, method, path, body=None, prefer=None): s.calls.append((method, path, body, prefer))
vp = VerPortal()
r = T.record_transition("SCC", "create-showmelocal", "needs-human", None, None, queue_path=QP, today="2026-10-27", portal=vp, verify_type="client-email", verification=vp, directories=FakeDirs(), observation=__import__("yt_obs").obs("client-email", "2026-10-27"))
b = [c for c in vp.calls if c[1].startswith("citation_verification")][0][2][0]
check("7 needs-human + client-email writes a portal verification row of type client-email", b["verification_type"] == "client-email" and b["state"] == "requires_verification" and "deadline" not in b and r["verification_written"])
hrow = json.load(open(QP))["create_rows"][0]; he = hrow["history"][-1]
check("7 history carries verify_type client-email", he.get("verify_type") == "client-email" and hrow["state"] == "needs-human")
check("7 the note says we never attest listings@ (the client's own address is needed)", "client's own email" in he["note"] and "never attest" in he["note"] and "listings@" in he["note"], he["note"])
check("7 internal state: no Activities row (client news) for a needs-human park", r["activity_record"] is None)
m = raises(lambda: T.record_transition("SCC", "create-showmelocal", "live", "https://x.example/a", None, queue_path=QP, today="2026-10-28", portal=FakePortal(), verify_type="client-email", dry_run=True, proof={"proof_url": "https://x.example/a", "proof_nap": "NAP", "proof_at": "2026-10-28T00:00:00Z", "proof_nap_match": True, "build_action": "new"}), T.TransitionRefused)
check("7 client-email only applies to needs-human", m and "needs-human" in m, str(m))
write_q([row("create-showmelocal", "showmelocal.com", "created-unlisted")])
m = raises(lambda: T.record_transition("SCC", "create-showmelocal", "needs-human", None, None, queue_path=QP, today="2026-10-28", portal=FakePortal(), verify_type="client-email", steps=["x"], observation=__import__("yt_obs").obs("client-email", "2026-10-28"), dry_run=True), T.TransitionRefused)
check("7 steps / directory_url are for id-check only (refused on client-email)", m and "id-check" in m, str(m))
write_q([row("create-showmelocal", "showmelocal.com", "created-unlisted")])
m = raises(lambda: T.record_transition("SCC", "create-showmelocal", "needs-human", None, None, queue_path=QP, today="2026-10-28", portal=FakePortal(), verify_type="listings-email", dry_run=True), T.TransitionRefused)
check("7 an unknown verify type is still refused", m and "client-email" in m, str(m))
buf = io.StringIO()
write_q([row("create-showmelocal", "showmelocal.com", "created-unlisted")])
with contextlib.redirect_stdout(buf):
    code = T.main(["--row", "create-showmelocal", "--to", "needs-human", "--verify-type", "client-email", "--queue", QP, "--dry-run", "--today", "2026-10-28", "--observed-type", "client-email", "--screenshot", __import__("yt_obs")._SHOT, "--price-seen", "none", "--observed-at", "2026-10-28", "--observed-url", "https://a.example/v"])
check("7 transitions CLI accepts --verify-type client-email", code == 0 and "client-email" in buf.getvalue())
mig = open(os.path.join(HERE, "..", "docs", "portal-client-email-verification.md"), encoding="utf-8").read()
check("7 the portal migration needed first is written down (the portal repo, additive CHECK widening)", "client-email" in mig and "citation_verification_verification_type_check" in mig)

# ---- skill + ci wiring ------------------------------------------------------------------------------------------------------------------------
ci = open(os.path.join(HERE, "..", ".github", "workflows", os.listdir(os.path.join(HERE, "..", ".github", "workflows"))[0]), encoding="utf-8").read()
check("CI runs this file", "tests/batch16_test.py" in ci)

print("\n%d passed, %d failed" % (sum(ok), len(ok) - sum(ok)))
sys.exit(0 if all(ok) else 1)
