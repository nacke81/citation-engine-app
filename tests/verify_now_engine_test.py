"""t_2211682c: NM Activities on, live moves close the Your turn row (fail loud), mobile-only directories park self-serve, NM backfill.
Run: python tests/verify_now_engine_test.py (CI). No network: urlopen is poisoned, the portal is a fake. Mutations at the end prove the tests can fail.

  A1 an NM live move plans exactly one deliverables row with the NM client id (and never the SCC id)   A2 tenant-swap mutation fails A1
  A3 CE_ACTIVITIES_WRITE=0 writes no row                       A4 needs-human / created-unlisted are not client news
  B1 the nm_transitions CLI path (t_d038172d: the writer that had no portal step) now closes the Your turn row and posts the row
  B2 the live PATCH reports rows closed; 0 closed with an open row for the directory (www/case) = error
  B3 CLI main() with a failing fake portal exits non-zero and names the step (upsert / live PATCH / activities)
  C1 set_verification_live writes one "Verified your <dir> listing by phone code" row, idempotent by source_ref
  D1 backfill: one row per history move, dated by the entry, Thumbtack verified row, a hand-closed row is NOT "verified"; second --write plans 0
  E1 alignable sms/phone-call park writes id-check (steps + directory_url), no Verify Now row, no allowlist; a non-flagged directory still parks sms
  E2 the flag is data (a flags file), not a code tuple
"""
import os, sys, json, tempfile, urllib.request, io, contextlib
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
os.environ["CE_DIRECTORIES_WRITE"] = "0"
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
os.environ["CE_PORTAL_ENV"] = os.path.join(HERE, "no-such-portal.env")   # fail closed, never the prod portal
sys.path.insert(0, os.path.join(ROOT, "job")); sys.path.insert(0, HERE)
import transitions as T, portal as P, nm_transitions as NMT, nm_activities_backfill as BF, verify_allowlist as AL
import yt_obs as YO

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d else ""), flush=True)

NM, SCC = P.ALLOWED["NM"], P.ALLOWED["SCC"]
DAY = "2026-11-20"
VID = "a25e00ff-0000-4000-8000-000000000001"

class Fake:
    """Portal fake. ver: open citation_verification rows. closes: whether the live PATCH matches (False models a directory-string mismatch)."""
    def __init__(self, ver=None, fail=(), patch_matches=True, reqs=None):
        self.calls, self.ver, self.fail, self.deliv, self.patch_matches, self.reqs = [], list(ver or []), fail, {}, patch_matches, list(reqs or [])
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body, prefer))
        if method != "GET" and "deliverables" in path: body = P.guard_deliverables(method, path, body)
        for f in self.fail:
            if f in path and (f != "deliverables" or method != "GET"): raise P.PortalWriteError("boom %s" % f)
        if path.startswith("deliverables"):
            if method == "POST":
                for r in body: self.deliv[(r["client_id"], r["source_ref"])] = r
                return None
            return [{"source_ref": k[1]} for k in self.deliv]
        if path.startswith("citation_code_request"): return [dict(r) for r in self.reqs]
        if path.startswith("citation_verification"):
            if method == "PATCH" and "state=eq.requires_verification" in path:
                hit = [v for v in self.ver if v["state"] == "requires_verification" and ("directory=eq.%s" % v["directory"] in path or "id=eq.%s" % v.get("id") in path)] if self.patch_matches else []
                for v in hit: v["state"] = "live"
                return [dict(v) for v in hit]
            if method == "GET":
                return [{"id": v["id"], "directory": v["directory"]} for v in self.ver if v["state"] == "requires_verification"] if "state=eq.requires_verification" in path else [dict(v) for v in self.ver if v["state"] == "live"]
        return None
    def posts(self, table): return [c for c in self.calls if c[0] == "POST" and c[1].startswith(table)]

def nm_row(rid, directory, state, history=None):
    return {"id": rid, "directory": directory, "kind": "create", "state": state, "cost": "free", "mike_approval": None, "history": history or [], "vaultwarden_item": "x"}
def nm_queue(rows):
    d = tempfile.mkdtemp(prefix="ce-nm-"); p = os.path.join(d, "nm-fix-queue.json")
    json.dump({"business": "NM fixture", "fix_queue": rows}, open(p, "w")); return p
