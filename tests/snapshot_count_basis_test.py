"""Count basis for the portal SCC live number (t_9d36198a). Run: python tests/snapshot_count_basis_test.py. No network, no prod env, no portal seed.

Pins the 11/16 prod shape: 26 scan/queue 'live' rows -> 24 counted = 23 rows with complete proof + GBP (google.com) once.
maps.apple.com and n49.com (scan found, no queue row, no proof) are re-stated couldnt_check / unproven, because the portal page counts state == "live" rows.
"""
import copy, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_DIRECTORIES_WRITE"] = "0"
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import os as _fo; _fo.environ["CE_PORTAL_ENV"] = _fo.path.join(_fo.path.dirname(_fo.path.abspath(__file__)), "no-such-portal.env")  # t_2ddc7067: fail closed, never the prod portal
import snapshot as SN, transitions as T  # noqa: E402

ok = []
LIVE = lambda pl: sum(1 for d in pl["directories"] if d["state"] == "live")   # what CitationsBlock counts
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

def proof(dom):
    return {"proof_url": "https://%s/biz/1" % dom, "proof_nap": "Senior Care Consulting & Solutions", "proof_at": "2026-11-10T00:00:00Z", "proof_nap_match": True, "build_action": "new"}

def row(dom, state="live", nap=True):
    return {"name": dom, "domain": dom, "state": state, "napConsistent": nap if state == "live" else None, "url": "https://%s/x" % dom, "urlKind": "listing"}

proofed = ["p%02d.example" % i for i in range(23)]
payload = {"directories": [row(d) for d in proofed] + [row("google.com"), row("maps.apple.com"), row("n49.com"), row("ibegin.com", "rejected")]}
payload = SN.finalize(payload)
check("old rule counts 26 (the bug)", payload["summary"]["live"] == 26, str(payload["summary"]))

PR = {d: proof(d) for d in proofed}
out = SN.apply_count_basis(payload, PR, T.proof_problems)
s = out["summary"]
check("23 proofed + GBP = 24 live", s["live"] == 24, str(s))
by = {d["domain"]: d for d in out["directories"]}
check("GBP counts once", by["google.com"]["state"] == "live" and sum(1 for d in out["directories"] if d["domain"] == "google.com") == 1)
dup = dict(payload, directories=payload["directories"] + [row("google.com")])
od = SN.apply_count_basis(dup, PR, T.proof_problems)
check("GBP twice in the rows (scan + queue) -> one google.com row, 24 not 25", sum(1 for d in od["directories"] if d["domain"] == "google.com") == 1 and LIVE(od) == 24 and od["summary"]["live"] == 24)
LIVE = lambda pl: sum(1 for d in pl["directories"] if d["state"] == "live")   # what CitationsBlock counts
check("the page's count (state == live rows) is 24", LIVE(out) == 24, str(LIVE(out)))
check("unproven rows re-stated couldnt_check / unproven / reasonText, url kept", all(by[x]["state"] == "couldnt_check" and by[x]["reason"] == "unproven" and by[x]["reasonText"] == "Listing seen, not yet verified" and by[x]["url"] == "https://%s/x" % x and by[x]["napConsistent"] is None for x in ("maps.apple.com", "n49.com")))
check("GBP row stays live", by["google.com"]["state"] == "live")
check("napChecked/napCorrect count counted rows only", s["napChecked"] == 24 and s["napCorrect"] == 24, str(s))
check("non-live rows untouched", by["ibegin.com"]["state"] == "rejected" and s["declined"] == 1)

# incomplete proof does not count
bad = dict(PR); bad[proofed[0]] = dict(proof(proofed[0]), proof_nap_match=False)
bad[proofed[1]] = {k: v for k, v in proof(proofed[1]).items() if k != "proof_url"}
bad[proofed[2]] = dict(proof(proofed[2]), proof_url="not-a-url")
check("proof_nap_match false / no proof_url / non-http url do not count", SN.apply_count_basis(payload, bad, T.proof_problems)["summary"]["live"] == 21 and LIVE(SN.apply_count_basis(payload, bad, T.proof_problems)) == 21)
check("no proof map at all -> GBP only", SN.apply_count_basis(payload, None, T.proof_problems)["summary"]["live"] == 1)

# idempotent; input untouched; a later finalize keeps the rule
before = copy.deepcopy(payload)
again = SN.apply_count_basis(out, PR, T.proof_problems)
check("idempotent", again["summary"] == s)
check("input payload not mutated", payload == before)
check("finalize after the rule keeps 24", SN.finalize(out)["summary"]["live"] == 24)

# write path: write_run (SCC) publishes the counted number, via a fake portal
import os as _fo; _fo.environ["CE_PORTAL_ENV"] = _fo.path.join(_fo.path.dirname(_fo.path.abspath(__file__)), "no-such-portal.env")  # t_2ddc7067: fail closed, never the prod portal
import portal as P  # noqa: E402
class FakePortal:
    def __init__(self): self.rows = {}
    def upsert_snapshot(self, cid, day, p):
        self.rows[cid] = p; return {"client_id": cid, "source": P.SOURCE, "captured_day": day, "payload": p}
import buildqueue as Q  # noqa: E402
qrows = [{"id": "create-" + d, "directory": d, "state": "live", "proof": proof(d)} for d in proofed]
def chk(biz, d, res="found"):
    return {"biz": biz, "directory": d, "result": res, "url": "https://%s/x" % d, "diffs": [], "note": None}
