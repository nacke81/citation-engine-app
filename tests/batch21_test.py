"""Batch 21 fix tests (t_8d1865a3): job/workable.py report, no-URL backoff + cap, mail_scan --presence --headers, capsolver User-Agent.
No network, no browser, no vault, no real queue: fakes, a scrubbed copy of the real queue's row shapes, and temp files only. Run: python tests/batch21_test.py (CI).
Lesson applied (test-the-rule-on-real-row-shapes): tests/fixtures/workable_queue.json is the real queue's 82 rows, scrubbed; the counts below are the real ones."""
import os, sys, json, tempfile, copy, io, subprocess, urllib.request, contextlib, re, shutil
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
import recheck as R, transitions as T, mail_scan as MS, workable as WK, walls as W, moz, count_capsolver_builds as CC
import directories as D
D._upsert_status = lambda *a, **k: None
D._status_row = lambda *a, **k: {}

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f" [{d}]" if d else ""), flush=True)
TMP = tempfile.mkdtemp()
TODAY = "2026-10-27"

# ---- 1 workable report on the real row shapes -----------------------------------------------------------------------------------------------------
FIX = os.path.join(HERE, "fixtures", "workable_queue.json")
q = json.load(open(FIX, encoding="utf-8"))
res = WK.classify(q, TODAY)
check("1 real-shape fixture has the real counts (82 rows: live 15, submitted 6, needs-human 30, rejected 27)", res["counts"] == {"created-unlisted": 2, "found": 1, "live": 15, "needs-human": 30, "pending-verify": 1, "rejected": 27, "submitted": 6}, str(res["counts"]))
wk = {i["row"]: i for i in res["workable"]}; nh = {i["row"]: i for i in res["needs_human"]}; oos = {i["row"]: i for i in res["out_of_scope"]}
check("1 every non-live, non-rejected row lands in exactly one list", len(wk) + len(nh) + len(oos) == 82 - 15 - 27 and not (set(wk) & set(nh)) and not (set(wk) & set(oos)) and not (set(nh) & set(oos)))
check("1 workable rows and their open dates (citylocalpro, cylex 10/28; bbb, businessyab, loc8nearme, chamberofcommerce, foursquare 10/29; fyple, yellowbot 10/30)",
      {k: v["opens"] for k, v in wk.items() if v["opens"] > TODAY} == {"create-citylocalpro": "2026-10-28", "create-cylex": "2026-10-28", "create-bbb": "2026-10-29", "create-businessyab": "2026-10-29",
                                                                    "create-chamberofcommerce": "2026-10-29", "create-foursquare": "2026-10-29", "create-loc8nearme": "2026-10-29",
                                                                    "create-fyple": "2026-10-30", "create-yellowbot": "2026-10-30"}, str({k: v["opens"] for k, v in wk.items()}))
check("1 discoverourtown (no recheck_due) is workable NOW and says it has no date yet", wk["create-discoverourtown"]["opens"] == TODAY and "NO recheck_due" in wk["create-discoverourtown"]["why"])
check("1 cylex: walls.gate says a hard-block try already ran today, so it opens tomorrow", "hard-block" in wk["create-cylex"]["why"] and wk["create-cylex"]["opens"] == "2026-10-28")
check("1 the cylex date follows walls.gate (a try yesterday would open it today)", WK.classify(q, "2026-10-28")["workable"][0]["opens"] <= "2026-10-28")
PHONE = {"create-com-yellowpages", "create-data-axle", "create-ibegin", "fix-dexknows", "fix-yellowpages"}
check("1 phone-call rows need Mike/client", all(r in nh and "phone-call" in nh[r]["why"] for r in PHONE))
check("1 sms, id-check (dnb, nextdoor) and client-email (showmelocal) rows need Mike/client", "SMS" in nh["create-ezlocal"]["why"] and "ID check" in nh["create-dnb"]["why"] and "ID check" in nh["create-nextdoor"]["why"] and "client's own address" in nh["create-showmelocal"]["why"])
check("1 paid-tier rows need Mike (ailoq, uscity, sbdpro ...) and the Cloudflare click row (enrollbusiness) needs a person",
      all("paid tier" in nh[r]["why"] for r in ("create-ailoq", "create-uscity", "create-sbdpro", "create-uscolist", "create-8coupons", "create-botw")) and "Cloudflare" in nh["create-enrollbusiness"]["why"])
