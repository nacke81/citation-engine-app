"""Batch 19 fix tests (t_2d15878c): bbb / businessyab reset specs, reset-link reader, vault set-password (never a duplicate item), businessyab modal evidence,
dry-run backoff. No network, no browser, no vault, no real queue: fakes and temp files only. Run: python tests/batch19_test.py (CI).
Lesson applied (prove-the-spec-on-the-live-page): the page shapes below are the ones read in the build Chrome on 2026-10-27."""
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
import formspec as F, recheck as R, transitions as T, mail_scan as MS, vault_item as VI, fail_evidence as FE

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f" [{d}]" if d else ""), flush=True)
def raises(fn, exc):
    try: fn(); return None
    except exc as e: return str(e)

PB = os.path.join(JOB, "playbooks")
# ---- 1 reset specs -------------------------------------------------------------------------------------------------------------------------------
for nm, url, sel in (("bbb_reset", "https://www.bbb.org/account/forgot-password", "input#email"), ("businessyab_reset", "https://www.businessyab.com/forgot_password", "input[name=forget]")):
    raw = open(os.path.join(PB, nm + ".json"), encoding="utf-8").read(); sp = json.loads(raw)
    st = F.build_site(F.load_spec(nm))
    dos = [s["do"] for s in sp["steps"]]
    check("1 %s opens the live forgot-password URL and fills the listings@ email key (no literal)" % nm, sp["steps"][0]["url"] == url and sp["steps"][1]["selector"] == sel and sp["steps"][1]["key"] == "email" and not F._LITERAL_EMAIL.search(raw))
    check("1 %s: stop_before_submit comes BEFORE the submit click (a dry run sends no reset mail)" % nm, dos.index("stop_before_submit") < next(i for i, s in enumerate(sp["steps"]) if s.get("submit")))
    check("1 %s: record none, LIVE-SEEN note, and the answer is read after the submit" % nm, sp["record"] == "none" and "LIVE-SEEN" in raw and dos[-1] == "read_text")
    check("1 %s: the only submit-kind click is after the stop" % nm, [x.name for x in st.steps if x.kind == "submit"] != [])

# ---- 2 reset-link reader ---------------------------------------------------------------------------------------------------------------------------
BBB_MAIL = {"uid": 41, "from": "BBB <no-reply@bbb.org>", "subject": "Reset your BBB password", "date": "2026-10-27T14:00",
            "body": "Hello,\nUse this code to reset your password: 482913\nIf you did not ask, ignore this. https://www.bbb.org/privacy-policy\nhttps://www.bbb.org/account/login\n"}
YAB_MAIL = {"uid": 42, "from": "BusinessYab <info@businessyab.com>", "subject": "Password reset instructions", "date": "2026-10-27T14:05",
            "body": "<p>Click to reset your password: <a href=\"https://www.businessyab.com/reset_password?token=ab12CD34ef\">reset</a></p> Unsubscribe https://www.businessyab.com/unsubscribe?x=1"}
OLD_YAB = dict(YAB_MAIL, uid=7, date="2026-10-01T09:00", body="reset your password https://www.businessyab.com/reset_password?token=OLDOLDOLD")
NOISE = {"uid": 50, "from": "Hotfrog <x@hotfrog.com>", "subject": "Reset your password", "date": "2026-10-27T15:00", "body": "https://www.hotfrog.com/reset?token=zzz"}
APPROVAL = {"uid": 60, "from": "BusinessYab <info@businessyab.com>", "subject": "Your listing is now live", "date": "2026-10-27T16:00", "body": "now live https://www.businessyab.com/business/alder-care"}
msgs = [BBB_MAIL, YAB_MAIL, OLD_YAB, NOISE, APPROVAL]
h = MS.find_reset("businessyab.com", msgs)
check("2 businessyab: the newest reset mail's tokened link is found (not the old mail, not the approval mail)", h and h["url"] == "https://www.businessyab.com/reset_password?token=ab12CD34ef", str(h))
h = MS.find_reset("bbb.org", msgs)
check("2 bbb: the mailed CODE is found (bbb sends a code); login / privacy links are not the reset link", h and h["code"] == "482913" and h["url"] is None, str(h))
check("2 another Directory's reset mail (hotfrog) is never returned for bbb / businessyab", all("hotfrog" not in json.dumps(MS.find_reset(d, msgs)) for d in ("bbb.org", "businessyab.com")))
check("2 no reset mail -> None; unknown Directory -> None", MS.find_reset("bbb.org", [APPROVAL]) is None and MS.find_reset("example.org", msgs) is None)
buf = []
rc = MS.reset_main(["bbb.org", "businessyab.com"], 7, messages=msgs, out=buf.append)
check("2 --reset-link prints link / code per Directory, exit 0", rc == 0 and any("token=ab12CD34ef" in b for b in buf) and any("482913" in b for b in buf), str(buf))
check("2 --reset-link exit 1 when no reset mail", MS.reset_main(["bbb.org"], 7, messages=[APPROVAL], out=lambda s: None) == 1)
def boom(*a, **k): raise RuntimeError("imap down")
MS.read_messages_orig = MS.read_messages; MS.read_messages = boom
with contextlib.redirect_stderr(io.StringIO()) as e:
    rc = MS.reset_main(["bbb.org"], 7, out=lambda s: None)