def verrow(directory="alignable.com", vt="phone-call", state="requires_verification", vid=VID, verified_at=None):
    return {"id": vid, "client_id": NM, "directory": directory, "verification_type": vt, "state": state, "verified_at": verified_at}

# ---- A / B: the NM writer path
def nm_live(portal, state="created-unlisted", rid="nm-create-alignable", d="alignable.com", **kw):
    p = nm_queue([nm_row(rid, d, state)])
    return p, NMT.record_transition("NM", rid, "live", "https://www.alignable.com/x", "note", queue_path=p, today=DAY, portal=portal, **kw)

f = Fake([verrow()])
p, r = nm_live(f)
rows = list(f.deliv.values())
check("A1 NM live: exactly one deliverables row, NM client id, no error", len(rows) == 1 and rows[0]["client_id"] == NM and not r["errors"] and r["activities_written"], r["errors"])
check("A1 row is the SCC shape: title, source, source_ref, label, date, approved_at, in_scope, units", rows and rows[0]["title"] == "Your alignable.com listing is live" and rows[0]["source"] == "citation_engine"
      and rows[0]["source_ref"] == "citation-transition:nm-create-alignable:live" and rows[0]["channel_label"] == "SEO & Local SEO" and rows[0]["date_completed"] == DAY
      and rows[0]["approved_at"] and rows[0]["in_scope"] is True and rows[0]["units"] == 1 and rows[0]["deliverable_type"] == "citation", rows)
check("A1 the live NM row has approved_at set (renders on the Activities page)", all(x.get("approved_at") for x in rows) and r["activity_record"]["approved_at"], rows)
check("A1 the Your turn row is closed and the PATCH reported 1 closed", f.ver[0]["state"] == "live" and r["verification_closed"] == 1, r)
check("A1 queue written", json.load(open(p))["fix_queue"][0]["state"] == "live")
check("A1 no SCC client id anywhere in the calls", not any(SCC in json.dumps(c[1:3]) for c in f.calls))

# A2 tenant-swap mutation: the NM tenant writing under the SCC id must FAIL the A1 assertion
_orig = P.client_for
P.client_for = lambda biz: _orig("SCC")
try:
    f2 = Fake([verrow()]); p2, r2 = nm_live(f2)
    swapped = list(f2.deliv.values())
    check("A2 mutation (tenant swap to SCC id) makes the A1 NM-client assertion fail", not (len(swapped) == 1 and swapped[0]["client_id"] == NM), [x["client_id"] for x in swapped])
finally:
    P.client_for = _orig

os.environ["CE_ACTIVITIES_WRITE"] = "0"
f3 = Fake([verrow()]); nm_live(f3)
check("A3 CE_ACTIVITIES_WRITE=0: no deliverables row (the Your turn row still closes)", not f3.deliv and f3.ver[0]["state"] == "live")
os.environ.pop("CE_ACTIVITIES_WRITE")
f4 = Fake(); p4 = nm_queue([nm_row("nm-fix-a", "a.example", "queued")])
r4 = NMT.record_transition("NM", "nm-fix-a", "created-unlisted", None, "n", queue_path=p4, today=DAY, portal=f4)
check("A4 created-unlisted is not client news: no deliverables row", not f4.deliv and r4["activity_record"] is None)
r4b = NMT.record_transition("NM", "nm-fix-a", "needs-human", None, "n", queue_path=p4, today=DAY, portal=f4)
check("A4 needs-human is not client news", not f4.deliv)
p5 = nm_queue([nm_row("nm-fix-b", "b.example", "queued")])
r5 = NMT.record_transition("NM", "nm-fix-b", "submitted", None, "n", queue_path=p5, today=DAY)
check("A5 a bare call (no portal, no side_effects) touches no portal (tests and old callers)", r5["errors"] == [] and "activities_written" not in r5)