check("1 the batch 21 out-of-scope rows are listed apart, from one module constant",
      set(oos) == {"create-2findlocal", "create-americasbestcompanies", "create-tupalo", "create-yelp", "fix-bing", "fix-mapquest", "fix-superpages"} and len(WK.OUT_OF_SCOPE) == 18 and "tupalo.com" in WK.OUT_OF_SCOPE)
check("1 a human-blocked row beats the out-of-scope list (botw is paid-tier: needs Mike)", "create-botw" in nh and "create-botw" not in oos)
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = WK.main(["--queue", FIX, "--today", TODAY])
txt = buf.getvalue()
check("1 CLI exits 0 and prints the table header, the 3 sections and a footer", rc == 0 and "row" in txt and "opens on" in txt and "NEEDS MIKE / CLIENT (23)" in txt and "OUT OF SCOPE THIS BATCH (7)" in txt and "AN AGENT CAN MOVE (10)" in txt and "open now: 1; open later: 9" in txt, txt[-120:])
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = WK.main(["--queue", FIX, "--today", TODAY, "--json"])
js = json.loads(buf.getvalue())
check("1 --json is valid and carries the same lists", rc == 0 and js["today"] == TODAY and len(js["workable"]) == 10 and len(js["needs_human"]) == 23 and len(js["out_of_scope"]) == 7)
before = open(FIX, "rb").read(); WK.classify(q, TODAY)
check("1 read-only: the queue file is untouched", open(FIX, "rb").read() == before)
STOP = copy.deepcopy(q)
cy = next(r for r in STOP["create_queue"]["rows"] if r["id"] == "create-cylex")
cy["history"] += [{"wall": "hard-block", "try": 3, "at": "2026-10-20", "note": "x"}, {"wall": "hard-block", "try": 3, "at": "2026-10-21", "note": "x"}]
check("1 a STOPPED hard-block row moves to needs Mike/client", "create-cylex" in {i["row"] for i in WK.classify(STOP, TODAY)["needs_human"]})
src = open(os.path.join(JOB, "workable.py"), encoding="utf-8").read()
check("1 workable.py never writes (no record_transition / open(..., 'w'))", "record_transition" not in src and not re.search(r"open\([^)]*['\"]w", src))

# ---- 2 no-URL backoff: every row gets a date, old -> new printed, cap 3 -> needs-human ---------------------------------------------------------------
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
QP = os.path.join(TMP, "queue.json")
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
def plain_404(u): return R.Page(404, u, "", html="")
def run(rows, today=TODAY, **kw):
    write_q(rows)
    r = R.recheck(json.load(open(QP)), IDENT, plain=plain_404, chrome=None, record=real_record, db=FakeDB(), queue_path=QP, today=today, use_chrome=False, **kw)
    return r, json.load(open(QP))["create_rows"]
NOURL = [row("create-dnb", "dnb.com", "found", evidence_url="https://my.dnb.com/lookup/duns-found?flow=lookup&type=self"),
         row("create-discoverourtown", "discoverourtown.com", evidence_url="https://www.discoverourtown.com/add/thankyou.php"),
         row("create-loc8nearme", "loc8nearme.com", recheck_due="2026-10-27"), row("create-bbb", "bbb.org")]