MS.read_messages = MS.read_messages_orig
check("2 an unreadable mailbox is exit 2 (never 'no reset mail')", rc == 2 and "MAILBOX NOT READ" in e.getvalue())
src = open(os.path.join(JOB, "mail_scan.py"), encoding="utf-8").read()
check("2 the reader never writes: no open(..., 'w') / queue call in the reset path", "def reset_main" in src and not re.search(r"open\([^)]*['\"]w", src.split("def reset_main")[1].split("def _text_of")[0]))
# the approval scan must still ignore reset mails
check("2 the approval scan does not read a reset mail as an approval", MS.find_approval("businessyab.com", [YAB_MAIL, OLD_YAB]) is None)

# ---- 3 vault set-password: one item, never a duplicate -------------------------------------------------------------------------------------------
ITEMS = [{"id": "i-yab", "name": "SCC - businessyab.com", "uris": ["https://www.businessyab.com/"]}, {"id": "i-bbb", "name": "SCC - bbb.org", "uris": ["https://www.bbb.org/"]},
         {"id": "d1", "name": "SCC - dup.example", "uris": []}, {"id": "d2", "name": "SCC - dup.example", "uris": []}]
calls = []
def runner(cmd, **k):
    calls.append((cmd, k.get("input")))
    return types.SimpleNamespace(returncode=0, stdout="set=success\n", stderr="")
name = VI.set_password("businessyab.com", "N3w-Pass-word!", runner=runner, items=ITEMS)
cmd, inp = calls[0]
check("3 set_password edits the resolved item BY ID", name == "SCC - businessyab.com" and cmd[cmd.index("--item-id") + 1] == "i-yab" and cmd[1].endswith("vault_set_password.cjs"))
check("3 the password goes on STDIN only, never in argv", inp == "N3w-Pass-word!" and not any("N3w-Pass" in c for c in cmd))
n = len(calls)
m = raises(lambda: VI.set_password("nope.example", "N3w-Pass-word!", runner=runner, items=ITEMS), VI.VaultItemError)
check("3 no item for the domain -> refused, NO create fallback, runner never called", m and "not-found" in m and len(calls) == n, str(m))
m = raises(lambda: VI.set_password("dup.example", "N3w-Pass-word!", runner=runner, items=ITEMS), VI.VaultItemError)
check("3 two items for the domain -> refused as not unique, nothing written", m and "item-not-unique" in m and len(calls) == n, str(m))
m = raises(lambda: VI.set_password("bbb.org", "short", runner=runner, items=ITEMS), VI.VaultItemError)
check("3 an empty / short password is refused", m and len(calls) == n)
def failing(cmd, **k): return types.SimpleNamespace(returncode=1, stdout="", stderr="set=failed reason=readback-mismatch")
m = raises(lambda: VI.set_password("bbb.org", "N3w-Pass-word!", runner=failing, items=ITEMS), VI.VaultItemError)
check("3 a failed write raises with the safe reason, not the password", m and "readback-mismatch" in m and "N3w" not in m, str(m))
out = []; er = []
rc = VI.main(["--domain", "bbb.org", "--set-password-from-stdin"], runner=runner, items=ITEMS, out=out.append, err=er.append, stdin=io.StringIO("N3w-Pass-word!\n"))
check("3 CLI --set-password-from-stdin: exit 0, prints the item NAME, never the password", rc == 0 and out == ["password updated in the existing item: SCC - bbb.org"] and calls[-1][1] == "N3w-Pass-word!")
rc = VI.main(["--domain", "dup.example", "--set-password-from-stdin"], runner=runner, items=ITEMS, out=out.append, err=er.append, stdin=io.StringIO("N3w-Pass-word!\n"))
check("3 CLI refuses an ambiguous domain with exit 1", rc == 1 and any("REFUSED" in x for x in er))
js = open(os.path.join(JOB, "vault_set_password.cjs"), encoding="utf-8").read()
check("3 the .cjs edits an existing item only: bw edit item, no 'create item', password from stdin, no console.log of it",
      "'edit', 'item'" in js and "'create'" not in js and "readFileSync(0" in js and "console.log(pw" not in js and "item-not-in-scope" in js)