# B2 live PATCH count
f = Fake([verrow(directory="www.alignable.com")]); p, r = nm_live(f)
check("B2 0 rows closed while an open row exists for the directory (www/case mismatch) = error naming the step", r["errors"] and "verification live PATCH" in r["errors"][0] and "a25e00ff"[:8] in r["errors"][0], r["errors"])
f = Fake([verrow(directory="other.example")]); p, r = nm_live(f)
check("B2 0 rows closed and nothing open for that directory = fine (no row to close)", not r["errors"] and r["verification_closed"] == 0, r)
fr = Fake([verrow()]); nm_live(fr)
check("B2 the PATCH asks for the representation", [c for c in fr.calls if c[0] == "PATCH"][0][3] == "return=representation")

# B3 CLI entrypoint with a failing fake portal
class FailingPortal:
    mode = ()
    def __init__(self, url, key, opener=None): self.inner = Fake([verrow()], fail=FailingPortal.mode)
    def call(self, *a, **k): return self.inner.call(*a, **k)
P.Portal = FailingPortal; P.load_portal_env = lambda path=None: ("https://fake.invalid", "k")
def cli(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): rc = mod.main(argv)
    return rc, out.getvalue(), err.getvalue()

FailingPortal.mode = ("citation_verification",)
p = nm_queue([nm_row("nm-create-alignable", "alignable.com", "created-unlisted")])
rc, o, e = cli(NMT, ["--row", "nm-create-alignable", "--to", "live", "--evidence", "https://www.alignable.com/x", "--note", "n", "--queue", p])
check("B3 nm_transitions CLI, live PATCH fails: non-zero exit, step named on stderr", rc != 0 and "FAILED STEP: verification live PATCH" in e, (rc, e))
FailingPortal.mode = ("deliverables",)
p = nm_queue([nm_row("nm-create-alignable", "alignable.com", "created-unlisted")])
rc, o, e = cli(NMT, ["--row", "nm-create-alignable", "--to", "live", "--evidence", "https://www.alignable.com/x", "--note", "n", "--queue", p])
check("B3 nm_transitions CLI, activities write fails: non-zero exit, step named", rc != 0 and "FAILED STEP: activities" in e, (rc, e))
FailingPortal.mode = ()
p = nm_queue([nm_row("nm-create-alignable", "alignable.com", "created-unlisted")])
rc, o, e = cli(NMT, ["--row", "nm-create-alignable", "--to", "live", "--evidence", "https://www.alignable.com/x", "--note", "n", "--queue", p])
check("B3 nm_transitions CLI, healthy portal: exit 0", rc == 0 and not e, (rc, e))
p = nm_queue([nm_row("nm-create-alignable", "alignable.com", "created-unlisted")]); before = open(p, "rb").read()
FailingPortal.mode = ("citation_verification", "deliverables")
rc, o, e = cli(NMT, ["--row", "nm-create-alignable", "--to", "live", "--evidence", "https://www.alignable.com/x", "--note", "n", "--queue", p, "--dry-run"])
check("B3 dry run: exit 0, no portal call, queue untouched", rc == 0 and not e and open(p, "rb").read() == before, (rc, e))
FailingPortal.mode = ()

# transitions.py CLI (the record_transition path): upsert and retype and live PATCH named
for mode, step in ((("citation_verification?on_conflict",), "verification upsert"),):
    FailingPortal.mode = mode
    p = nm_queue([nm_row("nm-fix-bbb", "bbb.org", "queued")])
    rc, o, e = cli(T, ["--client", "NM", "--row", "nm-fix-bbb", "--to", "needs-human", "--verify-type", "postcard", "--queue", p, "--today", DAY, "--note", "n",
                       "--observed-type", "postcard", "--screenshot", YO._SHOT, "--price-seen", "none", "--observed-at", DAY, "--observed-url", "https://a.example/verify"])
    check("B3 transitions CLI, %s fails: exit 2, step named on stderr" % step, rc == 2 and ("FAILED STEP: " + step) in e, (rc, e[-300:]))
FailingPortal.mode = ("citation_verification",)
p = nm_queue([nm_row("nm-fix-bbb", "bbb.org", "queued")])
rc, o, e = cli(T, ["--client", "NM", "--row", "nm-fix-bbb", "--to", "needs-human", "--verify-type", "sms", "--queue", p, "--today", DAY, "--note", "n",
                   "--observed-type", "sms", "--screenshot", YO._SHOT, "--price-seen", "none", "--observed-at", DAY, "--observed-url", "https://a.example/verify", "--vault-item", "NM - bbb"])