r, rows = run(NOURL, backoff_only=True)
by = {x["id"]: x for x in rows}
check("2 --backoff-only writes recheck_due for dnb AND discoverourtown (both had none): today + 2 days", by["create-dnb"].get("recheck_due") == "2026-10-29" and by["create-discoverourtown"].get("recheck_due") == "2026-10-29", str({k: v.get("recheck_due") for k, v in by.items()}))
check("2 every no-URL row it read has a date written", all(x.get("recheck_due") == "2026-10-29" for x in rows) and len(r) == len(NOURL))
check("2 the history entry carries a structured backoff marker (not prose)", all(x["history"][-1].get("backoff") == "no-permalink" and x["history"][-1].get("recheck_due") == "2026-10-29" for x in rows))
rep = R.format_report(r)
check("2 the report prints `recheck_due old -> new` per row, and `(written)` after reading the file back", "recheck_due none -> 2026-10-29 (written)" in rep and "recheck_due 2026-10-27 -> 2026-10-29 (written)" in rep and rep.count("(written)") == 4, rep)
check("2 a no-search Directory says so in the note", "no public search" in by["create-dnb"]["history"][-1]["note"] and "no public search" in by["create-discoverourtown"]["history"][-1]["note"])
check("2 state is unchanged (never live, never a transition)", all(x["state"] == o["state"] for x, o in zip(rows, NOURL)))
r, rows2 = run(NOURL, backoff_only=False)
check("2 a plain dry run (no --backoff-only, no --write) still writes nothing", all(not x.get("recheck_due") or x["id"] == "create-loc8nearme" for x in rows2) and all(not x["history"] for x in rows2) and "dry run: not stored" in R.format_report(r))
# the cap: 3 backoffs, the 4th no-URL read parks the row
cur = copy.deepcopy(NOURL[:2]); days = ["2026-10-27", "2026-10-30", "2026-11-02", "2026-11-05"]
for i, day in enumerate(days):
    r, cur = run(cur, today=day, backoff_only=True)
    st = [x["state"] for x in cur]
    if i < 3: check("2 backoff %d of 3: stays waiting with a date (%s)" % (i + 1, day), st == ["found", "submitted"] and all(x.get("recheck_due") for x in cur) and T.no_url_backoffs(cur[0]) == i + 1, str(st))
check("2 after 3 backoffs the 4th no-URL read moves both rows to needs-human", [x["state"] for x in cur] == ["needs-human", "needs-human"])
last = cur[0]["history"][-1]
check("2 the parking entry has park_reason no-public-permalink and a note", last["park_reason"] == "no-public-permalink" and last["to"] == "needs-human" and "no public permalink" in last["note"] and "recheck_due" not in cur[0])
check("2 the report says parked, not a date", "parked: found -> needs-human, reason no-public-permalink" in R.format_report(r))
r, again = run(cur, today="2026-11-08", backoff_only=True)
check("2 a parked row is not read again by a batch (needs-human is not a waiting state)", r == [] and again[0]["state"] == "needs-human")
# the cap on --write too
cur = [row("create-dnb", "dnb.com", "found", history=[{"at": "2026-10-2%d" % i, "from": "found", "to": "found", "backoff": "no-permalink", "recheck_due": "2026-10-2%d" % (i + 2), "note": "n"} for i in range(3)])]
r, cur = run(cur, write=True)
check("2 the cap holds on --write as well", cur[0]["state"] == "needs-human" and cur[0]["history"][-1]["park_reason"] == "no-public-permalink")
cur = [row("create-x", "dnb.com", "found", history=[{"at": "2026-10-20", "from": "found", "to": "found", "note": "prose only: no-permalink no-permalink no-permalink"}] * 4)]
r, cur = run(cur, backoff_only=True)
check("2 prose notes are not counters: four prose notes do not park the row", cur[0]["state"] == "found" and cur[0]["recheck_due"] == "2026-10-29")
# a URL found resets nothing wrongly: a row with a listing_url never takes the no-URL path
r, cur = run([row("create-bbb2", "tupalo.com", listing_url="https://tupalo.example/x")], backoff_only=True)
check("2 a row WITH a listing_url is not counted as a no-URL backoff", T.no_url_backoffs(cur[0]) == 0)
# transitions edges
p, rid = os.path.join(TMP, "t.json"), "create-dnb"
def tq(state, hist=None): json.dump({"canonical": CANON, "fix_queue": [], "create_rows": [row(rid, "dnb.com", state, history=hist or [])]}, open(p, "w"))
def rec(new, **kw):
    try: return T.record_transition("SCC", rid, new, None, kw.pop("note", "a note"), queue_path=p, today=TODAY, portal=FakePortal(), **kw)
    except T.TransitionRefused as e: return str(e)
for st in ("found", "submitted", "pending-verify", "created-unlisted"):
    tq(st); o = rec("needs-human", park_reason="no-public-permalink")
    check("2 transitions: %s -> needs-human with park_reason no-public-permalink is accepted" % st, isinstance(o, dict) and json.load(open(p))["create_rows"][0]["history"][-1]["park_reason"] == "no-public-permalink")
