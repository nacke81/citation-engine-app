"""Dry run must predict the 3/3 no-URL park (t_bee96b30). Run: python tests/recheck_dryrun_park_test.py (CI).
No network, no browser, no live Directory read: a 404 plain fetcher, in-memory fakes, temp files. Row shapes follow tests/batch21_test.py."""
import os, sys, json, tempfile, copy, subprocess, urllib.request, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
os.environ["CE_ACTIVITIES_WRITE"] = "0"
os.environ["CE_DIRECTORIES_WRITE"] = "0"
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
import recheck as R, transitions as T

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f" [{d}]" if d else ""), flush=True)

TMP = tempfile.mkdtemp()
QP = os.path.join(TMP, "queue.json")
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
TODAY = "2026-11-12"

def backoffs(n):
    return [{"at": "2026-10-%02d" % (20 + i), "from": "submitted", "to": "submitted", "backoff": "no-permalink", "recheck_due": "2026-10-%02d" % (22 + i), "note": "n"} for i in range(n)]
def row(n, **kw): return dict({"id": "create-usbizs", "directory": "usbizs.com", "state": "submitted", "mike_approval": None, "history": backoffs(n)}, **kw)
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
def run(r, **kw):
    json.dump({"canonical": CANON, "fix_queue": [], "create_rows": [r]}, open(QP, "w"))
    before = open(QP, "rb").read()
    res = R.recheck(json.load(open(QP)), IDENT, plain=plain_404, chrome=None, record=real_record, db=FakeDB(), queue_path=QP, today=kw.pop("today", TODAY), use_chrome=False, only={"create-usbizs"}, **kw)
    return res, json.load(open(QP))["create_rows"][0], open(QP, "rb").read() == before

# 3 prior backoffs, due: the dry run predicts the park and writes nothing
dry, cur, same = run(row(3, recheck_due="2026-11-12"))
rep = R.format_report(dry)
check("1 dry run, 3 prior backoffs: after = needs-human, would_park no-public-permalink, recheck_due None", dry[0]["after"] == "needs-human" and dry[0]["would_park"] == "no-public-permalink" and dry[0]["recheck_due"] is None, str(dry[0]))
check("1 the report says `-> needs-human (would park: no-public-permalink)` and `recheck_due 2026-11-12 -> none`", "-> needs-human (would park: no-public-permalink)" in rep and "recheck_due 2026-11-12 -> none" in rep, rep)
check("1 the dry run wrote nothing (queue file byte-identical, state still submitted)", same and cur["state"] == "submitted" and len(cur["history"]) == 3)
bo, parked, _ = run(row(3, recheck_due="2026-11-12"), backoff_only=True)
check("1 prediction matches what --backoff-only then writes (needs-human, no-public-permalink, no recheck_due)", parked["state"] == dry[0]["after"] == bo[0]["after"] and parked["history"][-1]["park_reason"] == dry[0]["would_park"] and "recheck_due" not in parked)
d_nodate, _, same2 = run(row(3))   # no recheck_due at all counts as due
check("1 a row with no recheck_due and 3 backoffs also predicts the park", d_nodate[0]["after"] == "needs-human" and same2)

# 2 prior backoffs: a normal backoff, no park predicted, matches --backoff-only
dry, cur, same = run(row(2, recheck_due="2026-11-12"))
rep = R.format_report(dry)
bo, wrote, _ = run(row(2, recheck_due="2026-11-12"), backoff_only=True)
check("2 dry run, 2 prior backoffs: stays submitted, no park predicted, new date today+2", dry[0]["after"] == "submitted" and "would_park" not in dry[0] and dry[0]["recheck_due"] == "2026-11-14" and "would park" not in rep and "recheck_due 2026-11-12 -> 2026-11-14" in rep, rep)
check("2 prediction matches what --backoff-only then writes (submitted, recheck_due 2026-11-14, 3rd backoff counted)", wrote["state"] == dry[0]["after"] and wrote["recheck_due"] == dry[0]["recheck_due"] and T.no_url_backoffs(wrote) == 3)
check("2 the dry run wrote nothing", same and cur["state"] == "submitted" and len(cur["history"]) == 2)

# not-due: read before its due date adds no backoff and predicts no park, with 3 prior backoffs too
for n in (2, 3):
    dry, cur, same = run(row(n, recheck_due="2026-11-14"))
    bo, wrote, _ = run(row(n, recheck_due="2026-11-14"), backoff_only=True)
    rep = R.format_report(dry)
    check("3 not due (%d prior backoffs): dry run predicts no park, date unchanged, no backoff counted" % n, dry[0]["after"] == "submitted" and "would_park" not in dry[0] and dry[0]["recheck_due"] == "2026-11-14" and dry[0].get("not_due") and "no backoff counted" in rep and same, rep)
    check("3 not due (%d prior backoffs): --backoff-only agrees (state, date, count unchanged)" % n, wrote["state"] == dry[0]["after"] and wrote["recheck_due"] == "2026-11-14" and T.no_url_backoffs(wrote) == n)