check("B3 transitions CLI, sms park, verification write fails: exit 2 and a step is named", rc == 2 and "FAILED STEP: verification" in e, (rc, e[-300:]))
FailingPortal.mode = ("deliverables",)
p = nm_queue([nm_row("nm-fix-bbb", "bbb.org", "queued")])
rc, o, e = cli(T, ["--client", "NM", "--row", "nm-fix-bbb", "--to", "submitted", "--queue", p, "--today", DAY, "--note", "n"])
check("B3 transitions CLI, NM submitted with a failing deliverables write: exit 2, activities named", rc == 2 and "FAILED STEP: activities" in e, (rc, e[-300:]))
import importlib; importlib.reload(P)   # restore the real Portal / load_portal_env

# the shared record_transition live branch names its step and counts rows (SCC-shaped queue is not needed: the NM tenant is locked to its queue file)
f = Fake([verrow(directory="www.bbb.org")])
p = nm_queue([nm_row("nm-fix-bbb", "bbb.org", "submitted")])
proof = {"proof_url": "https://www.bbb.org/x", "proof_nap": "Birch Media | 200 Sample Ave | Testville, TN", "proof_at": "2026-11-20T12:00:00Z", "proof_nap_match": True, "build_action": "built"}
try: rr = T.record_transition("NM", "nm-fix-bbb", "live", "https://www.bbb.org/x", "n", queue_path=p, today=DAY, portal=f, proof=proof)
except T.TransitionRefused as e: rr = {"errors": ["refused: %s" % e]}
check("B4 record_transition live: a 0-closed PATCH with an open row is an error naming 'verification live PATCH' (or the proof gate refused first)", any("verification live PATCH" in x or x.startswith("refused") for x in rr["errors"]), rr["errors"])

# ---- C
f = Fake([verrow(directory="thumbtack.com", vt="phone-call", vid="11111111-aaaa-4000-8000-000000000002")])
done = T.set_verification_live(f, "11111111-aaaa-4000-8000-000000000002", NM, now=None)
dr = list(f.deliv.values())
check("C1 accepted code: the row goes live and ONE Activities row is written", done and len(dr) == 1 and dr[0]["client_id"] == NM, dr)
check("C1 wording: client-voiced, domain only, no period; ref :verified; same-day", dr and dr[0]["title"] == "Verified your thumbtack.com listing by phone code" and not dr[0]["title"].endswith(".")
      and dr[0]["source_ref"] == "citation-transition:11111111-aaaa-4000-8000-000000000002:verified" and dr[0]["date_completed"] and dr[0]["approved_at"], dr)
f.ver[0]["state"] = "requires_verification"; T.set_verification_live(f, "11111111-aaaa-4000-8000-000000000002", NM)
check("C1 the verified row has approved_at", all(x.get("approved_at") for x in dr))
check("C1 idempotent by source_ref (a second accept leaves one row)", len(f.deliv) == 1)
fs = Fake([verrow(vt="sms", vid="22222222-aaaa-4000-8000-000000000003")]); T.set_verification_live(fs, "22222222-aaaa-4000-8000-000000000003", NM)
check("C1 sms says text code", list(fs.deliv.values())[0]["title"].endswith("by text code"))
fz = Fake([verrow()]); fz.fail = ("deliverables",)
with contextlib.redirect_stderr(io.StringIO()): d2 = T.set_verification_live(fz, VID, NM)
check("C1 an Activities failure never undoes the live flip", d2 is True and fz.ver[0]["state"] == "live")
fw = Fake([verrow()])
try: T.set_verification_live(fw, VID, "00000000-0000-0000-0000-000000000000"); refused_client = False
except P.PortalWriteError: refused_client = True
check("C1 a client id off the allow-list is refused before any call", refused_client and not fw.calls)

