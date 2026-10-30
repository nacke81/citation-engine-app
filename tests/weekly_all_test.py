"""Weekly finder covers every Directory in ce_directories (t_716fc9cd). Scrubbed identity, no network, no write."""
import json, os, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ["CE_IDENTITY"] = str(HERE / "test_identity.json")
sys.path.insert(0, str(HERE.parent / "job"))
TEMP = tempfile.TemporaryDirectory(prefix="weekly-all-", dir=HERE)
os.environ["CE_RUNS"] = TEMP.name
os.environ["CE_ROWS"] = str(Path(TEMP.name) / "rows.jsonl")
import run as R, dirlist, judge, listing, portal
from cfg import DIRS

ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

class FakeDB:
    """Records every call; GET only is allowed."""
    def __init__(self, rows=None, boom=None): self.rows, self.boom, self.calls = rows, boom, []
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path))
        if self.boom: raise self.boom
        return self.rows

seed = dirlist.seed_domains()
check("W1 seed has 86 unique Directories and contains the 25 proven ones", len(seed) == 86 and len(set(seed)) == 86 and set(DIRS) <= set(seed), len(seed))

db = FakeDB([{"domain": d} for d in seed])
doms, src = dirlist.load_directories(db, log=lambda m: None)
check("W2 list comes from ce_directories (GET only)", src == "ce_directories" and doms == seed and all(c[0] == "GET" for c in db.calls) and "ce_directories" in db.calls[0][1], db.calls)

new = "brand-new-directory.example"
doms2, _ = dirlist.load_directories(FakeDB([{"domain": d} for d in seed] + [{"domain": new}, {"domain": new.upper()}, {"domain": ""}]), log=lambda m: None)
check("W3 a new ce_directories row is in the next run with no code change (deduped, lowercased)", len(doms2) == 87 and doms2[-1] == new)

msgs = []
d3, s3 = dirlist.load_directories(FakeDB(boom=OSError("offline")), log=msgs.append)
check("W4 DB error -> seed fallback, loudly", s3 == "seed" and d3 == seed and msgs and "FALLBACK" in msgs[0])
d4, s4 = dirlist.load_directories(FakeDB([]), log=msgs.append)
check("W5 empty ce_directories -> seed fallback, never a zero-Directory run", s4 == "seed" and len(d4) == 86)

# Build over all 86 with discovery rows for the proven 25 only (SCC found on DIRS[0], NM noresult with control, everything else couldnt)
def row(**k):
    base = dict(kind="dir", method="chrome-search", status="couldnt", verified=False, results=0, url="", ev=None, blocked_on_purpose=False, note="")
    base.update(k); return base
rows = [row(biz="SCC", dir=DIRS[4], status="found", url="https://www.yelp.com/biz/x"),
        row(biz="NM", dir=DIRS[4], status="noresult", verified=True, results=5)]
for b in ("SCC", "NM", "FAKE"):
    for d in DIRS:
        if not any(r["biz"] == b and r["dir"] == d for r in rows): rows.append(row(biz=b, dir=d))
comb, checks = R.build(rows, {}, {}, doms2)
by = {(c["biz"], c["directory"]): c for c in checks}
check("W6 every business has one check per Directory (87 = 86 + new row)", all(sum(1 for c in checks if c["biz"] == b) == 87 for b in ("SCC", "NM")) and len(checks) == 174, len(checks))
extra = [d for d in doms2 if d not in DIRS]
check("W7 no-method Directories are couldnt_check / no-method for both, never absent or found",
      all(by[(b, d)]["result"] == "couldnt_check" and by[(b, d)]["note"] == "no-method" for b in ("SCC", "NM") for d in extra) and len(extra) == 62, len(extra))
check("W8 no-method rows never absent even with a control found elsewhere", not any(c["result"] == "absent" for c in checks if c["directory"] in extra) and by[("NM", DIRS[4])]["result"] == "absent")
check("W9 the 25 keep their verdicts (found / absent with control)", by[("SCC", DIRS[4])]["result"] == "found")
check("W10 made-up business still finds 0 over all Directories", judge.made_up_ok(comb))
r, txt = listing.reason_for(extra[0], "couldnt_check", "no-method")
check("W11 reason text says not checked, not absent", r == "no-method" and "not a finding" in txt and "absent" in txt)

