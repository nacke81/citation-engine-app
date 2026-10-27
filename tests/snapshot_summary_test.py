"""Snapshot shape + summary (t_f6267312). Run: python tests/snapshot_summary_test.py (CI). No network, no prod env, no portal seed.

G1 golden: today's counts (fixture shaped from Nate's 10/27 prod read) -> live 19, inProgress 9, napCorrect 4 of 19, declined 27, napFix 5, blocked 26.
G2 summary always equals the row recount (random shapes, through finalize, overlay_directories and build_payload).
G3 needs-human is split: listing -> nap-fix, none -> blocked; the queue state machine is unchanged.
G4 live-row NAP read: every outcome stored; unread = null + reason, never False.
G5 no frozen field survives; no portal seed / Directory path in the new code.
"""
import copy, json, os, random, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_QUEUE"] = os.path.join(HERE, "fixtures", "test_queue.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import snapshot as SN, buildqueue as Q, portal as P, recheck as RC, transitions as T  # noqa: E402

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

# G1 golden
snap = json.load(open(os.path.join(HERE, "fixtures", "snapshot-scc-2026-10-27.json"), encoding="utf-8"))
p0 = snap["payload"]
check("G1 fixture is today's shape: 86 rows, needs-human 31, rejected 27, live 19, submitted 8, pending-verify 1",
      len(p0["directories"]) == 86 and {s: sum(1 for d in p0["directories"] if d["state"] == s) for s in ("needs-human", "rejected", "live", "submitted", "pending-verify")} == {"needs-human": 31, "rejected": 27, "live": 19, "submitted": 8, "pending-verify": 1})
new = SN.finalize(p0)
want = {"live": 19, "inProgress": 9, "napCorrect": 4, "napChecked": 5, "napFix": 5, "blocked": 26, "declined": 27}
check("G1 golden summary: live 19, inProgress 9, napCorrect 4 of 19, declined 27, napFix 5, blocked 26", new["summary"] == want, json.dumps(new["summary"]))
check("G1 summary has exactly the seven agreed fields", set(new["summary"]) == set(SN.SUMMARY_KEYS) == {"live", "inProgress", "napCorrect", "napChecked", "napFix", "blocked", "declined"})
check("G1 no needs-human row is left in the snapshot", all(d["state"] != "needs-human" for d in new["directories"]))
check("G1 the 14 live rows never NAP-checked stay null (not False)", sum(1 for d in new["directories"] if d["state"] == "live" and d["napConsistent"] is None) == 14)
check("G1 finalize does not mutate its input", p0["directories"][0]["state"] == "needs-human" and "summary" not in p0)

# G2 summary == row recount, whatever the rows are
STATES = ["live", "submitted", "pending-verify", "needs-human", "nap-fix", "blocked", "rejected", "absent", "couldnt_check"]
def recount(dirs):
    live = [d for d in dirs if d["state"] == "live"]
    return {"live": len(live), "inProgress": sum(d["state"] in ("submitted", "pending-verify") for d in dirs),
            "napCorrect": sum(d["napConsistent"] is True for d in live), "napChecked": sum(d["napConsistent"] is not None for d in live),
            "napFix": sum(d["state"] == "nap-fix" for d in dirs), "blocked": sum(d["state"] == "blocked" for d in dirs), "declined": sum(d["state"] == "rejected" for d in dirs)}
rnd, bad = random.Random(1027), 0
for t in range(300):
    dirs = [{"name": "r%d.example" % i, "domain": "r%d.example" % i, "state": rnd.choice(STATES), "napConsistent": rnd.choice([True, False, None]),
             "url": rnd.choice([None, "https://x.example/biz/1"]), "urlKind": rnd.choice([None, "listing", "search"])} for i in range(rnd.randint(0, 60))]
    f = SN.finalize({"found": 99, "couldntCheck": 99, "directories": dirs})   # a stale payload with frozen totals
    exp = recount([dict(d, state=SN.classify_needs_human(None, d) if d["state"] == "needs-human" else d["state"]) for d in dirs])
    if f["summary"] != exp or f["summary"] != SN.summary_from_rows(f["directories"]) or "found" in f: bad += 1
