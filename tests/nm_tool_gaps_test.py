"""NM tool gaps (t_5b3b4a3f). Run: python tests/nm_tool_gaps_test.py (CI). Offline: placeholder identities, fake relay file, fake pages.
  G1 mail_scan --mailbox nm-relay --presence / --headers / --reset-link see n49 + techbehemoths mail (unlisted directories, matched by From domain / link host)
  G2 SCC unchanged: the default mailbox still returns nothing for those directories; the nm-relay flag does not leak into the next default run
  G3 recheck on an NM queue uses the NM identity (R1): passes its phone gate, refuses an SCC-phone canonical, refuses a mixed queue, records as NM
  G4 recheck on an SCC queue is unchanged (SCC identity, record as SCC)
"""
import contextlib, io, json, os, sys, tempfile, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "nm_r1_identity.json")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import mail_scan as M
import recheck as R
import buildqueue as Q

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

IDENT = json.load(open(os.path.join(HERE, "nm_r1_identity.json"), encoding="utf-8"))
RECENT = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
N49 = {"id": "a1", "from": "N49 <noreply@n49.com>", "subject": "N49 Password Reset", "received": RECENT,
       "links": ["https://www.n49.com/reset-password?token=abc123"], "codes": []}
TB = {"id": "b1", "from": "TechBehemoths <noreply@techbehemoths.com>", "subject": "Reset Password Notification", "received": RECENT,
      "links": ["https://techbehemoths.com/password/reset/zzz"], "codes": ["123456"]}
OTHER = {"id": "c1", "from": "Someone <hi@elsewhere.example>", "subject": "Hello", "received": RECENT, "links": [], "codes": []}

with tempfile.TemporaryDirectory() as td:
    rel = os.path.join(td, "relay.jsonl")
    open(rel, "w", encoding="utf-8").write("\n".join(json.dumps(x) for x in (N49, TB, OTHER)) + "\n")
    os.environ["NM_RELAY_FILE"] = rel

    def run(args):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = M.main(args)
        return rc, buf.getvalue()

    rc, txt = run(["--mailbox", "nm-relay", "--presence", "--directory", "n49.com", "--directory", "techbehemoths.com", "--directory", "absent.example", "--days", "5"])
    lines = txt.splitlines()
    check("G1 presence: n49.com sees its relay mail, reset + link present", rc == 0 and "mails from the Directory: 1" in lines[0] and "reset mail: yes" in lines[0] and "link present: yes" in lines[0], lines[0])
    check("G1 presence: techbehemoths.com sees its mail, code present", "mails from the Directory: 1" in lines[1] and "code present: yes" in lines[1], lines[1])
    check("G1 presence: a directory with no mail says 0 / no", "mails from the Directory: 0" in lines[2] and "reset mail: no" in lines[2], lines[2])
    check("G1 presence never prints the code or the link", "123456" not in txt and "abc123" not in txt)
    rc, txt = run(["--mailbox", "nm-relay", "--presence", "--headers", "--directory", "n49.com", "--days", "5"])
    check("G1 --headers lists the n49 mail", rc == 0 and "n49.com" in txt and "N49 Password Reset" in txt, txt[:120])
    rc, txt = run(["--mailbox", "nm-relay", "--reset-link", "--directory", "n49.com", "--days", "5"])
    check("G1 --reset-link finds the n49 reset", rc == 0 and "n49.com/reset-password" in txt, txt[:120])

    # G2: SCC (listings) behaviour is unchanged
    msgs = M.read_relay_messages(days=5)
    check("G2 SCC mode: _domain_of(n49.com) is None (flag off)", M._domain_of("n49.com") is None)
    check("G2 SCC mode: presence over the same messages finds nothing for n49.com", M.presence("n49.com", msgs)[0] == 0)
    check("G2 SCC mode: listed SCC directory unchanged", M._domain_of("bbb.org") == "bbb.org" and M._domain_of("cylex.us") == "cylex.us.com")
    check("G2 the flag does not outlive an nm-relay run", M._OPEN_DOMAINS is False)
    fake = lambda **k: msgs
    M.read_messages = fake
    rc, txt = run(["--presence", "--directory", "n49.com", "--days", "5"])
    check("G2 default-mailbox run finds nothing for n49.com", rc == 0 and "mails from the Directory: 0" in txt, txt[:100])
    del os.environ["NM_RELAY_FILE"]

# ---- recheck
TMP = tempfile.mkdtemp()
def row(rid, directory, state, **kw):
    r = {"id": rid, "directory": directory, "state": state, "mike_approval": None, "evidence_url": None, "history": []}
    r.update(kw); return r
def queue(canon, rows):
    p = os.path.join(TMP, "q.json"); json.dump({"canonical": canon, "fix_queue": rows}, open(p, "w")); return p
NM_CANON = {"name": "Birch Media", "address": "200 Sample Ave, Testville TN 39999", "phone": "(615) 555-0111"}
SCC_CANON = {"name": IDENT["BIZ"]["SCC"]["name"], "address": "100 Example Drive, Exampleton KY 40000", "phone": IDENT["BIZ"]["SCC"]["phones"][0]}
DAY = "2026-11-14"
def go(canon, rows, **kw):
    calls = []
    def record(*a, **k): calls.append(a); return {}
    p = queue(canon, rows); q = json.load(open(p))
    res = R.recheck(q, IDENT, plain=lambda u: R.Page(404, u, "", err="HTTP 404"), chrome=None, record=record, queue_path=p, today=DAY, write=True, use_chrome=False, **kw)
    return res, calls

nm_rows = [row("nm-n49", "n49.com", "submitted")]
try: res, calls = go(NM_CANON, nm_rows); err = None
except Exception as e: res, calls, err = [], [], e
check("G3 NM queue with the NM (R1) phone is accepted (no identity refusal)", err is None and [r["row"] for r in res] == ["nm-n49"], repr(err))
check("G3 a transition recorded for an NM row is recorded as NM, never SCC", calls and all(c[0] == "NM" for c in calls), str([c[:2] for c in calls]))
try: go(SCC_CANON, nm_rows); refused = False
except Q.QueueError: refused = True
check("G3 NM queue carrying the SCC phone is still refused", refused)
try: go(NM_CANON, nm_rows + [row("e1", "a.example", "submitted")]); refused = False
except Q.QueueError as e: refused = "mixes" in str(e)
check("G3 a mixed NM/SCC queue is refused", refused)
try: go({**NM_CANON, "phone": "(615) 555-9999"}, nm_rows); refused = False
except Q.QueueError: refused = True
check("G3 NM queue with a wrong phone is refused", refused)
check("G3 queue_biz: NM / SCC / empty", R.queue_biz({"fix_queue": nm_rows}) == "NM" and R.queue_biz({"fix_queue": [row("e1", "a.example", "queued")]}) == "SCC" and R.queue_biz({"fix_queue": []}) == "SCC")

scc_rows = [row("e1", "a.example", "submitted")]
try: res, calls = go(SCC_CANON, scc_rows); err = None
except Exception as e: res, calls, err = [], [], e
check("G4 SCC queue with the SCC phone is accepted", err is None and [r["row"] for r in res] == ["e1"], repr(err))
check("G4 SCC rows still record as SCC", calls and all(c[0] == "SCC" for c in calls), str([c[:2] for c in calls]))
try: go(NM_CANON, scc_rows); refused = False
except Q.QueueError: refused = True
check("G4 SCC queue carrying the NM phone is refused", refused)

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
