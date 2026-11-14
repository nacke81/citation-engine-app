"""Terminal `skipped` state for NM rows + --clear-recheck (kanban t_5ddb67a4). Run: python tests/nm_skipped_test.py (CI). No network, no browser, no portal, no live queue.

  S1 skipped from needs-human / pending-verify / queued: ok, state skipped, recheck_due gone, history entry with note
  S2 skipped refused: no note, from live/submitted/rejected, from skipped, with --recheck-due; the file is byte-identical after each refusal
  S3 skipped is NM only: the SCC writer (transitions.py) refuses --to skipped; an SCC row in state skipped fails parse_rows
  S4 readers: workable.classify, recheck.candidates (also --any-state --row), mail_scan.select_rows (historical), buildqueue.submit_row (live),
     fit.queued_in_order skip a skipped row; workable counts it as its own `skipped` count; a mutated reader (filter off) WOULD pick it (the test can fail)
  S5 dateless park: --clear-recheck on a same-state needs-human move drops recheck_due; without it the old date stays; a dated park still sets it; both together refused; same on transitions.py
"""
import contextlib, copy, hashlib, io, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
os.environ["CE_DIRECTORIES_WRITE"] = "0"
import buildqueue as Q
import nm_transitions as NM
import transitions as T
import workable as W
import recheck as RC
import mail_scan as MS
import fit as F

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (("  [%s]" % d) if d else ""), flush=True)
def refused(fn, exc=(NM.NMTransitionRefused, T.TransitionRefused, Q.QueueError)):
    try: fn()
    except exc as e: return str(e)
    return None

TMP = tempfile.mkdtemp()
DAY = "2026-11-14"
def row(rid, directory, state, **kw):
    r = {"id": rid, "directory": directory, "kind": "fix", "state": state, "cost": "free", "mike_approval": None, "history": [], "vaultwarden_item": "x"}
    r.update(kw); return r
def write_q(rows, name="nm-fix-queue.json"):
    d = tempfile.mkdtemp(dir=TMP); p = os.path.join(d, name)
    json.dump({"business": "NM fixture", "fix_queue": rows}, open(p, "w")); return p
def md5(p): return hashlib.md5(open(p, "rb").read()).hexdigest()
def load(p): return json.load(open(p))["fix_queue"]
def by(p, rid): return [r for r in load(p) if r["id"] == rid][0]
def rec(p, rid, to, note="ruling", **kw): return NM.record_transition("NM", rid, to, None, note, queue_path=p, today=DAY, **kw)

# S1
for st in ("needs-human", "pending-verify", "queued"):
    p = write_q([row("nm-fix-a", "a.example", st, recheck_due="2026-11-18")])
    r = rec(p, "nm-fix-a", "skipped", "Nate ruling: no city option, low value")
    row_ = by(p, "nm-fix-a")
    check("S1 %s -> skipped ok" % st, r["to"] == "skipped" and row_["state"] == "skipped")
    check("S1 %s -> skipped clears recheck_due" % st, "recheck_due" not in row_ or row_["recheck_due"] is None)
    check("S1 %s history entry has the note" % st, row_["history"][-1]["note"].startswith("Nate ruling") and row_["history"][-1]["to"] == "skipped")
    check("S1 %s skipped file still parses" % st, bool(Q.load_all_rows(p)))

# S2
p = write_q([row("nm-fix-n", "n.example", "needs-human", recheck_due="2026-11-18"), row("nm-fix-l", "l.example", "live"), row("nm-fix-s", "s.example", "submitted"),
             row("nm-fix-r", "r.example", "rejected"), row("nm-fix-k", "k.example", "skipped")])
h = md5(p)
check("S2 no note refused", refused(lambda: rec(p, "nm-fix-n", "skipped", "")) is not None)
check("S2 blank note refused", refused(lambda: rec(p, "nm-fix-n", "skipped", "   ")) is not None)
for rid in ("nm-fix-l", "nm-fix-s", "nm-fix-r", "nm-fix-k"):
    check("S2 %s -> skipped refused" % rid, refused(lambda: rec(p, rid, "skipped")) is not None)
