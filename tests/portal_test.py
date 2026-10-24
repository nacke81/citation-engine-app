"""Portal writer tests (placeholder identity, no network). Run: python tests/portal_test.py  (CI does this). Exit 1 on any failure.

P1 counts equal the build app for SCC 11=6+5,0,14 and NM 11=2+9,1,13.   P2 FBS / unknown ids / unknown biz refused with ZERO network calls.
P3 portal failure fails the run log loudly, build-DB rows already saved.  P4 key never in error text.  P5 no Directory / portal-seed path.
"""
import io, json, os, sys, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
# Tests must never depend on the private runtime queue or its presence on CI.
os.environ["CE_QUEUE"] = os.path.join(HERE, "fixtures", "test_queue.json")
import tempfile as _tf; os.environ["CE_RUNS"] = _tf.mkdtemp(prefix="ce-runs-")  # run.py makes dirs on import; never the real runs folder
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import portal as P  # noqa: E402

ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

DIRS = ["d%02d.example" % i for i in range(25)]
def mk(biz, correct, errs, absent, cant, unsearch):
    rows, i = [], 0
    def add(result, **k):
        nonlocal i
        rows.append(dict(biz=biz, directory=DIRS[i], result=result, url=("https://%s/x" % DIRS[i]) if result == "found" else None, method="m", note=k.get("note"), diffs=k.get("diffs"))); i += 1
    for _ in range(correct): add("found", diffs=[])
    for n in range(errs): add("found", diffs=[{"field": "site" if n == 0 else "phone", "live": "a", "canonical": "b"}])
    for _ in range(absent): add("absent")
    for n in range(cant): add("couldnt_check", note="blocked" if n % 2 else "error")
    for _ in range(unsearch): add("unsearchable", note="unsearchable")
    assert i == 25, i
    return rows
SCC = mk("SCC", 6, 5, 0, 13, 1)
NM = mk("NM", 2, 9, 1, 12, 1)

class FakePortal(P.Portal):
    def __init__(self, fail_on=None):
        super().__init__("https://portal.example", "SECRETKEY123", opener=self._open_fake); self.calls = []; self.store = {}; self.fail_on = fail_on
    def _open_fake(self, req):
        self.calls.append((req.get_method(), req.full_url))
        if self.fail_on and self.fail_on in req.full_url:
            raise RuntimeError("boom with header Bearer SECRETKEY123")
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

# P1
ps, pn = P.build_payload(SCC), P.build_payload(NM)
check("P1 SCC counts: 11 = 6 + 5, not found 0, couldn't check 14", (ps["found"], ps["correct"], ps["withNapErrors"], ps["notFound"], ps["couldntCheck"]) == (11, 6, 5, 0, 14), str(ps["found"]))
check("P1 NM counts: 11 = 2 + 9, not found 1, couldn't check 13", (pn["found"], pn["correct"], pn["withNapErrors"], pn["notFound"], pn["couldntCheck"]) == (11, 2, 9, 1, 13))
check("P1 Found = Correct + NAP errors for both", all(p["found"] == p["correct"] + p["withNapErrors"] for p in (ps, pn)))
check("P1 all 25 directories, each with domain/url/napConsistent/issues/status", len(ps["directories"]) == 25 and all(set(d) >= {"domain", "url", "napConsistent", "issues", "status"} for d in ps["directories"]))
check("P1 site diff is reported as issue 'website'", any(d["issues"] == ["website"] for d in ps["directories"]))
psd = P.build_payload(NM, "2026-10-18")
check("P1 rows carry name/state/stateDate in the portal contract (live/absent/couldnt_check)", all(d["name"] and d["stateDate"] == "2026-10-18" for d in psd["directories"]) and sorted({d["state"] for d in psd["directories"]}) == ["absent", "couldnt_check", "live"] and sum(d["state"] == "live" for d in psd["directories"]) == 11)
check("P1 keyScore null (no BrightLocal score)", ps["keyScore"] is None)

# successful write, readback
fp = FakePortal()
res = P.write_run(SCC + NM, "2026-10-16", fp)
check("P1 write_run writes both businesses with source citation_engine and the run day", sorted((v["client_id"], v["source"], v["captured_day"]) for v in res.values()) == sorted((i, "citation_engine", "2026-10-16") for i in P.ALLOWED.values()))
check("P1 only footprint_snapshot is touched", all("footprint_snapshot" in u for _, u in fp.calls))

# P2
for bad in ("430b764e-1a44-4246-959f-6b8945bf6a7c", "7caf0d65-333d-4ba3-b71e-f03aaad5a578", "00000000-0000-0000-0000-000000000000", ""):
    fp = FakePortal()
    try: fp.upsert_snapshot(bad, "2026-10-16", ps); raised = False
    except P.PortalWriteError: raised = True
    check("P2 id %s refused, zero network calls" % (bad[:8] or "empty"), raised and fp.calls == [])
fp = FakePortal()
try: P.write_run(SCC + [dict(SCC[0], biz="FBS")], "2026-10-16", fp); raised = False
except P.PortalWriteError: raised = True
check("P2 a business outside SCC/NM refuses the whole write before any call", raised and fp.calls == [])
fp = FakePortal()
try: P.write_run(SCC, "2026-10-16", fp); raised = False
except P.PortalWriteError: raised = True
check("P2 a partial run (NM missing) is refused before any call", raised and fp.calls == [])
check("P2 allow-list is exactly SCC + NM and disjoint from the forbidden ids", set(P.ALLOWED) == {"SCC", "NM"} and not (set(P.ALLOWED.values()) & P.FORBIDDEN))
# self-check: a guard that allows everything must fail the FBS test
_o = P.check_client; P.check_client = lambda c: c
fp = FakePortal()
try: fp.upsert_snapshot("430b764e-1a44-4246-959f-6b8945bf6a7c", "2026-10-16", ps); leaked = True
except Exception: leaked = False
P.check_client = _o
check("P2 self-check: with the guard removed the FBS write would reach the network", leaked and len(fp.calls) > 0)

# P3 / P4 via run.py's publish step
import run as jobrun  # noqa: E402
fp = FakePortal(fail_on="footprint_snapshot")
err, out = io.StringIO(), io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
    r = jobrun.portal_publish(SCC + NM, "2026-10-16", fp)
check("P3 portal failure returns False (run exits 1) and logs PORTAL WRITE FAILED", r is False and "PORTAL WRITE FAILED" in err.getvalue() and "PORTAL WRITE FAILED" in out.getvalue())
check("P4 the key never appears in the log", "SECRETKEY123" not in err.getvalue() + out.getvalue())
src = open(os.path.join(HERE, "..", "job", "run.py"), encoding="utf-8").read()
i_db, i_pub = src.index('db.call("POST", "ce_checks"'), src.index("portal_ok = portal_publish(")
check("P3 build-DB checks are written BEFORE the portal write", i_db < i_pub)
check("P3 portal_publish never raises (a failure cannot abort the run after the build-DB write)", "except Exception" in src[src.index("def portal_publish"):src.index("def portal_backfill")])

# P5
psrc = open(os.path.join(HERE, "..", "job", "portal.py"), encoding="utf-8").read()
check("P5 portal.py has no Directory path (no fetcher/discover/owned_chrome import) and no portal-seed script call", not any(w in psrc for w in ("import core", "import discover", "owned_chrome", "seed-nm", "subprocess")))
check("P5 job writes only the footprint_snapshot table on the portal", "footprint_snapshot" in psrc and psrc.count('"/rest/v1/"') == 1)

print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})")
sys.exit(0 if all(ok) else 1)