# ---- D backfill
H = lambda *e: [{"at": a, "from": fr, "to": to, "evidence_url": ev, "note": "n"} for a, fr, to, ev in e]
q = {"business": "NM", "fix_queue": [
    nm_row("nm-fix-a", "a.example", "live", H(("2026-11-01", "queued", "submitted", None), ("2026-11-05", "submitted", "live", "https://a.example/p"))),
    nm_row("nm-fix-b", "b.example", "rejected", H(("2026-11-02", "queued", "submitted", None), ("2026-11-06", "submitted", "rejected", None))),
    nm_row("nm-fix-c", "c.example", "needs-human", H(("2026-11-03", "queued", "needs-human", None))),
    nm_row("nm-fix-d", "d.example", "created-unlisted", H(("2026-11-04", "queued", "created-unlisted", None))),
    nm_row("nm-fix-e", "e.example", "live", H(("2026-11-04", "queued", "submitted", None), ("2026-11-05", "submitted", "pending-verify", None), ("2026-11-07", "pending-verify", "live", None), ("2026-11-08", "live", "live", None))),
], "create_queue": {"rows": []}}
qp = os.path.join(tempfile.mkdtemp(prefix="ce-bf-"), "nm-fix-queue.json"); json.dump(q, open(qp, "w"))
TB = "33333333-aaaa-4000-8000-000000000004"
fb = Fake([verrow(directory="thumbtack.com", vt="phone-call", state="live", vid=TB, verified_at="2026-11-19T18:19:43Z"),
           verrow(directory="alignable.com", vt="phone-call", state="live", vid=VID, verified_at="2026-11-20T18:46:16Z"),
           verrow(directory="stuck.example", vt="sms", state="live", vid="44444444-aaaa-4000-8000-000000000005", verified_at="2026-11-18T10:00:00Z")],
          reqs=[{"id": "db1fdaaa-0000-4000-8000-000000000006", "citation_verification_id": TB, "status": "verified", "finished_at": "2026-11-19T18:19:44Z"},
                {"id": "db1fdaab-0000-4000-8000-000000000007", "citation_verification_id": TB, "status": "verified", "finished_at": "2026-11-19T18:20:00Z"},
                {"id": "bad00000-0000-4000-8000-000000000008", "citation_verification_id": "44444444-aaaa-4000-8000-000000000005", "status": "failed", "finished_at": "2026-11-18T10:00:00Z"}])
res = BF.run(qp, False, fb)
refs = sorted(r["source_ref"] for r in res["rows"])
check("D1 dry run plans one row per move into submitted/pending-verify/live/rejected (+1 Thumbtack verified): 2+2+0+0+3 +1 = 8", res["planned"] == 8 and not fb.deliv, refs)
check("D1 dated by the history entry", {r["source_ref"]: r["date_completed"] for r in res["rows"]}["citation-transition:nm-fix-a:live"] == "2026-11-05")
check("D1 Thumbtack verified row dated 2026-11-19, ref uses the verification id", ("citation-transition:%s:verified" % TB) in refs and {r["source_ref"]: r["date_completed"] for r in res["rows"]}["citation-transition:%s:verified" % TB] == "2026-11-19")
check("D1 the hand-closed alignable row (live, no verified request) is NOT written as 'verified by code'", not any(VID in x for x in refs))
check("D1 a live row whose only request FAILED plans 0; two verified requests for one verification plan ONE row", not any("44444444" in x for x in refs) and refs.count("citation-transition:%s:verified" % TB) == 1)
check("D1 no CODE_VERIFIED tuple in the backfill (data comes from the request record)", not hasattr(BF, "CODE_VERIFIED"))
fv = Fake([verrow(directory="thumbtack.com", vt="sms", state="live", vid=TB, verified_at="2026-11-19T18:19:43Z")], reqs=[{"citation_verification_id": TB, "status": "verified", "finished_at": "2026-11-19T18:19:44Z"}])
rv = BF.plan_verified_rows(fv.ver, fv.reqs, NM)
check("D1 one verified request -> one row, the Thumbtack ref and date", len(rv) == 1 and rv[0]["source_ref"] == "citation-transition:%s:verified" % TB and rv[0]["date_completed"] == "2026-11-19" and rv[0]["approved_at"], rv)
check("D1 a live row with no verified request -> 0 rows", BF.plan_verified_rows(fv.ver, [], NM) == [])
check("D1 a verified request whose verification is not live -> 0 rows", BF.plan_verified_rows([dict(fv.ver[0], state="requires_verification")], fv.reqs, NM) == [])
fv.deliv = {}; BF.run(qp.replace("nm-fix-queue.json", "none.json") if False else qp, True, fv); n1 = len(fv.deliv); r2 = BF.run(qp, True, fv)
check("D1 recovery: a verified row lost by set_verification_live is re-posted by the backfill, and a second run plans 0", any(k[1].endswith(":verified") for k in fv.deliv) and r2["planned"] == 0 and len(fv.deliv) == n1)
check("D1 needs-human, created-unlisted and a live->live refresh add no row", not any(x.endswith((":created-unlisted")) or "nm-fix-c" in x or "nm-fix-d" in x for x in refs) and refs.count("citation-transition:nm-fix-e:live") == 1)
check("D1 every row is the NM client id, source citation_engine", all(r["client_id"] == NM and r["source"] == "citation_engine" for r in res["rows"]))
check("D1 every planned NM row carries approved_at (the Activities page hides a citation_engine row without it)", all(r.get("approved_at") for r in res["rows"]) and len(res["rows"]) == 8)
w1 = BF.run(qp, True, fb)
check("D1 the POSTed rows all have approved_at", len(fb.deliv) == 8 and all(r.get("approved_at") for r in fb.deliv.values()))
check("D1 --write posts the rows (8)", w1["written"] == 8 and len(fb.deliv) == 8)
w2 = BF.run(qp, True, fb)
check("D1 a second --write plans 0 (idempotent by source_ref)", w2["planned"] == 0 and w2["written"] == 0 and len(fb.deliv) == 8)
check("D1 only the deliverables table is written", all(c[0] == "GET" or c[1] == P.DELIVERABLES_PATH for c in fb.calls))