check("S2 skipped with --recheck-due refused", refused(lambda: rec(p, "nm-fix-n", "skipped", recheck_due="2026-12-01")) is not None)
check("S2 skipped is terminal: skipped -> queued refused", refused(lambda: rec(p, "nm-fix-k", "queued", reason="long enough reason here")) is not None)
check("S2 skipped is terminal: skipped -> needs-human refused", refused(lambda: rec(p, "nm-fix-k", "needs-human")) is not None)
check("S2 every refusal left the file byte-identical", md5(p) == h)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = NM.main(["--row", "nm-fix-n", "--to", "skipped", "--note", "x", "--queue", p, "--dry-run"])
check("S2 CLI --to skipped --dry-run ok, writes nothing", rc == 0 and md5(p) == h)

# S3
sp = write_q([row("fix-a", "a.example", "needs-human")], name="scc-fix-create-queue.json")
check("S3 SCC writer refuses --to skipped", refused(lambda: T.check_transition("needs-human", "skipped", "n")) is not None)
check("S3 skipped not in transitions.STATES", "skipped" not in T.STATES)
check("S3 SCC row in skipped fails parse_rows", refused(lambda: Q.parse_rows({"fix_queue": [row("fix-z", "z.example", "skipped")]})) is not None)
check("S3 NM row in skipped passes parse_rows", len(Q.parse_rows({"fix_queue": [row("nm-fix-z", "z.example", "skipped")]})) == 1)

# S4 readers
SK = row("nm-fix-sk", "sk.example", "skipped", cost="free", approval={"by": "nate", "card": "t_1", "at": DAY, "row_id": "nm-fix-sk"})
live_ = row("nm-fix-lv", "lv.example", "submitted")
q = {"fix_queue": [SK, live_], "build_order": ["nm-fix-sk"]}
def picked_workable(): c = W.classify(q, DAY); return [i["row"] for k in ("workable", "needs_human", "out_of_scope") for i in c[k]], c["counts"]
rows_, counts = picked_workable()
check("S4 workable.classify lists no skipped row", "nm-fix-sk" not in rows_, rows_)
check("S4 workable.classify counts skipped as its own count", counts.get("skipped") == 1 and counts.get("submitted") == 1, counts)
def picked_recheck(**kw): return [r["id"] for r in RC.candidates(q, only=kw.pop("only", None), today=DAY, **kw)] if True else []
def cand_ids(**kw):
    out = RC.candidates(q, **kw)
    return [(r[2] if isinstance(r, tuple) else r)["id"] if not isinstance(r, tuple) else None for r in out]
try:
    out = RC.candidates(q, today=DAY)
    flat = json.dumps(out, default=str)
    check("S4 recheck.candidates skips a skipped row", "nm-fix-sk" not in flat and "nm-fix-lv" in flat, flat[:120])
    out2 = RC.candidates(q, only={"nm-fix-sk"}, today=DAY, any_state=True)
    check("S4 recheck.candidates --any-state --row still skips a skipped row", "nm-fix-sk" not in json.dumps(out2, default=str), json.dumps(out2, default=str)[:120])
except Exception as e:
    check("S4 recheck.candidates callable", False, repr(e))
sel, _ = MS.select_rows([SK, live_], {"sk.example", "lv.example"}, DAY, historical=True)
check("S4 mail_scan.select_rows historical skips a skipped row", [r["id"] for r in sel] == ["nm-fix-lv"], [r["id"] for r in sel])
sel2, _ = MS.select_rows([SK, live_], {"sk.example", "lv.example"}, DAY)
check("S4 mail_scan.select_rows normal skips a skipped row", "nm-fix-sk" not in [r["id"] for r in sel2])
check("S4 fit.queued_in_order skips a skipped row", F.queued_in_order(q) == [])
check("S4 buildqueue.submit_row refuses a skipped row (build / live)",
      refused(lambda: Q.submit_row(SK, lambda i: {"u": 1}, live=True, record=lambda *a, **k: None), (Q.SubmitRefused,)) is not None)
