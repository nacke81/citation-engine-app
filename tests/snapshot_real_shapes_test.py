"""Snapshot on REAL row shapes (t_f6267312 round 2). Run: python tests/snapshot_real_shapes_test.py (CI). No network, no prod env, no portal seed.

Fixture tests/fixtures/real-shapes-scc-2026-10-27.json = the prod snapshot of 2026-10-27 (86 rows) + the real queue (fix_queue 7 rows, create_queue.rows 75 rows),
scrubbed: only domain, state, napConsistent, urlKind and the fields the rule reads (state, listing_url, evidence_url, nap_check); URLs are placeholders; no NAP, no notes.

R1 golden: napFix 5, blocked 26, live 19, inProgress 9, declined 27 and the SAME classes on finalize-only, fix-rows overlay and all-rows overlay.
R2 nap-fix means a wrong NAP read and nothing else (listing_url / evidence_url / urlKind listing / state found alone -> blocked).
R3 write_run overlays every queue list: a fake portal, create_queue rows in the payload, a live create row's nap_check shows and counts in napChecked.
"""
import copy, io, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_QUEUE"] = os.path.join(HERE, "fixtures", "test_queue.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import snapshot as SN, buildqueue as Q, portal as P  # noqa: E402

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

fx = json.load(open(os.path.join(HERE, "fixtures", "real-shapes-scc-2026-10-27.json"), encoding="utf-8"))
payload, queue = fx["payload"], fx["queue"]
want = {"live": 19, "inProgress": 9, "napCorrect": 4, "napChecked": 5, "napFix": 5, "blocked": 26, "declined": 27}
cls = lambda p: {d["domain"]: d["state"] for d in p["directories"]}

# R1 golden, three write paths
fin = SN.finalize(payload)
fix_rows = Q.parse_rows(queue)
all_rows = Q.all_rows(queue)
ov_fix = Q.overlay_directories(payload, fix_rows, "2026-10-27")
ov_all = Q.overlay_directories(payload, all_rows, "2026-10-27")
check("R1 fixture shape: 86 rows, fix_queue 7, create_queue.rows 75", len(payload["directories"]) == 86 and len(queue["fix_queue"]) == 7 and len(queue["create_queue"]["rows"]) == 75)
check("R1 fixture holds no NAP / contact data", not any(k in json.dumps(fx).lower() for k in ("555-", "@", "phone", "address")))
for name, p in (("finalize only", fin), ("fix-rows overlay", ov_fix), ("all-rows overlay", ov_all)):
    check("R1 %s: summary == golden (napFix 5, blocked 26, live 19, inProgress 9, declined 27)" % name, p["summary"] == want, json.dumps(p["summary"]))
    check("R1 %s: 86 rows, no needs-human left, summary == row recount" % name, len(p["directories"]) == 86 and all(d["state"] != "needs-human" for d in p["directories"]) and p["summary"] == SN.summary_from_rows(p["directories"]))
check("R1 the class of every row is the same on all three write paths", cls(fin) == cls(ov_fix) == cls(ov_all))

# R2 the rule
q = lambda **k: dict(id="create-x", directory="x.example", state="found", **k)
for label, qr, d in (("listing_url", q(listing_url="https://x.example/biz/1"), {}),
                     ("evidence_url permalink", q(evidence_url="https://x.example/biz/1"), {}),
                     ("urlKind listing + url", q(), {"url": "https://x.example/biz/1", "urlKind": "listing"}),
                     ("state claimed-unverified", dict(q(), state="claimed-unverified"), {}),
                     ("state found, nap null", q(), {"napConsistent": None}),
                     ("nap_check consistent None", q(nap_check={"consistent": None, "reason": "wall"}), {}),
                     ("nap_check consistent True", q(nap_check={"consistent": True}), {})):
    check("R2 %s alone -> blocked" % label, SN.classify_needs_human(qr, d) == "blocked")