# ---- E mobile-only
LOCAL = os.path.join(tempfile.mkdtemp(prefix="ce-al-"), "local.json")
def park(domain, vt, rid="nm-create-x", **kw):
    p = nm_queue([nm_row(rid, domain, "created-unlisted")]); fp = Fake()
    r = T.record_transition("NM", rid, "needs-human", None, "n", queue_path=p, today=DAY, portal=fp, verify_type=vt, observation=YO.obs(vt, DAY),
                            allowlist_path=LOCAL, vault_item="NM - x", **kw)
    return r, fp, json.load(open(p))["fix_queue"][0]
for vt in ("phone-call", "sms"):
    r, fp, qrow = park("alignable.com", vt)
    vp = fp.posts("citation_verification")
    body = vp[0][2][0] if vp else {}
    check("E1 alignable %s park writes id-check, not %s" % (vt, vt), len(vp) == 1 and body.get("verification_type") == "id-check", body)
    check("E1 alignable %s park: steps say mobile number + own cell, directory_url https" % vt, body.get("steps") and "mobile" in " ".join(body["steps"]).lower() and "own cell" in " ".join(body["steps"]) and body.get("directory_url", "").startswith("https://"), body)
    check("E1 alignable %s park: no retype PATCH to sms/phone-call, no allowlist add" % vt, not [c for c in fp.calls if c[0] == "PATCH"] and r["allowlist"] is None and not os.path.exists(LOCAL), (fp.calls, r["allowlist"]))
    check("E1 history carries id-check; row parked needs-human", qrow["state"] == "needs-human" and qrow["history"][-1].get("verify_type") == "id-check")
    check("E1 steps carry no digit run and no password word (the DB would refuse)", not T.ID_CHECK_BAD.search(" ".join(body.get("steps") or [])))
