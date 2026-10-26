"""Transition tests. Run: python tests/transitions_test.py (CI). No network: portal and activities are in-memory fakes."""
import os, sys, copy, json, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import buildqueue as Q
import portal as P
import transitions as T

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

SRC = os.path.join(HERE, "fixtures", "test_queue.json")
TMP = tempfile.mkdtemp()
SCC = P.ALLOWED["SCC"]
DAY = "2026-10-20"

class FakePortal:
    def __init__(self):
        self.snaps, self.calls = {}, []
    def latest_snapshot(self, cid):
        return {"payload": copy.deepcopy(self.snaps[cid])} if cid in self.snaps else None
    def upsert_snapshot(self, cid, day, payload):
        self.snaps[cid] = copy.deepcopy(payload); self.calls.append(("snap", day))
    def call(self, method, path, body=None, prefer=None):
        t = (method, path, body); self.calls.append(t); self.pref = getattr(self, "pref", {}); self.pref[id(t)] = prefer

def fresh(state="queued", approval=None):
    p = os.path.join(TMP, "q.json"); shutil.copy(SRC, p)
    q = json.load(open(p)); r = q["fix_queue"][0]; r["state"] = state; r["mike_approval"] = approval
    json.dump(q, open(p, "w")); return p, r["id"], r["directory"]

def portal_with(domain):
    fp = FakePortal()
    fp.snaps[SCC] = {"found": 1, "directories": [{"name": domain, "domain": domain, "state": "live", "url": None, "urlKind": "search"}]}
    return fp

def rec(path, rid, new, ev="https://a.example/listing/1", fp=None, note="n", **kw):
    return T.record_transition("SCC", rid, new, ev, note, queue_path=path, today=DAY, portal=fp or portal_with("a.example"), **kw)

def refused(path, rid, new, ev="https://a.example/listing/1", note=None):  # no note by default: same-state moves need one
    before = open(path, "rb").read(); fp = portal_with("a.example")
    try: rec(path, rid, new, ev, fp, note=note)
    except T.TransitionRefused: return open(path, "rb").read() == before and not fp.calls
    return False

# allowed matrix
ALLOWED = [("queued", "submitted"), ("submitted", "pending-verify"), ("submitted", "live"), ("pending-verify", "live"), ("needs-human", "live"),
           ("queued", "rejected"), ("submitted", "rejected"), ("pending-verify", "rejected"), ("live", "rejected"), ("needs-human", "rejected"),
           ("queued", "needs-human"), ("submitted", "needs-human"), ("pending-verify", "needs-human"), ("live", "needs-human"), ("rejected", "needs-human"),
           # fix 1 (t_e0abca7d): found state, needs-human can move forward
           ("queued", "found"), ("found", "submitted"), ("found", "pending-verify"), ("found", "live"), ("found", "needs-human"), ("found", "rejected"),
           ("needs-human", "submitted"), ("needs-human", "pending-verify"),
           # t_d13bd638: claimed-unverified (found, claimed, edits ID-gated)
           ("queued", "claimed-unverified"), ("found", "claimed-unverified"), ("needs-human", "claimed-unverified"),
           ("claimed-unverified", "live"), ("claimed-unverified", "rejected"), ("claimed-unverified", "needs-human")]
for old, new in ALLOWED:
    p, rid, d = fresh(old)
    try: r = rec(p, rid, new); good = r["to"] == new and json.load(open(p))["fix_queue"][0]["state"] == new
    except Exception as e: good = False
    check("T1 allowed %s -> %s" % (old, new), good)

# refused matrix: everything not allowed, incl. same-state and bogus
STATES = list(T.STATES)
for old in STATES:
    for new in STATES + ["bogus"]:
        if (old, new) in ALLOWED: continue
        p, rid, d = fresh(old)
        check("T2 refused %s -> %s (file untouched, no portal call)" % (old, new), refused(p, rid, new))
p, rid, d = fresh("submitted")
check("T2 live without evidence refused (real)", refused(p, rid, "live", None))
check("T2 evidence with credentials refused", refused(p, rid, "live", "https://u:pw@a.example/x"))
check("T2 evidence non-http refused", refused(p, rid, "live", "javascript:alert(1)"))
p, rid, d = fresh("queued")
try: T.record_transition("NM", rid, "submitted", None, None, queue_path=p, portal=FakePortal()); nm = False
except T.TransitionRefused: nm = True
check("T2 non-SCC client refused", nm)
check("T2 unknown row id refused", refused(p, "nope", "submitted"))