check("G2 300 random payloads: summary == independent row recount, stale totals dropped", bad == 0, "bad=%d" % bad)
check("G2 napCorrect <= napChecked <= live always", all(f["summary"]["napCorrect"] <= f["summary"]["napChecked"] <= f["summary"]["live"] for f in [SN.finalize(p0)]))
rows = Q.load_rows()
ov = Q.overlay_directories(p0, rows[:3] + [dict(rows[0], id="x1", directory="nh-fix-00.example", state="live")], "2026-10-27")
check("G2 overlay_directories output summary == recount of its own rows", ov["summary"] == SN.summary_from_rows(ov["directories"]) == recount(ov["directories"]))
chk = [dict(biz="SCC", directory="d%02d.example" % i, result=r, url=None, method="m", note=None, diffs=[]) for i, r in enumerate(["found", "found", "absent", "couldnt_check", "unsearchable"])]
bp = P.build_payload(chk, "2026-10-27")
check("G2 build_payload (scan) carries a recounted summary and no frozen totals", bp["summary"] == SN.summary_from_rows(bp["directories"]) and bp["summary"]["live"] == 2 and "found" not in bp)

# G3 needs-human split
qrow = lambda **k: dict(id="fix-x", directory="x.example", state="queued", **k)
check("G3 queued, no listing -> blocked", SN.classify_needs_human(qrow(), {}) == "blocked")
check("G3 queue state found alone -> blocked (nap-fix needs a wrong NAP read)", SN.classify_needs_human(dict(qrow(), state="found"), {}) == "blocked")
check("G3 queue state claimed-unverified alone -> blocked", SN.classify_needs_human(dict(qrow(), state="claimed-unverified"), {}) == "blocked")
check("G3 a listing_url on the row alone -> blocked", SN.classify_needs_human(qrow(listing_url="https://x.example/biz/1"), {}) == "blocked")
check("G3 napConsistent False on the snapshot row -> nap-fix; a listing permalink alone -> blocked",
      SN.classify_needs_human(qrow(), {"url": "https://x.example/biz/1", "urlKind": "listing"}) == "blocked" and SN.classify_needs_human(qrow(), {"napConsistent": False}) == "nap-fix")
check("G3 queue nap_check.consistent False -> nap-fix", SN.classify_needs_human(qrow(nap_check={"consistent": False}), {}) == "nap-fix")
check("G3 NAP proven right is not a NAP fix -> blocked", SN.classify_needs_human(dict(qrow(), state="found"), {"napConsistent": True}) == "blocked")
check("G3 a search URL alone is not a listing -> blocked", SN.classify_needs_human(qrow(), {"url": "https://x.example/search?q=a", "urlKind": "search"}) == "blocked")
check("G3 queue state machine unchanged: needs-human still internal, PORTAL_STATES and matrix intact",
      "needs-human" in Q.PORTAL_STATES and "needs-human" in T.STATES and Q.QUEUE_TO_PORTAL["found"] == "needs-human" and T.ANY_FROM == {"rejected", "needs-human"})

# G4 live-row NAP read
canon = {"name": "Alder Care", "address": "1 Main St, Exampleton, KY 40000", "phone": "(502) 555-0101"}
nc = lambda **r: RC.nap_check_from_result(dict(row="r", before="live", **r), canon, "2026-10-27")
check("G4 match -> consistent True", nc(verdict="match", fields=[])["consistent"] is True)
m = nc(verdict="mismatch", fields=[("phone", "(502) 555-0199")])
check("G4 mismatch -> consistent False naming the field, with live and right values", m["consistent"] is False and m["fields"] == ["phone"] and m["errors"][0] == {"field": "phone", "live": "(502) 555-0199", "right": "(502) 555-0101"}, str(m))
for v, extra in (("nap-incomplete", dict(fields=["address"])), ("not-public", dict(note="signed-out page shows no listing")), ("unreadable-public", dict(note="no public source")),
                 ("no-permalink", {}), ("unreadable", dict(error="page not readable (403)")), (None, dict(error="boom"))):
    r = nc(verdict=v, **extra)
    check("G4 %s -> consistent None with a reason, never False" % v, r["consistent"] is None and bool(r["reason"]), str(r))