scan = [chk("SCC", d) for d in proofed + ["google.com", "maps.apple.com", "n49.com"]] + [chk("NM", "google.com")]
Q.QUEUE_TO_PORTAL.setdefault("live", "live")
fp = FakePortal()
res = P.write_run(scan, "2026-11-16", fp, queue_rows=qrows, proof_by_dir={})
check("write_run SCC summary.live == 24 (23 proofed + GBP)", res["SCC"]["summary"]["live"] == 24, str(res["SCC"]["summary"]))
wp = fp.rows[P.ALLOWED["SCC"]]
check("write_run written payload: state == live rows == 24 (what the page shows)", LIVE(wp) == 24, str(LIVE(wp)))
check("write_run: maps.apple.com / n49.com written as couldnt_check", {d["domain"]: d["state"] for d in wp["directories"] if d["domain"] in ("maps.apple.com", "n49.com")} == {"maps.apple.com": "couldnt_check", "n49.com": "couldnt_check"})
fp2 = FakePortal(); q2 = qrows + [{"id": "create-google.com", "directory": "google.com", "state": "live", "proof": proof("google.com")}]
P.write_run(scan, "2026-11-16", fp2, queue_rows=q2, proof_by_dir={})
w2 = fp2.rows[P.ALLOWED["SCC"]]
check("write_run GBP twice (scan row + queue row): one google.com row, live 24", sum(1 for d in w2["directories"] if d["domain"] == "google.com") == 1 and LIVE(w2) == 24 and w2["summary"]["live"] == 24)
def boom(*a, **k): raise RuntimeError("db down")
_o = T.db_proof_by_directory; T.db_proof_by_directory = boom
fp3 = FakePortal()
try: P.write_run(scan, "2026-11-16", fp3, queue_rows=qrows); msg = ""
except P.PortalWriteError as e: msg = str(e)
T.db_proof_by_directory = _o
check("proof read failure refuses the write with 'proof read failed: ...' and writes nothing", msg.startswith("proof read failed:") and "db down" in msg and fp3.rows == {}, msg)
import json, tempfile, snapshot_dry_run as DR
tmp = tempfile.mkdtemp(); pf, qf = os.path.join(tmp, "p.json"), os.path.join(tmp, "q.json")
json.dump(payload, open(pf, "w")); json.dump({"create_queue": qrows}, open(qf, "w"))
lines = []; summ = DR.run(pf, qf, out=lines.append)
check("dry run applies the count basis: NEW SUMMARY live 24", summ["live"] == 24 and any("count basis applied" in l for l in lines), str(summ))
lines = []; DR.run(pf, None, out=lines.append)
check("dry run without a queue file says the basis is not applied", any("count basis NOT applied" in l for l in lines))
check("write_run NM unaffected by the SCC rule", not any(d.get("reason") == "unproven" for d in fp.rows[P.ALLOWED["NM"]]["directories"]))

# existing (t_dc4ffd67): a proofed pre-existing listing counts as live like any proofed row
PR_EX = dict(PR); PR_EX["maps.apple.com"] = dict(proof("maps.apple.com"), build_action="existing"); PR_EX["n49.com"] = dict(proof("n49.com"), build_action="existing")
ox = SN.apply_count_basis(payload, PR_EX, T.proof_problems)
check("existing rows with complete proof count live: 23 + GBP + 2 existing = 26", ox["summary"]["live"] == 26 and LIVE(ox) == 26, str(ox["summary"]))

# DB-proof precedence (t_be2150cd): count_proof merges queue proof and ce_directory_status proof; proof_by_dir is always explicit (never prod)
d0 = proofed[0]
q_nokey = [{"id": "create-" + d, "directory": d, "state": "live"} for d in proofed]          # pre-guard rows: no proof key in the queue
fp4 = FakePortal()
r4 = P.write_run(scan, "2026-11-16", fp4, queue_rows=q_nokey, proof_by_dir={d: proof(d) for d in proofed})
w4 = fp4.rows[P.ALLOWED["SCC"]]
check("DB-only proof: queue live rows with NO proof key stay live via proof_by_dir (24)", LIVE(w4) == 24 and r4["SCC"]["summary"]["live"] == 24, str(r4["SCC"]["summary"]))
check("DB-only proof: no proofed row is re-stated to couldnt_check", not any(d["state"] == "couldnt_check" and d["domain"] in proofed for d in w4["directories"]))
fp5 = FakePortal(); P.write_run(scan, "2026-11-16", fp5, queue_rows=q_nokey, proof_by_dir={})
check("no proof in queue or DB: the same rows are re-stated (GBP only live)", LIVE(fp5.rows[P.ALLOWED["SCC"]]) == 1)
badproof = dict(proof(d0), proof_nap_match=False)
fp6 = FakePortal(); P.write_run(scan, "2026-11-16", fp6, queue_rows=qrows, proof_by_dir={d0: badproof})
check("incomplete DB proof does not override a complete queue proof (stays live, 24)", LIVE(fp6.rows[P.ALLOWED["SCC"]]) == 24)
check("count_proof keeps the queue proof when the DB proof is incomplete", P.count_proof(qrows, {d0: badproof})[d0] == proof(d0))
fp7 = FakePortal(); P.write_run(scan, "2026-11-16", fp7, queue_rows=q_nokey, proof_by_dir=dict({d: proof(d) for d in proofed}, **{d0: badproof}))
check("incomplete DB proof and no queue proof: that row is re-stated (23 live)", LIVE(fp7.rows[P.ALLOWED["SCC"]]) == 23)
db_other = dict(proof(d0), proof_url="https://%s/db" % d0)
check("complete DB proof wins over the queue proof for the same directory", P.count_proof(qrows, {d0: db_other})[d0] == db_other)
check("count_proof with proof_by_dir={} uses queue proof only", P.count_proof(qrows, {}) == {d: proof(d) for d in proofed})

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