tq("submitted"); b = open(p, "rb").read()
check("2 transitions: an unknown park_reason is refused, nothing written", isinstance(rec("needs-human", park_reason="because"), str) and open(p, "rb").read() == b)
check("2 transitions: park_reason on a non needs-human target is refused", isinstance(rec("live", park_reason="no-public-permalink"), str) and open(p, "rb").read() == b)
check("2 transitions: park_reason needs a note", isinstance(rec("needs-human", park_reason="no-public-permalink", note=""), str) and open(p, "rb").read() == b)
tq("needs-human"); b = open(p, "rb").read()
check("2 transitions: park_reason on a row already needs-human is refused", isinstance(rec("needs-human", park_reason="no-public-permalink"), str) and open(p, "rb").read() == b)
tq("submitted"); b = open(p, "rb").read()
check("2 transitions: backoff marker needs a same-state move and a recheck_due", isinstance(rec("needs-human", backoff="no-permalink", recheck_due="2026-10-29"), str) and isinstance(rec("submitted", backoff="no-permalink"), str) and isinstance(rec("submitted", backoff="other", recheck_due="2026-10-29"), str) and open(p, "rb").read() == b)
o = rec("submitted", backoff="no-permalink", recheck_due="2026-10-29")
check("2 transitions: a same-state backoff with a date is accepted and counted", isinstance(o, dict) and T.no_url_backoffs(json.load(open(p))["create_rows"][0]) == 1)
tq("live"); b = open(p, "rb").read()
check("2 transitions: a live row can still not be parked by a cap move into needs-human with a prose-free reason only (any -> needs-human unchanged)", isinstance(rec("needs-human", park_reason="no-public-permalink"), dict))
check("2 the CLI has --park-reason", '"--park-reason"' in open(os.path.join(JOB, "transitions.py"), encoding="utf-8").read())

# ---- 3 mail_scan --presence --headers --------------------------------------------------------------------------------------------------------------
def raw(frm, to, subj, body, delivered=None, date="Mon, 26 Oct 2026 10:00:00 +0000"):
    h = "From: %s\r\nTo: %s\r\nSubject: %s\r\nDate: %s\r\n" % (frm, to, subj, date)
    if delivered: h += "Delivered-To: %s\r\n" % delivered
    return (h + "Content-Type: text/plain\r\n\r\n" + body).encode()
SECRET_BODY = "Your code is 482913. Reset: https://www.bbb.org/account/reset?token=SECRETTOKEN99"
BOXES = {"INBOX": {1: raw("BBB <no-reply@bbb.org>", "listings@example.org", "Welcome to BBB", "hello"),
                   2: raw("Someone <a@other.com>", "listings@example.org", "Lunch", "x")},
         "Junk": {7: raw("BBB <noreply@mail.bbb.org>", "Senior Care <info@example.org>", "Reset your BBB password, code 482913 https://www.bbb.org/r?t=1", SECRET_BODY, delivered="catchall@example.org", date="Tue, 27 Oct 2026 17:45:00 +0000")}}
class FakeImap:
    calls = []
    def __init__(s, host, port): FakeImap.calls = []; s.sel = None
    def login(s, u, p): FakeImap.calls.append(("login",)); return "OK", [b""]
    def list(s): FakeImap.calls.append(("list",)); return "OK", [b'(\\HasNoChildren) "/" INBOX', b'(\\HasNoChildren \\Junk) "/" "Junk"', b'(\\HasNoChildren \\Sent) "/" "Sent"']
    def select(s, box, readonly=False):
        FakeImap.calls.append(("select", box, readonly)); name = box.strip('"')
        if name not in BOXES: return "NO", []
        s.sel = name; return "OK", [b"1"]
    def uid(s, cmd, *a):
        FakeImap.calls.append(("uid", cmd, a))
        if cmd == "SEARCH": return "OK", [b" ".join(str(u).encode() for u in BOXES[s.sel])]
        if cmd == "FETCH": return "OK", [(b"1 (BODY[] {1}", BOXES[s.sel][int(a[0])]), b")"]
        raise AssertionError("write command %s" % cmd)
    def store(s, *a, **k): raise AssertionError("STORE attempted")
    def copy(s, *a, **k): raise AssertionError("COPY attempted")
    def expunge(s, *a, **k): raise AssertionError("EXPUNGE attempted")
    def logout(s): pass