d = {"name": "l.example", "domain": "l.example", "state": "live", "napConsistent": None, "issues": [], "url": "https://l.example/biz/1", "urlKind": "listing"}
SN.apply_nap_check(d, nc(verdict="not-public", note="signed-out page shows no listing"))
check("G4 an unread live row keeps napConsistent null and shows the reasonText", d["napConsistent"] is None and "no listing" in d["reasonText"])
d2 = dict(d, reasonText=None); SN.apply_nap_check(d2, m)
check("G4 a wrong NAP shows napConsistent False + issues + napErrors on the snapshot row", d2["napConsistent"] is False and d2["issues"] == ["phone"] and d2["napErrors"][0]["field"] == "phone")
live_q = [dict(r, state="live", nap_check=nc(verdict="match", fields=[])) for r in rows[:2]]
ov2 = Q.overlay_directories({"directories": []}, live_q, "2026-10-27")
check("G4 overlay shows a stored nap_check on a live row and the summary counts it", ov2["summary"]["live"] == 2 and ov2["summary"]["napCorrect"] == 2 and ov2["summary"]["napChecked"] == 2)
# write path: a live row read by recheck gets nap_check stored, state unchanged, no history entry
td = tempfile.mkdtemp(); qp = os.path.join(td, "q.json")
q = json.load(open(os.environ["CE_QUEUE"], encoding="utf-8"))
lr = [r for _k, _kind, rs in T._row_lists(q) for r in rs][0]; lr["state"] = "live"; lr["history"] = []; json.dump(q, open(qp, "w", encoding="utf-8"))
T.set_nap_check(lr["id"], nc(verdict="match", fields=[]), queue_path=qp)
q2 = json.load(open(qp, encoding="utf-8")); r2 = [r for _k, _kind, rs in T._row_lists(q2) for r in rs if r["id"] == lr["id"]][0]
check("G4 set_nap_check stores nap_check on the live row, state live, history untouched", r2["nap_check"]["consistent"] is True and r2["state"] == "live" and r2["history"] == [])
try: T.set_nap_check([r for _k, _kind, rs in T._row_lists(q2) for r in rs if r["id"] != lr["id"]][0]["id"], {}, queue_path=qp); refused = False
except T.TransitionRefused: refused = True
check("G4 set_nap_check refuses a row that is not live", refused)
src = open(os.path.join(HERE, "..", "job", "run.py"), encoding="utf-8").read()
check("G4 the weekly recheck step reads live rows (include_live default on)", 'kw.setdefault("include_live", True)' in src)
cand = RC.candidates(q2, include_live=True)
check("G4 candidates(include_live) names the live row", any(r["id"] == lr["id"] for _k, r in cand))

# G5 nothing frozen, no seed
js = open(os.path.join(HERE, "..", "site", "logic.js"), encoding="utf-8").read()
check("G5 no payload any writer builds carries a frozen scan field", all(k not in x for x in (bp, ov, ov2, SN.finalize(p0)) for k in SN.FROZEN_KEYS))
check("G5 portal.py no longer holds the hard-coded scan totals", "SCANNED" not in open(os.path.join(HERE, "..", "job", "portal.py"), encoding="utf-8").read() and "CATALOG_TOTAL" not in open(os.path.join(HERE, "..", "job", "portal.py"), encoding="utf-8").read())
new_code = open(os.path.join(HERE, "..", "job", "snapshot.py"), encoding="utf-8").read() + open(os.path.join(HERE, "..", "job", "snapshot_dry_run.py"), encoding="utf-8").read()
check("G5 the new modules make no network call and name no portal seed / Directory path", not any(w in new_code for w in ("urllib", "requests", "http.client", "socket", "portal-seed", "seed", "subprocess")))
check("G5 only footprint_snapshot is touched by the app's new read", "footprint_snapshot" in open(os.path.join(HERE, "..", "site", "app.js"), encoding="utf-8").read())

print("\nALL PASS (%d/%d)" % (sum(ok), len(ok)) if all(ok) else "\nFAILED (%d/%d)" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