# a row that is not in a waiting state is never predicted to park
d_live, _, _ = run(row(3, state="needs-human", recheck_due="2026-11-12"), any_state=True)
check("4 a needs-human row is not predicted to park again", all("would_park" not in r for r in d_live))

# t_baa09af1: dry run and write take ONE decision. Same after / recheck_due / parked for each shape; an already-parked row is never re-parked.
CALLS = []
def spy(*a, **k): CALLS.append(a); return real_record(*a, **k)
def run_direct(r, day):
    json.dump({"canonical": CANON, "fix_queue": [], "create_rows": [r]}, open(QP, "w"))
    res = {"row": r["id"], "before": r["state"], "after": r["state"], "fields": [], "note": None, "error": None, "verdict": "not-public"}
    R._backoff(res, copy.deepcopy(r), True, spy, QP, day, no_url=True)
    return [res], json.load(open(QP))["create_rows"][0], None
def agree(label, r, day, **kw):
    dry, dcur, dsame = run(r, today=day, **kw)
    wr, wcur, _ = run_direct(r, day) if kw.get("any_state") else run(r, today=day, backoff_only=True, **kw)   # candidates() never hands a needs-human row to a write run; call _backoff itself, as Nate's repro did
    d, w = dry[0], wr[0]
    check("6 %s: dry run and write agree on after / recheck_due / parked-or-would_park" % label,
          d["after"] == w["after"] and d["recheck_due"] == w["recheck_due"] and (d.get("would_park") or d.get("parked")) == (w.get("parked") or w.get("would_park")), "dry=%s write=%s" % ({k: d.get(k) for k in ("after", "recheck_due", "would_park", "already_parked")}, {k: w.get(k) for k in ("after", "recheck_due", "parked", "already_parked")}))
    check("6 %s: the dry run wrote nothing" % label, dsame)
    return d, w, dcur, wcur

d, w, _, wcur = agree("fresh row at 3 backoffs", row(3, recheck_due="2026-11-14"), "2026-11-14")
check("6 fresh row at 3 backoffs: both park", d["after"] == w["after"] == "needs-human" and w.get("parked") == "no-public-permalink" and d["recheck_due"] is None and wcur["state"] == "needs-human" and len(wcur["history"]) == 4)

parked_row = row(3, state="needs-human", recheck_due="2026-11-14", history=backoffs(3) + [{"at": "2026-11-10", "from": "submitted", "to": "needs-human", "park_reason": "no-public-permalink", "note": "parked"}])
d, w, dcur, wcur = agree("needs-human row at 3 backoffs (Nate repro, create-usbizs, 2026-11-14)", parked_row, "2026-11-14", any_state=True)
check("6 needs-human row: both report already parked, after needs-human, no park, no new date", d["after"] == w["after"] == "needs-human" and d.get("already_parked") and w.get("already_parked") and "parked" not in w and "would_park" not in d, str((d, w)))
check("6 needs-human row: the write adds 0 history entries and changes nothing", len(wcur["history"]) == len(parked_row["history"]) and wcur["state"] == "needs-human" and wcur.get("recheck_due") == "2026-11-14")
check("6 needs-human row: the report says already parked", "already parked" in R.format_report(run(parked_row, today="2026-11-14", any_state=True)[0]))
check("6 needs-human row: record() is never called by the write", CALLS == [])

d, w, _, wcur = agree("not-due row at 3 backoffs", row(3, recheck_due="2026-11-16"), "2026-11-14")
check("6 not-due row: both keep the date, no park, no backoff", d["after"] == w["after"] == "submitted" and d["recheck_due"] == w["recheck_due"] == "2026-11-16" and d.get("not_due") and w.get("not_due") and T.no_url_backoffs(wcur) == 3)

# docs: the --backoff-only help and the bw comment no longer say "no transition"
out = subprocess.run([sys.executable, os.path.join(JOB, "recheck.py"), "--help"], capture_output=True, text=True).stdout
flat = " ".join(out.split())
check("5 --backoff-only help says it may park after 3 no-URL backoffs", "3 no-URL backoffs" in flat and "parked" in flat and "no transition" not in flat, flat[flat.find("--backoff-only"):][:400])
src = open(os.path.join(JOB, "recheck.py"), encoding="utf-8").read()
bw_line = next(l for l in src.splitlines() if l.strip().startswith("bw = write or backoff_only"))
check("5 the bw comment says it may park after 3 no-URL backoffs", "PARK" in bw_line and "3 no-URL backoffs" in bw_line and "no transition" not in bw_line, bw_line)

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