# readers checked and why they need no change: proof.py + lookup.py read WAITING states only; directories.queue_rows_to_status / weekly_metrics are SCC-only;
# buildrows reads the existing-Directory set (a skipped row correctly still blocks a duplicate row); sitegate reads listing states only.
# mutation: filter off (SKIPPED renamed) -> each reader WOULD pick the row, so the checks above can fail.
real = Q.SKIPPED
Q.SKIPPED = "__off__"
try:
    r2, _c = picked_workable()
    check("S4 MUTATION workable filter off -> row listed", "nm-fix-sk" in r2)
    check("S4 MUTATION recheck filter off -> any-state row picked", "nm-fix-sk" in json.dumps(RC.candidates(q, only={"nm-fix-sk"}, today=DAY, any_state=True), default=str))
    s3, _ = MS.select_rows([SK, live_], {"sk.example", "lv.example"}, DAY, historical=True)
    check("S4 MUTATION mail_scan filter off -> row selected", "nm-fix-sk" in [r["id"] for r in s3])
finally:
    Q.SKIPPED = real

# S5
p = write_q([row("nm-fix-t", "t.example", "needs-human", recheck_due="2026-11-18")])
rec(p, "nm-fix-t", "needs-human", "note refresh, no date")
check("S5 same-state move without the flag keeps the old date (unchanged behaviour)", by(p, "nm-fix-t").get("recheck_due") == "2026-11-18")
rec(p, "nm-fix-t", "needs-human", "dateless park", clear_recheck=True)
check("S5 --clear-recheck drops recheck_due", "recheck_due" not in by(p, "nm-fix-t"))
rec(p, "nm-fix-t", "needs-human", "dated park", recheck_due="2026-11-20")
check("S5 dated park still sets recheck_due", by(p, "nm-fix-t").get("recheck_due") == "2026-11-20")
check("S5 --clear-recheck with --recheck-due refused", refused(lambda: rec(p, "nm-fix-t", "needs-human", "x", clear_recheck=True, recheck_due="2026-11-21")) is not None)
check("S5 refusal wrote nothing", by(p, "nm-fix-t").get("recheck_due") == "2026-11-20")
rec(p, "nm-fix-t", "needs-human", "cli", clear_recheck=True)
buf = io.StringIO()
p2 = write_q([row("nm-fix-u", "u.example", "needs-human", recheck_due="2026-11-18")])
with contextlib.redirect_stdout(buf):
    rc = NM.main(["--row", "nm-fix-u", "--to", "needs-human", "--note", "dateless", "--clear-recheck", "--queue", p2])
check("S5 CLI --clear-recheck clears the date", rc == 0 and "recheck_due" not in by(p2, "nm-fix-u"))
# transitions.py (the park path for --client NM)
os.environ["CE_ACTIVITIES_WRITE"] = "0"
class FP:
    def latest_snapshot(self, cid): return {"payload": {"found": 1, "directories": []}}
    def upsert_snapshot(self, cid, day, payload): pass
    def call(self, method, path, body=None, prefer=None): pass
p3 = write_q([row("nm-fix-v", "v.example", "needs-human", recheck_due="2026-11-18")])
def tpark(**kw): return T.record_transition("NM", "nm-fix-v", "needs-human", None, "park", queue_path=p3, today=DAY, portal=FP(), **kw)
tpark()
check("S5 transitions.py same-state park without the flag keeps the date", by(p3, "nm-fix-v").get("recheck_due") == "2026-11-18")
tpark(clear_recheck=True)
check("S5 transitions.py --clear-recheck drops the date", "recheck_due" not in by(p3, "nm-fix-v"))
tpark(recheck_due="2026-11-25")
check("S5 transitions.py dated park still sets the date", by(p3, "nm-fix-v").get("recheck_due") == "2026-11-25")
check("S5 transitions.py both together refused", refused(lambda: tpark(clear_recheck=True, recheck_due="2026-11-26")) is not None)
src = open(os.path.join(HERE, "..", "job", "transitions.py"), encoding="utf-8").read()
check("S5 transitions.py CLI exposes --clear-recheck", "--clear-recheck" in src and "clear_recheck=n.clear_recheck" in src)

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