# queue content
p, rid, d = fresh("queued")
rec(p, rid, "submitted")
row = json.load(open(p))["fix_queue"][0]
check("T3 queue row has state, evidence_url, dated history entry",
      row["state"] == "submitted" and row["evidence_url"] == "https://a.example/listing/1"
      and row["history"] == [{"at": DAY, "from": "queued", "to": "submitted", "evidence_url": "https://a.example/listing/1", "note": "n"}])
check("T3 other rows untouched", json.load(open(p))["fix_queue"][1:] == json.load(open(SRC))["fix_queue"][1:])

# mike_approval survives
ap = {"approved_by": "mike", "at": "2026-10-19T16:00:00", "row_id": None}
for new in ("submitted", "rejected", "needs-human"):
    p, rid, d = fresh("queued", dict(ap, row_id="x")); a0 = json.load(open(p))["fix_queue"][0]["mike_approval"]
    rec(p, rid, new)
    check("T4 mike_approval unchanged after queued -> %s" % new, json.load(open(p))["fix_queue"][0]["mike_approval"] == a0 and a0 is not None)
p, rid, d = fresh("queued"); rec(p, rid, "submitted")
check("T4 null mike_approval stays null (a transition never grants approval)", json.load(open(p))["fix_queue"][0]["mike_approval"] is None)

# portal
p, rid, d = fresh("queued"); fp = portal_with(d); before = copy.deepcopy(fp.snaps[SCC])
r = rec(p, rid, "submitted", fp=fp)
snap = fp.snaps[SCC]
check("T5 portal snapshot upserted same day with the new state on that directory",
      r["portal_written"] and fp.calls[0] == ("snap", DAY) and snap["directories"][0]["state"] == "submitted" and snap["directories"][0]["stateDate"] == DAY)
check("T5 portal counts unchanged", snap["found"] == before["found"])
check("T5 portal failure is reported, queue still written",
      (lambda x: x["portal_written"] is False and x["errors"] and json.load(open(p))["fix_queue"][0]["state"] == "pending-verify")(
          rec(p, rid, "pending-verify", fp=type("B", (), {"latest_snapshot": lambda s, c: None, "upsert_snapshot": lambda *a: None})())))

# activities gate
p, rid, d = fresh("queued"); fp = portal_with(d)
r = rec(p, rid, "submitted", fp=fp)
check("T6 activities ON by default: deliverables row written, approved_at never set", r["activities_written"] is True and any(str(c[1]).startswith("deliverables") for c in fp.calls if c[0] == "POST")
      and all("approved_at" not in b for c in fp.calls if c[0] == "POST" and str(c[1]).startswith("deliverables") for b in c[2]))
os.environ["CE_ACTIVITIES_WRITE"] = "0"
p, rid, d = fresh("queued"); fp = portal_with(d); r = rec(p, rid, "submitted", fp=fp)
os.environ.pop("CE_ACTIVITIES_WRITE")
check("T6 opt-out CE_ACTIVITIES_WRITE=0: no deliverables call", r["activities_written"] is False and not any(c[0] == "POST" for c in fp.calls))
for st in ("submitted", "pending-verify", "live", "rejected", "needs-human"):
    old = "queued" if st == "submitted" else "submitted"
    p, rid, d = fresh(old); fp = portal_with(d); r = rec(p, rid, st, fp=fp)
    wrote = any(c[0] == "POST" and str(c[1]).startswith("deliverables") for c in fp.calls)
    check("T6 activity row for %s: %s" % (st, "skipped" if st == "needs-human" else "written"), wrote == (st != "needs-human") and r["activities_written"] == wrote)