r, fp, qrow = park("www.alignable.com", "phone-call", rid="nm-create-y")
check("E1 www. form of the directory is flagged too", fp.posts("citation_verification")[0][2][0]["verification_type"] == "id-check")
r, fp, qrow = park("bbb.org", "sms", rid="nm-create-z")
check("E1 an unflagged directory still parks sms (Verify Now row + allowlist)", fp.posts("citation_verification")[0][2][0]["verification_type"] == "sms" and r["allowlist"] and r["allowlist"]["added"], r["allowlist"])
check("E1 mobile-only park never reaches the Directory/portal-seed: only citation_verification + deliverables-free calls", all(c[1].startswith("citation_verification") for c in park("alignable.com", "sms", rid="nm-create-q")[1].calls))
# E2 data, not code
ff = os.path.join(tempfile.mkdtemp(prefix="ce-fl-"), "flags.json"); json.dump({"directories": {"other.example": {"phone_verify_requires_mobile": True}}}, open(ff, "w"))
os.environ["CE_DIRECTORY_FLAGS"] = ff
check("E2 the flag comes from the data file: alignable off, other.example on", not AL.requires_mobile("alignable.com") and AL.requires_mobile("other.example"))
os.environ.pop("CE_DIRECTORY_FLAGS")
check("E2 the shipped data file sets alignable.com", AL.requires_mobile("alignable.com") and AL.directory_flags("alignable.com").get("phone_verify_requires_mobile") is True)
src = open(os.path.join(ROOT, "job", "transitions.py"), encoding="utf-8").read() + open(os.path.join(ROOT, "job", "verify_allowlist.py"), encoding="utf-8").read()
import re as _re
check("E2 no job code names a flagged directory as a literal domain", not _re.search(r"[\"']alignable\.com[\"']", src))

# ---- F same-state note refresh posts no Activities row (review round 1)
def refresh(rid, state, d="refresh.example", **kw):
    p = nm_queue([nm_row(rid, d, state, H(("2026-11-01", "queued", state, None)))]); fr = Fake([verrow(directory=d)])
    r = NMT.record_transition("NM", rid, state, "https://%s/p" % d if state == "live" else None, "weekly recheck note", queue_path=p, today="2026-11-27", portal=fr, **kw)
    return r, fr
for st in ("submitted", "pending-verify"):
    r, fr = refresh("nm-fix-%s" % st, st)
    check("F1 %s -> %s note refresh: 0 deliverables POSTs, no activity record" % (st, st), not fr.posts("deliverables") and r["activity_record"] is None and not r["activities_written"] and not r["errors"], fr.calls)
r, fr = refresh("nm-fix-live", "live", refresh_url="https://refresh.example/new")
check("F1 live -> live --refresh-url: 0 deliverables POSTs", not fr.posts("deliverables") and r["activity_record"] is None, fr.calls)
check("F1 a live -> live refresh still runs the live close (the open row is closed)", fr.ver[0]["state"] == "live" and r["verification_closed"] == 1)
p = nm_queue([nm_row("nm-fix-ch", "change.example", "submitted", H(("2026-11-01", "queued", "submitted", None)))]); fch = Fake()
NMT.record_transition("NM", "nm-fix-ch", "pending-verify", None, "moved on", queue_path=p, today="2026-11-27", portal=fch)
check("F1 a real change of state still posts exactly one row", len(fch.posts("deliverables")) == 1)
T2 = T
_orig_news = T2.is_client_news
T2.is_client_news = lambda tenant, old, new: bool(tenant["activities"] and new in T2.ACTIVITY_STATES)   # the guard removed
r, fr = refresh("nm-fix-submitted", "submitted")
check("M3 mutation (same-state guard removed) posts a row on a note refresh: F1 would fail", len(fr.posts("deliverables")) == 1)
T2.is_client_news = _orig_news

# ---- C2 failure line names step + verification id
fz = Fake([verrow()]); fz.fail = ("deliverables",); eb = io.StringIO()
with contextlib.redirect_stderr(eb): T.set_verification_live(fz, VID, NM)
check("C2 a failed verified-activity write names the step and the verification id on stderr", "FAILED STEP: activities" in eb.getvalue() and VID in eb.getvalue(), eb.getvalue())

# ---- mutations: the one-writer rule and the tenant gate can fail
import transitions as T2
orig = T2.TENANTS["NM"]["activities"]
T2.TENANTS["NM"]["activities"] = False
fm = Fake([verrow()]); nm_live(fm)
check("M1 mutation (NM activities False, the old state) leaves 0 rows: A1 would fail", len(fm.deliv) == 0)
T2.TENANTS["NM"]["activities"] = orig
orig_close = T2.close_verification_on_live
T2.close_verification_on_live = lambda ver, cid, d: 0   # the old behaviour: no count, never an error
fm = Fake([verrow(directory="www.alignable.com")]); _, rm = nm_live(fm)
check("M2 mutation (silent live PATCH) leaves the row open with no error: B2 would fail", not rm["errors"] and fm.ver[0]["state"] == "requires_verification")
T2.close_verification_on_live = orig_close

print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