# Snapshot shape: same keys per Directory entry as the 25-only payload
P87 = portal.build_payload([c for c in checks if c["biz"] == "SCC"], "2026-11-01")
P25 = portal.build_payload([c for c in R.build(rows, {}, {})[1] if c["biz"] == "SCC"], "2026-11-01")
check("W12 portal payload shape unchanged (same top keys, same per-Directory keys; counts differ)",
      set(P87) == set(P25) and set(P87["directories"][0]) == set(P25["directories"][0]) and set(P87["summary"]) == set(P25["summary"]) and len(P87["directories"]) == 87 and len(P25["directories"]) == 25,
      (len(P87["directories"]), len(P25["directories"])))
nm = [d for d in P87["directories"] if d["domain"] in extra]
check("W13 payload: no-method rows are couldnt_check, status unavailable, reason no-method", all(d["state"] == "couldnt_check" and d["reason"] == "no-method" and d["status"] == "unavailable" for d in nm) and len(nm) == 62)
check("W14 summary: same live count as the 25-only run; 62 more rows are couldnt_check, none absent",
      P87["summary"]["live"] == P25["summary"]["live"] and sum(1 for d in P87["directories"] if d["state"] == "couldnt_check") - sum(1 for d in P25["directories"] if d["state"] == "couldnt_check") == 62
      and not any(d["state"] == "absent" for d in nm), P87["summary"])

# directories_step: a no-method row must not overwrite an earlier verdict
import directories as D
class Rec(FakeDB): pass
rec = Rec([]); 
rows_out = D.check_rows(type("X", (), {"owner": "o"})(), checks, "2026-11-01")
check("W15 no-method rows write no ce_directory_status row (earlier verdicts kept)", not any(r["directory"] in extra for r in rows_out) and any(r["directory"] == DIRS[4] for r in rows_out))

# loader never writes and never touches the portal
src_text = open(HERE.parent / "job" / "dirlist.py", encoding="utf-8").read()
check("W16 dirlist has no write verb and no portal import", all(w not in src_text for w in ('"POST"', '"PATCH"', '"DELETE"', "portal")))

# buildrows: a no-method check must not hide a stored found/match/permalink status
import buildrows as BR
_d = {"domain": "botw.org", "cost": "free", "build_route": "form", "priority": 1}
_st = {"directory": "botw.org", "last_result": "found", "last_url": "https://botw.org/listing/abc-plumbing-123", "last_match": True}
_nm = {"directory": "botw.org", "result": "couldnt_check", "note": "no-method", "url": None}
_q = {"canonical": {}, "fix_queue": [], "create_rows": []}
try:
    _new, _rep = BR.build_rows(_q, [_d], [_st], [_nm], "2026-11-01")
    _ok = _rep.get("create", 0) == 0 and _rep.get("none", 0) == 1
except Exception as e:
    _ok = False; _rep = repr(e)
check("W17 buildrows: no-method check + stored found/match/permalink status gives none, not create", _ok, _rep)
try:
    _new, _rep2 = BR.build_rows(_q, [_d], [_st], [dict(_nm, note="blocked")], "2026-11-01")
    _ok2 = _rep2.get("create", 0) == 1
except Exception as e:
    _ok2 = False; _rep2 = repr(e)
check("W18 buildrows: a real couldnt_check (not no-method) is still taken as a check", _ok2, _rep2)

class _FakeDB:
    def __init__(self): self.urls = []
    def call(self, m, path, body=None, prefer=None):
        self.urls.append(path)
        if path.startswith("ce_directories"): return [dict(_d, name="BOTW")]
        if path.startswith("ce_directory_status"): return [_st]
        if path.startswith("ce_runs"): return [{"id": 7}]
        if path.startswith("ce_checks"): return [dict(_nm, match=None, diffs=None)]
        return []
try:
    _fdb = _FakeDB()
    _dd, _ss, _cc = BR.load_db_inputs(_fdb)
    _sel = [u for u in _fdb.urls if u.startswith("ce_checks")][0]
    _new, _rep3 = BR.build_rows(_q, _dd, _ss, _cc, "2026-11-01")
    _ok3 = ",note" in _sel and _rep3.get("create", 0) == 0 and _rep3.get("none", 0) == 1
except Exception as e:
    _ok3 = False; _rep3 = repr(e)
check("W19 load_db_inputs selects note; CLI path with no-method check gives none, not create", _ok3, _rep3)

print("\n%d/%d passed" % (sum(ok), len(ok)))
TEMP.cleanup()
sys.exit(0 if all(ok) else 1)