p, rid, d = fresh("queued"); fp = portal_with(d); acts = FakePortal()
r = rec(p, rid, "submitted", fp=fp, activities=acts, activities_flag=True)
b = acts.calls[0][2][0]
check("T6 flag on writes one client-voiced row", r["activities_written"] and len(acts.calls) == 1 and acts.calls[0][1].startswith("deliverables") and b["title"] == "Submitted your business listing to a.example"
      and b["client_id"] == SCC and b["source"] == "citation_engine" and b["source_ref"] == "citation-transition:%s:submitted" % rid)
check("T6 activity title has no terminal period and no NAP fields", all(not T.activity_title(s, "a.example").endswith(".") for s in T.ACTIVITY_STATES) and set(b) <= {"client_id", "deliverable_type", "title", "date_completed", "in_scope", "units", "evidence_url", "source", "source_ref"})
os.environ["CE_ACTIVITIES_WRITE"] = "1"
p, rid, d = fresh("queued"); acts = FakePortal(); r = rec(p, rid, "submitted", fp=portal_with(d), activities=acts)
os.environ.pop("CE_ACTIVITIES_WRITE")
check("T6 env flag CE_ACTIVITIES_WRITE=1 still on", r["activities_written"] is True)

# verification queue
def vcalls(fp): return [c for c in fp.calls if len(c) == 3 and str(c[1]).startswith("citation_verification")]
for vt in ("phone-call", "sms", "postcard"):
    p, rid, d = fresh("submitted"); fp = portal_with(d); r = rec(p, rid, "needs-human", fp=fp, verify_type=vt)
    vc = vcalls(fp); b = vc[0][2][0] if vc else {}
    qrow = json.load(open(p))["fix_queue"][0]
    check("T10 %s: one upsert on_conflict client_id,directory, state requires_verification" % vt,
          len(vc) == 1 and vc[0][0] == "POST" and "on_conflict=client_id,directory" in vc[0][1] and b["client_id"] == SCC and b["directory"] == d
          and b["verification_type"] == vt and b["state"] == "requires_verification" and r["verification_written"])
    check("T10 %s: deadline only for postcard (30d), parked_at/verified_at never sent" % vt,
          (b.get("deadline") == "2026-11-19") == (vt == "postcard") and ("deadline" in b) == (vt == "postcard") and "parked_at" not in b and "verified_at" not in b)
    check("T10 %s: queue row needs-human, blocker note, no activity" % vt, qrow["state"] == "needs-human" and qrow["history"][-1]["note"] == "parked for client verification (%s)" % vt and not r["activities_written"])
p, rid, d = fresh("submitted"); fp = portal_with(d); rec(p, rid, "needs-human", fp=fp, verify_type="sms")
p2, rid2, d2 = fresh("submitted"); fp2 = portal_with(d); rec(p2, rid2, "needs-human", fp=fp2, verify_type="sms")
check("T10 idempotent: repeat sends same merge-duplicates upsert on the (client, directory) key",
      vcalls(fp)[0][2] == vcalls(fp2)[0][2] and vcalls(fp)[0][1] == vcalls(fp2)[0][1])
p, rid, d = fresh("submitted"); fp = portal_with(d); rec(p, rid, "needs-human", fp=fp)
check("T10 no verify type: no verification call", not vcalls(fp))
for bad_new, bad_vt in (("submitted", "sms"), ("needs-human", "email"), ("live", "phone-call")):
    p, rid, d = fresh("queued" if bad_new == "submitted" else "submitted"); b0 = open(p, "rb").read(); fp = portal_with(d)
    try: rec(p, rid, bad_new, fp=fp, verify_type=bad_vt); rf = False
    except T.TransitionRefused: rf = open(p, "rb").read() == b0 and not fp.calls
    check("T10 refused verify_type=%s with %s" % (bad_vt, bad_new), rf)
p, rid, d = fresh("pending-verify"); fp = portal_with(d); r = rec(p, rid, "live", fp=fp)
vc = vcalls(fp)
check("T11 live sets verification row live with verified_at (PATCH scoped to client+directory+requires_verification)",
      len(vc) == 1 and vc[0][0] == "PATCH" and ("directory=eq." + d) in vc[0][1] and "state=eq.requires_verification" in vc[0][1]
      and vc[0][2]["state"] == "live" and vc[0][2]["verified_at"] and r["verification_written"])