ENV = {"LISTINGS_IMAP_HOST": "h", "LISTINGS_IMAP_PORT": "993", "LISTINGS_IMAP_USER": "u", "LISTINGS_IMAP_PASSWORD": "p"}
msgs = MS.read_messages(env=ENV, imap_cls=FakeImap, days=30, folders="all")
j = next(m for m in msgs if m["folder"] == "Junk")
check("3 messages carry the To addresses (To + Delivered-To), lowercased", j["to"] == ["info@example.org", "catchall@example.org"], str(j["to"]))
check("3 reading stays read-only (EXAMINE, PEEK, no STORE/COPY/EXPUNGE)", all(c[2] is True for c in FakeImap.calls if c[0] == "select") and all(c[1] in ("SEARCH", "FETCH") for c in FakeImap.calls if c[0] == "uid"))
out = []
rc = MS.headers_main(["bbb.org"], 30, messages=msgs, out=out.append)
txt = "\n".join(out)
check("3 prints folder | date | From domain | To | Subject for each bbb mail, newest first (Junk first)", rc == 0 and out[0] == "bbb.org | 2 matching mail(s)" and out[1].startswith("  Junk | 2026-10-27T17:45 | from @mail.bbb.org | to info@example.org, catchall@example.org |") and out[2].startswith("  INBOX | 2026-10-26T10:00 | from @bbb.org | to listings@example.org | Welcome to BBB"), txt)
check("3 the other sender's mail is not listed", "Lunch" not in txt and "other.com" not in txt)
check("3 never the body, a code or a link (code in the subject and body, token in the body)", "482913" not in txt and "SECRETTOKEN99" not in txt and "http" not in txt and "token" not in txt.lower(), txt)
check("3 the subject keeps its words ('Reset your BBB password') so the reset mail is recognisable", "Reset your BBB password, code [x] [x]" in txt, txt)
out = []; MS.headers_main(["loc8nearme.com"], 30, messages=msgs, out=out.append)
check("3 a Directory with no mail prints 0 matching", out == ["loc8nearme.com | 0 matching mail(s)"])
buf, err = io.StringIO(), io.StringIO()
orig = MS.read_messages
MS.read_messages = lambda **k: (_ for _ in ()).throw(MS.imaplib.IMAP4.error("down")) if False else MS.read_messages_real(**dict(k, env=ENV, imap_cls=FakeImap))
MS.read_messages_real = orig
with contextlib.redirect_stdout(buf): rc = MS.main(["--presence", "--headers", "--directory", "bbb.org"])
MS.read_messages = orig
check("3 CLI `--presence --headers --directory bbb.org` reads every folder by default (Junk is listed) and exits 0", rc == 0 and "Junk |" in buf.getvalue() and "482913" not in buf.getvalue(), buf.getvalue())
try:
    with contextlib.redirect_stderr(io.StringIO()): MS.main(["--headers"]); bad = False
except SystemExit: bad = True
check("3 --headers without --presence is refused", bad)
buf = io.StringIO()
MS.read_messages = lambda **k: orig(env=ENV, imap_cls=FakeImap, **k)
with contextlib.redirect_stdout(buf): MS.main(["--presence", "--directory", "bbb.org"])
MS.read_messages = orig
check("3 plain --presence is unchanged (INBOX only, yes/no line, no header lines)", "folders: INBOX" in buf.getvalue() and " from @" not in buf.getvalue(), buf.getvalue())
check("3 scrub_subject masks 4+ digit runs and URLs", MS.scrub_subject("Code 123456 at https://x.example/a?b=1 ok 12") == "Code [x] at [x] ok 12")

# ---- 4 capsolver User-Agent ------------------------------------------------------------------------------------------------------------------------
seen = {}
class Resp:
    def __enter__(s): return s
    def __exit__(s, *a): return False
    def read(s): return json.dumps({"errorId": 0, "balance": 3.5}).encode()
def opener(req, timeout=None): seen["req"] = req; return Resp()
bal = CC.live_balance("KEY-NOT-PRINTED", opener=opener)
check("4 getBalance sends the same User-Agent constant as moz.py", seen["req"].get_header("User-agent") == moz.USER_AGENT and bal == 3.5, str(seen["req"].headers))
check("4 count_capsolver_builds imports the constant (no second copy of the string)", CC.USER_AGENT is moz.USER_AGENT and "citation-engine/1.0" not in open(os.path.join(JOB, "count_capsolver_builds.py"), encoding="utf-8").read())
check("4 the key still travels in the body only", b"KEY-NOT-PRINTED" in seen["req"].data and "KEY-NOT-PRINTED" not in str(seen["req"].headers))

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