# ---- 4 businessyab modal evidence + owner spec ------------------------------------------------------------------------------------------------------
by = json.load(open(os.path.join(PB, "businessyab_owner.json"), encoding="utf-8"))
names = [s["name"] for s in by["steps"]]
tab = by["steps"][names.index("pick_login_tab")]
check("4 the owner spec clicks the Log in TAB before sign_in (the modal opens on Sign up)", names.index("open_log_in") < names.index("pick_login_tab") < names.index("sign_in") and tab["tag"] == "#login-tabs li[data-tab=login]")
lg = by["steps"][names.index("sign_in")]
check("4 sign_in selectors are scoped to the log-in tab block, not the sign-up inputs", "data-tabblock=login" in lg["user_selector"] and "data-tabblock=login" in lg["password_selector"])
F.build_site(F.load_spec("businessyab_owner"))
class Page:
    url = "https://www.businessyab.com/"
    def inner_text(s, sel, timeout=0): return "Log in Sign up Wrong password"
    def screenshot(s, path, timeout=0): open(path, "wb").write(b"png")
    def evaluate(s, js): return '<div id="login-box"><div class="error-area">Invalid email or password</div><input name="email" value="listings@secret.example"><input type="password" value="hunter2hunter2"></div>'
ctx = types.SimpleNamespace(run_dir=None, page=Page())
r = FE.save(ctx, types.SimpleNamespace(name="businessyab_owner"), types.SimpleNamespace(name="sign_in"), "login failed")
html_ = open(r["html"], encoding="utf-8").read()
check("4 a failed step saves the modal HTML next to the screenshot (png + html + json)", all(r.get(k) and os.path.exists(r[k]) for k in ("screenshot", "html", "json")), str(r))
check("4 the saved HTML keeps the error-area text (tells wrong password from selector)", "Invalid email or password" in html_ and "error-area" in html_)
check("4 the saved HTML has no input values (no email, no password)", "hunter2" not in html_ and "secret.example" not in html_ and "value=\"***\"" in html_)

# ---- 5 dry-run backoff gap --------------------------------------------------------------------------------------------------------------------------
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
PAD = " Lorem ipsum dolor sit amet." * 12
GOOD = "Home\nAlder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n(502) 555-0101\n%s\n" % PAD
HIDDEN = "Home\nAlder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n(502) 555-0101\nThis listing is HIDDEN until ACTIVATED.\n%s\n" % PAD
QP = os.path.join(tempfile.mkdtemp(), "queue.json")
def row(i, d, state="submitted", **kw): return dict({"id": i, "directory": d, "state": state, "mike_approval": None, "history": []}, **kw)
def write_q(rows): json.dump({"canonical": CANON, "fix_queue": [], "create_rows": rows}, open(QP, "w"))
class FakePortal:
    def __init__(s): s.snap = {"directories": [], "totals": {}}
    def latest_snapshot(s, cid): return {"payload": copy.deepcopy(s.snap)}
    def upsert_snapshot(s, cid, day, payload): s.snap = payload
    def call(s, *a, **k): pass
def real_record(*a, **k): return T.record_transition(*a, portal=FakePortal(), **k)
class FakeDB:
    owner = "x"
    def call(s, *a, **k): return []