p, rid, d = fresh("submitted"); fp = portal_with(d); r = rec(p, rid, "pending-verify", fp=fp)
check("T11 non-live transition: no verification call", not vcalls(fp))
p, rid, d = fresh("submitted"); fp = portal_with(d)
rec(p, rid, "needs-human", fp=fp, verify_type="postcard")
r = rec(p, rid, "live", fp=fp); vc = vcalls(fp)
check("T12 park with --verify-type then live on the same row: upsert then PATCH live with verified_at",
      len(vc) == 2 and vc[0][0] == "POST" and vc[1][0] == "PATCH" and vc[1][2]["state"] == "live" and vc[1][2]["verified_at"]
      and ("directory=eq." + d) in vc[1][1] and r["verification_written"] and json.load(open(p))["fix_queue"][0]["state"] == "live")
p, rid, d = fresh("submitted"); fp = portal_with(d)
rec(p, rid, "needs-human", fp=fp, verify_type="postcard"); rec(p, rid, "live", fp=fp); rec(p, rid, "needs-human", fp=fp, verify_type="postcard")
posts = [(c, fp.pref[id(c)]) for c in fp.calls if len(c) == 3 and c[0] == "POST" and str(c[1]).startswith("citation_verification")]
check("T12 re-park: every upsert is ignore-duplicates (existing deadline and live state never overwritten)",
      len(posts) == 2 and all("ignore-duplicates" in pr and "merge-duplicates" not in pr for _, pr in posts))
p, rid, d = fresh("submitted"); fp = portal_with(d); b0 = open(p, "rb").read()
r = rec(p, rid, "needs-human", fp=fp, verify_type="postcard", dry_run=True)
check("T11 dry run shows verification request, writes nothing", open(p, "rb").read() == b0 and not fp.calls and r["verification_request"]["body"][0]["deadline"] == "2026-11-19")

# dry run: no writes
p, rid, d = fresh("queued"); fp = portal_with(d); b0 = open(p, "rb").read()
r = rec(p, rid, "submitted", fp=fp, dry_run=True)
check("T7 dry run writes nothing and shows payloads", open(p, "rb").read() == b0 and not fp.calls and r["portal_request"]["row"]["directory_patch"][0]["state"] == "submitted"
      and r["activities_request"]["method"] == "POST" and "approved_at" not in r["activities_request"]["body"][0])

# submit_row wiring
rows = Q.load_rows(SRC) if False else None
p, rid, d = fresh("queued"); q = json.load(open(p)); row = q["fix_queue"][0]
row["mike_approval"] = {"approved_by": "mike", "at": "2026-10-19T16:00:00", "row_id": rid}; row["vaultwarden_item"] = "x"; row["cost"] = "free"; json.dump(q, open(p, "w"))
row = json.load(open(p))["fix_queue"][0]
calls = []
res = Q.submit_row(row, lambda i: {"u": 1}, record=lambda *a: calls.append(a) or "ok")
check("T8 submit_row success path calls record_transition-shaped hook with submitted", calls and calls[0][:3] == ("SCC", rid, "submitted") and res["recorded"] == "ok")
res = Q.submit_row(row, lambda i: {"u": 1})
check("T8 no hook and no env flag: nothing recorded", "recorded" not in res)
try: Q.submit_row(dict(row, mike_approval=None), lambda i: {"u": 1}, record=lambda *a: calls.append("bad")); rf = False
except Q.SubmitRefused: rf = "bad" not in calls
check("T8 refused submit records nothing", rf)

src = open(os.path.join(HERE, "..", "job", "buildqueue.py"), encoding="utf-8").read()
check("T9 buildqueue.py still has no network import", not any(w in src for w in ("urllib", "requests", "subprocess", "socket")))
# T13 (t_568f1ee6): history carries verify_type, not only the note text
for vt in ("phone-call", "sms", "postcard"):
    p, rid, d = fresh("submitted"); fp = portal_with(d); rec(p, rid, "needs-human", fp=fp, verify_type=vt)
    h = json.load(open(p))["fix_queue"][0]["history"][-1]
    check("T13 %s: queue history entry has verify_type=%s" % (vt, vt), h.get("verify_type") == vt and len(vcalls(fp)) == 1)