check("R2 napConsistent False on the snapshot row -> nap-fix", SN.classify_needs_human(q(), {"napConsistent": False}) == "nap-fix")
check("R2 nap_check.consistent False on the queue row -> nap-fix", SN.classify_needs_human(q(nap_check={"consistent": False}), {}) == "nap-fix")
check("R2 the five nap-fix rows in the real data are exactly the snapshot rows with napConsistent False and state needs-human",
      sorted(d["domain"] for d in payload["directories"] if d["state"] == "needs-human" and d["napConsistent"] is False) == sorted(d["domain"] for d in ov_all["directories"] if d["state"] == "nap-fix"))

# R3 write_run with a fake portal and create_queue rows
class FakePortal(P.Portal):
    def __init__(self):
        super().__init__("https://portal.example", "SECRETKEY123", opener=self._open_fake); self.calls = []; self.store = {}
    def _open_fake(self, req):
        self.calls.append((req.get_method(), req.full_url))
        body = json.loads(req.data) if req.data else None
        out = b""
        if req.get_method() == "POST":
            for r in body: self.store[(r["client_id"], r["source"], r["captured_day"])] = r
        else:
            out = json.dumps([r for r in self.store.values() if r["client_id"] in req.full_url and r["captured_day"] in req.full_url]).encode()
        class R(io.BytesIO):
            def __enter__(s): return s
            def __exit__(s, *a): return False
        return R(out)

def scan(biz):
    return [dict(biz=biz, directory="d%02d.example" % i, result=r, url=None, method="m", note=None, diffs=[]) for i, r in enumerate(["found", "found", "absent", "couldnt_check"])]
checks = scan("SCC") + scan("NM")
q3 = {"fix_queue": [dict(id="fix-a", directory="d00.example", state="queued")],
      "create_queue": {"rows": [dict(id="create-live1", directory="live-one.example", state="live", nap_check={"consistent": True, "at": "2026-10-27"}),
                                dict(id="create-live2", directory="live-two.example", state="live", nap_check={"consistent": None, "reason": "page not readable (403)", "at": "2026-10-27"}),
                                dict(id="create-wrong", directory="wrong.example", state="needs-human", nap_check={"consistent": False, "fields": ["phone"]}),
                                dict(id="create-wall", directory="wall.example", state="needs-human", evidence_url="https://wall.example/biz/9")]}}
qp = os.path.join(tempfile.mkdtemp(), "q.json"); json.dump(q3, open(qp, "w", encoding="utf-8"))
Q.QUEUE_PATH = qp
fp = FakePortal()
res = P.write_run(checks, "2026-10-27", fp)   # default overlay: no queue_rows passed
sent = [r for k, r in fp.store.items() if r["client_id"] == P.ALLOWED["SCC"]][0]["payload"]
byd = {d["domain"]: d for d in sent["directories"]}
check("R3 write_run payload holds the create_queue rows (live-one, live-two, wrong, wall)", all(x in byd for x in ("live-one.example", "live-two.example", "wrong.example", "wall.example")), str(sorted(byd)))
check("R3 a live create row's nap_check shows on its snapshot row", byd["live-one.example"]["napConsistent"] is True and byd["live-two.example"]["napConsistent"] is None and "403" in byd["live-two.example"]["reasonText"])
scan_live = [d for d in sent["directories"] if d["domain"].startswith("d") and d["state"] == "live"]   # the scan's own live row(s) are counted too
check("R3 napChecked counts the read create row, the unread live create row stays out of it", sent["summary"]["live"] == 2 + len(scan_live) and sent["summary"]["napChecked"] == 1 + sum(d["napConsistent"] is not None for d in scan_live)
      and byd["live-two.example"]["state"] == "live" and byd["live-two.example"]["napConsistent"] is None, json.dumps(sent["summary"]))
check("R3 wrong NAP read -> nap-fix; wall with an evidence URL only -> blocked", byd["wrong.example"]["state"] == "nap-fix" and byd["wall.example"]["state"] == "blocked")
check("R3 scan rows are kept (4 scan rows + 4 create rows) and the summary equals the recount", len(sent["directories"]) == 8 and sent["summary"] == SN.summary_from_rows(sent["directories"]) and res["SCC"]["summary"] == sent["summary"])
check("R3 only footprint_snapshot touched, no Directory / seed path", all("footprint_snapshot" in u for _, u in fp.calls))

print("\nALL PASS (%d/%d)" % (sum(ok), len(ok)) if all(ok) else "\nFAILED (%d/%d)" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