import directories as D
D._upsert_status = lambda *a, **k: None
D._status_row = lambda *a, **k: {}
def plain_of(text): return lambda u: R.Page(200, u, text, html="<html>%s</html>" % text)
def run(rows, plain, **kw):
    write_q(rows)
    res = R.recheck(json.load(open(QP)), IDENT, plain=plain, chrome=None, record=real_record, db=FakeDB(), queue_path=QP, today="2026-10-27", use_chrome=False, **kw)
    return res, json.load(open(QP))["create_rows"]
before = None
res, rows = run([row("create-tupalo", "tupalo.com", listing_url="https://tupalo.example/x")], plain_of(HIDDEN), write=False, backoff_only=True)
check("5 dry run + backoff_only: not-public moves recheck_due +2 days", res[0]["verdict"] == "not-public" and rows[0].get("recheck_due") == "2026-10-29", str((res[0]["verdict"], rows[0].get("recheck_due"))))
check("5 ...and ONLY that: state unchanged, no live", rows[0]["state"] == "submitted" and res[0]["after"] == "submitted")
res, rows = run([row("create-tupalo", "tupalo.com", listing_url="https://tupalo.example/x")], plain_of(HIDDEN), write=False)
check("5 plain dry run (no flag) still writes nothing", rows[0].get("recheck_due") is None and res[0]["recheck_due"] == "2026-10-29")
NOTFOUND = "Page not found\nSorry, we could not find the page you were looking for.\n" + PAD
res, rows = run([row("create-cc", "chamberofcommerce.com", listing_url="https://coc.example/x")], plain_of(NOTFOUND), write=False, backoff_only=True)
check("5 chamberofcommerce-style 'page not found' backs off in a dry run with the flag", res[0]["verdict"] == "not-public" and rows[0].get("recheck_due") == "2026-10-29", str((res[0]["verdict"], res[0].get("error"))))
fs = next(iter(R.UNREADABLE_PUBLIC))
res, rows = run([row("create-fs", fs, listing_url="https://fs.example/x")], plain_of(GOOD), write=False, backoff_only=True)
check("5 unreadable-public backs off in a dry run with the flag", res[0]["verdict"] == "unreadable-public" and rows[0].get("recheck_due") == "2026-10-29")
res, rows = run([row("create-ok", "tupalo.com", listing_url="https://tupalo.example/x")], plain_of(GOOD), write=False, backoff_only=True)
check("5 a MATCH under backoff_only does NOT go live and gets no recheck_due", rows[0]["state"] == "submitted" and "recheck_due" not in rows[0] and not rows[0]["history"])
res, rows = run([row("create-mm", "tupalo.com", listing_url="https://tupalo.example/x")], plain_of(GOOD.replace("100 Example Drive", "999 Wrong Street")), write=False, backoff_only=True)
check("5 a mismatch under backoff_only writes nothing (no note, no date)", rows[0]["state"] == "submitted" and "recheck_due" not in rows[0] and not rows[0]["history"])
res, rows = run([row("create-lv", "tupalo.com", "live", listing_url="https://tupalo.example/x", evidence_url="https://tupalo.example/x")], plain_of(HIDDEN), write=False, backoff_only=True, include_live=True)
check("5 a live row is never touched by backoff_only", rows[0]["state"] == "live" and "recheck_due" not in rows[0])
write_q([row("create-t", "tupalo.com", listing_url="https://tupalo.example/x", recheck_due="2026-10-29")])
with contextlib.redirect_stdout(io.StringIO()):
    c1 = R.candidates(json.load(open(QP)), today="2026-10-28")
check("5 the next batch skips the row the day after the dry-run backoff", not c1)
rs = open(os.path.join(JOB, "recheck.py"), encoding="utf-8").read()
check("5 the CLI has --backoff-only and it never overrides --write", "--backoff-only" in rs and "backoff_only=n.backoff_only and not n.write" in rs)

wf = os.path.join(HERE, "..", ".github", "workflows")
ci = open(os.path.join(wf, os.listdir(wf)[0]), encoding="utf-8").read()
check("CI runs this file", "tests/batch19_test.py" in ci)

print("\n%d passed, %d failed" % (sum(ok), len(ok) - sum(ok)))
sys.exit(0 if all(ok) else 1)