p, rid, d = fresh("submitted"); fp = portal_with(d); rec(p, rid, "needs-human", fp=fp)
check("T13 no verify type: history entry has no verify_type key", "verify_type" not in json.load(open(p))["fix_queue"][0]["history"][-1])
p, rid, d = fresh("submitted"); fp = portal_with(d); r = rec(p, rid, "needs-human", fp=fp, verify_type="sms", dry_run=True)
check("T13 dry run shows verify_type in the history entry", r["history_entry"].get("verify_type") == "sms")
# T14 found state + same-state note refresh (t_e0abca7d)
p, rid, d = fresh("needs-human")
r = rec(p, rid, "needs-human", None, note="hCaptcha after Continue")
h = json.load(open(p))["fix_queue"][0]["history"][-1]
check("T14 needs-human -> needs-human with a note is recorded", r["to"] == "needs-human" and h["note"] == "hCaptcha after Continue" and h["from"] == "needs-human")
check("T14 note refresh makes no client activity", r["activity_record"] is None and r["activities_written"] is False)
p, rid, d = fresh("found")
r = rec(p, rid, "found", None, note="still unclaimed")
check("T14 found -> found with a note is recorded", r["to"] == "found")
check("T14 found -> found without a note refused", refused(*fresh("found"), "found"))
check("T14 needs-human -> needs-human without a note refused", refused(*fresh("needs-human"), "needs-human"))
check("T14 live -> live refused even with a note", refused(*fresh("live"), "live", note="x"))
check("T14 needs-human -> found refused (found only from queued)", refused(*fresh("needs-human"), "found", note="x"))
p, rid, d = fresh("queued"); fp = portal_with(d)
r = rec(p, rid, "found", None, fp, note="listed, unclaimed")
check("T14 queued -> found: no client activity row", r["activity_record"] is None and not any(c[0] == "POST" and "deliverables" in str(c[1]) for c in fp.calls))
check("T14 found maps to portal needs-human and is not an activity state", Q.QUEUE_TO_PORTAL["found"] == "needs-human" and "found" not in T.ACTIVITY_STATES)
check("T14 parse_rows accepts a found row", Q.parse_rows(json.load(open(p))) is not None)
# T15 claimed-unverified: found, claimed, edits ID-gated (t_d13bd638). The allowed edges are in the T1 matrix above.
check("T15 submitted -> claimed-unverified refused", refused(*fresh("submitted"), "claimed-unverified", note="x"))
check("T15 live -> claimed-unverified refused", refused(*fresh("live"), "claimed-unverified", note="x"))
check("T15 claimed-unverified -> submitted refused", refused(*fresh("claimed-unverified"), "submitted", note="x"))
check("T15 claimed-unverified -> claimed-unverified without a note refused", refused(*fresh("claimed-unverified"), "claimed-unverified"))
p, rid, d = fresh("claimed-unverified")
r = rec(p, rid, "claimed-unverified", None, note="Veriff still pending")
check("T15 note refresh on a claimed-unverified row is recorded", r["to"] == "claimed-unverified" and json.load(open(p))["fix_queue"][0]["history"][-1]["note"] == "Veriff still pending")
p, rid, d = fresh("found"); fp = portal_with(d)
r = rec(p, rid, "claimed-unverified", None, fp, note="claimed; edits need ID check")
check("T15 no client activity row", r["activity_record"] is None and not any(c[0] == "POST" and "deliverables" in str(c[1]) for c in fp.calls))
check("T15 portal maps it to needs-human and it is not an activity state", Q.QUEUE_TO_PORTAL["claimed-unverified"] == "needs-human" and "claimed-unverified" not in T.ACTIVITY_STATES)
check("T15 portal snapshot row shows needs-human", fp.snaps[SCC]["directories"][0]["state"] == "needs-human")
check("T15 parse_rows accepts it", Q.parse_rows(json.load(open(p))) is not None)
import directories as DIR
check("T15 Directory sync knows the state", "claimed-unverified" in DIR.QUEUE_STATES)
sql = open(os.path.join(HERE, "..", "db", "005_claimed_unverified.sql"), encoding="utf-8").read().lower()
check("T15 migration 005 widens the check constraint, additive only", "claimed-unverified" in sql and "drop table" not in sql and "drop column" not in sql)
shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
